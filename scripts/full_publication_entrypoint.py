#!/usr/bin/env python3
"""Production CLI and exact arm adapter for the frozen full publication run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import os
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import psutil
import yaml

from benchmark_contract import (
    ContractError,
    assess_hardware_target,
    resource_capability_grant_from_identity_artifacts,
    validate_pre_run_resource_capability_grant,
)
from backend_runtime_grant import (
    BackendRuntimeGrantError,
    backend_runtime_grant_from_identity_artifacts,
    validate_pre_run_backend_runtime_grant,
)
from model_parity_grant import (
    ModelParityGrantError,
    model_parity_grant_from_identity_artifacts,
    validate_pre_run_model_parity_grant,
)
from checkpoint_acceptance_metadata_binding import (
    AcceptanceMetadataBindingError,
    validate_full_publication_execution_binding,
)
from full_publication_runner import (
    ArmContext,
    CallbackDecision,
    ExitCode,
    FullPublicationRunner,
    IdentityDriftError,
    PermanentRunError,
    RunContext,
    RunResult,
    RunRootLockedError,
    TransientRunError,
)
from full_publication_results import export_finalized_results
from full_publication_identity_artifacts import (
    DEFAULT_MANIFEST as DEFAULT_IDENTITY_ARTIFACT_MANIFEST,
    IdentityArtifactError,
    load_full_publication_identity_artifacts,
)
from full_publication_runtime import FullPublicationRuntime
from publication_matrix import (
    DATASET_BY_CODEC,
    PUBLISHABLE_SYSTEMS,
    build_full_publication_matrix,
    publication_matrix_identity,
    validate_full_publication_readiness,
)
from run_experiments import ExecutionContext, load_config, normalize_scenario, run_one
from seafile_artifact_store import (
    ArtifactIntegrityError,
    ArtifactStoreError,
    SeafileArtifactStore,
    SeafileShareLinks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IDENTITY_INPUTS_SCHEMA_VERSION = 1
RUNTIME_SOURCE_ROOTS = ("scripts", "deploy", "configs", "policies")
RUNTIME_ROOT_FILES = ("CMakeLists.txt", "requirements.txt")
FULL_PUBLICATION_RUN_NAMESPACE = Path("runs/full_publication")
MODEL_FIELDS = (
    ("model_path", "model_sha256", "model"),
    ("weights_path", "weights_sha256", "weights"),
)
ARM_FIELDS = frozenset(
    {
        "arm_id",
        "arm_position",
        "scenario",
        "system",
        "codec",
        "dataset",
        "policy",
        "deadline_ms",
        "repeat",
        "seed",
        "streams",
        "warmup_s",
        "measurement_s",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


CommandRunner = Callable[[list[str]], str]
DatasetLoader = Callable[..., dict[str, Any]]
RunOne = Callable[..., dict[str, Any]]
ResultsExporter = Callable[[Any], Mapping[str, Any]]
IdentityArtifactsLoader = Callable[..., dict[str, Any]]


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError(f"production entrypoint value is not canonical JSON: {error}") from error


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_file_record(path: Path, *, project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    if path.is_symlink():
        raise ContractError(f"identity input must not be a symlink: {path}")
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ContractError(f"identity input escaped project_root: {path}") from None
    if not resolved.is_file():
        raise ContractError(f"identity input is missing or not a regular file: {relative.as_posix()}")
    before = resolved.stat()
    digest = _sha256_file(resolved)
    after = resolved.stat()
    stable = (
        before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and getattr(before, "st_ino", None) == getattr(after, "st_ino", None)
    )
    if not stable:
        raise ContractError(f"identity input changed while hashing: {relative.as_posix()}")
    return {
        "path": relative.as_posix(),
        "size_bytes": int(after.st_size),
        "sha256": digest,
    }


def _read_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ContractError(f"invalid {label}: {error}") from error
    if type(value) is not dict:
        raise ContractError(f"invalid {label}: expected a mapping")
    return value


def _project_path(value: Path | str, *, project_root: Path, label: str) -> Path:
    root = project_root.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ContractError(f"{label} must be inside project_root") from None
    return resolved


def _validated_run_root(value: Path | str, *, project_root: Path) -> Path:
    root = project_root.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    lexical = Path(os.path.abspath(os.fspath(candidate)))
    resolved = lexical.resolve()
    namespace_lexical = Path(
        os.path.abspath(os.fspath(root / FULL_PUBLICATION_RUN_NAMESPACE))
    )
    namespace = namespace_lexical.resolve()
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if namespace != namespace_lexical or namespace.is_symlink() or is_junction(namespace):
        raise ContractError("full publication run namespace is a symlink, junction, or alias")
    if lexical != resolved or lexical.is_symlink() or is_junction(lexical):
        raise ContractError("full publication run_root is a symlink, junction, or alias")
    try:
        relative = resolved.relative_to(namespace)
    except ValueError:
        raise ContractError(
            f"run_root must be a child of {FULL_PUBLICATION_RUN_NAMESPACE.as_posix()}"
        ) from None
    if not relative.parts:
        raise ContractError("run_root must be a dedicated child directory")
    if resolved.exists() and not resolved.is_dir():
        raise ContractError("full publication run_root exists and is not a directory")
    return resolved


def _runtime_source_manifest(project_root: Path) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    for root_name in RUNTIME_SOURCE_ROOTS:
        source_root = project_root / root_name
        if not source_root.is_dir() or source_root.is_symlink():
            raise ContractError(f"runtime source root is missing or invalid: {root_name}")
        for path in sorted(source_root.rglob("*")):
            relative_parts = path.relative_to(project_root).parts
            if any(part in {"__pycache__", ".pytest_cache"} for part in relative_parts):
                continue
            if path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            if path.is_dir():
                continue
            record = _stable_file_record(path, project_root=project_root)
            records[record["path"]] = record
    for name in RUNTIME_ROOT_FILES:
        path = project_root / name
        if path.exists():
            record = _stable_file_record(path, project_root=project_root)
            records[record["path"]] = record
    files = [records[name] for name in sorted(records)]
    if not files:
        raise ContractError("runtime source manifest is empty")
    return {
        "schema_version": 1,
        "roots": list(RUNTIME_SOURCE_ROOTS),
        "files": files,
        "files_sha256": _sha256_bytes(_canonical_json(files)),
    }


def _default_command_runner(command: list[str]) -> str:
    environment = os.environ.copy()
    environment.pop("VAST_SEAFILE_UPLOAD_LINK", None)
    environment.pop("VAST_SEAFILE_READ_LINK", None)
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.DEVNULL,
            env=environment,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise OSError("read-only system probe failed") from error


def _inspect_container_images(
    config: Mapping[str, Any], *, command_runner: CommandRunner
) -> list[dict[str, Any]]:
    systems = config.get("systems")
    if type(systems) is not dict:
        raise ContractError("config.systems must be a mapping")
    inspected: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for system_name in PUBLISHABLE_SYSTEMS:
        system = systems.get(system_name)
        if type(system) is not dict:
            raise ContractError(f"publishable system is missing: {system_name}")
        reference = str(system.get("container_image", "")).strip()
        if not reference:
            raise ContractError(f"container image is missing for system '{system_name}'")
        if reference not in inspected:
            try:
                raw = command_runner(
                    ["docker", "image", "inspect", "--format", "{{json .}}", reference]
                )
                payload = json.loads(raw)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                raise ContractError(
                    f"container image inspect failed for system '{system_name}'"
                ) from None
            if type(payload) is not dict:
                raise ContractError(
                    f"container image inspect returned invalid data for system '{system_name}'"
                )
            image_id = str(payload.get("Id", ""))
            if not image_id.startswith("sha256:") or _SHA256_RE.fullmatch(image_id[7:]) is None:
                raise ContractError(f"container image ID is invalid for system '{system_name}'")
            repo_digests = payload.get("RepoDigests") or []
            if type(repo_digests) is not list or any(type(value) is not str for value in repo_digests):
                raise ContractError(f"container image digests are invalid for system '{system_name}'")
            inspected[reference] = {
                "reference": reference,
                "image_id": image_id,
                "repo_digests": sorted(set(repo_digests)),
                "architecture": str(payload.get("Architecture", "")),
                "os": str(payload.get("Os", "")),
            }
        results.append({"system": system_name, **copy.deepcopy(inspected[reference])})
    return results


def _docker_runtime_identity(*, command_runner: CommandRunner) -> dict[str, Any]:
    try:
        payload = json.loads(
            command_runner(["docker", "version", "--format", "{{json .}}"])
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise ContractError("docker runtime version probe failed") from None
    if type(payload) is not dict:
        raise ContractError("docker runtime version probe returned invalid data")

    def endpoint(name: str) -> dict[str, Any]:
        value = payload.get(name)
        if type(value) is not dict or not str(value.get("Version", "")):
            raise ContractError(f"docker {name.lower()} version identity is incomplete")
        result = {
            key: str(value.get(key, ""))
            for key in (
                "Version",
                "ApiVersion",
                "GitCommit",
                "GoVersion",
                "Os",
                "Arch",
                "KernelVersion",
            )
            if value.get(key) not in (None, "")
        }
        components = value.get("Components") or []
        if type(components) is list:
            result["components"] = sorted(
                [
                    {
                        "name": str(component.get("Name", "")),
                        "version": str(component.get("Version", "")),
                    }
                    for component in components
                    if type(component) is dict and component.get("Name")
                ],
                key=lambda item: item["name"],
            )
        return result

    return {"client": endpoint("Client"), "server": endpoint("Server")}


def _cpu_runtime_identity(*, command_runner: CommandRunner) -> dict[str, Any]:
    try:
        cpu_payload = json.loads(command_runner(["lscpu", "-J"]))
    except OSError:
        if platform.system() != "Windows":
            raise ContractError("CPU hardware probe failed") from None
        powershell_command = (
            "$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 "
            "Name,Manufacturer,NumberOfLogicalProcessors,Architecture,ProcessorId; "
            "$cpu | ConvertTo-Json -Compress"
        )
        try:
            cpu_payload = json.loads(
                command_runner(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        powershell_command,
                    ]
                )
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise ContractError("Windows CPU hardware probe failed") from None
        if type(cpu_payload) is not dict:
            raise ContractError("Windows CPU hardware probe returned invalid data")
        cpu_model = str(cpu_payload.get("Name", "")).strip()
        if not cpu_model:
            raise ContractError("CPU model identity is missing")
        return {
            "source": "windows_cim",
            "model_name": cpu_model,
            "architecture": str(cpu_payload.get("Architecture", "")),
            "logical_cpus": str(cpu_payload.get("NumberOfLogicalProcessors", "")),
            "vendor_id": str(cpu_payload.get("Manufacturer", "")),
            "processor_id": str(cpu_payload.get("ProcessorId", "")),
        }
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ContractError("CPU hardware probe failed") from None

    rows = cpu_payload.get("lscpu") if type(cpu_payload) is dict else None
    if type(rows) is not list:
        raise ContractError("CPU hardware probe returned invalid data")
    cpu_fields = {
        str(row.get("field", "")).rstrip(":"): str(row.get("data", ""))
        for row in rows
        if type(row) is dict and row.get("field")
    }
    cpu_model = cpu_fields.get("Model name", "").strip()
    if not cpu_model:
        raise ContractError("CPU model identity is missing")
    return {
        "source": "lscpu",
        "model_name": cpu_model,
        "architecture": cpu_fields.get("Architecture", ""),
        "logical_cpus": cpu_fields.get("CPU(s)", ""),
        "vendor_id": cpu_fields.get("Vendor ID", ""),
    }


def _hardware_runtime_identity(
    *, command_runner: CommandRunner, ram_bytes: int | None
) -> dict[str, Any]:
    try:
        gpu_output = command_runner(
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,pci.bus_id,driver_version",
                "--format=csv,noheader,nounits",
            ]
        )
    except OSError:
        raise ContractError("NVIDIA hardware/driver probe failed") from None
    gpus: list[dict[str, str]] = []
    for raw_line in gpu_output.splitlines():
        if not raw_line.strip():
            continue
        values = [value.strip() for value in raw_line.split(",")]
        if len(values) != 4 or any(not value for value in values):
            raise ContractError("NVIDIA hardware/driver probe returned invalid data")
        gpus.append(
            {
                "name": values[0],
                "uuid": values[1],
                "pci_bus_id": values[2],
                "driver_version": values[3],
            }
        )
    if not gpus:
        raise ContractError("NVIDIA hardware/driver probe found no GPU")

    cpu = _cpu_runtime_identity(command_runner=command_runner)
    cpu_model = str(cpu["model_name"])

    resolved_ram_bytes = int(psutil.virtual_memory().total if ram_bytes is None else ram_bytes)
    if resolved_ram_bytes <= 0:
        raise ContractError("RAM identity is invalid")
    detected_hardware = {
        "gpu_model": gpus[0]["name"],
        "cpu_model": cpu_model,
        "ram_gb": round(resolved_ram_bytes / (1024**3), 3),
    }
    return {
        "detected_hardware": detected_hardware,
        "gpus": gpus,
        "cpu": cpu,
        "ram_bytes": resolved_ram_bytes,
        "docker": _docker_runtime_identity(command_runner=command_runner),
        "host_runtime": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
    }


def _redacted_cloud_destination(
    links: SeafileShareLinks, *, destination_id: str
) -> dict[str, Any]:
    normalized_id = destination_id.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", normalized_id) is None:
        raise ContractError(
            "Seafile destination ID must be a stable 8-128 character identifier"
        )
    material = {"base_url": links.base_url, "destination_id": normalized_id}
    return {
        "schema_version": 1,
        "transport": "https",
        "same_origin_capability_pair": True,
        "origin_sha256": _sha256_bytes(links.base_url.encode("utf-8")),
        "destination_id_sha256": _sha256_bytes(normalized_id.encode("utf-8")),
        "destination_sha256": _sha256_bytes(_canonical_json(material)),
    }


def _model_identity(
    model_manifest_path: Path, *, project_root: Path
) -> dict[str, Any]:
    manifest = _read_yaml_object(model_manifest_path, label="analytics model manifest")
    branches = manifest.get("branches")
    if type(branches) is not dict or not branches:
        raise ContractError("analytics model manifest branches are missing")
    artifacts: list[dict[str, Any]] = []
    for branch_name in sorted(branches):
        branch = branches[branch_name]
        if type(branch) is not dict:
            raise ContractError(f"analytics model branch is invalid: {branch_name}")
        for path_field, sha_field, kind in MODEL_FIELDS:
            raw_path = str(branch.get(path_field, "")).strip()
            declared_sha = str(branch.get(sha_field, "")).strip()
            if not raw_path or _SHA256_RE.fullmatch(declared_sha) is None:
                raise ContractError(f"analytics model {branch_name}.{sha_field} is invalid")
            path = (model_manifest_path.parent / raw_path).resolve()
            record = _stable_file_record(path, project_root=project_root)
            if record["sha256"] != declared_sha:
                raise ContractError(f"analytics model {branch_name}.{sha_field} mismatch")
            artifacts.append(
                {
                    "branch": str(branch_name),
                    "kind": kind,
                    **record,
                }
            )
    return {
        "manifest": _stable_file_record(model_manifest_path, project_root=project_root),
        "artifacts": artifacts,
        "artifacts_sha256": _sha256_bytes(_canonical_json(artifacts)),
    }


@dataclass(frozen=True)
class ImmutableFileGuard:
    path: Path
    size_bytes: int
    mtime_ns: int
    sha256: str
    always_rehash: bool = False


DatasetFileGuard = ImmutableFileGuard


@dataclass(frozen=True)
class IdentityMaterial:
    identity_inputs: dict[str, Any]
    datasets: dict[str, dict[str, Any]]
    dataset_guards: dict[str, tuple[DatasetFileGuard, ...]]
    execution_guards: tuple[ImmutableFileGuard, ...]


def _identity_file_guards(
    value: Any, *, project_root: Path
) -> tuple[ImmutableFileGuard, ...]:
    records: dict[str, tuple[int, str]] = {}

    def visit(item: Any) -> None:
        if type(item) is dict:
            raw_path = item.get("path")
            size = item.get("size_bytes")
            sha256 = item.get("sha256")
            if (
                type(raw_path) is str
                and raw_path
                and type(size) is int
                and size >= 0
                and type(sha256) is str
                and _SHA256_RE.fullmatch(sha256) is not None
            ):
                identity = (size, sha256)
                previous = records.get(raw_path)
                if previous is not None and previous != identity:
                    raise ContractError(
                        f"identity file record conflicts for path: {raw_path}"
                    )
                records[raw_path] = identity
            for child in item.values():
                visit(child)
        elif type(item) is list:
            for child in item:
                visit(child)

    visit(value)
    identity_artifact_paths = {
        str(record.get("path"))
        for record in ((value.get("identity_artifacts") or {}).get("files") or [])
        if type(record) is dict and type(record.get("path")) is str
    }
    guards: list[ImmutableFileGuard] = []
    for relative_path in sorted(records):
        path = _project_path(
            relative_path,
            project_root=project_root,
            label="identity file guard",
        )
        if path.is_symlink() or not path.is_file():
            raise ContractError(f"identity file guard is invalid: {relative_path}")
        stat = path.stat()
        expected_size, expected_sha256 = records[relative_path]
        if int(stat.st_size) != expected_size:
            raise ContractError(f"identity file size drift: {relative_path}")
        guards.append(
            ImmutableFileGuard(
                path=path,
                size_bytes=expected_size,
                mtime_ns=int(stat.st_mtime_ns),
                sha256=expected_sha256,
                always_rehash=relative_path in identity_artifact_paths,
            )
        )
    if not guards:
        raise ContractError("immutable execution file guard set is empty")
    return tuple(guards)


def _dataset_identity_material(
    *,
    project_root: Path,
    dataset_manifest_path: Path,
    dataset_loader: DatasetLoader,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, tuple[DatasetFileGuard, ...]],
]:
    identity: dict[str, dict[str, Any]] = {}
    loaded: dict[str, dict[str, Any]] = {}
    guards: dict[str, tuple[DatasetFileGuard, ...]] = {}
    for dataset_name in sorted(set(DATASET_BY_CODEC.values())):
        try:
            raw_dataset = dataset_loader(
                dataset_manifest_path,
                dataset_name,
                mode="benchmark",
                project_root=project_root,
                require_files=True,
            )
        except ContractError:
            raise
        except Exception as error:
            raise ContractError(f"dataset load/checksum failed for '{dataset_name}': {error}") from error
        dataset = _json_copy(raw_dataset)
        if type(dataset) is not dict or dataset.get("name") != dataset_name:
            raise ContractError(f"dataset loader identity drift for '{dataset_name}'")
        streams = dataset.get("streams")
        if type(streams) is not list or not streams:
            raise ContractError(f"dataset '{dataset_name}' has no resolved streams")
        stream_records: list[dict[str, Any]] = []
        stream_guards: list[DatasetFileGuard] = []
        for index, stream in enumerate(streams):
            if type(stream) is not dict:
                raise ContractError(f"dataset '{dataset_name}' stream is invalid")
            raw_path = str(stream.get("absolute_path", "")).strip()
            if not raw_path:
                raise ContractError(f"dataset '{dataset_name}' stream lacks absolute_path")
            path = Path(raw_path)
            record = _stable_file_record(path, project_root=project_root)
            resolved_sha = str(stream.get("resolved_sha256", "")).strip()
            if resolved_sha != record["sha256"]:
                raise ContractError(
                    f"dataset '{dataset_name}' actual checksum drift: {record['path']}"
                )
            stat = path.stat()
            stream_records.append({"stream_index": index, **record})
            stream_guards.append(
                DatasetFileGuard(
                    path=path.resolve(),
                    size_bytes=int(stat.st_size),
                    mtime_ns=int(stat.st_mtime_ns),
                    sha256=str(record["sha256"]),
                )
            )
        manifest_schema = dataset.get("manifest_identity_schema_version")
        manifest_sha = dataset.get("manifest_identity_sha256")
        aggregate_sha = dataset.get("aggregate_sha256")
        if type(manifest_schema) is not int or not isinstance(manifest_sha, str):
            raise ContractError(f"dataset '{dataset_name}' manifest identity is missing")
        if _SHA256_RE.fullmatch(manifest_sha) is None or _SHA256_RE.fullmatch(str(aggregate_sha)) is None:
            raise ContractError(f"dataset '{dataset_name}' aggregate identity is invalid")
        identity[dataset_name] = {
            "manifest_identity": {
                "schema_version": manifest_schema,
                "sha256": manifest_sha,
            },
            "aggregate_sha256": str(aggregate_sha),
            "streams": stream_records,
        }
        loaded[dataset_name] = dataset
        guards[dataset_name] = tuple(stream_guards)
    return identity, loaded, guards


def build_identity_material(
    *,
    project_root: Path | str,
    config_path: Path | str,
    dataset_manifest_path: Path | str,
    model_manifest_path: Path | str,
    config: Mapping[str, Any],
    cloud_links: SeafileShareLinks,
    cloud_destination_id: str,
    dataset_loader: DatasetLoader,
    command_runner: CommandRunner = _default_command_runner,
    ram_bytes: int | None = None,
    identity_artifact_manifest_path: Path | str = DEFAULT_IDENTITY_ARTIFACT_MANIFEST,
    identity_artifacts: Mapping[str, Any] | None = None,
    identity_artifacts_loader: IdentityArtifactsLoader = (
        load_full_publication_identity_artifacts
    ),
) -> IdentityMaterial:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ContractError("project_root is missing")
    resolved_config_path = _project_path(config_path, project_root=root, label="config_path")
    resolved_dataset_path = _project_path(
        dataset_manifest_path, project_root=root, label="dataset_manifest_path"
    )
    resolved_model_path = _project_path(
        model_manifest_path, project_root=root, label="model_manifest_path"
    )
    parsed_config = _read_yaml_object(resolved_config_path, label="benchmark config")
    copied_config = _json_copy(config)
    if _canonical_json(parsed_config) != _canonical_json(copied_config):
        raise ContractError("in-memory benchmark config differs from config_path")

    if identity_artifacts is None:
        try:
            loaded_identity_artifacts = identity_artifacts_loader(
                project_root=root,
                manifest_path=identity_artifact_manifest_path,
            )
        except IdentityArtifactError as error:
            raise ContractError(
                f"full publication identity artifacts are blocked: {error}"
            ) from error
    else:
        loaded_identity_artifacts = _json_copy(identity_artifacts)
    if (
        type(loaded_identity_artifacts) is not dict
        or loaded_identity_artifacts.get("schema_version") != 2
        or loaded_identity_artifacts.get("artifact_kind")
        != "vast_full_publication_identity_artifact_binding"
        or _SHA256_RE.fullmatch(
            str(loaded_identity_artifacts.get("binding_sha256", ""))
        )
        is None
    ):
        raise ContractError("full publication identity artifact binding is invalid")

    dataset_identity, datasets, dataset_guards = _dataset_identity_material(
        project_root=root,
        dataset_manifest_path=resolved_dataset_path,
        dataset_loader=dataset_loader,
    )
    policies_root = root / "policies"
    policy_records = [
        _stable_file_record(path, project_root=root)
        for path in sorted(policies_root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    if not policy_records:
        raise ContractError("policy artifact identity is empty")

    identity_inputs = {
        "schema_version": IDENTITY_INPUTS_SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_identity_inputs",
        "runtime_sources": _runtime_source_manifest(root),
        "config": _stable_file_record(resolved_config_path, project_root=root),
        "dataset_manifest": _stable_file_record(resolved_dataset_path, project_root=root),
        "datasets": dataset_identity,
        "models": _model_identity(resolved_model_path, project_root=root),
        "identity_artifacts": loaded_identity_artifacts,
        "policy_artifacts": {
            "files": policy_records,
            "files_sha256": _sha256_bytes(_canonical_json(policy_records)),
        },
        "container_images": _inspect_container_images(
            copied_config, command_runner=command_runner
        ),
        "hardware_runtime": _hardware_runtime_identity(
            command_runner=command_runner,
            ram_bytes=ram_bytes,
        ),
        "cloud_destination": _redacted_cloud_destination(
            cloud_links, destination_id=cloud_destination_id
        ),
    }
    return IdentityMaterial(
        identity_inputs=_json_copy(identity_inputs),
        datasets=datasets,
        dataset_guards=dataset_guards,
        execution_guards=_identity_file_guards(
            identity_inputs, project_root=root
        ),
    )


def build_identity_inputs(**kwargs: Any) -> dict[str, Any]:
    """Public convenience wrapper for callers that only need immutable inputs."""

    return build_identity_material(**kwargs).identity_inputs


def build_offline_publication_plan(config: Mapping[str, Any]) -> dict[str, Any]:
    """Build and validate the frozen matrix/policy plan without execution probes.

    The offline plan deliberately has no ``run_identity``.  That identity is only
    valid after preflight has bound immutable datasets, models, runtime sources,
    container image IDs, hardware, and the stable cloud destination.
    """

    copied_config = _json_copy(config)
    if type(copied_config) is not dict:
        raise ContractError("benchmark config must be a mapping")
    matrix = build_full_publication_matrix(copied_config)
    validation_runner = FullPublicationRunner(
        Path("__vast_offline_plan_read_only__"),
        config=copied_config,
        identity_inputs={
            "schema_version": 1,
            "artifact_kind": "vast_offline_plan_validation_identity",
        },
        matrix_builder=lambda _config: copy.deepcopy(matrix),
    )
    validated = validation_runner.plan()
    matrix_identity = publication_matrix_identity(matrix)
    if _canonical_json(validated.get("matrix_identity")) != _canonical_json(
        matrix_identity
    ):
        raise ContractError("offline full publication matrix identity drift")
    if (validated.get("expected_pairs"), validated.get("expected_arms")) != (
        2800,
        5600,
    ):
        raise ContractError("offline full publication matrix cardinality drift")

    policy_identity = _json_copy(matrix.get("policy_contract_identity"))
    if (
        type(policy_identity) is not dict
        or _SHA256_RE.fullmatch(str(policy_identity.get("sha256", ""))) is None
    ):
        raise ContractError("offline full publication policy identity is invalid")
    contract_fields = (
        "publication_scope",
        "selection_basis",
        "order_strategy",
        "policy_contract_identity",
        "seed",
        "systems",
        "scenarios",
        "codecs",
        "policies",
        "deadlines_ms",
        "repeats",
        "warmup_s",
        "measurement_s",
        "expected_pairs",
        "expected_arms",
    )
    matrix_contract = {
        field: copy.deepcopy(matrix[field]) for field in contract_fields
    }
    offline_identity_material = {
        "matrix_identity": matrix_identity,
        "policy_contract_identity": policy_identity,
    }
    return _json_copy(
        {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_offline_plan",
            "planning_only": True,
            "execution_identity_status": "not_built_offline",
            "requires_execution_preflight": True,
            "offline_plan_identity": {
                "schema_version": 1,
                "sha256": _sha256_bytes(_canonical_json(offline_identity_material)),
            },
            "matrix_identity": matrix_identity,
            "policy_contract_identity": policy_identity,
            "matrix_contract": matrix_contract,
            "policies": copy.deepcopy(matrix["policies"]),
            "expected_pairs": int(validated["expected_pairs"]),
            "expected_arms": int(validated["expected_arms"]),
            "pairs": copy.deepcopy(validated["pairs"]),
        }
    )


class RealArmRunner:
    """Map one frozen arm exactly to ``run_experiments.run_one``."""

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        project_root: Path | str,
        dataset_manifest_path: Path | str,
        verified_datasets: Mapping[str, Mapping[str, Any]] | None = None,
        dataset_guards: Mapping[str, Sequence[DatasetFileGuard]] | None = None,
        execution_guards: Sequence[ImmutableFileGuard] | None = None,
        resource_capability_grant: Mapping[str, Any] | None = None,
        backend_runtime_grant: Mapping[str, Any] | None = None,
        model_parity_grant: Mapping[str, Any] | None = None,
        identity_artifacts: Mapping[str, Any] | None = None,
        frozen_image_ids: Mapping[str, str] | None = None,
        dataset_loader: DatasetLoader | None = None,
        run_one_fn: RunOne = run_one,
    ) -> None:
        self.config = _json_copy(config)
        self.project_root = Path(project_root).resolve()
        self.dataset_manifest_path = Path(dataset_manifest_path).resolve()
        self.run_one_fn = run_one_fn
        self.execution_guards = tuple(execution_guards or ())
        self.identity_artifacts = (
            _json_copy(identity_artifacts)
            if identity_artifacts is not None
            else None
        )
        self.resource_capability_grant = (
            validate_pre_run_resource_capability_grant(
                _json_copy(resource_capability_grant)
            )
            if resource_capability_grant is not None
            else None
        )
        try:
            self.backend_runtime_grant = (
                validate_pre_run_backend_runtime_grant(
                    _json_copy(backend_runtime_grant)
                )
                if backend_runtime_grant is not None
                else None
            )
        except BackendRuntimeGrantError as error:
            raise ContractError(f"invalid pre-run backend runtime grant: {error}") from error
        try:
            self.model_parity_grant = (
                validate_pre_run_model_parity_grant(
                    _json_copy(model_parity_grant)
                )
                if model_parity_grant is not None
                else None
            )
        except ModelParityGrantError as error:
            raise ContractError(f"invalid pre-run model-parity grant: {error}") from error
        if self.model_parity_grant is not None:
            if type(self.identity_artifacts) is not dict:
                raise ContractError(
                    "model-parity grant requires validated schema-2 identity artifacts"
                )
            try:
                identity_model_parity_grant = (
                    model_parity_grant_from_identity_artifacts(
                        self.identity_artifacts
                    )
                )
            except ModelParityGrantError as error:
                raise ContractError(
                    f"model-parity identity binding is invalid: {error}"
                ) from error
            if identity_model_parity_grant != self.model_parity_grant:
                raise ContractError(
                    "model-parity grant differs from immutable identity artifacts"
                )
            try:
                run_one_parameters = inspect.signature(self.run_one_fn).parameters
            except (TypeError, ValueError) as error:
                raise ContractError(
                    "run_one signature cannot receive the verified model-parity grant"
                ) from error
            accepts_model_parity_grant = (
                "model_parity_grant" in run_one_parameters
                or any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in run_one_parameters.values()
                )
            )
            if not accepts_model_parity_grant:
                raise ContractError(
                    "run_one cannot receive the verified model-parity grant"
                )
        if frozen_image_ids is not None:
            image_ids = {str(key): str(value) for key, value in frozen_image_ids.items()}
            if set(image_ids) != set(PUBLISHABLE_SYSTEMS):
                raise ContractError("frozen container image ID map is incomplete")
            systems = self.config.get("systems")
            if type(systems) is not dict:
                raise ContractError("config.systems must be a mapping")
            for system_name in PUBLISHABLE_SYSTEMS:
                image_id = image_ids[system_name]
                if not image_id.startswith("sha256:") or _SHA256_RE.fullmatch(image_id[7:]) is None:
                    raise ContractError(
                        f"frozen container image ID is invalid: {system_name}"
                    )
                system_config = systems.get(system_name)
                if type(system_config) is not dict:
                    raise ContractError(f"publishable system is missing: {system_name}")
                system_config["container_image"] = image_id
        if verified_datasets is None:
            loader = dataset_loader
            if loader is None:
                from benchmark_contract import load_dataset as loader

            _, loaded, guards = _dataset_identity_material(
                project_root=self.project_root,
                dataset_manifest_path=self.dataset_manifest_path,
                dataset_loader=loader,
            )
            self.datasets = loaded
            self.dataset_guards = guards
        else:
            self.datasets = {
                str(name): _json_copy(value)
                for name, value in verified_datasets.items()
            }
            if dataset_guards is None:
                derived: dict[str, tuple[DatasetFileGuard, ...]] = {}
                for name, dataset in self.datasets.items():
                    values: list[DatasetFileGuard] = []
                    for stream in dataset.get("streams") or []:
                        path = Path(str(stream.get("absolute_path", ""))).resolve()
                        if not path.is_file() or path.is_symlink():
                            raise ContractError(f"verified dataset file is missing: {path}")
                        stat = path.stat()
                        actual = _sha256_file(path)
                        if actual != str(stream.get("resolved_sha256", "")):
                            raise ContractError(f"verified dataset checksum drift: {path.name}")
                        values.append(
                            DatasetFileGuard(
                                path=path,
                                size_bytes=int(stat.st_size),
                                mtime_ns=int(stat.st_mtime_ns),
                                sha256=actual,
                            )
                        )
                    derived[name] = tuple(values)
                self.dataset_guards = derived
            else:
                self.dataset_guards = {
                    str(name): tuple(values) for name, values in dataset_guards.items()
                }

    @staticmethod
    def _equal_number(actual: Any, expected: Any) -> bool:
        if isinstance(actual, bool) or isinstance(expected, bool):
            return False
        try:
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False

    def _verify_dataset_unchanged(self, dataset_name: str) -> None:
        guards = list(self.dataset_guards.get(dataset_name) or ())
        if not guards:
            raise ContractError(f"dataset '{dataset_name}' has no checksum guards")
        refreshed: list[DatasetFileGuard] = []
        for guard in guards:
            if not guard.path.is_file() or guard.path.is_symlink():
                raise ContractError(f"dataset file disappeared: {guard.path.name}")
            stat = guard.path.stat()
            if int(stat.st_size) == guard.size_bytes and int(stat.st_mtime_ns) == guard.mtime_ns:
                refreshed.append(guard)
                continue
            actual = _sha256_file(guard.path)
            if actual != guard.sha256:
                raise ContractError(f"dataset checksum changed after run freeze: {guard.path.name}")
            refreshed.append(
                DatasetFileGuard(
                    path=guard.path,
                    size_bytes=int(stat.st_size),
                    mtime_ns=int(stat.st_mtime_ns),
                    sha256=actual,
                )
            )
        self.dataset_guards[dataset_name] = tuple(refreshed)

    def _verify_execution_inputs_unchanged(self) -> None:
        refreshed: list[ImmutableFileGuard] = []
        for guard in self.execution_guards:
            if guard.path.is_symlink() or not guard.path.is_file():
                raise ContractError(
                    f"immutable execution input disappeared: {guard.path.name}"
                )
            stat = guard.path.stat()
            if (
                int(stat.st_size) == guard.size_bytes
                and int(stat.st_mtime_ns) == guard.mtime_ns
                and not guard.always_rehash
            ):
                refreshed.append(guard)
                continue
            actual = _sha256_file(guard.path)
            if actual != guard.sha256:
                raise ContractError(
                    f"immutable execution input changed after run freeze: {guard.path.name}"
                )
            refreshed.append(
                ImmutableFileGuard(
                    path=guard.path,
                    size_bytes=int(stat.st_size),
                    mtime_ns=int(stat.st_mtime_ns),
                    sha256=actual,
                    always_rehash=guard.always_rehash,
                )
            )
        self.execution_guards = tuple(refreshed)

    def _validate_arm(self, arm: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if type(arm) is not dict or set(arm) != ARM_FIELDS:
            raise ContractError("frozen arm schema drift")
        protocol = self.config.get("protocol") or {}
        exact_protocol = {
            "warmup_s": int(protocol.get("warmup_s", 0) or 0),
            "measurement_s": int(protocol.get("measurement_s", 0) or 0),
        }
        for field, expected in exact_protocol.items():
            if type(arm.get(field)) is not int or arm[field] != expected:
                raise ContractError(f"frozen arm {field} drift")
        if type(arm.get("streams")) is not int or arm["streams"] != 6:
            raise ContractError("frozen arm streams drift")
        if type(arm.get("repeat")) is not int or not 1 <= arm["repeat"] <= int(
            protocol.get("repeats", 0) or 0
        ):
            raise ContractError("frozen arm repeat drift")
        benchmark = self.config.get("benchmark") or {}
        if arm.get("seed") != benchmark.get("default_seed"):
            raise ContractError("frozen arm seed drift")
        if arm.get("policy") not in (benchmark.get("scheduler_policies") or []):
            raise ContractError("frozen arm policy drift")
        if not any(
            self._equal_number(arm.get("deadline_ms"), value)
            for value in (benchmark.get("deadline_ms") or [])
        ):
            raise ContractError("frozen arm deadline_ms drift")
        codec = str(arm.get("codec", ""))
        expected_dataset = DATASET_BY_CODEC.get(codec)
        if expected_dataset is None or arm.get("dataset") != expected_dataset:
            raise ContractError("frozen arm codec/dataset mapping drift")
        dataset = self.datasets.get(expected_dataset)
        if type(dataset) is not dict:
            raise ContractError(f"verified dataset is missing: {expected_dataset}")
        system = str(arm.get("system", ""))
        system_config = (self.config.get("systems") or {}).get(system)
        if system not in PUBLISHABLE_SYSTEMS or type(system_config) is not dict:
            raise ContractError("frozen arm system drift")
        if str(system_config.get("benchmark_status", "supported")) != "supported":
            raise ContractError("frozen arm system is not benchmark-supported")
        scenario_name = str(arm.get("scenario", ""))
        raw_scenario = (self.config.get("scenarios") or {}).get(scenario_name)
        if type(raw_scenario) is not dict:
            raise ContractError("frozen arm scenario drift")
        scenario = normalize_scenario(scenario_name, raw_scenario)
        if bool((scenario.get("distributed") or {}).get("enabled")):
            raise ContractError("full publication arm must use local heterogeneous execution")
        workload_streams = int((scenario.get("workload") or {}).get("streams", 0) or 0)
        if workload_streams != arm["streams"]:
            raise ContractError("frozen arm streams differ from scenario workload")
        return scenario, dataset

    def __call__(self, context: ArmContext, arm_root: Path) -> dict[str, Any]:
        self._verify_execution_inputs_unchanged()
        arm = _json_copy(context.arm)
        scenario, dataset = self._validate_arm(arm)
        self._verify_dataset_unchanged(str(arm["dataset"]))
        workload = scenario.get("workload") or {}
        object_density = workload.get("object_density") or {}
        execution_context = ExecutionContext(
            run_kind="heterogeneous",
            deployment_mode="heterogeneous",
            host_topology="single_host",
            distributed_enabled=False,
            hosts_config={},
            hosts_config_path=Path("<local-heterogeneous>"),
            sync_project=False,
        )
        try:
            execution_binding = validate_full_publication_execution_binding(
                {
                    "schema_version": 1,
                    "artifact_kind": "vast_full_publication_arm_execution_binding",
                    "run_identity_sha256": str(
                        context.pair_context.run.run_identity["sha256"]
                    ),
                    "sequence": context.sequence,
                    "pair_id": str(context.pair_context.pair["pair_id"]),
                    "attempt": context.attempt,
                    "arm_id": str(arm["arm_id"]),
                }
            )
        except (AcceptanceMetadataBindingError, KeyError) as error:
            raise ContractError(
                f"invalid immutable arm execution identity: {error}"
            ) from error
        run_one_arguments = dict(
            config=copy.deepcopy(self.config),
            project_root=self.project_root,
            dataset=copy.deepcopy(dataset),
            system_key=str(arm["system"]),
            scenario=scenario,
            streams=int(arm["streams"]),
            min_objects=int(object_density.get("min", 0)),
            max_objects=int(object_density.get("max", 20)),
            duration_s=int(arm["measurement_s"]),
            repeat_index=int(arm["repeat"]),
            run_root=Path(arm_root),
            execution_context=execution_context,
            mode="benchmark",
            policy=str(arm["policy"]),
            deadline_ms=float(arm["deadline_ms"]),
            base_seed=int(arm["seed"]),
            dry_run_plan=False,
            directory_dataset_name=str(arm["dataset"]),
            directory_policy=str(arm["policy"]),
            primary_architecture_pair=None,
            primary_policy_pair=None,
            resource_capability_grant=copy.deepcopy(
                self.resource_capability_grant
            ),
            backend_runtime_grant=copy.deepcopy(self.backend_runtime_grant),
            full_publication_execution_binding=execution_binding,
            full_publication_identity_artifacts=copy.deepcopy(
                self.identity_artifacts
            ),
        )
        if self.model_parity_grant is not None:
            run_one_arguments["model_parity_grant"] = copy.deepcopy(
                self.model_parity_grant
            )
        result = self.run_one_fn(**run_one_arguments)
        if type(result) is not dict:
            raise ContractError("run_one returned an invalid result")
        exact_fields = (
            "system",
            "scenario",
            "repeat",
            "streams",
            "duration_s",
            "policy",
            "dataset",
            "seed",
        )
        for field in exact_fields:
            if result.get(field) != arm[field if field != "duration_s" else "measurement_s"]:
                raise ContractError(f"run_one result identity drift: {field}")
        if not self._equal_number(result.get("deadline_ms"), arm["deadline_ms"]):
            raise ContractError("run_one result identity drift: deadline_ms")
        if (
            result.get("status") != "completed"
            or result.get("distributed") is not False
            or result.get("deployment_mode") != "heterogeneous"
        ):
            raise ContractError("run_one did not complete in local heterogeneous mode")
        return {"status": "completed", "arm_id": str(arm["arm_id"])}


def production_readiness_validator(
    config: Mapping[str, Any],
    *,
    detected_hardware: Mapping[str, Any],
    resource_capability_grant: Mapping[str, Any] | None = None,
    backend_runtime_grant: Mapping[str, Any] | None = None,
    model_parity_grant: Mapping[str, Any] | None = None,
    scientific_validator: Callable[..., Mapping[str, Any]] = (
        validate_full_publication_readiness
    ),
) -> dict[str, Any]:
    verified_grant = (
        validate_pre_run_resource_capability_grant(
            _json_copy(resource_capability_grant)
        )
        if resource_capability_grant is not None
        else None
    )
    try:
        verified_backend_grant = (
            validate_pre_run_backend_runtime_grant(
                _json_copy(backend_runtime_grant)
            )
            if backend_runtime_grant is not None
            else None
        )
    except BackendRuntimeGrantError as error:
        raise ContractError(f"invalid pre-run backend runtime grant: {error}") from error
    try:
        verified_model_parity_grant = (
            validate_pre_run_model_parity_grant(
                _json_copy(model_parity_grant)
            )
            if model_parity_grant is not None
            else None
        )
    except ModelParityGrantError as error:
        raise ContractError(f"invalid pre-run model-parity grant: {error}") from error
    copied_config = _json_copy(config)
    try:
        inspect.signature(scientific_validator).bind(
            copied_config,
            resource_capability_grant=copy.deepcopy(verified_grant),
            backend_runtime_grant=copy.deepcopy(verified_backend_grant),
            model_parity_grant=copy.deepcopy(verified_model_parity_grant),
        )
    except (TypeError, ValueError):
        if (
            verified_grant is not None
            or verified_backend_grant is not None
            or verified_model_parity_grant is not None
        ):
            raise ContractError(
                "scientific readiness validator cannot receive all verified pre-run grants"
            )
        raw_assessment = scientific_validator(copied_config)
    else:
        raw_assessment = scientific_validator(
            copied_config,
            resource_capability_grant=copy.deepcopy(verified_grant),
            backend_runtime_grant=copy.deepcopy(verified_backend_grant),
            model_parity_grant=copy.deepcopy(verified_model_parity_grant),
        )
    assessment = _json_copy(raw_assessment)
    if type(assessment) is not dict or type(assessment.get("passed")) is not bool:
        raise ContractError("scientific readiness validator returned an invalid assessment")
    blockers = [str(value) for value in assessment.get("blockers") or []]
    hardware = assess_hardware_target(
        dict(config.get("hardware_target") or {}),
        dict(detected_hardware),
    )
    blockers.extend(f"hardware:{value}" for value in hardware["blockers"])
    blockers = list(dict.fromkeys(blockers))
    assessment["passed"] = not blockers
    assessment["status"] = "ready" if not blockers else "blocked"
    assessment["blockers"] = blockers
    assessment["hardware_target_assessment"] = hardware
    return assessment


class OfflinePlanEntrypoint:
    """Dispatch only a pure, explicitly non-executable matrix/policy plan."""

    def __init__(self, *, config: Mapping[str, Any]) -> None:
        self._plan_payload = build_offline_publication_plan(config)

    def dispatch(self, command: str) -> tuple[int, dict[str, Any]]:
        if command != "plan":
            raise ContractError("offline publication planner only supports 'plan'")
        return int(ExitCode.COMPLETE), _json_copy(self._plan_payload)


class ProductionEntrypoint:
    """Read-only planning/preflight plus persistent full-run command dispatch."""

    def __init__(
        self,
        *,
        runner: FullPublicationRunner,
        runtime: FullPublicationRuntime,
        results_exporter: ResultsExporter = export_finalized_results,
    ) -> None:
        self.runner = runner
        self.runtime = runtime
        self.results_exporter = results_exporter

    def _plan(self) -> dict[str, Any]:
        plan = _json_copy(self.runner.plan())
        if (
            type(plan) is not dict
            or type(plan.get("expected_pairs")) is not int
            or type(plan.get("expected_arms")) is not int
            or plan["expected_arms"] != plan["expected_pairs"] * 2
        ):
            raise ContractError("full publication plan is invalid")
        for field in ("matrix_identity", "run_identity"):
            value = plan.get(field)
            if type(value) is not dict or _SHA256_RE.fullmatch(str(value.get("sha256", ""))) is None:
                raise ContractError(f"full publication plan lacks {field}")
        return plan

    def external_preflight(self) -> CallbackDecision:
        plan = self._plan()
        run_root = Path(self.runner.run_root)
        manifest_path = run_root / str(
            getattr(self.runner, "MANIFEST_NAME", "run_manifest.json")
        )
        checkpoint_path = run_root / str(
            getattr(self.runner, "CHECKPOINT_NAME", "checkpoint.json")
        )
        next_sequence = 0
        if manifest_path.exists() or checkpoint_path.exists():
            if (
                manifest_path.is_symlink()
                or checkpoint_path.is_symlink()
                or not manifest_path.is_file()
                or not checkpoint_path.is_file()
            ):
                raise ContractError("full publication resume markers are incomplete")
            status = _json_copy(self.runner.status())
            completed_pairs = status.get("completed_pairs")
            if (
                type(completed_pairs) is not int
                or completed_pairs < 0
                or completed_pairs > int(plan["expected_pairs"])
                or status.get("total_pairs") != int(plan["expected_pairs"])
                or _canonical_json(status.get("matrix_identity"))
                != _canonical_json(plan["matrix_identity"])
                or _canonical_json(status.get("run_identity"))
                != _canonical_json(plan["run_identity"])
            ):
                raise ContractError("full publication resume status identity drift")
            next_sequence = completed_pairs
        context = RunContext(
            run_root=run_root,
            matrix_identity=plan["matrix_identity"],
            run_identity=plan["run_identity"],
            next_sequence=next_sequence,
            total_pairs=int(plan["expected_pairs"]),
        )
        decision = self.runtime.preflight(context)
        if type(decision) is not CallbackDecision:
            raise ContractError("production preflight returned an invalid decision")
        return decision

    @staticmethod
    def _preflight_result(decision: CallbackDecision) -> tuple[int, dict[str, Any]]:
        details = _json_copy(decision.details)
        if type(details) is not dict:
            raise ContractError("production preflight details must be a mapping")
        if decision.accepted:
            return 0, {
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_external_preflight",
                "status": "ready",
                "passed": True,
                "retryable": False,
                "details": details,
            }
        exit_code = ExitCode.TRANSIENT if decision.retryable else ExitCode.PERMANENT
        return int(exit_code), {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_external_preflight",
            "status": "blocked_preflight",
            "passed": False,
            "retryable": bool(decision.retryable),
            "reason": str(decision.reason),
            "details": details,
        }

    @staticmethod
    def _run_result(result: RunResult) -> tuple[int, dict[str, Any]]:
        if type(result) is not RunResult or int(result.exit_code) not in {0, 75, 78}:
            raise ContractError("full runner returned invalid exit semantics")
        payload = asdict(result)
        payload["exit_code"] = int(result.exit_code)
        payload["schema_version"] = 1
        payload["artifact_kind"] = "vast_full_publication_command_result"
        return int(result.exit_code), _json_copy(payload)

    def _require_initialized_root(self) -> None:
        root = Path(self.runner.run_root)
        manifest_name = str(getattr(self.runner, "MANIFEST_NAME", "run_manifest.json"))
        if not root.is_dir():
            raise ContractError("full publication run is not initialized")
        if isinstance(self.runner, FullPublicationRunner) and not (root / manifest_name).is_file():
            raise ContractError("full publication run is not initialized")

    def dispatch(self, command: str) -> tuple[int, dict[str, Any]]:
        if command == "plan":
            return 0, self._plan()
        if command == "preflight":
            return self._preflight_result(self.external_preflight())
        if command == "run":
            preflight_exit, preflight_payload = self._preflight_result(
                self.external_preflight()
            )
            if preflight_exit != 0:
                return preflight_exit, preflight_payload
            return self._run_result(self.runner.run())
        self._require_initialized_root()
        if command == "status":
            payload = _json_copy(self.runner.status())
            code = payload.get("exit_code")
            if type(code) is not int or code not in {0, 75, 78}:
                raise ContractError("full publication status has invalid exit semantics")
            return code, payload
        if command == "verify":
            payload = _json_copy(self.runner.verify())
            if payload.get("passed") is not True:
                return int(ExitCode.PERMANENT), payload
            return (
                int(ExitCode.COMPLETE if payload.get("complete") is True else ExitCode.TRANSIENT),
                payload,
            )
        if command == "finalize":
            payload = _json_copy(self.runner.finalize())
            if payload.get("verified") is not True:
                return int(ExitCode.PERMANENT), payload
            return int(ExitCode.COMPLETE), payload
        if command == "export":
            payload = _json_copy(self.results_exporter(self.runner))
            if (
                type(payload) is not dict
                or payload.get("artifact_kind")
                != "vast_full_publication_compact_result_bundle"
            ):
                raise ContractError("full publication exporter returned an invalid bundle")
            return int(ExitCode.COMPLETE), payload
        raise ContractError(f"unknown production entrypoint command: {command}")


def _capacity_from_args(args: argparse.Namespace) -> float:
    raw: Any = args.capacity_confirmed_gib
    if raw is None:
        raw = os.environ.get("VAST_SEAFILE_CAPACITY_CONFIRMED_GIB", "0")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ContractError("confirmed Seafile capacity must be a finite number") from None
    if not math.isfinite(value) or value < 0:
        raise ContractError("confirmed Seafile capacity must be a non-negative finite number")
    return value


def _destination_id_from_args(args: argparse.Namespace) -> str:
    value = args.cloud_destination_id
    if value is None:
        value = os.environ.get("VAST_SEAFILE_DESTINATION_ID", "")
    normalized = str(value).strip()
    if not normalized:
        raise ContractError(
            "VAST_SEAFILE_DESTINATION_ID or --cloud-destination-id is required"
        )
    return normalized


def _consume_cloud_links_from_environment() -> SeafileShareLinks:
    try:
        return SeafileShareLinks.from_environment()
    finally:
        os.environ.pop("VAST_SEAFILE_UPLOAD_LINK", None)
        os.environ.pop("VAST_SEAFILE_READ_LINK", None)


def create_application(
    args: argparse.Namespace,
) -> OfflinePlanEntrypoint | ProductionEntrypoint:
    project_root = Path(args.project_root).resolve()
    config_path = _project_path(args.config, project_root=project_root, label="config")
    config = load_config(config_path)
    if type(config) is not dict:
        raise ContractError("benchmark config must be a mapping")
    if args.command == "plan":
        return OfflinePlanEntrypoint(config=config)

    if args.run_root is None:
        raise ContractError(f"--run-root is required for '{args.command}'")
    run_root = _validated_run_root(args.run_root, project_root=project_root)
    dataset_manifest_path = _project_path(
        args.datasets, project_root=project_root, label="datasets"
    )
    model_manifest_path = _project_path(
        args.models, project_root=project_root, label="models"
    )
    identity_artifact_manifest_path = _project_path(
        args.identity_artifacts,
        project_root=project_root,
        label="identity_artifacts",
    )
    try:
        identity_artifacts = load_full_publication_identity_artifacts(
            project_root=project_root,
            manifest_path=identity_artifact_manifest_path,
        )
    except IdentityArtifactError as error:
        raise ContractError(
            f"full publication identity artifacts are blocked: {error}"
        ) from error
    try:
        model_parity_grant = model_parity_grant_from_identity_artifacts(
            identity_artifacts
        )
    except ModelParityGrantError as error:
        raise ContractError(
            f"full publication model-parity grant is blocked: {error}"
        ) from error
    resource_capability_grant = resource_capability_grant_from_identity_artifacts(
        identity_artifacts
    )
    try:
        backend_runtime_grant = backend_runtime_grant_from_identity_artifacts(
            identity_artifacts
        )
    except BackendRuntimeGrantError as error:
        raise ContractError(
            f"full publication backend runtime grant is blocked: {error}"
        ) from error
    links = _consume_cloud_links_from_environment()
    from benchmark_contract import load_dataset

    material = build_identity_material(
        project_root=project_root,
        config_path=config_path,
        dataset_manifest_path=dataset_manifest_path,
        model_manifest_path=model_manifest_path,
        config=config,
        cloud_links=links,
        cloud_destination_id=_destination_id_from_args(args),
        dataset_loader=load_dataset,
        identity_artifact_manifest_path=identity_artifact_manifest_path,
        identity_artifacts=identity_artifacts,
    )
    detected_hardware = material.identity_inputs["hardware_runtime"]["detected_hardware"]
    readiness = lambda value: production_readiness_validator(
        value,
        detected_hardware=detected_hardware,
        resource_capability_grant=resource_capability_grant,
        backend_runtime_grant=backend_runtime_grant,
        model_parity_grant=model_parity_grant,
    )
    store = SeafileArtifactStore(links, timeout_s=float(args.cloud_timeout_s))
    arm_runner = RealArmRunner(
        config=config,
        project_root=project_root,
        dataset_manifest_path=dataset_manifest_path,
        verified_datasets=material.datasets,
        dataset_guards=material.dataset_guards,
        execution_guards=material.execution_guards,
        resource_capability_grant=resource_capability_grant,
        backend_runtime_grant=backend_runtime_grant,
        model_parity_grant=model_parity_grant,
        identity_artifacts=identity_artifacts,
        frozen_image_ids={
            str(record["system"]): str(record["image_id"])
            for record in material.identity_inputs["container_images"]
        },
    )
    runtime = FullPublicationRuntime(
        run_root=run_root,
        config=config,
        cloud_store=store,
        arm_runner=arm_runner,
        readiness_validator=readiness,
        minimum_free_bytes=int(float(args.minimum_free_gib) * 1024**3),
        capacity_confirmed_gib=_capacity_from_args(args),
    )
    runner = FullPublicationRunner(
        run_root,
        config=config,
        identity_inputs=material.identity_inputs,
        callbacks=runtime.callbacks(),
    )
    return ProductionEntrypoint(runner=runner, runtime=runtime)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute the immutable full VAST publication benchmark matrix."
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    parser.add_argument("--datasets", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument(
        "--models",
        type=Path,
        default=Path("configs/checkpoint_analytics_models_openvino.yaml"),
    )
    parser.add_argument(
        "--identity-artifacts",
        type=Path,
        default=DEFAULT_IDENTITY_ARTIFACT_MANIFEST,
    )
    parser.add_argument("--capacity-confirmed-gib", type=float)
    parser.add_argument("--cloud-destination-id")
    parser.add_argument("--minimum-free-gib", type=float, default=20.0)
    parser.add_argument("--cloud-timeout-s", type=float, default=120.0)
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "preflight",
            "run",
            "status",
            "verify",
            "finalize",
            "export",
        ),
    )
    return parser


def _error_payload(error: BaseException, *, exit_code: ExitCode) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_command_error",
        "status": "transient_error" if exit_code == ExitCode.TRANSIENT else "permanent_error",
        "exit_code": int(exit_code),
        "error_type": type(error).__name__,
        "message": str(error),
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    application_factory: Callable[
        [argparse.Namespace], OfflinePlanEntrypoint | ProductionEntrypoint
    ] = create_application,
    output_fn: Callable[[str], None] = print,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if float(args.minimum_free_gib) <= 0 or float(args.cloud_timeout_s) <= 0:
            raise ContractError("minimum free space and cloud timeout must be positive")
        application = application_factory(args)
        exit_code, payload = application.dispatch(args.command)
        if exit_code not in {0, 75, 78}:
            raise ContractError("production command returned unsupported exit code")
    except (RunRootLockedError, TransientRunError) as error:
        exit_code = int(ExitCode.TRANSIENT)
        payload = _error_payload(error, exit_code=ExitCode.TRANSIENT)
    except (
        ArtifactIntegrityError,
        ArtifactStoreError,
        ContractError,
        IdentityDriftError,
        PermanentRunError,
    ) as error:
        exit_code = int(ExitCode.PERMANENT)
        payload = _error_payload(error, exit_code=ExitCode.PERMANENT)
    except Exception as error:
        exit_code = int(ExitCode.PERMANENT)
        payload = _error_payload(error, exit_code=ExitCode.PERMANENT)
    output_fn(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "IdentityMaterial",
    "ImmutableFileGuard",
    "OfflinePlanEntrypoint",
    "ProductionEntrypoint",
    "RealArmRunner",
    "build_identity_inputs",
    "build_identity_material",
    "build_offline_publication_plan",
    "build_parser",
    "create_application",
    "main",
    "production_readiness_validator",
]
