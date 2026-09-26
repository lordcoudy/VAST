#!/usr/bin/env python3
"""Materialize the exact 32 native qualification runtime-input bundles.

This is a non-authorizing bridge between the fragment/bootstrap transaction and
the physical ABI-v3 runtimes.  It never consumes or emits a production grant.
The complete bundle directory is committed atomically only after every source
file, image, Unix socket, device probe, and candidate/bootstrap identity has
been verified.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import posixpath
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any


sys.dont_write_bytecode = True

import checkpoint_deepstream_publication_runtime_v3 as deepstream_runtime
import checkpoint_gstreamer_publication_runtime_v3 as gstreamer_runtime
import checkpoint_openvino_gva_publication_runtime_v3 as openvino_runtime
import checkpoint_savant_publication_runtime_v3 as savant_runtime
from analytics_execution_endpoint import (
    expected_capability_from_binding_and_probe,
    terminal_detector_identity,
)
from publication_policy_qualification_pilot_executor_v2 import (
    CHILD_EVIDENCE_FILES,
    CODECS,
    RUNTIME_BUNDLE_DIRECTORY,
    RUNTIME_BUNDLE_KIND,
    RUNTIME_BUNDLE_SCOPE,
    RUNTIME_INPUT_KEY_BY_SYSTEM,
    RUNTIME_MATERIALIZATION_RECEIPT_FILENAME,
    RUNTIME_MATERIALIZATION_RECEIPT_KIND,
    SYSTEMS,
    QualificationPilotCellV2,
    _canonical_bytes,
    _canonical_sha,
    _descriptor_matches,
    _assert_pin_unchanged,
    _is_link_or_reparse,
    _load_qualification_inputs,
    _physical_directory,
    _physical_root,
    _pin_json,
    _rename_directory_noreplace,
    _runtime_bundle_path,
    _walk_forbidden_production_claims,
    qualification_pilot_cells_v2,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


MATERIALIZATION_RECEIPT = RUNTIME_MATERIALIZATION_RECEIPT_FILENAME
MATERIALIZATION_RECEIPT_KIND = RUNTIME_MATERIALIZATION_RECEIPT_KIND
ASSET_DIRECTORY = "_assets"
DOCKER_ASSET = f"{ASSET_DIRECTORY}/container-engine/docker"
DEFAULT_CONTAINER_ENGINE = Path("/usr/bin/docker")
DEFAULT_CONTAINER_ENGINE_SOCKET = Path("/var/run/docker.sock")
DEFAULT_ANALYTICS_SOCKET = Path(
    ".publication-sockets/model-parity-v3/analytics-execution.sock"
)
DEFAULT_SCRATCH_ROOT = Path("/tmp")
DATASETS_PATH = "configs/datasets.yaml"
EXPERIMENTS_PATH = "configs/experiments.yaml"
ANALYTICS_EXECUTION_PATH = "configs/analytics_execution_layer.yaml"
OPENVINO_MODEL_MANIFEST_PATH = "configs/checkpoint_analytics_models_openvino.yaml"
DEVICE_PROBE_PATH = "deploy/openvino/checkpoint/probe_openvino_devices.py"
ANALYTICS_BINDING_INDEX_PATH = (
    "artifacts/analytics_execution_bindings/publication_v3/index.json"
)
ANALYTICS_PROBE_PATHS = {
    "cpu": "artifacts/analytics_runtime_probes/publication_v3/cpu_runtime_probe.json",
    "gpu": "artifacts/analytics_runtime_probes/publication_v3/gpu_runtime_probe.json",
}
SAVANT_REACHABLE_RUNTIME_SOURCES = (
    "deploy/savant/publication/Dockerfile",
    "deploy/savant/publication/runtime-source-allowlist.txt",
    "deploy/savant/publication/vast_savant_checkpoint_runtime",
    "scripts/checkpoint_savant_container_runtime_v3.py",
    "scripts/checkpoint_savant_publication_specs_v3.py",
    "scripts/checkpoint_savant_sdk_runtime_v3.py",
)
SAVANT_ENTRYPOINT_TARGET = "/usr/local/bin/vast_savant_checkpoint_runtime"
SAVANT_SDK_WORKER_TARGET = (
    "/opt/vast/checkpoint/checkpoint_savant_sdk_runtime_v3.py"
)
PREPROCESSING_SHA256 = (
    "0307abfe6c5f652cc06f3f3df8ecf5050e5ed29b9ed5f40cb6fe728f47627090"
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REFERENCE_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_.-]+$"
)
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
ENGINE_BY_RESOURCE = {"cpu": "openvino_cpu", "gpu": "tensorrt_cuda"}
DETECT_BIN = (
    "videoconvert ! video/x-raw,format={input_format} ! "
    "vastanalyticsqueue branch-id={branch} detector-id={detector_id} "
    "expected-downstream-factory={factory} "
    "expected-model-sha256={model_sha256} "
    "expected-weights-sha256={weights_sha256} "
    "max-buffers={max_buffers} ! {factory} "
    "name=checkpoint_detector_{branch} model={model_path} "
    "device={device} batch-size={batch_size} nireq={nireq} "
    "ie-config={ie_config} ! vastanalyticsterminal "
    "branch-id={branch} detector-id={detector_id} "
    "expected-upstream-factory={factory} "
    "expected-model-sha256={model_sha256} "
    "expected-weights-sha256={weights_sha256} "
    "expected-device={device}"
)


class QualificationRuntimeInputMaterializationV2Error(RuntimeError):
    """Physical qualification runtime inputs are incomplete or unsafe."""


ImageInspector = Callable[[Path, Path, str], dict[str, Any]]
DeviceProbe = Callable[[Path, Path, Path, str, str], dict[str, Any]]


@dataclass(frozen=True)
class RuntimeInputMaterializationDependenciesV2:
    inspect_image: ImageInspector
    probe_openvino_device: DeviceProbe


@dataclass(frozen=True)
class _FilePin:
    path: Path
    relative: str
    size: int
    sha256: str
    snapshot: tuple[int, ...]


@dataclass(frozen=True)
class _SourceInventory:
    root: Path
    dataset_pin: _FilePin
    parity_pin: _FilePin
    datasets: dict[str, Any]
    parity: dict[str, Any]
    capability: dict[str, Any]
    calibrations: Mapping[str, Any]
    resource_bindings: Mapping[tuple[str, str], dict[str, Any]]
    policy_bindings: Mapping[tuple[str, str, str], dict[str, Any]]
    analytics_execution_pin: _FilePin
    analytics_bindings: Mapping[tuple[str, str], dict[str, Any]]
    analytics_binding_pins: Mapping[tuple[str, str], _FilePin]
    runtime_probes: Mapping[str, dict[str, Any]]
    runtime_probe_pins: Mapping[str, _FilePin]
    model_pins: tuple[_FilePin, ...]
    support_pins: tuple[_FilePin, ...]
    nvidia: dict[str, str]
    preprocessing_sha256: str


def _fail(message: str) -> None:
    raise QualificationRuntimeInputMaterializationV2Error(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _canonical(value: object) -> bytes:
    return _canonical_bytes(value).rstrip(b"\n")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _fd_hash(fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return size, digest.hexdigest()


def _project_pin(
    root: Path,
    value: str | Path,
    *,
    label: str,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    executable: bool = False,
) -> _FilePin:
    raw = value.as_posix() if isinstance(value, Path) else value
    _require(
        type(raw) is str and raw and "\\" not in raw and "\x00" not in raw,
        f"{label} path is invalid",
    )
    pure = PurePosixPath(raw)
    _require(
        not pure.is_absolute()
        and pure.as_posix() == raw
        and all(part not in {"", ".", ".."} for part in pure.parts),
        f"{label} path is not a canonical project-relative path",
    )
    path = root.joinpath(*pure.parts)
    fd = -1
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        if (
            resolved != path
            or not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(before)
            or int(before.st_nlink) != 1
            or (executable and not int(before.st_mode) & 0o111)
        ):
            raise OSError("unsafe physical file")
        fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(fd)
        size, digest = _fd_hash(fd)
        after = path.lstat()
        if (
            _snapshot(before) != _snapshot(opened)
            or _snapshot(opened) != _snapshot(after)
            or size != int(after.st_size)
            or (expected_size is not None and size != expected_size)
            or (expected_sha256 is not None and digest != expected_sha256)
        ):
            raise OSError("physical identity changed")
    except (OSError, RuntimeError, ValueError) as error:
        _fail(f"{label} physical pin failed: {error}")
    finally:
        if fd >= 0:
            os.close(fd)
    return _FilePin(path, raw, size, digest, _snapshot(after))


def _external_executable_pin(path: Path, *, label: str) -> _FilePin:
    _require(path.is_absolute(), f"{label} must be absolute")
    fd = -1
    try:
        before = path.lstat()
        if (
            path.resolve(strict=True) != path
            or not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or int(before.st_nlink) != 1
            or not int(before.st_mode) & 0o111
        ):
            raise OSError("unsafe executable")
        fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(fd)
        size, digest = _fd_hash(fd)
        after = path.lstat()
        if _snapshot(before) != _snapshot(opened) or _snapshot(opened) != _snapshot(after):
            raise OSError("executable identity changed")
    except (OSError, RuntimeError) as error:
        _fail(f"{label} physical pin failed: {error}")
    finally:
        if fd >= 0:
            os.close(fd)
    return _FilePin(path, path.as_posix(), size, digest, _snapshot(after))


def _descriptor(pin: _FilePin, *, container_path: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": pin.relative,
        "size_bytes": pin.size,
        "sha256": pin.sha256,
    }
    if container_path is not None:
        result["container_path"] = container_path
    return result


def _future_descriptor(
    root: Path,
    final_path: Path,
    payload: bytes,
    *,
    container_path: str | None,
    absolute_host_path: bool = False,
) -> dict[str, Any]:
    relative = final_path.relative_to(root).as_posix()
    result: dict[str, Any] = {
        "path": final_path.as_posix() if absolute_host_path else relative,
        "size_bytes": len(payload),
        "sha256": _sha_bytes(payload),
    }
    if container_path is not None:
        result["container_path"] = container_path
    return result


def _load_yaml(path: Path, *, label: str) -> dict[str, Any]:
    try:
        import yaml

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (ImportError, OSError, UnicodeError, ValueError) as error:
        _fail(f"{label} is not valid YAML: {error}")
    _require(type(value) is dict, f"{label} must contain a mapping")
    return dict(value)


def _load_json_pin(pin: _FilePin, *, label: str) -> dict[str, Any]:
    try:
        payload = pin.path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not valid JSON: {error}")
    _require(
        type(value) is dict
        and payload == _canonical_bytes(value),
        f"{label} is not canonical JSON",
    )
    return dict(value)


def _descriptor_pin(
    root: Path,
    value: Any,
    *,
    label: str,
    size_field: str = "size_bytes",
) -> _FilePin:
    _require(
        type(value) is dict
        and set(value) >= {"path", size_field, "sha256"}
        and type(value.get(size_field)) is int
        and value[size_field] > 0
        and type(value.get("sha256")) is str
        and SHA_RE.fullmatch(value["sha256"]) is not None,
        f"{label} descriptor is invalid",
    )
    return _project_pin(
        root,
        value["path"],
        label=label,
        expected_size=value[size_field],
        expected_sha256=value["sha256"],
    )


def _socket_record(path: Path, *, label: str) -> dict[str, Any]:
    _require(path.is_absolute(), f"{label} path must be absolute")
    try:
        info = path.lstat()
        _require(
            path.resolve(strict=True) == path
            and stat.S_ISSOCK(info.st_mode)
            and not _is_link_or_reparse(info),
            f"{label} is not a canonical live Unix socket",
        )
    except (OSError, RuntimeError) as error:
        _fail(f"{label} physical pin failed: {error}")
    return {
        "path": path.as_posix(),
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "owner_uid": int(info.st_uid),
        "owner_gid": int(info.st_gid),
    }


def _run_json(
    argv: Sequence[str], *, timeout: float, label: str
) -> dict[str, Any] | list[Any]:
    try:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _fail(f"{label} invocation failed: {error}")
    _require(
        completed.returncode == 0 and not completed.stderr,
        f"{label} failed closed",
    )
    try:
        return json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{label} returned invalid JSON: {error}")


def _default_inspect_image(
    engine: Path, engine_socket: Path, image_id: str
) -> dict[str, Any]:
    value = _run_json(
        (
            engine.as_posix(),
            f"--host=unix://{engine_socket.as_posix()}",
            "image",
            "inspect",
            image_id,
        ),
        timeout=60.0,
        label=f"container image inspect {image_id}",
    )
    _require(
        type(value) is list and len(value) == 1 and type(value[0]) is dict,
        f"container image inspect {image_id} cardinality drifted",
    )
    return dict(value[0])


def _default_probe_openvino_device(
    engine: Path,
    engine_socket: Path,
    project_root: Path,
    image_id: str,
    system: str,
) -> dict[str, Any]:
    extra_environment: tuple[str, ...] = ()
    if system == "gstreamer_custom":
        extra_environment = (
            "--env",
            "GST_REGISTRY=/opt/vast/share/gstreamer-registry.bin",
            "--env",
            "GST_REGISTRY_UPDATE=no",
        )
    value = _run_json(
        (
            engine.as_posix(),
            f"--host=unix://{engine_socket.as_posix()}",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--ipc",
            "none",
            "--gpus",
            "all",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=268435456",
            "--mount",
            (
                f"type=bind,src={project_root.as_posix()},"
                "dst=/workspace/project,readonly"
            ),
            "--env",
            "HOME=/tmp",
            "--env",
            "XDG_CACHE_HOME=/tmp",
            *extra_environment,
            "--workdir",
            "/workspace/project",
            "--entrypoint",
            "/usr/bin/python3",
            image_id,
            "-B",
            f"/workspace/project/{DEVICE_PROBE_PATH}",
        ),
        timeout=180.0,
        label=f"{system} OpenVINO device probe",
    )
    _require(type(value) is dict, f"{system} OpenVINO device probe is invalid")
    return dict(value)


DEFAULT_DEPENDENCIES = RuntimeInputMaterializationDependenciesV2(
    inspect_image=_default_inspect_image,
    probe_openvino_device=_default_probe_openvino_device,
)


def _resource_binding_inventory(
    root: Path, index_value: Mapping[str, Any]
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
]:
    rows = index_value.get("bindings")
    _require(type(rows) is list and len(rows) == 32, "candidate binding set drifted")
    fragment_pins: dict[str, Any] = {}
    fragments: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        system_rows = [
            row
            for row in rows
            if type(row) is dict and row.get("system") == system
        ]
        _require(len(system_rows) == 8, f"{system} candidate binding coverage drifted")
        descriptor = system_rows[0].get("fragment_artifact")
        _require(
            all(row.get("fragment_artifact") == descriptor for row in system_rows),
            f"{system} candidate fragment descriptor drifted",
        )
        pin = _pin_json(root, descriptor.get("path"), label=f"{system} fragment")
        _require(
            _descriptor_matches(root, descriptor, pin),
            f"{system} candidate fragment physical binding drifted",
        )
        value = pin.value
        _require(
            set(value)
            == {
                "schema_version",
                "artifact_kind",
                "system",
                "policy_bindings",
                "resource_bindings",
                "pilots",
            }
            and value.get("schema_version") == 1
            and value.get("artifact_kind")
            == "vast_publication_qualification_system_fragment_v1"
            and value.get("system") == system
            and value.get("pilots") == [],
            f"{system} qualification fragment identity drifted",
        )
        fragment_pins[system] = pin
        fragments[system] = value

    result: dict[tuple[str, str], dict[str, Any]] = {}
    policies: dict[tuple[str, str, str], dict[str, Any]] = {}
    binding_schema_versions: set[int] = set()
    physical_identities: set[tuple[int, int]] = set()
    for system in SYSTEMS:
        rows = fragments[system].get("resource_bindings")
        _require(
            type(rows) is list and len(rows) == 2,
            f"{system} resource binding coverage drifted",
        )
        by_resource = {
            row.get("resource"): row for row in rows if type(row) is dict
        }
        _require(
            set(by_resource) == set(RESOURCES),
            f"{system} resource coordinate set drifted",
        )
        for resource in RESOURCES:
            row = by_resource[resource]
            _require(
                row.get("role") == "resource"
                and row.get("branch") == "all_branches"
                and type(row.get("size")) is int
                and row["size"] > 0
                and type(row.get("sha256")) is str
                and SHA_RE.fullmatch(row["sha256"]) is not None,
                f"{system}/{resource} resource fragment row drifted",
            )
            pin = _project_pin(
                root,
                row.get("path"),
                label=f"{system}/{resource} resource binding",
                expected_size=row["size"],
                expected_sha256=row["sha256"],
            )
            identity = (pin.snapshot[0], pin.snapshot[1])
            _require(
                identity not in physical_identities,
                "resource binding physical alias is prohibited",
            )
            physical_identities.add(identity)
            value = _load_json_pin(
                pin, label=f"{system}/{resource} resource binding"
            )
            schema_version = _binding_document_schema(
                value, label=f"{system}/{resource} resource binding"
            )
            _require(
                value.get("system") == system
                and value.get("resource") == resource
                and value.get("role") == "resource"
                and value.get("branch") == "all_branches"
                and value.get("runtime_identity") == row.get("runtime_identity")
                and value.get("implementation_id") == row.get("implementation_id")
                and value.get("emitter_id") == row.get("emitter_id"),
                f"{system}/{resource} resource binding identity drifted",
            )
            binding_schema_versions.add(schema_version)
            result[(system, resource)] = value
    _require(len(result) == 8, "resource binding inventory is incomplete")

    for system in SYSTEMS:
        rows = fragments[system].get("policy_bindings")
        _require(
            type(rows) is list and len(rows) == 8,
            f"{system} policy binding coverage drifted",
        )
        by_coordinate = {
            (row.get("branch"), row.get("resource")): row
            for row in rows
            if type(row) is dict
        }
        _require(
            set(by_coordinate)
            == {(branch, resource) for branch in BRANCHES for resource in RESOURCES},
            f"{system} policy binding coordinate set drifted",
        )
        for branch in BRANCHES:
            for resource in RESOURCES:
                row = by_coordinate[(branch, resource)]
                _require(
                    row.get("role") == "policy"
                    and type(row.get("size")) is int
                    and row["size"] > 0
                    and type(row.get("sha256")) is str
                    and SHA_RE.fullmatch(row["sha256"]) is not None,
                    f"{system}/{branch}/{resource} policy fragment row drifted",
                )
                pin = _project_pin(
                    root,
                    row.get("path"),
                    label=f"{system}/{branch}/{resource} policy binding",
                    expected_size=row["size"],
                    expected_sha256=row["sha256"],
                )
                identity = (pin.snapshot[0], pin.snapshot[1])
                _require(
                    identity not in physical_identities,
                    "candidate binding physical alias is prohibited",
                )
                physical_identities.add(identity)
                value = _load_json_pin(
                    pin, label=f"{system}/{branch}/{resource} policy binding"
                )
                schema_version = _binding_document_schema(
                    value,
                    label=f"{system}/{branch}/{resource} policy binding",
                )
                _require(
                    value.get("system") == system
                    and value.get("resource") == resource
                    and value.get("role") == "policy"
                    and value.get("branch") == branch
                    and value.get("runtime_identity") == row.get("runtime_identity")
                    and value.get("implementation_id")
                    == row.get("implementation_id")
                    and value.get("emitter_id") == row.get("emitter_id"),
                    f"{system}/{branch}/{resource} policy binding identity drifted",
                )
                binding_schema_versions.add(schema_version)
                policies[(system, branch, resource)] = value
    _require(len(policies) == 32, "policy binding inventory is incomplete")
    _require(
        binding_schema_versions in ({1}, {2}),
        "candidate binding document versions are mixed",
    )
    return result, policies


def _binding_document_schema(value: Mapping[str, Any], *, label: str) -> int:
    schema_version = value.get("schema_version")
    if schema_version == 1:
        return 1
    _require(
        schema_version == 2
        and value.get("artifact_kind")
        == "vast_publication_policy_qualification_authority_binding_v2"
        and type(value.get("binding_sha256")) is str
        and SHA_RE.fullmatch(value["binding_sha256"]) is not None
        and value["binding_sha256"]
        == _canonical_sha(
            {key: item for key, item in value.items() if key != "binding_sha256"}
        ),
        f"{label} versioned authority identity drifted",
    )
    return 2


def _authority_descriptor_consensus(
    policy_bindings: Mapping[tuple[str, str, str], Mapping[str, Any]],
    field: str,
) -> dict[str, Any] | None:
    values = [binding.get(field) for binding in policy_bindings.values()]
    versioned = [
        binding.get("schema_version") == 2
        and binding.get("artifact_kind")
        == "vast_publication_policy_qualification_authority_binding_v2"
        for binding in policy_bindings.values()
    ]
    _require(all(versioned) or not any(versioned), "qualification runtime authority versions are mixed")
    if not any(versioned):
        return None
    _require(
        all(type(value) is dict and value == values[0] for value in values),
        f"versioned qualification {field} authority drifted across bindings",
    )
    return dict(values[0])


def _analytics_inventory(
    root: Path,
    policy_bindings: Mapping[tuple[str, str, str], dict[str, Any]],
) -> tuple[
    _FilePin,
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], _FilePin],
    dict[str, dict[str, Any]],
    dict[str, _FilePin],
    tuple[_FilePin, ...],
]:
    execution_authority = _authority_descriptor_consensus(
        policy_bindings, "execution_config"
    )
    index_authority = _authority_descriptor_consensus(
        policy_bindings, "analytics_execution_binding_index"
    )
    if execution_authority is None:
        execution_pin = _project_pin(
            root, ANALYTICS_EXECUTION_PATH, label="analytics execution config"
        )
        index_path = ANALYTICS_BINDING_INDEX_PATH
    else:
        execution_pin = _descriptor_pin(
            root, execution_authority, label="versioned analytics execution config"
        )
        _require(
            type(index_authority) is dict,
            "versioned analytics binding-set authority is absent",
        )
        index_path = str(index_authority.get("path"))
        try:
            from analytics_execution_capability import load_execution_layer_config

            execution_config = load_execution_layer_config(execution_pin.path)
        except Exception as error:
            _fail(f"versioned analytics execution config is invalid: {error}")
        _require(
            execution_config.get("identity", {}).get("sha256")
            == execution_authority.get("content_identity_sha256")
            and _canonical_sha(execution_config.get("workers"))
            == execution_authority.get("worker_projection_sha256"),
            "versioned analytics execution authority identity drifted",
        )
    index_pin = _project_pin(root, index_path, label="analytics binding index")
    if index_authority is not None:
        _require(
            index_pin.size == index_authority.get("size_bytes")
            and index_pin.sha256 == index_authority.get("sha256"),
            "versioned analytics binding-set index descriptor drifted",
        )
    index = _load_json_pin(index_pin, label="analytics binding index")
    records = index.get("files")
    _require(
        index.get("schema_version") == 1
        and index.get("artifact_kind")
        == "vast_analytics_execution_worker_binding_set"
        and type(records) is list
        and len(records) == 8,
        "analytics binding index identity/coverage drifted",
    )
    if index_authority is not None:
        _require(
            index.get("identity", {}).get("sha256")
            == index_authority.get("identity_sha256")
            and index.get("bindings_identity_sha256")
            == index_authority.get("bindings_identity_sha256")
            and index.get("execution_config_identity_sha256")
            == execution_authority.get("content_identity_sha256"),
            "versioned analytics binding-set semantic identity drifted",
        )
    by_name = {
        record.get("path"): record
        for record in records
        if type(record) is dict
    }
    expected_names = {
        f"{branch}.{ENGINE_BY_RESOURCE[resource]}.json"
        for branch in BRANCHES
        for resource in RESOURCES
    }
    _require(
        set(by_name) == expected_names,
        "analytics binding file coordinate set drifted",
    )
    bindings: dict[tuple[str, str], dict[str, Any]] = {}
    binding_pins: dict[tuple[str, str], _FilePin] = {}
    canonical_identities: dict[str, str] = {}
    index_parent = PurePosixPath(index_pin.relative).parent
    for branch in BRANCHES:
        for resource in RESOURCES:
            name = f"{branch}.{ENGINE_BY_RESOURCE[resource]}.json"
            record = by_name[name]
            _require(
                set(record) == {"path", "bytes", "sha256"},
                f"analytics binding {branch}/{resource} descriptor drifted",
            )
            pin = _project_pin(
                root,
                (index_parent / name).as_posix(),
                label=f"analytics binding {branch}/{resource}",
                expected_size=record["bytes"],
                expected_sha256=record["sha256"],
            )
            value = _load_json_pin(
                pin, label=f"analytics binding {branch}/{resource}"
            )
            coordinate_policy_bindings = [
                policy_bindings[(system, branch, resource)]
                for system in SYSTEMS
            ]
            if execution_authority is not None:
                binding_descriptors = [
                    policy_binding.get("analytics_execution_worker_binding")
                    for policy_binding in coordinate_policy_bindings
                ]
                _require(
                    all(
                        type(descriptor) is dict
                        and descriptor == binding_descriptors[0]
                        for descriptor in binding_descriptors
                    )
                    and _descriptor_equals_pin(binding_descriptors[0], pin),
                    f"versioned analytics binding {branch}/{resource} descriptor drifted",
                )
            _require(
                value.get("branch") == branch,
                f"analytics binding {branch}/{resource} branch drifted",
            )
            bindings[(branch, resource)] = value
            binding_pins[(branch, resource)] = pin
            canonical_identities[name] = _canonical_sha(value)
    _require(
        index.get("bindings_identity_sha256")
        == _canonical_sha(canonical_identities),
        "analytics binding-set content identity drifted",
    )

    probes: dict[str, dict[str, Any]] = {}
    probe_pins: dict[str, _FilePin] = {}
    for resource in RESOURCES:
        if execution_authority is None:
            probe_value = ANALYTICS_PROBE_PATHS[resource]
        else:
            resource_rows = [
                value
                for key, value in policy_bindings.items()
                if key[2] == resource
            ]
            descriptors = [
                value.get("analytics_runtime_probe") for value in resource_rows
            ]
            _require(
                all(
                    type(value) is dict and value == descriptors[0]
                    for value in descriptors
                ),
                f"versioned analytics {resource} probe authority drifted",
            )
            probe_value = str(descriptors[0].get("path"))
        pin = _project_pin(root, probe_value, label=f"analytics {resource} runtime probe")
        value = _load_json_pin(pin, label=f"analytics {resource} runtime probe")
        if execution_authority is not None:
            _require(
                _descriptor_equals_pin(descriptors[0], pin)
                and all(
                    row.get("analytics_runtime_probe_identity_sha256")
                    == _canonical_sha(value)
                    for row in resource_rows
                ),
                f"versioned analytics {resource} probe descriptor drifted",
            )
        _require(
            value.get("schema_version") == 1
            and value.get("artifact_kind")
            == "vast_analytics_execution_worker_runtime_probe"
            and value.get("engine") == ENGINE_BY_RESOURCE[resource],
            f"analytics {resource} runtime probe identity drifted",
        )
        probes[resource] = value
        probe_pins[resource] = pin
        for branch in BRANCHES:
            try:
                capability = expected_capability_from_binding_and_probe(
                    binding=bindings[(branch, resource)],
                    runtime_probe=value,
                    resource=resource,
                )
            except Exception as error:
                _fail(
                    f"analytics binding/probe {branch}/{resource} is invalid: {error}"
                )
            _require(
                capability.get("branch") == branch,
                f"analytics capability {branch}/{resource} drifted",
            )
    support = (
        index_pin,
        *(binding_pins[(branch, resource)] for branch in BRANCHES for resource in RESOURCES),
        *(probe_pins[resource] for resource in RESOURCES),
    )
    return execution_pin, bindings, binding_pins, probes, probe_pins, support


def _parity_model_inventory(root: Path, parity: Mapping[str, Any]) -> tuple[_FilePin, ...]:
    source_registry = parity.get("source_registry")
    workload = parity.get("workload_slots")
    _require(
        type(source_registry) is dict
        and len(source_registry) == 4
        and type(workload) is dict
        and set(workload) == set(BRANCHES),
        "accepted parity model inventory drifted",
    )
    records: list[tuple[str, Mapping[str, Any]]] = []
    for source_name, record in sorted(source_registry.items()):
        _require(type(record) is dict, f"parity source {source_name} is invalid")
        records.append((f"parity source {source_name}", record))
    for branch in BRANCHES:
        slot = workload[branch]
        _require(type(slot) is dict, f"parity slot {branch} is invalid")
        openvino = slot.get("openvino_ir")
        tensorrt = slot.get("tensorrt_engine")
        _require(
            type(openvino) is dict and type(tensorrt) is dict,
            f"parity slot {branch} derived artifacts are missing",
        )
        records.extend(
            (
                (f"{branch} OpenVINO model", openvino.get("model")),
                (f"{branch} OpenVINO weights", openvino.get("weights")),
                (f"{branch} TensorRT engine", tensorrt.get("artifact")),
            )
        )
    pins: list[_FilePin] = []
    identities: set[tuple[int, int]] = set()
    digests: set[str] = set()
    for label, record in records:
        pin = _descriptor_pin(root, record, label=label)
        identity = (pin.snapshot[0], pin.snapshot[1])
        _require(
            identity not in identities and pin.sha256 not in digests,
            "parity model artifact alias/digest duplicate is prohibited",
        )
        identities.add(identity)
        digests.add(pin.sha256)
        pins.append(pin)
    _require(len(pins) == 16, "accepted parity model inventory must contain 16 files")
    return tuple(pins)


def _load_source_inventory(inputs: Any) -> _SourceInventory:
    root = inputs.root
    dataset_descriptor = inputs.candidate_index.value.get("dataset_manifest")
    dataset_pin = _descriptor_pin(
        root, dataset_descriptor, label="candidate dataset manifest"
    )
    _require(
        dataset_pin.relative == DATASETS_PATH,
        "candidate dataset manifest is not configs/datasets.yaml",
    )
    datasets_document = _load_yaml(dataset_pin.path, label="candidate datasets")
    datasets = datasets_document.get("datasets")
    _require(type(datasets) is dict, "candidate dataset registry is missing")

    receipt = inputs.bootstrap_receipt.value
    parity_pin = _descriptor_pin(
        root,
        receipt.get("accepted_model_parity_manifest"),
        label="accepted parity manifest",
    )
    parity = _load_yaml(parity_pin.path, label="accepted parity manifest")
    preprocessing = parity.get("preprocessing_contract")
    _require(
        type(preprocessing) is dict
        and _canonical_sha(preprocessing) == PREPROCESSING_SHA256,
        "accepted preprocessing contract identity drifted",
    )
    _require(
        (
            (
                parity.get("schema_version") == 3
                and parity.get("artifact_kind")
                == "checkpoint_analytics_model_parity_manifest"
            )
            or (
                parity.get("schema_version") == 4
                and parity.get("artifact_kind")
                == "checkpoint_analytics_model_parity_manifest_v4"
            )
        )
        and parity.get("required_branches") == list(BRANCHES),
        "accepted parity manifest identity drifted",
    )

    resource_bindings, policy_bindings = _resource_binding_inventory(
        root, inputs.candidate_index.value
    )
    (
        analytics_execution_pin,
        analytics_bindings,
        analytics_binding_pins,
        runtime_probes,
        runtime_probe_pins,
        analytics_support,
    ) = _analytics_inventory(root, policy_bindings)
    model_pins = _parity_model_inventory(root, parity)

    extra_support = []
    for field, label in (
        ("accepted_model_parity_assessment", "accepted parity assessment"),
        ("accepted_model_parity_receipt", "accepted parity receipt"),
    ):
        extra_support.append(
            _descriptor_pin(root, receipt.get(field), label=label)
        )
    support_pins = (*analytics_support, *extra_support)
    _require(
        len({(pin.snapshot[0], pin.snapshot[1]) for pin in support_pins})
        == len(support_pins)
        and len({pin.sha256 for pin in support_pins}) == len(support_pins),
        "support artifact alias/digest duplicate is prohibited",
    )

    toolchain = parity.get("toolchain_registry")
    gpu = toolchain.get("tensorrt_cuda") if type(toolchain) is dict else None
    _require(
        type(gpu) is dict
        and type(gpu.get("gpu_uuid")) is str
        and type(gpu.get("gpu_name")) is str
        and type(gpu.get("driver_version")) is str,
        "accepted NVIDIA toolchain binding is missing",
    )
    nvidia = {
        "uuid": gpu["gpu_uuid"],
        "name": gpu["gpu_name"],
        "driver_version": gpu["driver_version"],
    }
    for system in ("savant", "openvino_gva", "gstreamer_custom"):
        for resource in RESOURCES:
            binding = resource_bindings[(system, resource)]
            hardware = binding.get("nvidia_hardware_binding")
            if type(hardware) is dict:
                observed = {
                    key: hardware.get(key)
                    for key in ("uuid", "name", "driver_version")
                }
                _require(
                    observed == nvidia,
                    f"{system}/{resource} NVIDIA binding differs from accepted parity",
                )

    return _SourceInventory(
        root=root,
        dataset_pin=dataset_pin,
        parity_pin=parity_pin,
        datasets=dict(datasets),
        parity=parity,
        capability=inputs.candidate_manifest.value,
        calibrations=inputs.calibrations,
        resource_bindings=resource_bindings,
        policy_bindings=policy_bindings,
        analytics_execution_pin=analytics_execution_pin,
        analytics_bindings=analytics_bindings,
        analytics_binding_pins=analytics_binding_pins,
        runtime_probes=runtime_probes,
        runtime_probe_pins=runtime_probe_pins,
        model_pins=model_pins,
        support_pins=tuple(support_pins),
        nvidia=nvidia,
        preprocessing_sha256=PREPROCESSING_SHA256,
    )


def _descriptor_equals_pin(value: Any, pin: _FilePin) -> bool:
    return (
        type(value) is dict
        and value.get("path") == pin.relative
        and value.get("size_bytes") == pin.size
        and value.get("sha256") == pin.sha256
    )


def _preflight_savant_reachable_worker(root: Path) -> None:
    pins = {
        path: _project_pin(root, path, label=f"reachable Savant source {path}")
        for path in SAVANT_REACHABLE_RUNTIME_SOURCES
    }
    try:
        allowlist = pins[
            "deploy/savant/publication/runtime-source-allowlist.txt"
        ].path.read_text(encoding="utf-8").splitlines()
        dockerfile = pins["deploy/savant/publication/Dockerfile"].path.read_text(
            encoding="utf-8"
        )
        entrypoint = pins[
            "deploy/savant/publication/vast_savant_checkpoint_runtime"
        ].path.read_text(encoding="utf-8")
        specs_source = pins[
            "scripts/checkpoint_savant_publication_specs_v3.py"
        ].path.read_text(encoding="utf-8")
        sdk_source = pins["scripts/checkpoint_savant_sdk_runtime_v3.py"].path.read_text(
            encoding="utf-8"
        )
        specs_tree = ast.parse(specs_source)
        sdk_tree = ast.parse(sdk_source)
    except (OSError, UnicodeError, SyntaxError) as error:
        _fail(f"reachable Savant runtime closure cannot be parsed: {error}")
    listed = {
        line.strip()
        for line in allowlist
        if line.strip() and not line.lstrip().startswith("#")
    }
    for required in (
        "deploy/savant/publication/vast_savant_checkpoint_runtime",
        "scripts/checkpoint_savant_container_runtime_v3.py",
        "scripts/checkpoint_savant_publication_specs_v3.py",
        "scripts/checkpoint_savant_sdk_runtime_v3.py",
    ):
        _require(required in listed, f"reachable Savant allowlist omits {required}")
    _require(
        f'ENTRYPOINT ["{SAVANT_ENTRYPOINT_TARGET}"]' in dockerfile
        and "scripts/checkpoint_savant_sdk_runtime_v3.py" in dockerfile,
        "Savant Docker closure does not bind its entrypoint and SDK worker",
    )
    _require(
        "/opt/vast/checkpoint/checkpoint_savant_container_runtime_v3.py" in entrypoint
        and '"arm"' in entrypoint,
        "Savant entrypoint does not reach the v3 arm coordinator",
    )
    specs_literals = {
        node.value
        for node in ast.walk(specs_tree)
        if isinstance(node, ast.Constant) and type(node.value) is str
    }
    sdk_literals = {
        node.value
        for node in ast.walk(sdk_tree)
        if isinstance(node, ast.Constant) and type(node.value) is str
    }
    _require(
        SAVANT_SDK_WORKER_TARGET in specs_literals and "run" in specs_literals,
        "Savant worker specs do not invoke the image-local SDK v3 run path",
    )
    _require(
        "run" in sdk_literals and "vast_savant_sdk_worker_exit_v3" in sdk_literals,
        "Savant SDK worker has no reachable run/terminal receipt path",
    )


def _normalized_manifest_model_path(raw: Any) -> str:
    _require(type(raw) is str and bool(raw), "local OMZ model path is invalid")
    pure = PurePosixPath("configs") / PurePosixPath(raw)
    normalized = PurePosixPath(posixpath.normpath(pure.as_posix()))
    _require(
        not normalized.is_absolute()
        and all(part not in {"", ".", ".."} for part in normalized.parts),
        "local OMZ model path escapes project_root",
    )
    return normalized.as_posix()


def _validate_dual_execution_contract(inventory: _SourceInventory) -> None:
    manifest_pin = _project_pin(
        inventory.root,
        OPENVINO_MODEL_MANIFEST_PATH,
        label="OpenVINO/GStreamer nonterminal model manifest",
    )
    manifest = _load_yaml(
        manifest_pin.path, label="OpenVINO/GStreamer nonterminal model manifest"
    )
    manifest_branches = manifest.get("branches")
    _require(
        manifest.get("schema_version") == 2
        and manifest.get("artifact_kind") == "checkpoint_analytics_model_bindings"
        and type(manifest_branches) is dict
        and set(manifest_branches) == set(BRANCHES),
        "OpenVINO/GStreamer nonterminal model manifest drifted",
    )
    for branch in BRANCHES:
        local_manifest = manifest_branches[branch]
        _require(
            type(local_manifest) is dict
            and local_manifest.get("semantic_claim") == "topology_load_proxy_only",
            f"{branch} local OMZ binding is not explicitly nonterminal",
        )
        expected_local = {
            "detector_id": local_manifest.get("detector_id"),
            "device": local_manifest.get("device"),
            "factory": local_manifest.get("factory"),
            "model": {
                "path": _normalized_manifest_model_path(
                    local_manifest.get("model_path")
                ),
                "sha256": local_manifest.get("model_sha256"),
            },
            "weights": {
                "path": _normalized_manifest_model_path(
                    local_manifest.get("weights_path")
                ),
                "sha256": local_manifest.get("weights_sha256"),
            },
        }
        for system, field in (
            ("openvino_gva", "gva_sdk_binding_nonterminal"),
            ("gstreamer_custom", "openvino_cpu_binding"),
        ):
            for resource in RESOURCES:
                policy = inventory.policy_bindings[(system, branch, resource)]
                local = policy.get(field)
                _require(type(local) is dict, f"{system}/{branch}/{resource} local proxy is missing")
                for name in ("detector_id", "device", "factory"):
                    _require(
                        local.get(name) == expected_local[name],
                        f"{system}/{branch}/{resource} local OMZ {name} drifted",
                    )
                for role in ("model", "weights"):
                    descriptor = local.get(role)
                    expected = expected_local[role]
                    _require(
                        type(descriptor) is dict
                        and descriptor.get("path") == expected["path"]
                        and descriptor.get("sha256") == expected["sha256"],
                        f"{system}/{branch}/{resource} local OMZ {role} drifted",
                    )
                    _descriptor_pin(
                        inventory.root,
                        descriptor,
                        label=f"{system}/{branch}/{resource} local OMZ {role}",
                    )
                if system == "openvino_gva":
                    _require(
                        policy.get("terminal_authority")
                        == "external_analytics_execution_worker_only",
                        f"{system}/{branch}/{resource} terminal authority drifted",
                    )

                binding = inventory.analytics_bindings[(branch, resource)]
                binding_pin = inventory.analytics_binding_pins[(branch, resource)]
                probe = inventory.runtime_probes[resource]
                probe_pin = inventory.runtime_probe_pins[resource]
                identity = policy.get("analytics_execution_worker_binding_identity")
                runtime_identity = policy.get("runtime_identity")
                try:
                    capability = expected_capability_from_binding_and_probe(
                        binding=binding, runtime_probe=probe, resource=resource
                    )
                    expected_terminal_detector = terminal_detector_identity(capability)
                except Exception as error:
                    _fail(
                        f"{system}/{branch}/{resource} terminal capability is invalid: {error}"
                    )
                _require(
                    _descriptor_equals_pin(
                        policy.get("analytics_execution_worker_binding"), binding_pin
                    )
                    and _descriptor_equals_pin(
                        policy.get("analytics_runtime_probe"), probe_pin
                    )
                    and type(identity) is dict
                    and type(runtime_identity) is dict
                    and identity.get("artifact_kind") == binding.get("artifact_kind")
                    and identity.get("model_id") == binding.get("model_id")
                    and identity.get("model_artifact_sha256")
                    == binding.get("model_artifact_sha256")
                    and identity.get("worker_image_id")
                    == binding.get("worker_image_id")
                    and runtime_identity.get("terminal_detector")
                    == expected_terminal_detector
                    and runtime_identity.get("worker_image_digest")
                    == binding.get("worker_image_id")
                    and runtime_identity.get("implementation_version")
                    == f"sha256:{probe.get('worker_implementation_sha256')}",
                    f"{system}/{branch}/{resource} terminal worker identity drifted",
                )
                _require(
                    expected_terminal_detector == runtime_identity["terminal_detector"]
                    and capability.get("worker_image_id")
                    == runtime_identity["worker_image_digest"],
                    f"{system}/{branch}/{resource} terminal capability drifted",
                )


def _preflight_reachable_runtime_contracts(inventory: _SourceInventory) -> None:
    _preflight_savant_reachable_worker(inventory.root)
    _validate_dual_execution_contract(inventory)


def _image_material(binding: Mapping[str, Any], system: str) -> dict[str, Any]:
    if system == "deepstream":
        raw = binding.get("image_identity")
        _require(type(raw) is dict, "DeepStream runtime image identity is missing")
        return {
            "final_reference": raw.get("final_reference"),
            "image_id": raw.get("image_id"),
            "repository_digest": raw.get("repository_digest"),
            "coordinator_path": raw.get("entrypoint"),
        }
    if system == "savant":
        material = binding.get("savant_runtime_image")
        identity = material.get("identity") if type(material) is dict else None
        _require(type(identity) is dict, "Savant runtime image identity is missing")
        digests = identity.get("repository_digests")
        _require(
            type(digests) is list and len(digests) == 1,
            "Savant runtime repository digest coverage drifted",
        )
        entrypoint = identity.get("entrypoint")
        _require(
            type(entrypoint) is list and len(entrypoint) == 1,
            "Savant runtime image entrypoint drifted",
        )
        return {
            "final_reference": identity.get("final_reference"),
            "image_id": identity.get("image_id"),
            "repository_digest": digests[0],
            "coordinator_path": entrypoint[0],
        }
    key = (
        "openvino_gva_runtime_image"
        if system == "openvino_gva"
        else "gstreamer_runtime_image"
    )
    raw = binding.get(key)
    _require(type(raw) is dict, f"{system} runtime image identity is missing")
    return dict(raw)


def _validate_raw_image(
    value: Mapping[str, Any],
    *,
    system: str,
    image_id: str,
    repository_digest: str,
    entrypoint: str,
    required_labels: Mapping[str, str],
) -> str:
    config = value.get("Config")
    _require(
        value.get("Id") == image_id
        and value.get("Os") == "linux"
        and value.get("Architecture") == "amd64"
        and type(config) is dict
        and config.get("Entrypoint") == [entrypoint]
        and type(config.get("Labels")) is dict
        and all(
            config["Labels"].get(key) == expected
            for key, expected in required_labels.items()
        )
        and repository_digest in (value.get("RepoDigests") or []),
        f"{system} live runtime image differs from its resource binding",
    )
    return _sha_bytes(_canonical(dict(value)))


def _inspect_runtime_images(
    inventory: _SourceInventory,
    *,
    engine: Path,
    engine_socket: Path,
    dependencies: RuntimeInputMaterializationDependenciesV2,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        cpu = _image_material(inventory.resource_bindings[(system, "cpu")], system)
        gpu = _image_material(inventory.resource_bindings[(system, "gpu")], system)
        _require(cpu == gpu, f"{system} CPU/GPU runtime image binding drifted")
        image_id = cpu.get("image_id")
        repository_digest = cpu.get("repository_digest")
        final_reference = cpu.get("final_reference")
        _require(
            type(image_id) is str
            and IMAGE_ID_RE.fullmatch(image_id) is not None
            and type(repository_digest) is str
            and "@sha256:" in repository_digest,
            f"{system} runtime image ID/repository digest is invalid",
        )
        repository = repository_digest.partition("@")[0]
        _require(
            type(final_reference) is str
            and IMAGE_REFERENCE_RE.fullmatch(final_reference) is not None
            and final_reference.startswith(repository + ":"),
            f"{system} runtime image reference is invalid",
        )
        if system == "openvino_gva":
            _require(
                final_reference == openvino_runtime.EXPECTED_IMAGE_REFERENCE,
                "OpenVINO resource binding reference differs from the lower runtime constant",
            )
        elif system == "gstreamer_custom":
            _require(
                final_reference == gstreamer_runtime.EXPECTED_IMAGE_REFERENCE,
                "GStreamer resource binding reference differs from the lower runtime constant",
            )
        try:
            inspected = dependencies.inspect_image(
                engine, engine_socket, final_reference,
            )
        except QualificationRuntimeInputMaterializationV2Error:
            raise
        except Exception as error:
            _fail(f"{system} image inspect dependency failed: {error}")
        _require(type(inspected) is dict, f"{system} image inspect result is invalid")

        if system == "deepstream":
            inspect_sha = _validate_raw_image(
                inspected,
                system=system,
                image_id=image_id,
                repository_digest=repository_digest,
                entrypoint=deepstream_runtime.EXPECTED_COORDINATOR_PATH,
                required_labels=deepstream_runtime.REQUIRED_IMAGE_LABELS,
            )
            _require(
                cpu.get("coordinator_path")
                == deepstream_runtime.EXPECTED_COORDINATOR_PATH,
                "DeepStream resource binding coordinator path drifted",
            )
            contract = {
                "image_id": image_id,
                "repository_digest": repository_digest,
                "inspect_sha256": inspect_sha,
                "coordinator_path": deepstream_runtime.EXPECTED_COORDINATOR_PATH,
                "required_labels": dict(deepstream_runtime.REQUIRED_IMAGE_LABELS),
            }
        elif system == "savant":
            inspect_sha = _validate_raw_image(
                inspected,
                system=system,
                image_id=image_id,
                repository_digest=repository_digest,
                entrypoint=savant_runtime.EXPECTED_COORDINATOR_PATH,
                required_labels=savant_runtime.REQUIRED_IMAGE_LABELS,
            )
            _require(
                cpu.get("coordinator_path") == savant_runtime.EXPECTED_COORDINATOR_PATH,
                "Savant resource binding coordinator path drifted",
            )
            contract = {
                "image_id": image_id,
                "repository_digest": repository_digest,
                "inspect_sha256": inspect_sha,
                "coordinator_path": savant_runtime.EXPECTED_COORDINATOR_PATH,
                "required_labels": dict(savant_runtime.REQUIRED_IMAGE_LABELS),
            }
        elif system == "openvino_gva":
            _require(
                image_id == openvino_runtime.EXPECTED_IMAGE_ID
                and repository_digest == openvino_runtime.EXPECTED_REPOSITORY_DIGEST
                and cpu.get("inspect_projection_sha256")
                == openvino_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
                "OpenVINO resource binding differs from the lower runtime constants",
            )
            try:
                projection = openvino_runtime._image_projection(inspected)
                projection_sha = openvino_runtime.image_projection_sha256(projection)
            except Exception as error:
                _fail(f"OpenVINO image projection is invalid: {error}")
            _require(
                projection_sha
                == openvino_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
                "OpenVINO live image inspect projection drifted",
            )
            contract = {
                "image_id": image_id,
                "repository_digest": repository_digest,
                "inspect_projection_sha256": projection_sha,
            }
        else:
            _require(
                image_id == gstreamer_runtime.EXPECTED_IMAGE_ID
                and repository_digest == gstreamer_runtime.EXPECTED_REPOSITORY_DIGEST
                and cpu.get("base_image_id")
                == gstreamer_runtime.EXPECTED_BASE_IMAGE_ID
                and cpu.get("inspect_projection_sha256")
                == gstreamer_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
                "GStreamer resource binding differs from the lower runtime constants",
            )
            try:
                projection = gstreamer_runtime._image_projection(inspected)
                projection_sha = gstreamer_runtime.image_projection_sha256(projection)
            except Exception as error:
                _fail(f"GStreamer image projection is invalid: {error}")
            _require(
                projection_sha
                == gstreamer_runtime.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256,
                "GStreamer live image inspect projection drifted",
            )
            contract = {
                "image_id": image_id,
                "repository_digest": repository_digest,
                "inspect_projection_sha256": projection_sha,
                "base_image_id": gstreamer_runtime.EXPECTED_BASE_IMAGE_ID,
            }
        result[system] = {
            "contract": contract,
            "inspect_sha256": _sha_bytes(_canonical(dict(inspected))),
        }
    return result


def _probe_devices(
    inventory: _SourceInventory,
    images: Mapping[str, Mapping[str, Any]],
    *,
    engine: Path,
    engine_socket: Path,
    dependencies: RuntimeInputMaterializationDependenciesV2,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for system, module in (
        ("openvino_gva", openvino_runtime),
        ("gstreamer_custom", gstreamer_runtime),
    ):
        image_id = images[system]["contract"]["image_id"]
        try:
            value = dependencies.probe_openvino_device(
                engine, engine_socket, inventory.root, image_id, system
            )
        except QualificationRuntimeInputMaterializationV2Error:
            raise
        except Exception as error:
            _fail(f"{system} device probe dependency failed: {error}")
        devices = value.get("available_devices") if type(value) is dict else None
        elements = value.get("gstreamer_elements") if type(value) is dict else None
        required_elements = module.REQUIRED_GSTREAMER_ELEMENTS
        _require(
            value.get("schema_version") == 1
            and value.get("artifact_kind") == "vast_openvino_checkpoint_device_probe"
            and type(value.get("openvino_version")) is str
            and bool(value["openvino_version"].strip())
            and type(devices) is list
            and any(
                type(item) is dict and item.get("device_id") == "CPU"
                for item in devices
            )
            and type(elements) is dict
            and all(
                type(elements.get(name)) is dict
                and elements[name].get("available") is True
                for name in required_elements
            ),
            f"{system} live OpenVINO/GStreamer device probe is incomplete",
        )
        result[system] = {
            "value": dict(value),
            "sha256": _sha_bytes(_canonical(dict(value))),
        }
    return result


def _bundle_value_v2(
    cell: QualificationPilotCellV2,
    runtime_inputs: Mapping[str, Any],
    *,
    hardware_resource_collector: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = dict(runtime_inputs)
    runtime_key = RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
    dataset = runtime.get("dataset")
    contract = dataset.get(runtime_key) if type(dataset) is dict else None
    expected = {
        "system": cell.system,
        "resource": cell.resource,
        "scenario": cell.scenario,
        "topology_kind": cell.topology_kind,
        "codec": cell.codec,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "duration_s": cell.duration_s,
        "streams": 6,
        "run_id": cell.run_id,
    }
    _require(
        all(runtime.get(key) == value for key, value in expected.items())
        and type(contract) is dict
        and contract.get("defer_full_resource_acceptance") is True
        and contract.get("evidence_mapping")
        == {name: name for name in CHILD_EVIDENCE_FILES},
        f"{cell.arm_id} runtime input identity/deferred acceptance drifted",
    )
    try:
        _walk_forbidden_production_claims(
            runtime, location=f"materialized runtime {cell.arm_id}"
        )
    except Exception as error:
        _fail(f"{cell.arm_id} runtime contains a production authority claim: {error}")
    _require(
        type(hardware_resource_collector) is dict
        and set(hardware_resource_collector)
        == {"path", "size_bytes", "sha256"}
        and hardware_resource_collector.get("path") == "scripts/collect_metrics.py"
        and type(hardware_resource_collector.get("size_bytes")) is int
        and hardware_resource_collector["size_bytes"] > 0
        and type(hardware_resource_collector.get("sha256")) is str
        and SHA_RE.fullmatch(hardware_resource_collector["sha256"]) is not None,
        f"{cell.arm_id} hardware resource collector descriptor drifted",
    )
    unsigned = {
        "schema_version": 2,
        "artifact_kind": RUNTIME_BUNDLE_KIND,
        "status": "materialized_for_native_qualification_only",
        "accepted": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "scope": RUNTIME_BUNDLE_SCOPE,
        "system": cell.system,
        "resource": cell.resource,
        "codec": cell.codec,
        "topology_kind": cell.topology_kind,
        "run_id": cell.run_id,
        "arm_id": cell.arm_id,
        "hardware_resource_collector": dict(hardware_resource_collector),
        "runtime_inputs": runtime,
        "launcher_evidence_files": list(CHILD_EVIDENCE_FILES),
    }
    return {**unsigned, "bundle_sha256": _canonical_sha(unsigned)}


def _write_exclusive_bytes(path: Path, payload: bytes, *, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    try:
        fd = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(fd)
        os.fchmod(fd, mode)
    except OSError as error:
        _fail(f"immutable materialization write failed for {path.name}: {error}")
    finally:
        if fd >= 0:
            os.close(fd)


def _write_bundle_tree_v2(
    tree: Path,
    *,
    cells: Sequence[QualificationPilotCellV2],
    runtime_factory: Callable[[QualificationPilotCellV2], Mapping[str, Any]],
    hardware_resource_collector: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    _require(
        tuple(cells) == qualification_pilot_cells_v2(),
        "runtime input materialization requires the exact 32-cell matrix",
    )
    records: list[dict[str, Any]] = []
    for cell in cells:
        relative = (
            Path(cell.system)
            / cell.resource
            / cell.codec
            / f"{cell.topology_kind}.json"
        )
        path = tree / relative
        value = _bundle_value_v2(
            cell,
            runtime_factory(cell),
            hardware_resource_collector=hardware_resource_collector,
        )
        payload = _canonical_bytes(value)
        _write_exclusive_bytes(path, payload)
        records.append(
            {
                "arm_id": cell.arm_id,
                "run_id": cell.run_id,
                "path": relative.as_posix(),
                "size_bytes": len(payload),
                "sha256": _sha_bytes(payload),
                "bundle_sha256": value["bundle_sha256"],
            }
        )
    _require(
        len(records) == 32
        and len({record["arm_id"] for record in records}) == 32
        and len({record["run_id"] for record in records}) == 32
        and len({record["path"] for record in records}) == 32
        and len({record["sha256"] for record in records}) == 32,
        "materialized runtime input bundle identities are not unique",
    )
    return tuple(records)


def _json_descriptor(
    root: Path, pin: Any, *, container_path: str | None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": pin.path.relative_to(root).as_posix(),
        "size_bytes": int(pin.snapshot[4]),
        "sha256": pin.sha256,
    }
    if container_path is not None:
        result["container_path"] = container_path
    return result


def _future_pin_descriptor(
    root: Path,
    final_path: Path,
    *,
    size: int,
    sha256: str,
    container_path: str | None,
) -> dict[str, Any]:
    _require(
        final_path.is_absolute()
        and final_path.is_relative_to(root)
        and type(size) is int
        and size > 0
        and SHA_RE.fullmatch(sha256) is not None,
        "future immutable file descriptor is invalid",
    )
    value: dict[str, Any] = {
        "path": final_path.relative_to(root).as_posix(),
        "size_bytes": size,
        "sha256": sha256,
    }
    if container_path is not None:
        value["container_path"] = container_path
    return value


def _project_container_path(relative: str) -> str:
    return f"/workspace/project/{relative}"


def _sdk_container_path(category: str, relative: str) -> str:
    _require(
        category in {"runtime", "sources", "models", "support"},
        "SDK materialization category is invalid",
    )
    return f"/opt/vast/input/{category}/{relative}"


def _dataset_material(
    inventory: _SourceInventory, codec: str
) -> tuple[dict[str, Any], tuple[_FilePin, ...]]:
    name = f"kpp_iss_publication_v3_{codec}"
    value = inventory.datasets.get(name)
    _require(
        type(value) is dict
        and value.get("kind") == "frozen_publication_codec_corpus"
        and value.get("generation_id") == "kpp_iss_publication_v3"
        and value.get("dataset_contract_version") == 3
        and value.get("codec_variant") == codec
        and value.get("logical_stream_instances") == 6
        and value.get("status") == "frozen_publication_corpus"
        and value.get("publication_scope")
        == "performance_and_topology_benchmark_results_only",
        f"{name} frozen dataset identity drifted",
    )
    streams = value.get("streams")
    _require(type(streams) is list and len(streams) == 6, f"{name} streams drifted")
    by_id = {
        item.get("stream_id"): item
        for item in streams
        if type(item) is dict and type(item.get("stream_id")) is int
    }
    _require(set(by_id) == set(range(6)), f"{name} stream coordinates drifted")
    provenance = value.get("provenance")
    media = provenance.get("media_artifacts") if type(provenance) is dict else None
    _require(type(media) is list and len(media) == 2, f"{name} media pins drifted")
    media_by_path = {
        item.get("path"): item for item in media if type(item) is dict
    }
    unique_paths = {by_id[index].get("path") for index in range(6)}
    _require(
        len(unique_paths) == 2 and set(media_by_path) == unique_paths,
        f"{name} stream/media path binding drifted",
    )
    pins_by_path: dict[str, _FilePin] = {}
    normalized_streams: list[dict[str, Any]] = []
    for index in range(6):
        stream = by_id[index]
        raw_codec = str(stream.get("codec_name", "")).strip().lower()
        normalized_codec = "h265" if raw_codec == "hevc" else raw_codec
        path = stream.get("path")
        digest = stream.get("sha256")
        _require(
            normalized_codec == codec
            and type(path) is str
            and path in media_by_path
            and type(digest) is str
            and SHA_RE.fullmatch(digest) is not None
            and media_by_path[path].get("sha256") == digest,
            f"{name} stream {index} identity drifted",
        )
        if path not in pins_by_path:
            descriptor = media_by_path[path]
            pins_by_path[path] = _project_pin(
                inventory.root,
                path,
                label=f"{name} media {path}",
                expected_size=descriptor.get("size_bytes"),
                expected_sha256=digest,
            )
        normalized_streams.append(
            {"stream_id": index, "codec_name": codec, "sha256": digest}
        )
    _require(
        all(by_id[index].get("path") == by_id[0].get("path") for index in range(5))
        and by_id[5].get("path") != by_id[0].get("path"),
        f"{name} must map streams 0..4 to front gate and 5 to underbody",
    )
    pins = tuple(pins_by_path[path] for path in sorted(pins_by_path))
    return (
        {
            "name": name,
            "codec_variant": codec,
            "logical_stream_instances": 6,
            "streams": normalized_streams,
        },
        pins,
    )


def _source_descriptors(
    pins: Sequence[_FilePin], *, system: str
) -> list[dict[str, Any]]:
    result = []
    for pin in pins:
        target = (
            _sdk_container_path("sources", pin.relative)
            if system in {"deepstream", "savant"}
            else _project_container_path(pin.relative)
        )
        result.append(_descriptor(pin, container_path=target))
    return result


def _local_omz_model_pins(inventory: _SourceInventory) -> tuple[_FilePin, ...]:
    pins: dict[str, _FilePin] = {}
    for branch in BRANCHES:
        policy = inventory.policy_bindings[("openvino_gva", branch, "cpu")]
        local = policy.get("gva_sdk_binding_nonterminal")
        _require(type(local) is dict, f"{branch} local OMZ binding is missing")
        for role in ("model", "weights"):
            pin = _descriptor_pin(
                inventory.root,
                local.get(role),
                label=f"{branch} local OMZ {role}",
            )
            previous = pins.get(pin.relative)
            _require(
                previous is None or previous.sha256 == pin.sha256,
                "local OMZ model path has multiple physical identities",
            )
            pins[pin.relative] = pin
    _require(len(pins) == 8, "local OMZ model inventory must contain eight files")
    return tuple(pins[path] for path in sorted(pins))


def _model_descriptors(
    inventory: _SourceInventory, *, system: str
) -> list[dict[str, Any]]:
    pins = list(inventory.model_pins)
    if system in {"openvino_gva", "gstreamer_custom"}:
        pins.extend(_local_omz_model_pins(inventory))
    _require(
        len({pin.relative for pin in pins}) == len(pins)
        and len({(pin.snapshot[0], pin.snapshot[1]) for pin in pins}) == len(pins),
        f"{system} model descriptor set contains an alias",
    )
    return [
        _descriptor(
            pin,
            container_path=(
                _sdk_container_path("models", pin.relative)
                if system in {"deepstream", "savant"}
                else _project_container_path(pin.relative)
            ),
        )
        for pin in pins
    ]


def _support_target(pin: _FilePin, *, system: str) -> str:
    return (
        _sdk_container_path("support", pin.relative)
        if system in {"deepstream", "savant"}
        else _project_container_path(pin.relative)
    )


def _support_descriptors(
    inventory: _SourceInventory, *, system: str
) -> list[dict[str, Any]]:
    _require(system in SYSTEMS, "runtime support system is invalid")
    pins: Sequence[_FilePin] = inventory.support_pins
    if system in {"deepstream", "savant"}:
        pins = (
            *(
                inventory.analytics_binding_pins[(branch, resource)]
                for branch in BRANCHES
                for resource in RESOURCES
            ),
            *(inventory.runtime_probe_pins[resource] for resource in RESOURCES),
        )
        selected = {
            (pin.relative, pin.size, pin.sha256, pin.snapshot) for pin in pins
        }
        inventory_keys = {
            (pin.relative, pin.size, pin.sha256, pin.snapshot)
            for pin in inventory.support_pins
        }
        _require(
            len(pins) == len(BRANCHES) * len(RESOURCES) + len(RESOURCES)
            and len(selected) == len(pins)
            and selected <= inventory_keys,
            f"{system} adapter support closure differs from the validated inventory",
        )
    return [
        _descriptor(pin, container_path=_support_target(pin, system=system))
        for pin in pins
    ]


def _adapter_asset(
    inventory: _SourceInventory,
    *,
    system: str,
    final_root: Path,
) -> tuple[Path, bytes, dict[str, Any]]:
    _require(system in SYSTEMS, "adapter system is invalid")
    if system in {"openvino_gva", "gstreamer_custom"}:
        # These runtimes route terminal inference to the same authenticated
        # workers as the SDK adapters; legacy in-process detector manifests
        # cannot describe their actual CPU/TensorRT execution paths.
        value = {
            "schema_version": 1,
            "artifact_kind": "vast_checkpoint_external_analytics_execution_manifest_v1",
            "system": system,
            "execution_config": _descriptor(inventory.analytics_execution_pin, container_path=None),
            "policy_capability_manifest_sha256": _canonical_sha(inventory.capability),
            "branches": {
                branch: {
                    resource: expected_capability_from_binding_and_probe(
                        binding=inventory.analytics_bindings[(branch, resource)],
                        runtime_probe=inventory.runtime_probes[resource],
                        resource=resource,
                    )
                    for resource in RESOURCES
                }
                for branch in BRANCHES
            },
        }
        payload = _canonical_bytes(value)
        path = final_root / ASSET_DIRECTORY / system / "analytics-execution-manifest.json"
        return path, payload, _future_descriptor(
            inventory.root, path, payload,
            container_path=_project_container_path(path.relative_to(inventory.root).as_posix()),
        )
    branches: dict[str, Any] = {}
    for branch in BRANCHES:
        branches[branch] = {}
        for resource in RESOURCES:
            binding_pin = inventory.analytics_binding_pins[(branch, resource)]
            probe_pin = inventory.runtime_probe_pins[resource]
            policy = inventory.policy_bindings[(system, branch, resource)]
            implementation_id = policy.get("implementation_id")
            _require(
                type(implementation_id) is str and bool(implementation_id),
                f"{system}/{branch}/{resource} implementation ID is missing",
            )
            branches[branch][resource] = {
                "implementation_id": implementation_id,
                "socket_path": "/run/vast/analytics.sock",
                "binding_path": _support_target(binding_pin, system=system),
                "runtime_probe_path": _support_target(probe_pin, system=system),
            }
    value = {
        "schema_version": 1,
        "artifact_kind": "vast_deepstream_protocol_adapter_config",
        "claim_status": "native_sdk_adapter_requires_external_acceptance",
        "preprocessing_manifest_path": _sdk_container_path(
            "runtime", inventory.parity_pin.relative
        ),
        "branches": branches,
    }
    payload = _canonical_bytes(value)
    path = final_root / ASSET_DIRECTORY / system / "adapter-config.json"
    descriptor = _future_descriptor(
        inventory.root,
        path,
        payload,
        container_path=(
            f"/opt/vast/input/runtime/generated/{system}/adapter-config.json"
        ),
    )
    return path, payload, descriptor


def _runtime_source_pins(
    inventory: _SourceInventory, *, system: str
) -> tuple[_FilePin, ...]:
    _require(system == "openvino_gva", "runtime_files only apply to OpenVINO GVA")
    allowlist_path = "deploy/openvino_gva/publication/runtime-source-allowlist.txt"
    allowlist_pin = _project_pin(
        inventory.root, allowlist_path, label="OpenVINO runtime source allowlist"
    )
    try:
        lines = allowlist_pin.path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        _fail(f"OpenVINO runtime source allowlist is unreadable: {error}")
    fixed = {
        "scripts/checkpoint_gstreamer_runtime.py",
        "scripts/checkpoint_openvino_gva_container_coordinator_v3.py",
    }
    paths = tuple(
        sorted(
            line.strip()
            for line in lines
            if line.strip().endswith(".py") and line.strip() not in fixed
        )
    )
    _require(paths and len(paths) == len(set(paths)), "OpenVINO runtime closure drifted")
    return tuple(
        _project_pin(
            inventory.root, path, label=f"OpenVINO runtime dependency {path}"
        )
        for path in paths
    )


def _analytics_capability_hashes(inventory: _SourceInventory) -> dict[str, str]:
    result: dict[str, str] = {}
    for resource in RESOURCES:
        values = []
        for branch in BRANCHES:
            try:
                capability = expected_capability_from_binding_and_probe(
                    binding=inventory.analytics_bindings[(branch, resource)],
                    runtime_probe=inventory.runtime_probes[resource],
                    resource=resource,
                )
            except Exception as error:
                _fail(f"{branch}/{resource} terminal capability is invalid: {error}")
            values.append(capability)
        result[resource] = _sha_bytes(_canonical(values))
    return result


def _device_binding(
    inventory: _SourceInventory,
    *,
    probe: Mapping[str, Any],
    capability_hashes: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "nvidia_decoder_gpu": dict(inventory.nvidia),
        "docker_gpus_request": f"device={inventory.nvidia['uuid']}",
        # Native runtime identity hashes include the canonical trailing newline.
        "openvino_device_probe_sha256": _sha_bytes(_canonical_bytes(probe["value"])),
        "required_openvino_device_ids": ["CPU"],
        "nvidia_gpu_counted_as_openvino_gpu": False,
        "analytics_resources": {
            "cpu": {
                "runtime": "openvino_cpu",
                "device": "CPU",
                "capability_sha256": capability_hashes["cpu"],
            },
            "gpu": {
                "runtime": "tensorrt_cuda",
                "device": inventory.nvidia["uuid"],
                "capability_sha256": capability_hashes["gpu"],
            },
        },
    }


def _external_directory(path: Path, *, label: str) -> Path:
    _require(path.is_absolute(), f"{label} must be absolute")
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        _fail(f"{label} is unavailable: {error}")
    _require(
        resolved == path
        and stat.S_ISDIR(info.st_mode)
        and not _is_link_or_reparse(info),
        f"{label} must be a canonical physical directory",
    )
    return path


def _fixed_project_pins(inventory: _SourceInventory) -> dict[str, _FilePin]:
    paths = {
        "experiments_config": EXPERIMENTS_PATH,
        "analytics_model_manifest": OPENVINO_MODEL_MANIFEST_PATH,
        "device_probe": DEVICE_PROBE_PATH,
        "checkpoint_runtime": "scripts/checkpoint_gstreamer_runtime.py",
        "openvino_publication_coordinator": (
            "scripts/checkpoint_openvino_gva_container_coordinator_v3.py"
        ),
    }
    result = {
        role: _project_pin(inventory.root, path, label=f"runtime file {role}")
        for role, path in paths.items()
    }
    result["analytics_execution_manifest"] = inventory.analytics_execution_pin
    return result


def _system_file_descriptors(
    *,
    inputs: Any,
    inventory: _SourceInventory,
    system: str,
    fixed: Mapping[str, _FilePin],
    engine_asset_path: Path,
    engine_pin: _FilePin,
    adapter_descriptor: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    engine = _future_pin_descriptor(
        inventory.root,
        engine_asset_path,
        size=engine_pin.size,
        sha256=engine_pin.sha256,
        container_path=(
            "/opt/vast/input/runtime/container-engine/docker"
            if system in {"deepstream", "savant"}
            else None
        ),
    )
    candidate = _json_descriptor(
        inventory.root,
        inputs.candidate_manifest,
        container_path=(
            _sdk_container_path(
                "runtime",
                inputs.candidate_manifest.path.relative_to(inventory.root).as_posix(),
            )
            if system in {"deepstream", "savant"}
            else _project_container_path(
                inputs.candidate_manifest.path.relative_to(inventory.root).as_posix()
            )
        ),
    )
    calibration_pin = inputs.calibrations[system]
    calibration_relative = calibration_pin.path.relative_to(inventory.root).as_posix()
    calibration = _json_descriptor(
        inventory.root,
        calibration_pin,
        container_path=(
            _sdk_container_path("runtime", calibration_relative)
            if system in {"deepstream", "savant"}
            else _project_container_path(calibration_relative)
        ),
    )
    if system in {"deepstream", "savant"}:
        _require(type(adapter_descriptor) is dict, f"{system} adapter is missing")
        return {
            "container_engine": engine,
            "experiments_config": _descriptor(
                fixed["experiments_config"],
                container_path=_sdk_container_path(
                    "runtime", fixed["experiments_config"].relative
                ),
            ),
            "datasets_config": _descriptor(
                inventory.dataset_pin,
                container_path=_sdk_container_path(
                    "runtime", inventory.dataset_pin.relative
                ),
            ),
            "adapter_config": dict(adapter_descriptor),
            "analytics_model_manifest": _descriptor(
                inventory.parity_pin,
                container_path=_sdk_container_path(
                    "runtime", inventory.parity_pin.relative
                ),
            ),
            "policy_capability_manifest": candidate,
            "policy_calibration": calibration,
        }
    _require(type(adapter_descriptor) is dict, f"{system} execution manifest is missing")
    common = {
        "container_engine": engine,
        "device_probe": _descriptor(
            fixed["device_probe"],
            container_path=_project_container_path(fixed["device_probe"].relative),
        ),
        "experiments_config": _descriptor(
            fixed["experiments_config"],
            container_path=_project_container_path(
                fixed["experiments_config"].relative
            ),
        ),
        "datasets_config": _descriptor(
            inventory.dataset_pin,
            container_path=_project_container_path(inventory.dataset_pin.relative),
        ),
        "analytics_model_manifest": _descriptor(
            fixed["analytics_model_manifest"],
            container_path=_project_container_path(
                fixed["analytics_model_manifest"].relative
            ),
        ),
        "analytics_execution_manifest": dict(adapter_descriptor),
        "policy_capability_manifest": candidate,
        "policy_calibration": calibration,
    }
    if system == "openvino_gva":
        return {
            **common,
            "checkpoint_runtime": _descriptor(
                fixed["checkpoint_runtime"],
                container_path=openvino_runtime.ROLE_CONTAINER_PATHS[
                    "checkpoint_runtime"
                ],
            ),
            "publication_coordinator": _descriptor(
                fixed["openvino_publication_coordinator"],
                container_path=openvino_runtime.ROLE_CONTAINER_PATHS[
                    "publication_coordinator"
                ],
            ),
        }
    return common


def _endpoint_socket_contract(
    system: str, analytics_socket: Mapping[str, Any]
) -> list[dict[str, Any]] | dict[str, Any]:
    if system in {"deepstream", "savant"}:
        return [
            {
                "host_path": analytics_socket["path"],
                "container_path": "/run/vast/analytics.sock",
                **{
                    key: analytics_socket[key]
                    for key in ("device", "inode", "owner_uid", "owner_gid")
                },
            }
        ]
    return {
        "analytics_execution": {
            **dict(analytics_socket),
            "container_path": "/run/vast/analytics-execution.sock",
        }
    }


def _runtime_contract_for_cell(
    cell: QualificationPilotCellV2,
    *,
    inventory: _SourceInventory,
    files: Mapping[str, Mapping[str, Any]],
    source_files: Sequence[Mapping[str, Any]],
    model_files: Sequence[Mapping[str, Any]],
    support_files: Sequence[Mapping[str, Any]],
    image: Mapping[str, Any],
    engine_socket: Mapping[str, Any],
    analytics_socket: Mapping[str, Any],
    scratch_root: Path,
    probe: Mapping[str, Any] | None,
    capability_hashes: Mapping[str, str],
    runtime_files: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    common = {
        "schema_version": 3,
        "files": copy.deepcopy(dict(files)),
        "source_files": copy.deepcopy(list(source_files)),
        "model_files": copy.deepcopy(list(model_files)),
        "support_files": copy.deepcopy(list(support_files)),
        "static_hybrid_map": None,
        "container_image": copy.deepcopy(dict(image)),
        "container_engine_socket": dict(engine_socket),
        "endpoint_sockets": _endpoint_socket_contract(
            cell.system, analytics_socket
        ),
        "scratch_root": scratch_root.as_posix(),
        "ready_timeout_s": 300.0,
        "drain_timeout_s": 10.0,
        "start_lead_ms": 100,
        "container_timeout_s": 900.0,
        "defer_full_resource_acceptance": True,
        "evidence_mapping": {name: name for name in CHILD_EVIDENCE_FILES},
    }
    if cell.system == "deepstream":
        return {
            **common,
            "artifact_kind": deepstream_runtime.RUNTIME_INPUT_KIND,
        }
    if cell.system == "savant":
        return {
            **common,
            "artifact_kind": savant_runtime.RUNTIME_INPUT_KIND,
        }
    _require(type(probe) is dict, f"{cell.system} live device probe is missing")
    native = {
        **common,
        "artifact_kind": (
            openvino_runtime.RUNTIME_INPUT_KIND
            if cell.system == "openvino_gva"
            else gstreamer_runtime.RUNTIME_INPUT_KIND
        ),
        "embedded_artifacts": copy.deepcopy(
            openvino_runtime.EXPECTED_EMBEDDED_ARTIFACTS
            if cell.system == "openvino_gva"
            else gstreamer_runtime.EXPECTED_EMBEDDED_ARTIFACTS
        ),
        "device_binding": _device_binding(
            inventory,
            probe=probe,
            capability_hashes=capability_hashes,
        ),
        "preprocessing_contract_sha256": inventory.preprocessing_sha256,
        "detect_bin": DETECT_BIN,
        "analytics_queue_max_buffers": 1,
    }
    if cell.system == "openvino_gva":
        native["runtime_files"] = copy.deepcopy(list(runtime_files))
    return native


def _runtime_inputs_for_cell(
    cell: QualificationPilotCellV2,
    *,
    dataset: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    dataset_value = copy.deepcopy(dict(dataset))
    dataset_value[RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]] = copy.deepcopy(
        dict(contract)
    )
    return {
        "system": cell.system,
        "resource": cell.resource,
        "scenario": cell.scenario,
        "topology_kind": cell.topology_kind,
        "codec": cell.codec,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "duration_s": cell.duration_s,
        "streams": 6,
        "run_id": cell.run_id,
        "dataset": dataset_value,
    }


def _require_socket_transport(
    record: Mapping[str, Any], *, expected_type: str, label: str
) -> None:
    _require(
        expected_type in {"0001", "0005"}, "Unix socket transport type is invalid"
    )
    if expected_type == "0001":
        try:
            lines = (
                Path("/proc/net/unix")
                .read_text(encoding="ascii")
                .splitlines()[1:]
            )
        except (OSError, UnicodeError) as error:
            _fail(f"{label} transport cannot be inspected: {error}")
        listeners = []
        for line in lines:
            fields = line.split()
            if (
                len(fields) >= 8
                and fields[7] == record["path"]
                and fields[4] == expected_type
                and fields[5] == "01"
            ):
                # fields[6] is the kernel socket-object inode.  The physical
                # runtime pin deliberately stores the distinct filesystem
                # socket node inode returned by lstat(2).  Connected clients
                # may retain the bound path in additional state-03 rows; they
                # do not create additional bound transports.
                listeners.append((fields[4], fields[5], fields[7]))
        _require(
            listeners == [(expected_type, "01", record["path"])],
            f"{label} is not the exact live Unix socket transport",
        )
        return

    path = Path(record["path"])
    try:
        before = path.lstat()
    except OSError as error:
        _fail(f"{label} cannot be inspected before transport validation: {error}")
    _require(
        stat.S_ISSOCK(before.st_mode)
        and int(before.st_dev) == record["device"]
        and int(before.st_ino) == record["inode"]
        and int(before.st_uid) == record["owner_uid"]
        and int(before.st_gid) == record["owner_gid"],
        f"{label} socket identity drifted before transport validation",
    )
    before_snapshot = _snapshot(before)

    endpoint: socket.socket | None = None
    try:
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        endpoint.settimeout(5.0)
        endpoint.connect(record["path"])
        observed_type = endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
        peer_name = endpoint.getpeername()
        try:
            lines = (
                Path("/proc/net/unix")
                .read_text(encoding="ascii")
                .splitlines()[1:]
            )
        except (OSError, UnicodeError) as error:
            _fail(f"{label} transport cannot be inspected: {error}")
        listening_peers = []
        for line in lines:
            fields = line.split(maxsplit=7)
            if (
                type(peer_name) is str
                and len(fields) == 8
                and fields[7] == peer_name
                and fields[3] == "00010000"
                and fields[5] == "01"
            ):
                listening_peers.append((fields[4], fields[7]))
        _require(
            listening_peers == [(expected_type, peer_name)],
            f"{label} connected peer is not the exact live Unix socket transport",
        )
    except OSError as error:
        _fail(f"{label} is not a reachable live SOCK_SEQPACKET transport: {error}")
    finally:
        if endpoint is not None:
            endpoint.close()

    try:
        after = path.lstat()
    except OSError as error:
        _fail(f"{label} identity changed during transport validation: {error}")
    _require(
        _snapshot(after) == before_snapshot
        and stat.S_ISSOCK(after.st_mode)
        and int(after.st_dev) == record["device"]
        and int(after.st_ino) == record["inode"]
        and int(after.st_uid) == record["owner_uid"]
        and int(after.st_gid) == record["owner_gid"],
        f"{label} identity changed during transport validation",
    )
    _require(
        observed_type == socket.SOCK_SEQPACKET,
        f"{label} connected transport type drifted",
    )


def _require_file_pin_unchanged(pin: _FilePin, *, label: str) -> None:
    fd = -1
    try:
        before = pin.path.lstat()
        fd = os.open(
            pin.path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(fd)
        size, digest = _fd_hash(fd)
        after = pin.path.lstat()
    except OSError as error:
        _fail(f"{label} disappeared during materialization: {error}")
    finally:
        if fd >= 0:
            os.close(fd)
    _require(
        _snapshot(before) == pin.snapshot
        and _snapshot(opened) == pin.snapshot
        and _snapshot(after) == pin.snapshot
        and size == pin.size
        and digest == pin.sha256,
        f"{label} changed during materialization",
    )


def _inventory_identity(inventory: _SourceInventory) -> str:
    return _canonical_sha(
        {
            "datasets": inventory.datasets,
            "parity": inventory.parity,
            "resource_bindings": {
                f"{system}/{resource}": value
                for (system, resource), value in sorted(
                    inventory.resource_bindings.items()
                )
            },
            "policy_bindings": {
                f"{system}/{branch}/{resource}": value
                for (system, branch, resource), value in sorted(
                    inventory.policy_bindings.items()
                )
            },
            "analytics_bindings": {
                f"{branch}/{resource}": value
                for (branch, resource), value in sorted(
                    inventory.analytics_bindings.items()
                )
            },
            "runtime_probes": dict(inventory.runtime_probes),
            "nvidia": inventory.nvidia,
        }
    )


def _copy_engine_asset(root: Path, pin: _FilePin, target: Path) -> _FilePin:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pin.path.open("rb", buffering=0) as source:
            fd = os.open(
                target,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o700,
            )
            try:
                with os.fdopen(fd, "wb", buffering=0, closefd=False) as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                os.fsync(fd)
                os.fchmod(fd, 0o555)
            finally:
                os.close(fd)
    except OSError as error:
        _fail(f"container engine asset copy failed: {error}")
    copied = _project_pin(
        root,
        target.relative_to(root).as_posix(),
        label="copied container engine",
        expected_size=pin.size,
        expected_sha256=pin.sha256,
        executable=True,
    )
    _require(copied.path == target, "copied container engine target drifted")
    return copied


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
        "runtime-input directory identity is unsafe",
    )
    return int(info.st_dev), int(info.st_ino)


def _runtime_tree_records(tree: Path) -> tuple[tuple[object, ...], ...]:
    """Cold-describe one sealed runtime tree without following any links."""

    _directory_identity(tree)
    records: list[tuple[object, ...]] = [
        (".", "directory", stat.S_IMODE(tree.lstat().st_mode))
    ]
    try:
        paths = sorted(tree.rglob("*"), key=lambda path: path.relative_to(tree).as_posix())
    except OSError as error:
        _fail(f"runtime-input tree traversal failed: {error}")
    for path in paths:
        relative = path.relative_to(tree).as_posix()
        fd = -1
        try:
            before = path.lstat()
            if stat.S_ISDIR(before.st_mode) and not _is_link_or_reparse(before):
                records.append((relative, "directory", stat.S_IMODE(before.st_mode)))
                continue
            if (
                not stat.S_ISREG(before.st_mode)
                or _is_link_or_reparse(before)
                or int(before.st_nlink) != 1
            ):
                raise OSError("unsafe non-file tree entry")
            fd = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(fd)
            size, digest = _fd_hash(fd)
            after = path.lstat()
            if (
                _snapshot(before) != _snapshot(opened)
                or _snapshot(opened) != _snapshot(after)
                or size != int(after.st_size)
            ):
                raise OSError("physical file identity changed")
            records.append(
                (relative, "file", stat.S_IMODE(after.st_mode), size, digest)
            )
        except OSError as error:
            _fail(f"runtime-input tree entry {relative!r} is unsafe: {error}")
        finally:
            if fd >= 0:
                os.close(fd)
    return tuple(records)


def _require_exact_runtime_tree(staged: Path, published: Path) -> tuple[int, int]:
    """Adopt only a byte-, mode-, and namespace-exact prior publication."""

    published_identity = _directory_identity(published)
    _require(
        _runtime_tree_records(published) == _runtime_tree_records(staged),
        "existing runtime-input tree is not the exact staged publication",
    )
    _require(
        _directory_identity(published) == published_identity,
        "existing runtime-input tree identity changed during adoption",
    )
    return published_identity


def _durable_runtime_tree(
    tree: Path,
    *,
    parent: Path,
    expected_tree_identity: tuple[int, int],
    expected_parent_identity: tuple[int, int],
) -> None:
    """Fsync every sealed leaf/directory and the publication parent."""

    _require(tree.parent == parent, "runtime-input durability parent drifted")
    before_records = _runtime_tree_records(tree)
    _require(
        _directory_identity(tree) == expected_tree_identity
        and _directory_identity(parent) == expected_parent_identity,
        "runtime-input tree/parent identity drifted before durability barrier",
    )
    paths = sorted(tree.rglob("*"), key=lambda path: path.relative_to(tree).as_posix())
    try:
        for path in paths:
            before = path.lstat()
            if stat.S_ISDIR(before.st_mode) and not _is_link_or_reparse(before):
                continue
            if (
                not stat.S_ISREG(before.st_mode)
                or _is_link_or_reparse(before)
                or int(before.st_nlink) != 1
            ):
                raise OSError(f"unsafe tree leaf {path.relative_to(tree).as_posix()!r}")
            fd = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                opened = os.fstat(fd)
                os.fsync(fd)
                after = path.lstat()
                if (
                    _snapshot(before) != _snapshot(opened)
                    or _snapshot(opened) != _snapshot(after)
                ):
                    raise OSError("tree leaf identity changed across fsync")
            finally:
                os.close(fd)
        directories = sorted(
            (path for path in paths if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        directories.append(tree)
        for directory in directories:
            before = directory.lstat()
            if not stat.S_ISDIR(before.st_mode) or _is_link_or_reparse(before):
                raise OSError("unsafe tree directory")
            fd = os.open(
                directory,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                opened = os.fstat(fd)
                os.fsync(fd)
                after = directory.lstat()
                if (
                    _snapshot(before) != _snapshot(opened)
                    or _snapshot(opened) != _snapshot(after)
                ):
                    raise OSError("tree directory identity changed across fsync")
            finally:
                os.close(fd)
        parent_before = parent.lstat()
        parent_fd = os.open(
            parent,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            parent_opened = os.fstat(parent_fd)
            os.fsync(parent_fd)
            parent_after = parent.lstat()
            if (
                _snapshot(parent_before) != _snapshot(parent_opened)
                or _snapshot(parent_opened) != _snapshot(parent_after)
            ):
                raise OSError("publication parent identity changed across fsync")
        finally:
            os.close(parent_fd)
    except OSError as error:
        _fail(f"runtime-input durability barrier failed: {error}")
    _require(
        _directory_identity(tree) == expected_tree_identity
        and _directory_identity(parent) == expected_parent_identity
        and _runtime_tree_records(tree) == before_records,
        "runtime-input tree/parent drifted across durability barrier",
    )


def _safe_remove_staging(
    staging: Path,
    *,
    parent: Path,
    expected_staging_identity: tuple[int, int],
    expected_parent_identity: tuple[int, int],
) -> None:
    _require(
        staging.parent == parent
        and staging.name.startswith(f".{RUNTIME_BUNDLE_DIRECTORY}.")
        and staging != parent,
        "unsafe runtime-input staging cleanup target",
    )
    if not staging.exists():
        return
    _require(
        _directory_identity(parent) == expected_parent_identity
        and _directory_identity(staging) == expected_staging_identity,
        "runtime-input staging/parent inode changed before cleanup",
    )
    for path in staging.rglob("*"):
        info = path.lstat()
        _require(
            (
                stat.S_ISDIR(info.st_mode)
                and not _is_link_or_reparse(info)
            )
            or (
                stat.S_ISREG(info.st_mode)
                and not _is_link_or_reparse(info)
                and int(info.st_nlink) == 1
            ),
            "runtime-input cleanup found an unowned inode",
        )
    for path in sorted(staging.rglob("*"), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
            elif path.exists() and not path.is_symlink():
                path.chmod(0o600)
        except OSError:
            pass
    try:
        staging.chmod(0o700)
        shutil.rmtree(staging)
    except OSError as error:
        _fail(f"runtime-input staging cleanup failed: {error}")


def _cold_validate_runtime_input_commit(
    *, root: Path, final_root: Path, custody: PhysicalRootCustodyV1
) -> None:
    try:
        _descriptor, payload = custody.read_descriptor(
            final_root / MATERIALIZATION_RECEIPT,
            label="cold runtime-input receipt",
            maximum=64 * 1024 * 1024,
            capture=True,
        )
    except PublicationPhysicalIoV1Error as error:
        _fail(f"cold runtime-input receipt custody failed: {error}")
    assert payload is not None
    try:
        receipt = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"cold runtime-input receipt is not JSON: {error}")
    unsigned = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    _require(
        type(receipt) is dict
        and payload == _canonical_bytes(receipt)
        and receipt.get("receipt_sha256") == _canonical_sha(unsigned),
        "cold runtime-input receipt identity drifted",
    )
    bundles = receipt.get("bundles")
    _require(
        type(bundles) is list
        and len(bundles) == 32
        and len({row.get("path") for row in bundles if type(row) is dict}) == 32,
        "cold runtime-input bundle coverage drifted",
    )
    for position, record in enumerate(bundles):
        _require(type(record) is dict, "cold runtime-input bundle record drifted")
        try:
            observed, _bundle_payload = custody.read_descriptor(
                final_root / str(record.get("path")),
                label=f"cold runtime-input bundle[{position}]",
                maximum=64 * 1024 * 1024,
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"cold runtime-input bundle custody failed: {error}")
        _require(
            observed["size_bytes"] == record.get("size_bytes")
            and observed["sha256"] == record.get("sha256"),
            f"cold runtime-input bundle[{position}] drifted",
        )
    asset_descriptors = [receipt.get("container_engine"), *receipt.get("generated_assets", [])]
    for position, descriptor in enumerate(asset_descriptors):
        _require(type(descriptor) is dict, "cold runtime-input asset descriptor drifted")
        try:
            observed, _asset_payload = custody.read_descriptor(
                str(descriptor.get("asset_path", descriptor.get("path"))),
                label=f"cold runtime-input asset[{position}]",
                maximum=1024 * 1024 * 1024,
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"cold runtime-input asset custody failed: {error}")
        _require(
            observed["size_bytes"] == descriptor.get("size_bytes")
            and observed["sha256"] == descriptor.get("sha256"),
            f"cold runtime-input asset[{position}] drifted",
        )


def _seal_tree(tree: Path) -> None:
    files = sorted(path for path in tree.rglob("*") if path.is_file())
    directories = sorted(
        (path for path in tree.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    try:
        for path in files:
            mode = path.lstat().st_mode
            path.chmod(0o555 if mode & 0o111 else 0o444)
        for path in directories:
            path.chmod(0o555)
        tree.chmod(0o555)
        parent_fd = os.open(tree.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError as error:
        _fail(f"runtime-input staging seal failed: {error}")


def _publish_runtime_tree_noreplace(
    staging: Path,
    final_root: Path,
    *,
    parent: Path,
    staging_identity: tuple[int, int],
    parent_identity: tuple[int, int],
    destination_preexisted: bool,
    after_directory_publish_step: Callable[[str, Path], None] | None,
) -> str:
    """Durably publish, or exact-adopt, one complete sealed runtime tree."""

    _durable_runtime_tree(
        staging,
        parent=parent,
        expected_tree_identity=staging_identity,
        expected_parent_identity=parent_identity,
    )
    if destination_preexisted:
        adopted_identity = _require_exact_runtime_tree(staging, final_root)
        _durable_runtime_tree(
            final_root,
            parent=parent,
            expected_tree_identity=adopted_identity,
            expected_parent_identity=parent_identity,
        )
        return "adopted"
    try:
        _rename_directory_noreplace(staging, final_root)
    except Exception as error:
        if not os.path.lexists(final_root):
            _fail(f"runtime-input atomic no-overwrite commit failed: {error}")
        adopted_identity = _require_exact_runtime_tree(staging, final_root)
        _durable_runtime_tree(
            final_root,
            parent=parent,
            expected_tree_identity=adopted_identity,
            expected_parent_identity=parent_identity,
        )
        return "adopted"
    if after_directory_publish_step is not None:
        after_directory_publish_step("post_publish_pre_parent_fsync", final_root)
    _durable_runtime_tree(
        final_root,
        parent=parent,
        expected_tree_identity=staging_identity,
        expected_parent_identity=parent_identity,
    )
    return "published"


def _materialize_publication_policy_qualification_runtime_inputs_v2_held(
    *,
    project_root: Path | str,
    candidate_index_path: Path | str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_receipt_path: Path | str,
    bootstrap_dir: Path | str,
    transaction_receipt_path: Path | str,
    container_engine_path: Path | str = DEFAULT_CONTAINER_ENGINE,
    container_engine_socket_path: Path | str = DEFAULT_CONTAINER_ENGINE_SOCKET,
    analytics_socket_path: Path | str = DEFAULT_ANALYTICS_SOCKET,
    scratch_root: Path | str = DEFAULT_SCRATCH_ROOT,
    deadline_ms: int | float = 100,
    duration_s: int = 180,
    dependencies: RuntimeInputMaterializationDependenciesV2 = DEFAULT_DEPENDENCIES,
    after_directory_publish_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Atomically publish all live, exact-input qualification bundles."""

    _require(
        os.name == "posix" and Path("/proc/self/fd").is_dir(),
        "qualification runtime inputs must be materialized inside WSL/Linux",
    )
    cells = qualification_pilot_cells_v2(
        deadline_ms=deadline_ms, duration_s=duration_s
    )
    try:
        inputs = _load_qualification_inputs(
            project_root=project_root,
            candidate_index_path=candidate_index_path,
            candidate_manifest_path=candidate_manifest_path,
            candidate_receipt_path=candidate_receipt_path,
            bootstrap_mapping_path=bootstrap_mapping_path,
            bootstrap_receipt_path=bootstrap_receipt_path,
            bootstrap_dir=bootstrap_dir,
            transaction_receipt_path=transaction_receipt_path,
        )
    except Exception as error:
        _fail(f"qualification transaction preflight failed: {error}")
    root = inputs.root
    _require(
        inputs.transaction_receipt is not None,
        "qualification input transaction receipt is required",
    )
    try:
        bootstrap_root = _physical_directory(
            root, bootstrap_dir, label="qualification bootstrap directory"
        )
    except Exception as error:
        _fail(f"qualification bootstrap directory is invalid: {error}")
    final_root = bootstrap_root / RUNTIME_BUNDLE_DIRECTORY
    try:
        destination_info = final_root.lstat()
    except FileNotFoundError:
        destination_preexisted = False
    except OSError as error:
        _fail(f"qualification runtime-input destination is unreadable: {error}")
    else:
        _require(
            stat.S_ISDIR(destination_info.st_mode)
            and not _is_link_or_reparse(destination_info),
            "qualification runtime-input destination is an unsafe preexisting entry",
        )
        destination_preexisted = True

    inventory = _load_source_inventory(inputs)
    _preflight_reachable_runtime_contracts(inventory)
    initial_inventory_identity = _inventory_identity(inventory)

    engine = Path(os.path.abspath(os.fspath(container_engine_path)))
    engine_socket_path = Path(
        os.path.abspath(os.fspath(container_engine_socket_path))
    )
    analytics_raw = Path(analytics_socket_path)
    analytics_path = Path(
        os.path.abspath(
            os.fspath(analytics_raw if analytics_raw.is_absolute() else root / analytics_raw)
        )
    )
    scratch_path = Path(os.path.abspath(os.fspath(scratch_root)))
    engine_pin = _external_executable_pin(engine, label="container engine")
    engine_socket = _socket_record(engine_socket_path, label="container engine socket")
    analytics_socket = _socket_record(
        analytics_path, label="analytics execution endpoint"
    )
    _require_socket_transport(
        engine_socket, expected_type="0001", label="container engine socket"
    )
    _require_socket_transport(
        analytics_socket,
        expected_type="0005",
        label="analytics execution endpoint",
    )
    scratch_path = _external_directory(scratch_path, label="runtime scratch_root")

    images = _inspect_runtime_images(
        inventory,
        engine=engine,
        engine_socket=engine_socket_path,
        dependencies=dependencies,
    )
    device_probes = _probe_devices(
        inventory,
        images,
        engine=engine,
        engine_socket=engine_socket_path,
        dependencies=dependencies,
    )
    fixed = _fixed_project_pins(inventory)
    capability_hashes = _analytics_capability_hashes(inventory)
    datasets: dict[str, dict[str, Any]] = {}
    media_pins: dict[str, tuple[_FilePin, ...]] = {}
    sources: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for codec in CODECS:
        datasets[codec], media_pins[codec] = _dataset_material(inventory, codec)
        for system in SYSTEMS:
            sources[(system, codec)] = _source_descriptors(
                media_pins[codec], system=system
            )
    models = {
        system: _model_descriptors(inventory, system=system) for system in SYSTEMS
    }
    support = {
        system: _support_descriptors(inventory, system=system) for system in SYSTEMS
    }
    runtime_pins = _runtime_source_pins(inventory, system="openvino_gva")
    runtime_files = [
        _descriptor(pin, container_path=_project_container_path(pin.relative))
        for pin in runtime_pins
    ]

    engine_asset_final = final_root / PurePosixPath(DOCKER_ASSET)
    adapter_assets: dict[str, tuple[Path, bytes, dict[str, Any]]] = {
        system: _adapter_asset(inventory, system=system, final_root=final_root)
        for system in SYSTEMS
    }
    files = {
        system: _system_file_descriptors(
            inputs=inputs,
            inventory=inventory,
            system=system,
            fixed=fixed,
            engine_asset_path=engine_asset_final,
            engine_pin=engine_pin,
            adapter_descriptor=(
                adapter_assets[system][2]
                if system in adapter_assets
                else None
            ),
        )
        for system in SYSTEMS
    }

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{RUNTIME_BUNDLE_DIRECTORY}.", dir=bootstrap_root
        )
    )
    bootstrap_identity = _directory_identity(bootstrap_root)
    staging_identity = _directory_identity(staging)
    committed = False
    try:
        engine_asset_staging = staging / PurePosixPath(DOCKER_ASSET)
        copied_engine_pin = _copy_engine_asset(root, engine_pin, engine_asset_staging)
        for final_path, payload, _ in adapter_assets.values():
            relative = final_path.relative_to(final_root)
            _write_exclusive_bytes(staging / relative, payload)

        def runtime_factory(cell: QualificationPilotCellV2) -> Mapping[str, Any]:
            contract = _runtime_contract_for_cell(
                cell,
                inventory=inventory,
                files=files[cell.system],
                source_files=sources[(cell.system, cell.codec)],
                model_files=models[cell.system],
                support_files=support[cell.system],
                image=images[cell.system]["contract"],
                engine_socket=engine_socket,
                analytics_socket=analytics_socket,
                scratch_root=scratch_path,
                probe=device_probes.get(cell.system),
                capability_hashes=capability_hashes,
                runtime_files=(
                    runtime_files if cell.system == "openvino_gva" else ()
                ),
            )
            return _runtime_inputs_for_cell(
                cell, dataset=datasets[cell.codec], contract=contract
            )

        _require(
            inputs.hardware_resource_collector is not None,
            "hardware resource collector authority is required",
        )
        hardware_collector_descriptor = {
            "path": inputs.hardware_resource_collector.path.relative_to(root).as_posix(),
            "size_bytes": inputs.hardware_resource_collector.snapshot[4],
            "sha256": inputs.hardware_resource_collector.sha256,
        }
        bundle_records = _write_bundle_tree_v2(
            staging,
            cells=cells,
            runtime_factory=runtime_factory,
            hardware_resource_collector=hardware_collector_descriptor,
        )
        receipt_unsigned = {
            "schema_version": 2,
            "artifact_kind": MATERIALIZATION_RECEIPT_KIND,
            "status": "materialized_for_native_qualification_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "scope": RUNTIME_BUNDLE_SCOPE,
            "matrix_sha256": _canonical_sha([cell.__dict__ for cell in cells]),
            "inputs": {
                "candidate_index_sha256": inputs.candidate_index.sha256,
                "candidate_manifest_sha256": inputs.candidate_manifest.sha256,
                "candidate_receipt_sha256": inputs.candidate_receipt.sha256,
                "bootstrap_mapping_sha256": inputs.bootstrap_mapping.sha256,
                "bootstrap_receipt_sha256": inputs.bootstrap_receipt.sha256,
                "qualification_input_transaction_receipt_sha256": (
                    inputs.transaction_receipt.sha256
                ),
                "hardware_resource_collector": hardware_collector_descriptor,
                "inventory_sha256": initial_inventory_identity,
            },
            "container_engine": {
                "source_path": engine.as_posix(),
                "asset_path": engine_asset_final.relative_to(root).as_posix(),
                "size_bytes": engine_pin.size,
                "sha256": engine_pin.sha256,
            },
            "live_sockets": {
                "container_engine": engine_socket,
                "analytics_execution": analytics_socket,
            },
            "container_images": {
                system: copy.deepcopy(images[system]) for system in SYSTEMS
            },
            "device_probes": {
                system: copy.deepcopy(device_probes[system])
                for system in sorted(device_probes)
            },
            "generated_assets": [
                {
                    "system": system,
                    **copy.deepcopy(adapter_assets[system][2]),
                }
                for system in sorted(adapter_assets)
            ],
            "bundles": list(bundle_records),
            "blockers": [
                "qualification_runtime_inputs_are_not_production_authority"
            ],
        }
        receipt = {
            **receipt_unsigned,
            "receipt_sha256": _canonical_sha(receipt_unsigned),
        }
        _write_exclusive_bytes(
            staging / MATERIALIZATION_RECEIPT, _canonical_bytes(receipt)
        )

        _require_file_pin_unchanged(
            copied_engine_pin, label="staged container engine asset"
        )
        for system, (final_path, payload, descriptor) in adapter_assets.items():
            staged_path = staging / final_path.relative_to(final_root)
            pin = _project_pin(
                root,
                staged_path.relative_to(root).as_posix(),
                label=f"staged {system} adapter asset",
                expected_size=descriptor["size_bytes"],
                expected_sha256=descriptor["sha256"],
            )
            _require(pin.size == len(payload), f"staged {system} adapter size drifted")
        for record in bundle_records:
            _project_pin(
                root,
                (staging / record["path"]).relative_to(root).as_posix(),
                label=f"staged bundle {record['arm_id']}",
                expected_size=record["size_bytes"],
                expected_sha256=record["sha256"],
            )
        receipt_payload = _canonical_bytes(receipt)
        _project_pin(
            root,
            (staging / MATERIALIZATION_RECEIPT).relative_to(root).as_posix(),
            label="staged runtime-input receipt",
            expected_size=len(receipt_payload),
            expected_sha256=_sha_bytes(receipt_payload),
        )

        for pin in inputs.pins:
            _assert_pin_unchanged(pin, label=f"qualification input {pin.path.name}")
        for label, pin in (
            ("container engine", engine_pin),
            ("dataset manifest", inventory.dataset_pin),
            ("parity manifest", inventory.parity_pin),
            *((f"fixed runtime {role}", pin) for role, pin in fixed.items()),
            *((f"runtime closure {pin.relative}", pin) for pin in runtime_pins),
            *((f"model {pin.relative}", pin) for pin in inventory.model_pins),
            *((f"support {pin.relative}", pin) for pin in inventory.support_pins),
            *(
                (f"media {pin.relative}", pin)
                for codec in CODECS
                for pin in media_pins[codec]
            ),
        ):
            _require_file_pin_unchanged(pin, label=label)
        current_inventory = _load_source_inventory(inputs)
        _require(
            _inventory_identity(current_inventory) == initial_inventory_identity,
            "candidate/runtime inventory changed during materialization",
        )
        _require(
            _socket_record(engine_socket_path, label="container engine socket")
            == engine_socket
            and _socket_record(analytics_path, label="analytics execution endpoint")
            == analytics_socket,
            "live socket identity changed during materialization",
        )
        _require_socket_transport(
            engine_socket, expected_type="0001", label="container engine socket"
        )
        _require_socket_transport(
            analytics_socket,
            expected_type="0005",
            label="analytics execution endpoint",
        )
        _seal_tree(staging)
        _require(
            _directory_identity(bootstrap_root) == bootstrap_identity,
            "qualification bootstrap directory changed before runtime-input commit",
        )
        disposition = _publish_runtime_tree_noreplace(
            staging,
            final_root,
            parent=bootstrap_root,
            staging_identity=staging_identity,
            parent_identity=bootstrap_identity,
            destination_preexisted=destination_preexisted,
            after_directory_publish_step=after_directory_publish_step,
        )
        committed = disposition == "published"
    finally:
        if not committed and staging.exists():
            _safe_remove_staging(
                staging,
                parent=bootstrap_root,
                expected_staging_identity=staging_identity,
                expected_parent_identity=bootstrap_identity,
            )

    return {
        "runtime_input_root": final_root,
        "receipt_path": final_root / MATERIALIZATION_RECEIPT,
        "bundle_count": 32,
        "matrix_sha256": _canonical_sha([cell.__dict__ for cell in cells]),
    }


@wraps(_materialize_publication_policy_qualification_runtime_inputs_v2_held)
def materialize_publication_policy_qualification_runtime_inputs_v2(
    *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Materialize with held source custody and autonomous postcommit reload."""

    _require(not args, "runtime-input materializer accepts keyword arguments only")
    root = _physical_root(kwargs.get("project_root"))
    bootstrap_root = _physical_directory(
        root, kwargs.get("bootstrap_dir"), label="qualification bootstrap directory"
    )
    source_paths: list[Path | str] = [
        kwargs.get("candidate_index_path"),
        kwargs.get("candidate_manifest_path"),
        kwargs.get("candidate_receipt_path"),
        kwargs.get("bootstrap_mapping_path"),
        kwargs.get("bootstrap_receipt_path"),
        kwargs.get("transaction_receipt_path"),
        *(
            bootstrap_root / f"checkpoint_policy_qualification_bootstrap_calibration.{system}.v2.json"
            for system in SYSTEMS
        ),
    ]
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification runtime-input project_root"
        ) as custody:
            pinned: list[tuple[Path | str, dict[str, Any], tuple[int, int]]] = []
            for position, path in enumerate(source_paths):
                descriptor, _payload, identity = custody.read_descriptor_identity(
                    path,
                    label=f"qualification runtime-input source[{position}]",
                    maximum=1024 * 1024 * 1024,
                )
                pinned.append((path, descriptor, identity))
            result = _materialize_publication_policy_qualification_runtime_inputs_v2_held(
                **kwargs
            )
            for position, (path, descriptor, identity) in enumerate(pinned):
                observed, _payload, observed_identity = custody.read_descriptor_identity(
                    path,
                    label=f"qualification runtime-input source[{position}] reload",
                    maximum=1024 * 1024 * 1024,
                )
                _require(
                    observed == descriptor and observed_identity == identity,
                    f"qualification runtime-input source[{position}] changed",
                )
            custody.verify()
        with PhysicalRootCustodyV1.open(
            root, label="qualification runtime-input cold project_root"
        ) as cold:
            _cold_validate_runtime_input_commit(
                root=root,
                final_root=Path(result["runtime_input_root"]),
                custody=cold,
            )
            cold.verify()
        return result
    except QualificationRuntimeInputMaterializationV2Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        _fail(f"qualification runtime-input physical custody failed: {error}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically materialize the exact 32 live native qualification "
            "runtime-input bundles"
        )
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--candidate-index", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--bootstrap-mapping", type=Path, required=True)
    parser.add_argument("--bootstrap-receipt", type=Path, required=True)
    parser.add_argument("--bootstrap-dir", type=Path, required=True)
    parser.add_argument(
        "--qualification-transaction-receipt", type=Path, required=True
    )
    parser.add_argument(
        "--container-engine", type=Path, default=DEFAULT_CONTAINER_ENGINE
    )
    parser.add_argument(
        "--container-engine-socket",
        type=Path,
        default=DEFAULT_CONTAINER_ENGINE_SOCKET,
    )
    parser.add_argument(
        "--analytics-socket", type=Path, default=DEFAULT_ANALYTICS_SOCKET
    )
    parser.add_argument("--scratch-root", type=Path, default=DEFAULT_SCRATCH_ROOT)
    parser.add_argument("--deadline-ms", type=float, default=100.0)
    parser.add_argument("--duration-s", type=int, default=180)
    args = parser.parse_args(argv)
    result = materialize_publication_policy_qualification_runtime_inputs_v2(
        project_root=args.project_root,
        candidate_index_path=args.candidate_index,
        candidate_manifest_path=args.candidate_manifest,
        candidate_receipt_path=args.candidate_receipt,
        bootstrap_mapping_path=args.bootstrap_mapping,
        bootstrap_receipt_path=args.bootstrap_receipt,
        bootstrap_dir=args.bootstrap_dir,
        transaction_receipt_path=args.qualification_transaction_receipt,
        container_engine_path=args.container_engine,
        container_engine_socket_path=args.container_engine_socket,
        analytics_socket_path=args.analytics_socket,
        scratch_root=args.scratch_root,
        deadline_ms=args.deadline_ms,
        duration_s=args.duration_s,
    )
    print(
        json.dumps(
            {
                key: value.as_posix() if isinstance(value, Path) else value
                for key, value in result.items()
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    return 0


__all__ = [
    "DEFAULT_DEPENDENCIES",
    "MATERIALIZATION_RECEIPT",
    "QualificationRuntimeInputMaterializationV2Error",
    "RuntimeInputMaterializationDependenciesV2",
    "materialize_publication_policy_qualification_runtime_inputs_v2",
]


if __name__ == "__main__":
    raise SystemExit(main())
