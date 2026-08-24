#!/usr/bin/env python3
"""Fail-closed preflight for the dual OpenVINO CPU/TensorRT CUDA layer."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from analytics_execution_protocol import (
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    MAX_CONTROL_BYTES,
    MAX_TENSOR_BYTES,
    PROTOCOL_IDENTITY_SHA256,
    TRANSPORT_KIND,
    ProtocolError,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
    valid_image_id,
    verify_sealed_memfd,
)
from analytics_execution_worker import validate_runtime_probe
from checkpoint_model_parity import assess_model_parity


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "analytics_execution_layer.yaml"
CONFIG_KIND = "vast_analytics_execution_layer_config"
ASSESSMENT_KIND = "vast_analytics_execution_layer_assessment"
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CommandRunner = Callable[[list[str]], str]
ParityAssessor = Callable[..., dict[str, Any]]
KernelProbe = Callable[[], dict[str, bool]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields have drifted")
    return value


def _visible(value: Any, label: str, maximum: int = 512) -> str:
    result = str(value or "")
    _require(0 < len(result) <= maximum, f"{label} is invalid")
    _require(all(ord(character) >= 0x20 and ord(character) != 0x7F for character in result), f"{label} contains controls")
    return result


def _sha256(value: Any, label: str) -> str:
    _require(
        type(value) is str and _SHA256_RE.fullmatch(value) is not None,
        f"{label} must be a lowercase SHA-256",
    )
    return value


def _validate_config(value: Any) -> dict[str, Any]:
    config = _exact(
        value,
        {
            "schema_version", "artifact_kind", "config_id",
            "protocol_identity_sha256", "model_parity_manifest", "transport",
            "workers",
        },
        "analytics execution layer config",
    )
    _require(config["schema_version"] == 1, "analytics execution layer config schema_version is invalid")
    _require(config["artifact_kind"] == CONFIG_KIND, "analytics execution layer config kind is invalid")
    _require(_STABLE_ID_RE.fullmatch(str(config["config_id"] or "")) is not None, "analytics execution layer config_id is invalid")
    _require(config["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "analytics execution layer protocol identity mismatch")
    manifest = _visible(config["model_parity_manifest"], "analytics execution model parity manifest", 512)
    manifest_path = Path(manifest)
    _require(not manifest_path.is_absolute() and ".." not in manifest_path.parts, "analytics execution model parity manifest path is unsafe")
    transport = _exact(
        config["transport"],
        {"kind", "max_control_bytes", "max_tensor_bytes", "max_inflight_requests_per_worker"},
        "analytics execution transport config",
    )
    _require(transport["kind"] == TRANSPORT_KIND, "analytics execution transport kind is invalid")
    _require(transport["max_control_bytes"] == MAX_CONTROL_BYTES, "analytics execution max control bytes drifted")
    _require(transport["max_tensor_bytes"] == MAX_TENSOR_BYTES, "analytics execution max tensor bytes drifted")
    _require(transport["max_inflight_requests_per_worker"] == 1, "analytics execution worker inflight bound must be one")
    workers = _exact(config["workers"], {"cpu", "gpu"}, "analytics execution workers config")
    normalized_workers: dict[str, dict[str, Any]] = {}
    for resource_name, expected_engine, gpu_required in (
        ("cpu", ENGINE_OPENVINO_CPU, False),
        ("gpu", ENGINE_TENSORRT_CUDA, True),
    ):
        worker = _exact(
            workers[resource_name],
            {
                "engine", "base_image", "base_image_id", "image", "image_id",
                "worker_implementation_sha256", "entrypoint",
                "requires_nvidia_runtime",
            },
            f"analytics execution {resource_name} worker config",
        )
        _require(worker["engine"] == expected_engine, f"analytics execution {resource_name} worker engine is invalid")
        _require(worker["requires_nvidia_runtime"] is gpu_required, f"analytics execution {resource_name} NVIDIA runtime binding is invalid")
        base_id = worker["base_image_id"]
        image_id = worker["image_id"]
        _require(valid_image_id(base_id), f"analytics execution {resource_name} base image ID is invalid")
        _require(image_id is None or valid_image_id(image_id), f"analytics execution {resource_name} worker image ID is invalid")
        entrypoint = _visible(worker["entrypoint"], f"analytics execution {resource_name} entrypoint", 512)
        _require(entrypoint.startswith("/") and "\n" not in entrypoint, f"analytics execution {resource_name} entrypoint must be an absolute container path")
        normalized_workers[resource_name] = {
            "engine": expected_engine,
            "base_image": _visible(worker["base_image"], f"analytics execution {resource_name} base image", 512),
            "base_image_id": base_id,
            "image": _visible(worker["image"], f"analytics execution {resource_name} image", 512),
            "image_id": image_id,
            "worker_implementation_sha256": _sha256(
                worker["worker_implementation_sha256"],
                f"analytics execution {resource_name} worker implementation SHA-256",
            ),
            "entrypoint": entrypoint,
            "requires_nvidia_runtime": gpu_required,
        }
    normalized = {
        "schema_version": 1,
        "artifact_kind": CONFIG_KIND,
        "config_id": str(config["config_id"]),
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "model_parity_manifest": manifest,
        "transport": dict(transport),
        "workers": normalized_workers,
    }
    normalized["identity"] = {
        "algorithm": "sha256",
        "sha256": canonical_sha256(normalized),
    }
    return normalized


def load_execution_layer_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    resolved = Path(path).resolve()
    _require(resolved.is_file(), f"analytics execution layer config was not found: {resolved}")
    try:
        with resolved.open("r", encoding="utf-8") as source:
            value = yaml.safe_load(source) or {}
    except (OSError, yaml.YAMLError) as error:
        raise ProtocolError(f"cannot read analytics execution layer config: {error}") from error
    return _validate_config(value)


def _default_command_runner(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return completed.stdout


def _inspect_image(reference: str, runner: CommandRunner) -> dict[str, Any] | None:
    try:
        raw = runner(["docker", "image", "inspect", reference])
        value = json.loads(raw)
        if isinstance(value, list):
            _require(len(value) == 1, "docker image inspect returned an unexpected record count")
            value = value[0]
        _require(isinstance(value, Mapping), "docker image inspect result must be a mapping")
        image_id = value.get("Id")
        _require(valid_image_id(image_id), "docker image inspect returned an invalid image ID")
        _require(value.get("Architecture") == "amd64" and value.get("Os") == "linux", "analytics worker image must be linux/amd64")
        config = value.get("Config") if isinstance(value.get("Config"), Mapping) else {}
        labels = config.get("Labels") if isinstance(config.get("Labels"), Mapping) else {}
        return {
            "reference": reference,
            "image_id": image_id,
            "architecture": "amd64",
            "os": "linux",
            "labels": {
                "base_image_id": labels.get("org.vast.analytics_worker.base_image_id"),
                "engine": labels.get("org.vast.analytics_worker.engine"),
            },
        }
    except (OSError, subprocess.SubprocessError, ValueError, ProtocolError, json.JSONDecodeError):
        return None


def build_runtime_probe_command(worker: Mapping[str, Any]) -> list[str]:
    command = ["docker", "run", "--rm", "--network", "none"]
    if worker["requires_nvidia_runtime"]:
        command.extend(["--gpus", "all"])
    command.extend(["--entrypoint", str(worker["entrypoint"]), str(worker["image"]), "--capability"])
    return command


def _runtime_probe(worker: Mapping[str, Any], runner: CommandRunner) -> dict[str, Any] | None:
    try:
        raw = runner(build_runtime_probe_command(worker))
        value = json.loads(raw)
        return validate_runtime_probe(value, engine=str(worker["engine"]))
    except (OSError, subprocess.SubprocessError, ValueError, ProtocolError, json.JSONDecodeError):
        return None


def probe_local_ipc_kernel() -> dict[str, bool]:
    result = {"socket_seqpacket": False, "scm_rights": False, "memfd_sealing": False}
    if not hasattr(socket, "SOCK_SEQPACKET") or not hasattr(os, "memfd_create"):
        return result
    left: socket.socket | None = None
    right: socket.socket | None = None
    source_fd: int | None = None
    received_fds: list[int] = []
    payload = b"vast-ipc-capability-probe"
    try:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        result["socket_seqpacket"] = True
        source_fd = create_sealed_memfd("vast-ipc-probe", payload)
        result["memfd_sealing"] = True
        message = {"message_type": "ipc_probe", "schema_version": 1}
        send_packet(left, message, fds=(source_fd,))
        received, received_fds = receive_packet(right, expected_fds=1)
        _require(received == message, "IPC capability probe message mismatch")
        _require(
            verify_sealed_memfd(
                received_fds[0],
                expected_bytes=len(payload),
                expected_sha256=__import__("hashlib").sha256(payload).hexdigest(),
            ) == payload,
            "IPC capability probe payload mismatch",
        )
        result["scm_rights"] = True
    except (OSError, ProtocolError):
        pass
    finally:
        close_fds(received_fds)
        if source_fd is not None:
            close_fds((source_fd,))
        if left is not None:
            left.close()
        if right is not None:
            right.close()
    return result


def assess_execution_layer(
    config_or_path: Mapping[str, Any] | Path | str = DEFAULT_CONFIG,
    *,
    project_root: Path | str = PROJECT_ROOT,
    command_runner: CommandRunner = _default_command_runner,
    model_parity_assessor: ParityAssessor = assess_model_parity,
    kernel_probe: KernelProbe = probe_local_ipc_kernel,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    config = _validate_config(config_or_path) if isinstance(config_or_path, Mapping) else load_execution_layer_config(config_or_path)
    blockers: list[str] = []
    kernel = kernel_probe()
    for primitive in ("socket_seqpacket", "scm_rights", "memfd_sealing"):
        if kernel.get(primitive) is not True:
            blockers.append(f"kernel_capability_missing:{primitive}")
    images: dict[str, dict[str, Any]] = {}
    probes: dict[str, dict[str, Any] | None] = {}
    for resource_name in ("cpu", "gpu"):
        worker = config["workers"][resource_name]
        base = _inspect_image(worker["base_image"], command_runner)
        derived = _inspect_image(worker["image"], command_runner)
        images[resource_name] = {
            "base": base or {"reference": worker["base_image"], "available": False},
            "worker": derived or {"reference": worker["image"], "available": False},
        }
        if base is None:
            blockers.append(f"base_image_missing:{resource_name}")
        elif base["image_id"] != worker["base_image_id"]:
            blockers.append(f"base_image_id_mismatch:{resource_name}")
        if worker["image_id"] is None:
            blockers.append(f"worker_image_id_not_frozen:{resource_name}")
        if derived is None:
            blockers.append(f"worker_image_missing:{resource_name}")
        elif worker["image_id"] is not None and derived["image_id"] != worker["image_id"]:
            blockers.append(f"worker_image_id_mismatch:{resource_name}")
        if derived is not None:
            if derived["labels"]["base_image_id"] != worker["base_image_id"]:
                blockers.append(f"worker_base_label_mismatch:{resource_name}")
            if derived["labels"]["engine"] != worker["engine"]:
                blockers.append(f"worker_engine_label_mismatch:{resource_name}")
        probe = _runtime_probe(worker, command_runner) if derived is not None else None
        probes[resource_name] = probe
        if probe is None:
            blockers.append(f"worker_probe_contract_invalid:{resource_name}")
        elif probe["worker_implementation_sha256"] != worker["worker_implementation_sha256"]:
            blockers.append(f"worker_implementation_sha256_mismatch:{resource_name}")
    manifest_path = root / config["model_parity_manifest"]
    try:
        parity = model_parity_assessor(
            manifest_path,
            project_root=root,
            command_runner=command_runner,
        )
    except Exception as error:
        parity = {"publication_ready": False, "manifest_identity_sha256": None, "blockers": [f"assessment_error:{type(error).__name__}"]}
    if parity.get("publication_ready") is not True:
        blockers.append("model_parity_not_ready")
        blockers.extend(f"model_parity:{value}" for value in parity.get("blockers", []))
    blockers = list(dict.fromkeys(blockers))
    assessment = {
        "schema_version": 1,
        "artifact_kind": ASSESSMENT_KIND,
        "config_identity_sha256": config["identity"]["sha256"],
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "execution_layer_ready": not blockers,
        "openvino_gpu_counted_as_nvidia_cuda": False,
        "network_or_download_performed": False,
        "model_inference_performed": False,
        "kernel_capabilities": kernel,
        "runtime_images": images,
        "runtime_probes": probes,
        "model_parity": {
            "publication_ready": parity.get("publication_ready") is True,
            "manifest_identity_sha256": parity.get("manifest_identity_sha256"),
            "blocker_count": len(parity.get("blockers", [])),
        },
        "blockers": blockers,
    }
    assessment["identity"] = {"algorithm": "sha256", "sha256": canonical_sha256(assessment)}
    return assessment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assess the native dual analytics execution layer.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = assess_execution_layer(args.config, project_root=args.project_root)
        exit_code = 0 if result["execution_layer_ready"] else 78
    except ProtocolError as error:
        result = {
            "schema_version": 1,
            "artifact_kind": "vast_analytics_execution_layer_error",
            "status": "contract_error",
            "message": str(error),
        }
        exit_code = 78
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSESSMENT_KIND", "CONFIG_KIND", "assess_execution_layer",
    "build_runtime_probe_command", "load_execution_layer_config", "main",
    "probe_local_ipc_kernel",
]
