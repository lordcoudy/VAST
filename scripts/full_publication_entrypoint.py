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

import backend_publication_dispatch_v3 as backend_dispatch_v3
import backend_publication_output_transaction_production_v3 as production_transaction_v3
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
from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
)
from run_experiments import (
    ExecutionContext,
    build_run_seed,
    deadline_slug,
    load_config,
    normalize_scenario,
)
from seafile_artifact_store import (
    ArtifactIntegrityError,
    ArtifactStoreError,
    SeafileArtifactStore,
    SeafileShareLinks,
)
from seafile_capacity_attestation_v1 import (
    SeafileCapacityAttestationV1Error,
    validate_seafile_capacity_attestation_v1,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IDENTITY_INPUTS_SCHEMA_VERSION = 1
RUNTIME_SOURCE_ROOTS = ("scripts", "deploy", "configs", "policies")
RUNTIME_ROOT_FILES = ("CMakeLists.txt", "requirements.txt")
FULL_PUBLICATION_RUN_NAMESPACE = Path("runs/full_publication")
PRODUCTION_RUNTIME_SOURCE_RELATIVE = Path(
    ".local/state/vast/publication/runtime/full-publication-cp312-v1"
)
PRODUCTION_RUNTIME_PROJECT_MOUNT = (
    ".publication-runtime/full-publication-cp312-v1"
)
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
ProductionV3Executor = Callable[..., dict[str, Any]]
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


def publication_arm_semantic_evidence_validator_v3(
    request: dict[str, object],
) -> dict[str, object]:
    """Validate held full-publication evidence without ambient module state.

    The production transaction admits only a stateless top-level function whose
    bytecode depends on deterministic builtins.  A small bounded JSON decoder is
    therefore kept inside this function instead of importing a parser through
    mutable module state.  Cryptographic file identities are supplied from the
    transaction's held descriptors; this validator cross-binds their exact
    paths/sizes/SHA-256 values to the arm acceptance and durable metadata.
    """

    def rejected(reason: str) -> dict[str, object]:
        return {
            "accepted": False,
            "status": "rejected",
            "details": {"reason": reason},
        }

    def valid_sha(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    def equal_number(left: object, right: object) -> bool:
        if left is True or left is False or right is True or right is False:
            return False
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return False
        return float(left) == float(right)

    def parse_json(payload: object) -> tuple[bool, object]:
        if (
            not isinstance(payload, bytes)
            or not payload
            or len(payload) > 64 * 1024 * 1024
            or not all(value < 128 for value in payload)
        ):
            return False, None
        text = payload.decode("ascii")
        text_size = len(text)

        def whitespace(position: int) -> int:
            while position < text_size and text[position] in " \t\r\n":
                position += 1
            return position

        def string_value(position: int) -> tuple[bool, object, int]:
            if position >= text_size or text[position] != '"':
                return False, None, position
            position += 1
            characters: list[str] = []
            escapes = {
                '"': '"',
                "\\": "\\",
                "/": "/",
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
            }
            while position < text_size:
                character = text[position]
                position += 1
                if character == '"':
                    return True, "".join(characters), position
                if character == "\\":
                    if position >= text_size:
                        return False, None, position
                    escaped = text[position]
                    position += 1
                    if escaped == "u":
                        if position + 4 > text_size:
                            return False, None, position
                        digits = text[position : position + 4]
                        if not all(
                            value in "0123456789abcdefABCDEF" for value in digits
                        ):
                            return False, None, position
                        position += 4
                        characters.append("?")
                    elif escaped in escapes:
                        characters.append(escapes[escaped])
                    else:
                        return False, None, position
                elif character in "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f":
                    return False, None, position
                else:
                    characters.append(character)
            return False, None, position

        def number_value(position: int) -> tuple[bool, object, int]:
            start = position
            if position < text_size and text[position] == "-":
                position += 1
            if position >= text_size:
                return False, None, position
            if text[position] == "0":
                position += 1
                if position < text_size and text[position] in "0123456789":
                    return False, None, position
            elif text[position] in "123456789":
                position += 1
                while position < text_size and text[position] in "0123456789":
                    position += 1
            else:
                return False, None, position
            floating = False
            if position < text_size and text[position] == ".":
                floating = True
                position += 1
                fraction_start = position
                while position < text_size and text[position] in "0123456789":
                    position += 1
                if position == fraction_start:
                    return False, None, position
            if position < text_size and text[position] in "eE":
                floating = True
                position += 1
                if position < text_size and text[position] in "+-":
                    position += 1
                exponent_start = position
                while position < text_size and text[position] in "0123456789":
                    position += 1
                if position == exponent_start:
                    return False, None, position
            token = text[start:position]
            if len(token) > 128:
                return False, None, position
            number = float(token) if floating else int(token)
            if isinstance(number, float) and not (-1e308 <= number <= 1e308):
                return False, None, position
            return True, number, position

        def value_at(position: int, depth: int) -> tuple[bool, object, int]:
            if depth > 80:
                return False, None, position
            position = whitespace(position)
            if position >= text_size:
                return False, None, position
            character = text[position]
            if character == '"':
                return string_value(position)
            if character == "{":
                result: dict[str, object] = {}
                position = whitespace(position + 1)
                if position < text_size and text[position] == "}":
                    return True, result, position + 1
                while position < text_size:
                    key_ok, key, position = string_value(position)
                    if not key_ok or not isinstance(key, str) or key in result:
                        return False, None, position
                    position = whitespace(position)
                    if position >= text_size or text[position] != ":":
                        return False, None, position
                    item_ok, item, position = value_at(position + 1, depth + 1)
                    if not item_ok:
                        return False, None, position
                    result[key] = item
                    position = whitespace(position)
                    if position < text_size and text[position] == "}":
                        return True, result, position + 1
                    if position >= text_size or text[position] != ",":
                        return False, None, position
                    position = whitespace(position + 1)
                return False, None, position
            if character == "[":
                result_list: list[object] = []
                position = whitespace(position + 1)
                if position < text_size and text[position] == "]":
                    return True, result_list, position + 1
                while position < text_size:
                    item_ok, item, position = value_at(position, depth + 1)
                    if not item_ok:
                        return False, None, position
                    result_list.append(item)
                    position = whitespace(position)
                    if position < text_size and text[position] == "]":
                        return True, result_list, position + 1
                    if position >= text_size or text[position] != ",":
                        return False, None, position
                    position = whitespace(position + 1)
                return False, None, position
            for token, item in (("true", True), ("false", False), ("null", None)):
                if text[position : position + len(token)] == token:
                    return True, item, position + len(token)
            if character == "-" or character in "0123456789":
                return number_value(position)
            return False, None, position

        parsed, value, end = value_at(0, 0)
        return parsed and whitespace(end) == text_size, value

    def sha256_bytes(payload: object) -> object:
        if not isinstance(payload, bytes):
            return None
        constants = (
            0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5,
            0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
            0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
            0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
            0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC,
            0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
            0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7,
            0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
            0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
            0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85,
            0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3,
            0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
            0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5,
            0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3,
            0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
            0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
        )
        words = list(payload)
        bit_length = len(words) * 8
        words.append(0x80)
        while len(words) % 64 != 56:
            words.append(0)
        for shift in range(56, -1, -8):
            words.append((bit_length >> shift) & 0xFF)
        state = [
            0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
            0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
        ]

        def rotate(value: int, amount: int) -> int:
            return ((value >> amount) | (value << (32 - amount))) & 0xFFFFFFFF

        for offset in range(0, len(words), 64):
            schedule: list[int] = []
            for position in range(16):
                start = offset + position * 4
                schedule.append(
                    (words[start] << 24)
                    | (words[start + 1] << 16)
                    | (words[start + 2] << 8)
                    | words[start + 3]
                )
            for position in range(16, 64):
                first = (
                    rotate(schedule[position - 15], 7)
                    ^ rotate(schedule[position - 15], 18)
                    ^ (schedule[position - 15] >> 3)
                )
                second = (
                    rotate(schedule[position - 2], 17)
                    ^ rotate(schedule[position - 2], 19)
                    ^ (schedule[position - 2] >> 10)
                )
                schedule.append(
                    (
                        schedule[position - 16]
                        + first
                        + schedule[position - 7]
                        + second
                    )
                    & 0xFFFFFFFF
                )
            a, b, c, d, e, f, g, h = state
            for position in range(64):
                upper = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)
                choice = (e & f) ^ ((~e) & g)
                first = (
                    h + upper + choice + constants[position] + schedule[position]
                ) & 0xFFFFFFFF
                lower = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)
                majority = (a & b) ^ (a & c) ^ (b & c)
                second = (lower + majority) & 0xFFFFFFFF
                h, g, f, e, d, c, b, a = (
                    g,
                    f,
                    e,
                    (d + first) & 0xFFFFFFFF,
                    c,
                    b,
                    a,
                    (first + second) & 0xFFFFFFFF,
                )
            state = [
                (state[0] + a) & 0xFFFFFFFF,
                (state[1] + b) & 0xFFFFFFFF,
                (state[2] + c) & 0xFFFFFFFF,
                (state[3] + d) & 0xFFFFFFFF,
                (state[4] + e) & 0xFFFFFFFF,
                (state[5] + f) & 0xFFFFFFFF,
                (state[6] + g) & 0xFFFFFFFF,
                (state[7] + h) & 0xFFFFFFFF,
            ]
        digits = "0123456789abcdef"
        return "".join(
            digits[(value >> shift) & 15]
            for value in state
            for shift in range(28, -1, -4)
        )

    def canonical_json(value: object) -> object:
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if not (-1e308 <= value <= 1e308):
                return None
            return str(value)
        if isinstance(value, str):
            escapes = {
                '"': '\\"',
                "\\": "\\\\",
                "\b": "\\b",
                "\f": "\\f",
                "\n": "\\n",
                "\r": "\\r",
                "\t": "\\t",
            }
            rendered = ['"']
            for character in value:
                if character in escapes:
                    rendered.append(escapes[character])
                elif character in "\x00\x01\x02\x03\x04\x05\x06\x07\x0b\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f":
                    return None
                else:
                    rendered.append(character)
            rendered.append('"')
            return "".join(rendered)
        if isinstance(value, list):
            items = [canonical_json(item) for item in value]
            if any(item is None for item in items):
                return None
            return "[" + ",".join(items) + "]"
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                return None
            items: list[str] = []
            for key in sorted(value):
                rendered_key = canonical_json(key)
                rendered_value = canonical_json(value[key])
                if rendered_key is None or rendered_value is None:
                    return None
                items.append(rendered_key + ":" + rendered_value)
            return "{" + ",".join(items) + "}"
        return None

    def canonical_sha(value: object) -> object:
        rendered = canonical_json(value)
        if not isinstance(rendered, str):
            return None
        return sha256_bytes(rendered.encode("ascii"))

    expected_request_fields = {
        "schema_version",
        "artifact_kind",
        "arm_contract",
        "arm_contract_file",
        "evidence_files",
        "evidence_aggregate_sha256",
        "evidence_payloads",
    }
    if not isinstance(request, dict) or set(request) != expected_request_fields:
        return rejected("semantic request fields drifted")
    if (
        request.get("schema_version") != 3
        or request.get("artifact_kind")
        != "vast_backend_publication_production_semantic_evidence_request_v3"
    ):
        return rejected("semantic request identity drifted")
    arm = request.get("arm_contract")
    descriptors = request.get("evidence_files")
    payloads = request.get("evidence_payloads")
    if not isinstance(arm, dict) or not isinstance(descriptors, list) or not isinstance(payloads, dict):
        return rejected("semantic request material is invalid")
    descriptor_by_name: dict[str, object] = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "path",
            "size_bytes",
            "sha256",
        }:
            return rejected("evidence descriptor fields drifted")
        name = descriptor.get("path")
        size = descriptor.get("size_bytes")
        digest = descriptor.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or name in descriptor_by_name
            or not isinstance(size, int)
            or size <= 0
            or not valid_sha(digest)
        ):
            return rejected("evidence descriptor is invalid")
        payload = payloads.get(name)
        if (
            not isinstance(payload, bytes)
            or len(payload) != size
            or sha256_bytes(payload) != digest
        ):
            return rejected("held evidence size drifted")
        descriptor_by_name[name] = descriptor
    if set(payloads) != set(descriptor_by_name) or not {
        "checkpoint_publication_acceptance.json",
        "run_metadata.json",
    } <= set(payloads):
        return rejected("required arm evidence is missing")

    acceptance_ok, acceptance = parse_json(
        payloads["checkpoint_publication_acceptance.json"]
    )
    metadata_ok, metadata = parse_json(payloads["run_metadata.json"])
    if not acceptance_ok or not metadata_ok or not isinstance(acceptance, dict) or not isinstance(metadata, dict):
        return rejected("acceptance or metadata JSON is invalid")
    runtime = arm.get("runtime_inputs")
    execution = arm.get("full_publication_execution_binding")
    if not isinstance(runtime, dict) or not isinstance(execution, dict):
        return rejected("arm runtime or execution binding is missing")
    dataset = runtime.get("dataset")
    dataset_name = dataset.get("name") if isinstance(dataset, dict) else None
    if (
        acceptance.get("schema_version") != 2
        or acceptance.get("artifact_kind")
        != "checkpoint_publication_runtime_acceptance"
        or acceptance.get("status") != "accepted_native_checkpoint_arm"
        or acceptance.get("system") != runtime.get("system")
        or acceptance.get("scenario") != runtime.get("scenario")
        or acceptance.get("codec") != runtime.get("codec")
        or acceptance.get("policy") != runtime.get("policy")
        or acceptance.get("run_id") != runtime.get("run_id")
        or not equal_number(
            acceptance.get("deadline_ms"), runtime.get("deadline_ms")
        )
        or not valid_sha(
            acceptance.get("measurement_schedule_fingerprint_sha256")
        )
    ):
        return rejected("acceptance coordinate or identity drifted")
    summary = acceptance.get("summary")
    required_gates = (
        "ingress_ledger_complete",
        "ingress_cohort_closed",
        "branch_terminal_trace_complete",
        "checkpoint_frame_aggregation_complete",
        "stage_semantic_contract_complete",
        "decoder_placement_verified",
        "resource_attribution_complete",
        "reset_state_verified",
        "full_resource_evidence_accepted",
        "full_resource_coverage_complete",
    )
    if (
        not isinstance(summary, dict)
        or summary.get("resource_contract_version") != 2
        or any(summary.get(gate) is not True for gate in required_gates)
    ):
        return rejected("acceptance gates are incomplete")
    evidence_hashes = acceptance.get("evidence_sha256")
    full_resource_hashes = acceptance.get("full_resource_evidence_sha256")
    if not isinstance(evidence_hashes, dict) or not evidence_hashes:
        return rejected("acceptance evidence hash set is invalid")
    for name, digest in evidence_hashes.items():
        descriptor = descriptor_by_name.get(name)
        if (
            not isinstance(name, str)
            or not isinstance(descriptor, dict)
            or not valid_sha(digest)
            or descriptor.get("sha256") != digest
        ):
            return rejected("acceptance evidence descriptor drifted")
    if (
        not isinstance(full_resource_hashes, dict)
        or not full_resource_hashes
        or any(evidence_hashes.get(name) != digest for name, digest in full_resource_hashes.items())
    ):
        return rejected("full-resource evidence binding drifted")
    resource_summary = acceptance.get("full_resource_summary")
    if (
        not isinstance(resource_summary, dict)
        or resource_summary.get("resource_contract_version") != 2
        or resource_summary.get("evidence_accepted") is not True
        or resource_summary.get("publication_bundle_bound") is not True
        or resource_summary.get("full_resource_coverage_complete") is not True
        or acceptance.get("acceptance_finalization")
        != {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
        }
    ):
        return rejected("full-resource acceptance is not finalized")

    binding = acceptance.get("publication_metadata_binding")
    metadata_descriptor = descriptor_by_name["run_metadata.json"]
    pin_fields = (
        ("identity_artifact_binding_sha256", "identity_artifact_binding_sha256"),
        ("resource_capability_grant_sha256", "resource_capability_grant_sha256"),
        ("backend_runtime_grant_sha256", "backend_runtime_grant_sha256"),
        ("model_parity_grant_sha256", "model_parity_grant_sha256"),
        (
            "model_parity_acceptance_binding_sha256",
            "model_parity_acceptance_binding_sha256",
        ),
    )
    if (
        not isinstance(binding, dict)
        or binding.get("schema_version") != 2
        or binding.get("artifact_kind")
        != "checkpoint_publication_acceptance_metadata_binding"
        or binding.get("run_metadata_file") != "run_metadata.json"
        or binding.get("run_metadata_size_bytes")
        != metadata_descriptor.get("size_bytes")
        or binding.get("run_metadata_sha256") != metadata_descriptor.get("sha256")
        or binding.get("execution_binding") != execution
        or not valid_sha(binding.get("binding_sha256"))
        or any(binding.get(binding_field) != arm.get(arm_field) for binding_field, arm_field in pin_fields)
    ):
        return rejected("acceptance metadata binding drifted")

    result = metadata.get("result")
    if (
        metadata.get("schema_version") != 2
        or metadata.get("mode") != "benchmark"
        or not isinstance(result, dict)
        or result.get("status") != "completed"
        or result.get("system") != runtime.get("system")
        or result.get("scenario") != runtime.get("scenario")
        or result.get("policy") != runtime.get("policy")
        or result.get("dataset") != dataset_name
        or result.get("repeat") != runtime.get("repeat_index")
        or result.get("streams") != runtime.get("streams")
        or result.get("duration_s") != runtime.get("duration_s")
        or result.get("seed") != runtime.get("base_seed")
        or result.get("run_seed") != runtime.get("run_seed")
        or metadata.get("run_seed") != runtime.get("run_seed")
        or not equal_number(result.get("deadline_ms"), runtime.get("deadline_ms"))
        or result.get("distributed") is not False
        or result.get("deployment_mode") != "heterogeneous"
    ):
        return rejected("durable metadata result drifted")
    publication_contract = metadata.get("publication_run_contract")
    if not isinstance(publication_contract, dict) or publication_contract.get(
        "full_publication_execution_binding"
    ) != execution:
        return rejected("metadata publication execution binding drifted")
    resource_grant = publication_contract.get("pre_run_resource_capability_grant")
    backend_grant = publication_contract.get("pre_run_backend_runtime_grant")
    model_grant = publication_contract.get("pre_run_model_parity_grant")
    if (
        not isinstance(resource_grant, dict)
        or resource_grant.get("grant_sha256")
        != arm.get("resource_capability_grant_sha256")
        or not isinstance(backend_grant, dict)
        or backend_grant.get("grant_sha256")
        != arm.get("backend_runtime_grant_sha256")
        or not isinstance(model_grant, dict)
        or model_grant.get("grant_sha256") != arm.get("model_parity_grant_sha256")
        or model_grant.get("parity_acceptance_binding_sha256")
        != arm.get("model_parity_acceptance_binding_sha256")
    ):
        return rejected("metadata qualification authority drifted")
    return {
        "accepted": True,
        "status": "accepted",
        "details": {
            "arm_id": execution.get("arm_id"),
            "run_id": runtime.get("run_id"),
            "evidence_file_count": len(descriptor_by_name),
            "validated_files": sorted(descriptor_by_name),
        },
    }


_PRODUCTION_RUNTIME_INPUT_KEYS = {
    "deepstream": "deepstream_publication_runtime_v3",
    "savant": "savant_publication_runtime_v3",
    "openvino_gva": "openvino_gva_publication_runtime_v3",
    "gstreamer_custom": "gstreamer_custom_publication_runtime_v3",
}
_PRODUCTION_TOPOLOGY_BY_SCENARIO = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}


def _required_sha(value: Any, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ContractError(f"production-v3 {label} SHA-256 is invalid")
    return value


def _canonical_production_v3_deadline(value: Any) -> int | float:
    if isinstance(value, bool):
        raise ContractError("production-v3 deadline is invalid")
    try:
        observed = float(value)
    except (TypeError, ValueError):
        raise ContractError("production-v3 deadline is invalid") from None
    for candidate in backend_dispatch_v3.DEADLINES_MS:
        if observed == float(candidate):
            return candidate
    raise ContractError("production-v3 deadline is outside the frozen coordinate set")


def _production_v3_coordinate_match(
    value: Mapping[str, Any], *, coordinate: Mapping[str, Any]
) -> bool:
    if type(value) is not dict:
        return False
    return (
        value.get("system") == coordinate["system"]
        and value.get("codec") == coordinate["codec"]
        and value.get("topology_kind") == coordinate["topology_kind"]
        and value.get("policy") == coordinate["policy"]
        and not isinstance(value.get("deadline_ms"), bool)
        and isinstance(value.get("deadline_ms"), (int, float))
        and float(value["deadline_ms"]) == float(coordinate["deadline_ms"])
    )


def _select_production_v3_authority(
    *,
    identity_artifacts: Mapping[str, Any],
    backend_runtime_grant: Mapping[str, Any],
    coordinate: Mapping[str, Any],
) -> dict[str, Any]:
    bindings = identity_artifacts.get("bindings")
    backend_binding = (
        bindings.get("backend_runtime_qualification")
        if type(bindings) is dict
        else None
    )
    if (
        type(backend_binding) is not dict
        or backend_binding.get("schema_version") != 3
        or backend_binding.get("artifact_kind")
        != "vast_full_publication_backend_runtime_qualification_binding_v3"
        or backend_binding.get("authorization_eligible") is not True
        or backend_binding.get("semantic_crossbinding_complete") is not True
        or backend_binding.get("authorization_blockers") != []
    ):
        raise ContractError(
            "production-v3 accepted runtime authority binding is missing or non-authorizing"
        )
    system = str(coordinate["system"])
    identity_systems = backend_binding.get("systems")
    grant_systems = backend_runtime_grant.get("systems")
    identity_system = (
        identity_systems.get(system) if type(identity_systems) is dict else None
    )
    grant_system = grant_systems.get(system) if type(grant_systems) is dict else None
    if type(identity_system) is not dict or type(grant_system) is not dict:
        raise ContractError("production-v3 system runtime authority is missing")
    launcher = identity_system.get("launcher")
    if (
        type(launcher) is not dict
        or set(launcher) != {"path", "size_bytes", "sha256"}
        or grant_system.get("launcher") != launcher
    ):
        raise ContractError("production-v3 launcher authority drifted")
    expected_launcher_path = (
        f"scripts/checkpoint_{system}_publication_launcher_v3.py"
    )
    if launcher.get("path") != expected_launcher_path:
        raise ContractError("production-v3 launcher is not the dedicated ABI-v3 entrypoint")
    authorities = identity_system.get("runtime_authorities")
    if type(authorities) is not list:
        raise ContractError("production-v3 runtime authority set is missing")
    selected_authorities = [
        item
        for item in authorities
        if type(item) is dict
        and item.get("system") == coordinate["system"]
        and item.get("codec") == coordinate["codec"]
        and item.get("topology_kind") == coordinate["topology_kind"]
        and item.get("policy") == coordinate["policy"]
    ]
    if len(selected_authorities) != 1:
        raise ContractError("production-v3 runtime authority coordinate is ambiguous")
    authority_record = selected_authorities[0]
    authority = authority_record.get("artifact")
    authority_sha = _required_sha(
        authority_record.get("runtime_authority_sha256"),
        label="runtime authority",
    )
    if type(authority) is not dict or authority.get("authority_sha256") != authority_sha:
        raise ContractError("production-v3 runtime authority artifact drifted")
    launcher_input = authority.get("system_specific_launcher_input")
    launcher_content = (
        launcher_input.get("content") if type(launcher_input) is dict else None
    )
    runtime_input_key = _PRODUCTION_RUNTIME_INPUT_KEYS.get(system)
    if (
        type(launcher_content) is not dict
        or launcher_content.get("system") != system
        or launcher_content.get("launcher_kind")
        != "dedicated_publication_runtime_v3"
        or launcher_content.get("dataset_runtime_input_key") != runtime_input_key
        or type(launcher_content.get("dataset_runtime_input")) is not dict
        or type(launcher_content.get("launcher_evidence_files")) is not list
    ):
        raise ContractError(
            "production-v3 system launcher input is not materialized in runtime authority"
        )
    evidence_names = launcher_content["launcher_evidence_files"]
    if (
        not evidence_names
        or len(evidence_names) != len(set(evidence_names))
        or any(
            type(name) is not str or not name or Path(name).name != name
            for name in evidence_names
        )
        or not {
            "checkpoint_publication_acceptance.json",
            "run_metadata.json",
        }
        <= set(evidence_names)
    ):
        raise ContractError("production-v3 launcher evidence allowlist is incomplete")
    runtime_input = copy.deepcopy(launcher_content["dataset_runtime_input"])
    evidence_mapping = runtime_input.get("evidence_mapping")
    if (
        type(evidence_mapping) is not dict
        or set(evidence_mapping) != set(evidence_names)
        or len(set(evidence_mapping.values())) != len(evidence_mapping)
    ):
        raise ContractError("production-v3 runtime evidence mapping drifted")

    grant_cells = grant_system.get("qualified_cells")
    identity_cells = identity_system.get("qualified_cells")
    if type(grant_cells) is not list or type(identity_cells) is not list:
        raise ContractError("production-v3 qualified cell set is missing")
    selected_grant_cells = [
        item
        for item in grant_cells
        if _production_v3_coordinate_match(item, coordinate=coordinate)
    ]
    selected_identity_cells = [
        item
        for item in identity_cells
        if _production_v3_coordinate_match(item, coordinate=coordinate)
    ]
    if len(selected_grant_cells) != 1 or len(selected_identity_cells) != 1:
        raise ContractError("production-v3 qualified cell coordinate is ambiguous")
    cell = selected_grant_cells[0]
    identity_cell = selected_identity_cells[0]
    for field in (
        "cell_identity_sha256",
        "validation_record_sha256",
        "runtime_authority_sha256",
        "launcher_invocation_sha256",
    ):
        if cell.get(field) != identity_cell.get(field):
            raise ContractError(f"production-v3 qualified cell {field} drifted")
    invocation = publication_launcher_invocation_v3_contract()
    if (
        cell.get("runtime_authority_sha256") != authority_sha
        or cell.get("launcher_invocation_sha256")
        != invocation["invocation_sha256"]
    ):
        raise ContractError("production-v3 qualified cell is not bound to ABI v3")
    return {
        "launcher": copy.deepcopy(launcher),
        "launcher_invocation": invocation,
        "cell_identity_sha256": _required_sha(
            cell.get("cell_identity_sha256"), label="qualified cell"
        ),
        "validation_record_sha256": _required_sha(
            cell.get("validation_record_sha256"), label="validation record"
        ),
        "runtime_authority_sha256": authority_sha,
        "model_parity_acceptance_binding_sha256": _required_sha(
            authority.get("model_parity_acceptance_binding_sha256"),
            label="runtime authority model-parity acceptance",
        ),
        "dataset_runtime_input_key": runtime_input_key,
        "dataset_runtime_input": runtime_input,
        "launcher_evidence_files": list(evidence_names),
    }


def _execute_production_v3_arm(
    *,
    config: Mapping[str, Any],
    project_root: Path,
    arm_root: Path,
    arm: Mapping[str, Any],
    scenario: Mapping[str, Any],
    dataset: Mapping[str, Any],
    execution_binding: Mapping[str, Any],
    resource_capability_grant: Mapping[str, Any] | None,
    backend_runtime_grant: Mapping[str, Any] | None,
    model_parity_grant: Mapping[str, Any] | None,
    identity_artifacts: Mapping[str, Any] | None,
    production_runtime_bind_mount: Mapping[str, Any] | None,
    semantic_evidence_validator: Callable[[dict[str, object]], Mapping[str, Any]],
    semantic_validator_identity_sha256: str,
) -> dict[str, Any]:
    """Build and commit exactly one parent-owned production ABI-v3 arm."""

    del config
    if (
        type(resource_capability_grant) is not dict
        or type(backend_runtime_grant) is not dict
        or type(model_parity_grant) is not dict
        or type(identity_artifacts) is not dict
        or type(production_runtime_bind_mount) is not dict
    ):
        raise ContractError(
            "production-v3 execution requires resource/backend/parity/identity/runtime grants"
        )
    identity_sha = _required_sha(
        identity_artifacts.get("binding_sha256"), label="identity artifact binding"
    )
    for grant, label in (
        (resource_capability_grant, "resource capability grant"),
        (backend_runtime_grant, "backend runtime grant"),
        (model_parity_grant, "model-parity grant"),
    ):
        if grant.get("identity_artifact_binding_sha256") != identity_sha:
            raise ContractError(f"production-v3 {label} identity binding drifted")
    resource_grant_sha = _required_sha(
        resource_capability_grant.get("grant_sha256"),
        label="resource capability grant",
    )
    backend_grant_sha = _required_sha(
        backend_runtime_grant.get("grant_sha256"), label="backend runtime grant"
    )
    model_grant_sha = _required_sha(
        model_parity_grant.get("grant_sha256"), label="model-parity grant"
    )
    parity_binding_sha = _required_sha(
        model_parity_grant.get("parity_acceptance_binding_sha256"),
        label="model-parity acceptance binding",
    )
    topology_kind = _PRODUCTION_TOPOLOGY_BY_SCENARIO.get(str(arm.get("scenario")))
    if topology_kind is None:
        raise ContractError("production-v3 scenario topology is invalid")
    deadline = _canonical_production_v3_deadline(arm.get("deadline_ms"))
    coordinate = {
        "system": str(arm["system"]),
        "codec": str(arm["codec"]),
        "topology_kind": topology_kind,
        "policy": str(arm["policy"]),
        "deadline_ms": deadline,
    }
    selected = _select_production_v3_authority(
        identity_artifacts=identity_artifacts,
        backend_runtime_grant=backend_runtime_grant,
        coordinate=coordinate,
    )
    if selected["model_parity_acceptance_binding_sha256"] != parity_binding_sha:
        raise ContractError("production-v3 runtime authority parity binding drifted")

    runtime_binding_sha = _required_sha(
        production_runtime_bind_mount.get("binding_sha256"),
        label="read-only ext4 runtime bind mount",
    )
    python_descriptor = {
        "path": production_runtime_bind_mount.get("project_python_path"),
        "size_bytes": production_runtime_bind_mount.get(
            "source_python_size_bytes"
        ),
        "sha256": production_runtime_bind_mount.get("source_python_sha256"),
    }
    dataset_value = _json_copy(dataset)
    runtime_key = str(selected["dataset_runtime_input_key"])
    existing_runtime_input = dataset_value.get(runtime_key)
    if existing_runtime_input is not None and existing_runtime_input != selected[
        "dataset_runtime_input"
    ]:
        raise ContractError("production-v3 dataset runtime input drifted")
    dataset_value[runtime_key] = copy.deepcopy(selected["dataset_runtime_input"])

    workload = scenario.get("workload")
    workload = workload if type(workload) is dict else {}
    variant_name = str(workload.get("variant", "")).strip()
    seed_key = str(workload.get("seed_group", arm["scenario"]))
    run_seed = build_run_seed(
        int(arm["seed"]),
        seed_key,
        variant_name,
        int(arm["streams"]),
        int(arm["repeat"]),
    )
    output_dir = Path(arm_root).resolve()
    root = Path(project_root).resolve(strict=True)
    try:
        relative_output = output_dir.relative_to(root)
    except ValueError:
        raise ContractError("production-v3 arm output escaped project_root") from None
    if not relative_output.parts or output_dir.exists():
        raise ContractError("production-v3 arm output must be a fresh project descendant")
    run_id = "-".join(
        part
        for part in (
            output_dir.name,
            str(arm["scenario"]),
            variant_name,
            f"streams{int(arm['streams'])}",
            str(arm["dataset"]),
            str(arm["policy"]),
            deadline_slug(float(arm["deadline_ms"])),
            str(arm["system"]),
            f"rep{int(arm['repeat']):02d}",
        )
        if part
    )
    runtime_inputs = {
        **coordinate,
        "scenario": str(arm["scenario"]),
        "dataset": dataset_value,
        "streams": int(arm["streams"]),
        "duration_s": int(arm["measurement_s"]),
        "repeat_index": int(arm["repeat"]),
        "base_seed": int(arm["seed"]),
        "run_seed": int(run_seed),
        "run_id": run_id,
        "project_root": str(root),
        "output_dir": str(output_dir),
        "arm_contract_path": str(
            output_dir / backend_dispatch_v3.ARM_CONTRACT_FILENAME
        ),
    }
    invocation = selected["launcher_invocation"]
    resolution = backend_dispatch_v3.build_backend_publication_dispatch_resolution_v3(
        coordinate=coordinate,
        python_executable=python_descriptor,
        publication_launcher=selected["launcher"],
        launcher_invocation=invocation,
        backend_runtime_grant_sha256=backend_grant_sha,
        identity_artifact_binding_sha256=identity_sha,
        cell_identity_sha256=selected["cell_identity_sha256"],
        validation_record_sha256=selected["validation_record_sha256"],
        runtime_binding_identity_sha256=runtime_binding_sha,
    )
    evidence_names = selected["launcher_evidence_files"]
    arm_contract = backend_dispatch_v3.build_backend_publication_arm_contract_v3(
        dispatch_resolution=resolution,
        full_publication_execution_binding=execution_binding,
        resource_capability_grant_sha256=resource_grant_sha,
        model_parity_grant_sha256=model_grant_sha,
        model_parity_acceptance_binding_sha256=parity_binding_sha,
        runtime_inputs=runtime_inputs,
        launcher_evidence_files=evidence_names,
    )
    raw_arm = backend_dispatch_v3.canonical_backend_publication_arm_contract_bytes_v3(
        arm_contract
    )
    arm_file_sha = hashlib.sha256(raw_arm).hexdigest()
    try:
        prepared = (
            production_transaction_v3.prepare_backend_publication_production_transaction_v3(
                output_dir=output_dir,
                arm_contract=arm_contract,
            )
        )
        if (
            prepared.get("status") != "prepared_production_arm_not_executed"
            or prepared.get("sha256") != arm_file_sha
            or any(
                prepared.get(field) is not False
                for field in production_transaction_v3.PRODUCTION_ACCEPTANCE_CLAIM_FIELDS
            )
        ):
            raise ContractError("production-v3 prepare authority drifted")
        return production_transaction_v3.run_or_resume_backend_publication_production_transaction_v3(
            project_root=root,
            output_dir=output_dir,
            expected_arm_contract_file_sha256=arm_file_sha,
            execution_scope=production_transaction_v3.PRODUCTION_EXECUTION_SCOPE,
            expected_coordinate=coordinate,
            expected_python_executable=python_descriptor,
            expected_publication_launcher=selected["launcher"],
            expected_launcher_invocation_sha256=invocation["invocation_sha256"],
            expected_backend_runtime_grant_sha256=backend_grant_sha,
            expected_identity_artifact_binding_sha256=identity_sha,
            expected_cell_identity_sha256=selected["cell_identity_sha256"],
            expected_validation_record_sha256=selected[
                "validation_record_sha256"
            ],
            expected_runtime_binding_identity_sha256=runtime_binding_sha,
            expected_dispatch_resolution_sha256=resolution["resolution_sha256"],
            expected_full_publication_execution_binding=execution_binding,
            expected_resource_capability_grant_sha256=resource_grant_sha,
            expected_model_parity_grant_sha256=model_grant_sha,
            expected_model_parity_acceptance_binding_sha256=parity_binding_sha,
            expected_runtime_inputs=runtime_inputs,
            expected_launcher_evidence_files=evidence_names,
            expected_semantic_validator_identity_sha256=(
                semantic_validator_identity_sha256
            ),
            semantic_evidence_validator=semantic_evidence_validator,
            expected_production_runtime_bind_mount=production_runtime_bind_mount,
        )
    except ContractError:
        raise
    except Exception as error:
        raise ContractError(f"production-v3 transaction rejected arm: {error}") from error


class RealArmRunner:
    """Execute a frozen arm through production ABI v3 by default.

    ``run_one_fn`` is an explicit compatibility seam for isolated unit tests.
    The application factory never supplies it, so a real publication arm cannot
    silently fall back to the legacy in-process ``run_one`` path.
    """

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
        production_runtime_bind_mount: Mapping[str, Any] | None = None,
        production_v3_executor_fn: ProductionV3Executor | None = None,
        dataset_loader: DatasetLoader | None = None,
        run_one_fn: RunOne | None = None,
    ) -> None:
        self.config = _json_copy(config)
        self.project_root = Path(project_root).resolve()
        self.dataset_manifest_path = Path(dataset_manifest_path).resolve()
        self.run_one_fn = run_one_fn
        self.production_v3_executor_fn = (
            _execute_production_v3_arm
            if production_v3_executor_fn is None
            else production_v3_executor_fn
        )
        self.production_runtime_bind_mount = (
            _json_copy(production_runtime_bind_mount)
            if production_runtime_bind_mount is not None
            else None
        )
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
            if self.run_one_fn is not None:
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

    @staticmethod
    def _validate_production_v3_authority(
        value: Any,
        *,
        execution_binding: Mapping[str, Any],
        semantic_validator_identity_sha256: str,
    ) -> dict[str, Any]:
        if type(value) is not dict:
            raise ContractError("production-v3 transaction returned no receipt authority")
        if (
            value.get("schema_version") != 3
            or value.get("artifact_kind")
            != production_transaction_v3.RECEIPT_AUTHORITY_KIND
            or value.get("status") != "accepted_publishable_backend_output"
            or value.get("execution_scope")
            != production_transaction_v3.PRODUCTION_EXECUTION_SCOPE
            or value.get("full_publication_execution_binding")
            != dict(execution_binding)
            or value.get("run_identity_sha256")
            != execution_binding.get("run_identity_sha256")
            or _SHA256_RE.fullmatch(
                str(value.get("dispatch_resolution_sha256", ""))
            )
            is None
        ):
            raise ContractError("production-v3 receipt authority identity drift")
        assessment = value.get("semantic_evidence_assessment")
        if (
            type(assessment) is not dict
            or assessment.get("status") != "accepted"
            or assessment.get("accepted_measurement_evidence") is not True
            or assessment.get("semantic_evidence_validated") is not True
            or assessment.get("validator_identity_sha256")
            != semantic_validator_identity_sha256
        ):
            raise ContractError(
                "production-v3 semantic evidence was not accepted by the pinned validator"
            )
        for field in production_transaction_v3.PRODUCTION_ACCEPTANCE_CLAIM_FIELDS:
            if value.get(field) is not True:
                raise ContractError(
                    f"production-v3 receipt authority did not commit claim: {field}"
                )
        evidence = value.get("evidence_files")
        if type(evidence) is not list:
            raise ContractError("production-v3 receipt lacks held evidence descriptors")
        names: set[str] = set()
        for descriptor in evidence:
            if (
                type(descriptor) is not dict
                or set(descriptor) != {"path", "size_bytes", "sha256"}
                or type(descriptor.get("path")) is not str
                or type(descriptor.get("size_bytes")) is not int
                or descriptor["size_bytes"] <= 0
                or _SHA256_RE.fullmatch(str(descriptor.get("sha256", ""))) is None
            ):
                raise ContractError("production-v3 evidence descriptor drift")
            names.add(str(descriptor["path"]))
        if not {
            "checkpoint_publication_acceptance.json",
            "run_metadata.json",
        } <= names:
            raise ContractError(
                "production-v3 semantic evidence lacks acceptance or durable metadata"
            )
        return _json_copy(value)

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
        if self.run_one_fn is None:
            try:
                validator_identity = (
                    production_transaction_v3.semantic_evidence_validator_identity_v3(
                        publication_arm_semantic_evidence_validator_v3
                    )
                )
                authority = self.production_v3_executor_fn(
                    config=copy.deepcopy(self.config),
                    project_root=self.project_root,
                    arm_root=Path(arm_root),
                    arm=copy.deepcopy(arm),
                    scenario=copy.deepcopy(scenario),
                    dataset=copy.deepcopy(dataset),
                    execution_binding=copy.deepcopy(execution_binding),
                    resource_capability_grant=copy.deepcopy(
                        self.resource_capability_grant
                    ),
                    backend_runtime_grant=copy.deepcopy(
                        self.backend_runtime_grant
                    ),
                    model_parity_grant=copy.deepcopy(self.model_parity_grant),
                    identity_artifacts=copy.deepcopy(self.identity_artifacts),
                    production_runtime_bind_mount=copy.deepcopy(
                        self.production_runtime_bind_mount
                    ),
                    semantic_evidence_validator=(
                        publication_arm_semantic_evidence_validator_v3
                    ),
                    semantic_validator_identity_sha256=validator_identity,
                )
            except ContractError:
                raise
            except Exception as error:
                raise ContractError(
                    f"production-v3 arm transaction failed closed: {error}"
                ) from error
            self._validate_production_v3_authority(
                authority,
                execution_binding=execution_binding,
                semantic_validator_identity_sha256=validator_identity,
            )
            self._verify_dataset_unchanged(str(arm["dataset"]))
            self._verify_execution_inputs_unchanged()
            return {"status": "completed", "arm_id": str(arm["arm_id"])}

        assert self.run_one_fn is not None
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


def _capacity_attestation_path_from_args(args: argparse.Namespace) -> Path:
    legacy_env = os.environ.get("VAST_SEAFILE_CAPACITY_CONFIRMED_GIB", "").strip()
    if args.capacity_confirmed_gib is not None or legacy_env:
        raise ContractError(
            "a numeric Seafile capacity claim is not an authority; a physical "
            "quota/sizing attestation is required"
        )
    raw = args.capacity_attestation
    if raw is None:
        raw = os.environ.get("VAST_SEAFILE_CAPACITY_ATTESTATION", "").strip()
    if not raw:
        raise ContractError(
            "VAST_SEAFILE_CAPACITY_ATTESTATION or --capacity-attestation is required"
        )
    return Path(raw)


def _load_seafile_capacity_attestation(
    *,
    project_root: Path,
    path: Path,
    links: SeafileShareLinks,
    destination_id: str,
) -> dict[str, Any]:
    resolved = _project_path(
        path, project_root=project_root, label="Seafile capacity attestation"
    )
    try:
        info = resolved.lstat()
    except OSError as error:
        raise ContractError(f"Seafile capacity attestation is unavailable: {error}") from error
    if resolved.is_symlink() or not resolved.is_file() or int(info.st_nlink) != 1:
        raise ContractError(
            "Seafile capacity attestation must be a unique physical regular file"
        )
    descriptor = _stable_file_record(resolved, project_root=project_root)
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid Seafile capacity attestation: {error}") from error
    try:
        accepted = validate_seafile_capacity_attestation_v1(
            raw,
            upload_url=(
                f"{links.base_url}/u/d/{links.upload_token}"
            ),
            read_url=f"{links.base_url}/d/{links.read_token}",
            repo_id=destination_id,
        )
    except SeafileCapacityAttestationV1Error as error:
        raise ContractError(f"Seafile capacity attestation is blocked: {error}") from error
    available = int(accepted["account_quota"]["available_bytes"])
    return {
        "attestation": accepted,
        "descriptor": descriptor,
        "capacity_confirmed_gib": available / float(1024**3),
    }


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


def _production_runtime_bind_mount(
    *, project_root: Path
) -> dict[str, Any]:
    if os.name == "nt" or not sys.platform.startswith("linux"):
        raise ContractError(
            "full publication production runtime requires WSL/Linux"
        )
    raw_source = os.environ.get("VAST_PUBLICATION_RUNTIME_SOURCE")
    source = (
        Path(raw_source)
        if raw_source
        else Path.home() / PRODUCTION_RUNTIME_SOURCE_RELATIVE
    )
    try:
        contract = (
            production_transaction_v3.build_production_runtime_bind_mount_contract_v3(
                source_runtime_root=source,
                project_runtime_mount=PRODUCTION_RUNTIME_PROJECT_MOUNT,
            )
        )
        python_descriptor = {
            "path": contract["project_python_path"],
            "size_bytes": contract["source_python_size_bytes"],
            "sha256": contract["source_python_sha256"],
        }
        verified = production_transaction_v3.preflight_production_runtime_bind_mount_v3(
            project_root=project_root,
            expected_python_executable=python_descriptor,
            expected_binding=contract,
        )
    except Exception as error:
        raise ContractError(
            f"production WSL ext4 read-only runtime preflight failed: {error}"
        ) from error
    if verified != contract:
        raise ContractError("production WSL runtime bind mount identity drifted")
    return _json_copy(contract)


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
    destination_id = _destination_id_from_args(args)
    capacity_binding = _load_seafile_capacity_attestation(
        project_root=project_root,
        path=_capacity_attestation_path_from_args(args),
        links=links,
        destination_id=destination_id,
    )
    from benchmark_contract import load_dataset

    material = build_identity_material(
        project_root=project_root,
        config_path=config_path,
        dataset_manifest_path=dataset_manifest_path,
        model_manifest_path=model_manifest_path,
        config=config,
        cloud_links=links,
        cloud_destination_id=destination_id,
        dataset_loader=load_dataset,
        identity_artifact_manifest_path=identity_artifact_manifest_path,
        identity_artifacts=identity_artifacts,
    )
    production_runtime_bind_mount = _production_runtime_bind_mount(
        project_root=project_root
    )
    material.identity_inputs["production_runtime_bind_mount"] = copy.deepcopy(
        production_runtime_bind_mount
    )
    capacity_attestation = capacity_binding["attestation"]
    capacity_descriptor = capacity_binding["descriptor"]
    material.identity_inputs["seafile_capacity_attestation"] = {
        "descriptor": copy.deepcopy(capacity_descriptor),
        "attestation_sha256": capacity_attestation["sha256"],
        "destination_identity_sha256": capacity_attestation["destination"][
            "destination_identity_sha256"
        ],
        "required_capacity_bytes": capacity_attestation["sizing_projection"][
            "required_capacity_bytes"
        ],
        "available_bytes": capacity_attestation["account_quota"]["available_bytes"],
    }
    capacity_path = project_root / str(capacity_descriptor["path"])
    capacity_stat = capacity_path.stat()
    execution_guards = material.execution_guards + (
        ImmutableFileGuard(
            path=capacity_path,
            size_bytes=int(capacity_descriptor["size_bytes"]),
            mtime_ns=int(capacity_stat.st_mtime_ns),
            sha256=str(capacity_descriptor["sha256"]),
            always_rehash=True,
        ),
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
        execution_guards=execution_guards,
        resource_capability_grant=resource_capability_grant,
        backend_runtime_grant=backend_runtime_grant,
        model_parity_grant=model_parity_grant,
        identity_artifacts=identity_artifacts,
        frozen_image_ids={
            str(record["system"]): str(record["image_id"])
            for record in material.identity_inputs["container_images"]
        },
        production_runtime_bind_mount=production_runtime_bind_mount,
    )
    runtime = FullPublicationRuntime(
        run_root=run_root,
        config=config,
        cloud_store=store,
        arm_runner=arm_runner,
        readiness_validator=readiness,
        minimum_free_bytes=int(float(args.minimum_free_gib) * 1024**3),
        capacity_confirmed_gib=float(capacity_binding["capacity_confirmed_gib"]),
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
    parser.add_argument(
        "--capacity-confirmed-gib",
        type=float,
        help="deprecated and rejected: use --capacity-attestation",
    )
    parser.add_argument("--capacity-attestation", type=Path)
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
    "publication_arm_semantic_evidence_validator_v3",
    "production_readiness_validator",
]
