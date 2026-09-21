#!/usr/bin/env python3
"""Run the patch-bound schema-4 physical model-parity refresh.

The authority order is fixed and fail-closed:

1. verify the non-authorizing image identity patch;
2. inspect the exact two new image IDs and run two live capability probes;
3. create a versioned execution config from those probes;
4. materialize the exact eight endpoint bindings;
5. reuse the production NativeEndpointRunner/evidence collector for all 480
   native executions;
6. promote and accept schema 4 with the binding written last.

No Docker operation is performed at import time or by the pure builders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

import yaml

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_immutable_directory_v1 import (
    JOURNAL_ROOT,
    commit_or_adopt_immutable_directory_v1,
)
from publication_owned_staging_cleanup_v1 import (
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
    OwnedStagingFileV1,
)

import checkpoint_model_parity_materializer as materializer_v3
import checkpoint_model_parity_v4 as parity_v4
from analytics_execution_bindings import materialize_worker_bindings
from analytics_execution_capability import build_runtime_probe_command
from analytics_execution_protocol import canonical_sha256
from analytics_execution_worker import validate_runtime_probe
from checkpoint_gstreamer_analytics_sidecar import (
    load_execution_config,
    load_materialized_binding_set,
)
import publication_qualification_image_refreeze_v1 as image_refreeze


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CommandRunner = Callable[[list[str]], str]


class ModelParityMaterializerV4Error(RuntimeError):
    """The patch-bound physical refresh could not be completed exactly."""


@dataclass(frozen=True)
class RefreshFoundationV4:
    project_root: Path
    image_patch: Mapping[str, Any]
    image_patch_descriptor: Mapping[str, Any]
    patch_projection: Mapping[str, Any]
    runtime_probes: Mapping[str, Mapping[str, Any]]
    execution_config: Mapping[str, Any]
    execution_config_authority: Mapping[str, Any]
    base_manifest: Mapping[str, Any]
    base_manifest_descriptor: Mapping[str, Any]
    binding_set_authority: Mapping[str, Any]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelParityMaterializerV4Error(message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ModelParityMaterializerV4Error("model-parity v4 material is not canonical JSON") from error


def _root(project_root: Path | str) -> Path:
    try:
        return parity_v4._physical_root(project_root)
    except Exception as error:
        raise ModelParityMaterializerV4Error(str(error)) from error


def _relative_to_root(root: Path, value: Path | str, label: str) -> str:
    path = Path(os.path.abspath(os.fspath(value if Path(value).is_absolute() else root / Path(value))))
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise ModelParityMaterializerV4Error(f"{label} escaped project_root") from error
    parity_v4._relative(relative, label)
    return relative


def _safe_new_path(root: Path, value: Path | str, label: str) -> Path:
    relative = _relative_to_root(root, value, label)
    path = root.joinpath(*PurePosixPath(relative).parts)
    _require(path.parent.is_dir() and path.parent.resolve() == path.parent, f"{label} parent is missing or unsafe")
    _require(not materializer_v3._is_reparse(path.parent), f"{label} parent is a reparse point")
    return path


def _write_new_bytes(
    root: Path,
    value: Path | str,
    payload: bytes,
    label: str,
    *,
    _fault_hook: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    path = _safe_new_path(root, value, label)
    custody: PhysicalRootCustodyV1 | None = None
    try:
        custody = PhysicalRootCustodyV1.open(root, label=f"{label} project root")
        descriptor, _identity, _disposition = custody.commit_or_adopt_exact_identity(
            path.relative_to(root).as_posix(),
            payload,
            label=label,
            mode=0o444,
            create_parents=False,
            after_publish_step=_fault_hook,
        )
        custody.verify()
        return descriptor
    except PublicationPhysicalIoV1Error as error:
        raise ModelParityMaterializerV4Error(
            f"{label} atomic commit/adoption failed"
        ) from error
    finally:
        if custody is not None:
            custody.close()


def _write_new_json(root: Path, value: Path | str, document: Mapping[str, Any], label: str) -> dict[str, Any]:
    return _write_new_bytes(root, value, _canonical(document) + b"\n", label)


def _default_runner(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ModelParityMaterializerV4Error(f"command failed: {command[0]}") from error
    _require(completed.returncode == 0, f"command failed: {' '.join(command[:4])}")
    _require(len(completed.stdout.encode("utf-8")) <= 8 * 1024 * 1024, "command output exceeded capture bound")
    return completed.stdout


def _inspect_image(command_runner: CommandRunner, image: str) -> dict[str, Any]:
    try:
        raw = command_runner(["docker", "image", "inspect", image])
        value = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ModelParityMaterializerV4Error(f"cannot inspect worker image: {image}") from error
    if type(value) is list:
        _require(len(value) == 1 and type(value[0]) is dict, f"worker image inspect cardinality drifted: {image}")
        value = value[0]
    _require(
        type(value) is dict
        and value.get("Architecture") == "amd64"
        and value.get("Os") == "linux"
        and type(value.get("Id")) is str,
        f"worker image inspect platform/identity drifted: {image}",
    )
    return dict(value)


def validate_resolved_worker_projection_v4(
    *,
    patch_projection: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    workers = execution_config.get("workers")
    _require(type(workers) is dict and set(workers) == {"cpu", "gpu"}, "versioned execution worker coverage drifted")
    _require(type(runtime_probes) is dict and set(runtime_probes) == {"cpu", "gpu"}, "live runtime probe coverage drifted")
    patch_workers = patch_projection.get("workers")
    _require(type(patch_workers) is dict and set(patch_workers) == {"cpu", "gpu"}, "image patch worker coverage drifted")
    result: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        patch_worker = patch_workers[resource]
        config_worker = workers[resource]
        probe = runtime_probes[resource]
        _require(
            config_worker.get("image") == patch_worker.get("image")
            and config_worker.get("image_id") == patch_worker.get("image_id")
            and config_worker.get("base_image") == patch_worker.get("base_image")
            and config_worker.get("base_image_id") == patch_worker.get("base_image_id"),
            f"{resource} resolved worker image identity drifted",
        )
        implementation = probe.get("worker_implementation_sha256")
        _require(
            type(implementation) is str
            and len(implementation) == 64
            and config_worker.get("worker_implementation_sha256") == implementation,
            f"{resource} resolved worker implementation identity drifted",
        )
        result[resource] = {
            "image": patch_worker["image"],
            "image_id": patch_worker["image_id"],
            "worker_implementation_sha256": implementation,
            "source_set_sha256": patch_worker["source_set_sha256"],
            "receipt_sha256": patch_worker["receipt_sha256"],
        }
    return result


def capture_live_runtime_probes_v4(
    *,
    project_root: Path | str,
    patch_projection: Mapping[str, Any],
    source_execution_config: Mapping[str, Any],
    output_dir: Path | str,
    command_runner: CommandRunner = _default_runner,
    after_directory_publish_step: Callable[[str], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Inspect and probe both new workers before committing either probe file."""

    root = _root(project_root)
    target_relative = _relative_to_root(root, output_dir, "live runtime probe directory")
    target = root.joinpath(*PurePosixPath(target_relative).parts)
    _require(target.parent.is_dir(), "live runtime probe directory parent is missing")
    patch_workers = patch_projection.get("workers")
    source_workers = source_execution_config.get("workers")
    _require(type(patch_workers) is dict and set(patch_workers) == {"cpu", "gpu"}, "image patch worker coverage drifted")
    _require(type(source_workers) is dict and set(source_workers) == {"cpu", "gpu"}, "source execution worker coverage drifted")

    documents: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        patch_worker = patch_workers[resource]
        source_worker = source_workers[resource]
        before = _inspect_image(command_runner, str(patch_worker["image"]))
        _require(before.get("Id") == patch_worker["image_id"], f"{resource} worker image identity differs from the patch")
        worker = {
            **dict(source_worker),
            "image": patch_worker["image"],
            "image_id": patch_worker["image_id"],
            "base_image": patch_worker["base_image"],
            "base_image_id": patch_worker["base_image_id"],
        }
        try:
            raw = command_runner(build_runtime_probe_command(worker))
            probe = json.loads(raw)
            checked = validate_runtime_probe(probe, engine=str(worker["engine"]))
        except Exception as error:
            raise ModelParityMaterializerV4Error(f"{resource} live capability probe failed: {error}") from error
        after = _inspect_image(command_runner, str(patch_worker["image"]))
        _require(after.get("Id") == before.get("Id") == patch_worker["image_id"], f"{resource} worker image identity drifted around the live probe")
        documents[resource] = checked

    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.staging.", dir=target.parent)
    )
    cleanup_anchor: OwnedStagingDirectoryV1 | None = None
    committed = False
    try:
        try:
            cleanup_anchor = OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=target.parent,
                expected_prefix=f".{target.name}.staging.",
                label="model-parity v4 live-probe staging",
            )
        except OwnedStagingCleanupV1Error as error:
            raise ModelParityMaterializerV4Error(str(error)) from error
        for resource in ("cpu", "gpu"):
            path = staging / f"{resource}_runtime_probe.json"
            payload = _canonical(documents[resource]) + b"\n"
            path.write_bytes(payload)
            with path.open("rb") as source:
                os.fsync(source.fileno())
            path.chmod(0o444)
        for path in staging.iterdir():
            path.chmod(0o444)
        staging.chmod(0o755)
        try:
            cleanup_anchor.seal_tree()
        except OwnedStagingCleanupV1Error as error:
            raise ModelParityMaterializerV4Error(str(error)) from error
        publication = commit_or_adopt_immutable_directory_v1(
            project_root=root,
            staging=staging,
            target=target,
            after_publish_step=after_directory_publish_step,
        )
        try:
            cleanup_anchor.cleanup_after_publication(final_target=target)
        except OwnedStagingCleanupV1Error as error:
            raise ModelParityMaterializerV4Error(str(error)) from error
        committed = True
    finally:
        try:
            intent_key = hashlib.sha256(target_relative.encode("utf-8")).hexdigest()
            intent_exists = os.path.lexists(root / JOURNAL_ROOT / f"{intent_key}.json")
            if not committed and not intent_exists and cleanup_anchor is not None:
                try:
                    if not cleanup_anchor.sealed:
                        cleanup_anchor.seal_tree()
                    cleanup_anchor.cleanup_after_publication(final_target=target)
                except OwnedStagingCleanupV1Error as error:
                    raise ModelParityMaterializerV4Error(str(error)) from error
        finally:
            if cleanup_anchor is not None:
                cleanup_anchor.close()

    result: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        descriptor = parity_v4.file_descriptor(root, target / f"{resource}_runtime_probe.json", f"{resource} live runtime probe")
        result[resource] = {
            **descriptor,
            "worker_implementation_sha256": documents[resource]["worker_implementation_sha256"],
        }
    return result


def _load_probe_documents(root: Path, authorities: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    _require(type(authorities) is dict and set(authorities) == {"cpu", "gpu"}, "live runtime probe authority coverage drifted")
    result: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        value = authorities[resource]
        path = parity_v4.verify_descriptor(
            root,
            {key: value[key] for key in ("path", "size_bytes", "sha256")},
            f"{resource} live runtime probe",
        )
        raw = path.read_bytes()
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ModelParityMaterializerV4Error(f"invalid {resource} live runtime probe") from error
        _require(_canonical(document) + b"\n" == raw, f"{resource} live runtime probe is not canonical JSON")
        result[resource] = document
    return result


def build_versioned_execution_config_v4(
    *,
    project_root: Path | str,
    source_execution_config: Mapping[str, Any],
    patch_projection: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
    model_parity_manifest_path: Path | str,
    output_path: Path | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _root(project_root)
    probes = _load_probe_documents(root, runtime_probes)
    patch_workers = patch_projection.get("workers")
    source_workers = source_execution_config.get("workers")
    _require(type(patch_workers) is dict and set(patch_workers) == {"cpu", "gpu"}, "image patch worker coverage drifted")
    _require(type(source_workers) is dict and set(source_workers) == {"cpu", "gpu"}, "source execution worker coverage drifted")
    manifest_relative = _relative_to_root(root, model_parity_manifest_path, "model-parity v4 base manifest")
    raw = {
        key: json.loads(_canonical(item).decode("ascii"))
        for key, item in source_execution_config.items()
        if key != "identity"
    }
    raw["config_id"] = f"kpp-analytics-execution-layer-{patch_projection['patch_sha256'][:16]}-v4"
    raw["model_parity_manifest"] = manifest_relative
    raw["workers"] = {}
    for resource in ("cpu", "gpu"):
        source_worker = source_workers[resource]
        patch_worker = patch_workers[resource]
        checked = validate_runtime_probe(probes[resource], engine=str(source_worker["engine"]))
        _require(
            checked["worker_implementation_sha256"] == runtime_probes[resource]["worker_implementation_sha256"],
            f"{resource} live probe authority implementation drifted",
        )
        raw["workers"][resource] = {
            **dict(source_worker),
            "image": patch_worker["image"],
            "image_id": patch_worker["image_id"],
            "base_image": patch_worker["base_image"],
            "base_image_id": patch_worker["base_image_id"],
            "worker_implementation_sha256": checked["worker_implementation_sha256"],
        }
    descriptor = _write_new_json(root, output_path, raw, "versioned execution config")
    config = load_execution_config(root.joinpath(*PurePosixPath(descriptor["path"]).parts))
    validate_resolved_worker_projection_v4(
        patch_projection=patch_projection,
        execution_config=config,
        runtime_probes=runtime_probes,
    )
    authority = {
        **descriptor,
        "content_identity_sha256": config["identity"]["sha256"],
        "worker_projection_sha256": canonical_sha256(config["workers"]),
    }
    return config, authority


def write_base_manifest_v4(
    *,
    project_root: Path | str,
    source_manifest_path: Path | str,
    image_patch: Mapping[str, Any],
    image_patch_descriptor: Mapping[str, Any],
    execution_config_authority: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
    output_path: Path | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _root(project_root)
    try:
        source_manifest = __import__("checkpoint_model_parity").load_parity_manifest(source_manifest_path)
    except Exception as error:
        raise ModelParityMaterializerV4Error(f"source schema-3 parity manifest rejected: {error}") from error
    source_descriptor = parity_v4.file_descriptor(root, source_manifest_path, "source schema-3 parity manifest")
    manifest = parity_v4.build_patch_bound_manifest_v4(
        source_manifest=source_manifest,
        source_manifest_descriptor=source_descriptor,
        image_patch=image_patch,
        image_patch_descriptor=image_patch_descriptor,
        execution_config=execution_config_authority,
        runtime_probes=runtime_probes,
    )
    unsigned = {key: item for key, item in manifest.items() if key != "identity"}
    try:
        payload = yaml.safe_dump(
            unsigned,
            sort_keys=False,
            allow_unicode=False,
            default_flow_style=False,
        ).encode("ascii")
    except (UnicodeError, yaml.YAMLError) as error:
        raise ModelParityMaterializerV4Error("cannot serialize base model-parity v4 manifest") from error
    descriptor = _write_new_bytes(root, output_path, payload, "base model-parity v4 manifest")
    loaded = parity_v4.load_parity_manifest_v4(
        root.joinpath(*PurePosixPath(descriptor["path"]).parts),
        project_root=root,
    )
    _require(loaded == manifest, "base model-parity v4 manifest roundtrip drifted")
    return loaded, descriptor


def materialize_binding_set_v4(
    *,
    project_root: Path | str,
    output_dir: Path | str,
    manifest: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    root = _root(project_root)
    output_relative = _relative_to_root(root, output_dir, "model-parity v4 binding set")
    target = root.joinpath(*PurePosixPath(output_relative).parts)
    probes = _load_probe_documents(root, runtime_probes)
    try:
        index = materialize_worker_bindings(
            target,
            manifest=manifest,
            execution_config=execution_config,
            project_root=root,
        )
        loaded = load_materialized_binding_set(
            target,
            execution_config=execution_config,
            runtime_probes=probes,
        )
    except Exception as error:
        raise ModelParityMaterializerV4Error(f"model-parity v4 binding set rejected: {error}") from error
    _require(loaded.index == index and len(loaded.bindings) == 8, "model-parity v4 binding coverage drifted")
    binding_descriptors: dict[str, dict[str, Any]] = {}
    for (branch, resource), path in sorted(loaded.binding_paths.items()):
        binding_descriptors[f"{branch}:{resource}"] = parity_v4.file_descriptor(
            root, path, f"{branch}/{resource} endpoint binding"
        )
    _require(len(binding_descriptors) == 8, "model-parity v4 binding descriptor coverage is not exact 8")
    return {
        "index": parity_v4.file_descriptor(root, target / "index.json", "model-parity v4 binding index"),
        "identity_sha256": index["identity"]["sha256"],
        "bindings_identity_sha256": index["bindings_identity_sha256"],
        "bindings": binding_descriptors,
    }


def prepare_refresh_foundation_v4(
    *,
    project_root: Path | str,
    image_patch_path: Path | str,
    source_execution_config_path: Path | str,
    source_manifest_path: Path | str,
    runtime_probe_dir: Path | str,
    versioned_execution_config_path: Path | str,
    base_manifest_v4_path: Path | str,
    binding_set_dir: Path | str,
    command_runner: CommandRunner = _default_runner,
) -> RefreshFoundationV4:
    root = _root(project_root)
    patch_descriptor = parity_v4.file_descriptor(root, image_patch_path, "qualification image patch")
    try:
        patch = image_refreeze.load_identity_patch(
            project_root=root,
            patch_path=root.joinpath(*PurePosixPath(patch_descriptor["path"]).parts),
            require_candidate_eligible=False,
        )
        projection = parity_v4.validate_refresh_patch_v4(patch)
        source_config = load_execution_config(source_execution_config_path)
    except Exception as error:
        raise ModelParityMaterializerV4Error(f"model-parity v4 refresh input rejected: {error}") from error
    probes = capture_live_runtime_probes_v4(
        project_root=root,
        patch_projection=projection,
        source_execution_config=source_config,
        output_dir=runtime_probe_dir,
        command_runner=command_runner,
    )
    config, config_authority = build_versioned_execution_config_v4(
        project_root=root,
        source_execution_config=source_config,
        patch_projection=projection,
        runtime_probes=probes,
        model_parity_manifest_path=base_manifest_v4_path,
        output_path=versioned_execution_config_path,
    )
    manifest, manifest_descriptor = write_base_manifest_v4(
        project_root=root,
        source_manifest_path=source_manifest_path,
        image_patch=patch,
        image_patch_descriptor=patch_descriptor,
        execution_config_authority=config_authority,
        runtime_probes=probes,
        output_path=base_manifest_v4_path,
    )
    binding_authority = materialize_binding_set_v4(
        project_root=root,
        output_dir=binding_set_dir,
        manifest=manifest,
        execution_config=config,
        runtime_probes=probes,
    )
    validate_resolved_worker_projection_v4(
        patch_projection=projection,
        execution_config=config,
        runtime_probes=probes,
    )
    return RefreshFoundationV4(
        project_root=root,
        image_patch=patch,
        image_patch_descriptor=patch_descriptor,
        patch_projection=projection,
        runtime_probes=probes,
        execution_config=config,
        execution_config_authority=config_authority,
        base_manifest=manifest,
        base_manifest_descriptor=manifest_descriptor,
        binding_set_authority=binding_authority,
    )


def _preflight_v4(
    *,
    project_root: Path | str,
    dataset_manifest_path: Path | str,
    base_manifest_path: Path | str,
    materialization_dir: Path | str,
    accepted_manifest_path: Path | str,
) -> materializer_v3._Preflight:
    root = materializer_v3._physical_root(project_root)
    dataset_relative = materializer_v3._project_relative(root, dataset_manifest_path, label="frozen dataset config")
    base_relative = materializer_v3._project_relative(root, base_manifest_path, label="base model-parity v4 manifest")
    dataset_record, dataset_payload = materializer_v3._read_physical_file(root, dataset_relative, expected_sha256=None, expected_size=None, label="frozen dataset config")
    materializer_v3._validate_frozen_dataset_config(materializer_v3._load_yaml_payload(dataset_payload, label="frozen dataset config"))
    base_record, _payload = materializer_v3._read_physical_file(root, base_relative, expected_sha256=None, expected_size=None, label="base model-parity v4 manifest")
    try:
        loaded = parity_v4.load_parity_manifest_v4(base_record.path, project_root=root)
    except Exception as error:
        raise ModelParityMaterializerV4Error(f"base model-parity v4 manifest rejected: {error}") from error
    base_manifest = {key: item for key, item in loaded.items() if key != "identity"}
    _require(parity_v4._evidence_state(base_manifest) == "unmaterialized", "base model-parity v4 manifest is not unmaterialized")
    kpp: dict[str, materializer_v3.PhysicalFileRecord] = {}
    for frozen in materializer_v3.FROZEN_KPP_FILES:
        record, _ = materializer_v3._read_physical_file(root, frozen.relative_path, expected_sha256=frozen.sha256, expected_size=None, label=f"frozen KPP {frozen.relative_path}")
        _require(record.size_bytes > 0, f"frozen KPP file is empty: {frozen.relative_path}")
        kpp[frozen.relative_path] = record
    materializer_v3._safe_output_path(root, materialization_dir, label="materialization directory", must_not_exist=True)
    accepted = materializer_v3._safe_output_path(root, accepted_manifest_path, label="accepted manifest", must_not_exist=False)
    _require(accepted != base_record.path, "accepted manifest must differ from base model-parity v4 manifest")
    return materializer_v3._Preflight(root, dataset_record, base_record, base_manifest, kpp)


def _yaml_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        payload = yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=False, default_flow_style=False).encode("ascii")
    except (UnicodeError, yaml.YAMLError) as error:
        raise ModelParityMaterializerV4Error("accepted model-parity v4 manifest cannot be serialized") from error
    _require(b".staging" not in payload, "accepted model-parity v4 manifest contains a staging reference")
    return payload


def promote_model_parity_evidence_v4(
    collection: materializer_v3.ProductionCollection,
    *,
    accepted_manifest_path: Path | str,
    after_manifest_publish_step: Callable[[str], None] | None = None,
) -> materializer_v3.PromotionResult:
    if type(collection) is not materializer_v3.ProductionCollection or collection._token is not materializer_v3._PRODUCTION_TOKEN:
        raise TypeError("schema-4 promotion requires an internal production collection")
    root = collection.project_root
    accepted = materializer_v3._safe_output_path(root, accepted_manifest_path, label="accepted model-parity v4 manifest", must_not_exist=False)
    _require(accepted.suffix.lower() in {".yaml", ".yml"}, "accepted model-parity v4 manifest must be YAML")
    _require(accepted != collection.base_manifest_record.path, "accepted model-parity v4 manifest must differ from its base")
    payload = _yaml_bytes(collection.promoted_manifest)
    materializer_v3._verify_collection_final_paths(collection)
    candidate = accepted.parent / f".{accepted.name}.candidate.{os.getpid()}"
    _require(not candidate.exists() and not os.path.lexists(candidate), "accepted model-parity v4 candidate collision")
    record: materializer_v3.PhysicalFileRecord | None = None
    candidate_anchor: OwnedStagingFileV1 | None = None
    try:
        record = materializer_v3._write_new_file(candidate, payload)
        try:
            candidate_anchor = OwnedStagingFileV1.capture(
                candidate, label="accepted model-parity v4 candidate"
            )
        except OwnedStagingCleanupV1Error as error:
            raise ModelParityMaterializerV4Error(str(error)) from error
        loaded = parity_v4.load_parity_manifest_v4(candidate, project_root=root)
        expected = {key: item for key, item in loaded.items() if key != "identity"}
        _require(expected == collection.promoted_manifest, "accepted model-parity v4 candidate roundtrip drifted")
        assessment = parity_v4.assess_model_parity_v4(candidate, project_root=root)
        _require(assessment.get("publication_ready") is True and assessment.get("blockers") == [], "model-parity v4 evidence is not publication-ready")
        materializer_v3._verify_collection_final_paths(collection)
        custody = PhysicalRootCustodyV1.open(
            root, label="accepted model-parity v4 project root"
        )
        try:
            custody.commit_or_adopt_exact_identity(
                accepted.relative_to(root).as_posix(),
                payload,
                label="accepted model-parity v4 manifest",
                mode=0o444,
                create_parents=False,
                after_publish_step=after_manifest_publish_step,
            )
            custody.verify()
        finally:
            custody.close()
        final = materializer_v3.verify_physical_file(root, accepted.relative_to(root), expected_sha256=hashlib.sha256(payload).hexdigest(), expected_size=len(payload), label="accepted model-parity v4 manifest")
        return materializer_v3.PromotionResult(final, assessment)
    finally:
        try:
            if record is not None and candidate_anchor is not None:
                try:
                    candidate_anchor.unlink_owned(final_target=accepted)
                except OwnedStagingCleanupV1Error as error:
                    raise ModelParityMaterializerV4Error(str(error)) from error
        finally:
            if candidate_anchor is not None:
                candidate_anchor.close()


def materialize_and_promote_model_parity_v4(
    *,
    project_root: Path | str,
    image_patch_path: Path | str,
    source_execution_config_path: Path | str,
    source_manifest_path: Path | str,
    dataset_manifest_path: Path | str,
    runtime_probe_dir: Path | str,
    versioned_execution_config_path: Path | str,
    base_manifest_v4_path: Path | str,
    binding_set_dir: Path | str,
    materialization_dir: Path | str,
    accepted_manifest_path: Path | str,
    accepted_assessment_path: Path | str,
    acceptance_receipt_path: Path | str,
    acceptance_binding_path: Path | str,
    ffmpeg_executable: Path | str,
    socket_dir: Path | str,
) -> materializer_v3.PromotionResult:
    foundation = prepare_refresh_foundation_v4(
        project_root=project_root,
        image_patch_path=image_patch_path,
        source_execution_config_path=source_execution_config_path,
        source_manifest_path=source_manifest_path,
        runtime_probe_dir=runtime_probe_dir,
        versioned_execution_config_path=versioned_execution_config_path,
        base_manifest_v4_path=base_manifest_v4_path,
        binding_set_dir=binding_set_dir,
    )
    preflight = _preflight_v4(
        project_root=foundation.project_root,
        dataset_manifest_path=dataset_manifest_path,
        base_manifest_path=base_manifest_v4_path,
        materialization_dir=materialization_dir,
        accepted_manifest_path=accepted_manifest_path,
    )
    collection = materializer_v3._collect_production_evidence(
        preflight,
        materialization_dir=materialization_dir,
        ffmpeg_executable=ffmpeg_executable,
        execution_config_path=versioned_execution_config_path,
        binding_set_dir=binding_set_dir,
        runtime_probe_paths={
            resource: foundation.runtime_probes[resource]["path"]
            for resource in ("cpu", "gpu")
        },
        socket_dir=socket_dir,
    )
    promoted = promote_model_parity_evidence_v4(collection, accepted_manifest_path=accepted_manifest_path)
    from checkpoint_model_parity_acceptance_v4 import promote_model_parity_acceptance_v4
    binding = promote_model_parity_acceptance_v4(
        project_root=foundation.project_root,
        accepted_manifest_path=promoted.accepted_manifest.path,
        accepted_assessment_path=accepted_assessment_path,
        acceptance_receipt_path=acceptance_receipt_path,
        acceptance_binding_path=acceptance_binding_path,
        binding_set_authority=foundation.binding_set_authority,
    )
    return materializer_v3.PromotionResult(promoted.accepted_manifest, promoted.assessment, binding)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run patch-bound physical model parity v4")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--image-patch", type=Path, required=True)
    parser.add_argument("--source-execution-config", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--runtime-probe-dir", type=Path, required=True)
    parser.add_argument("--versioned-execution-config", type=Path, required=True)
    parser.add_argument("--base-v4-manifest", type=Path, required=True)
    parser.add_argument("--binding-set", type=Path, required=True)
    parser.add_argument("--materialization-dir", type=Path, required=True)
    parser.add_argument("--accepted-manifest", type=Path, required=True)
    parser.add_argument("--accepted-assessment", type=Path, required=True)
    parser.add_argument("--acceptance-receipt", type=Path, required=True)
    parser.add_argument("--acceptance-binding", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--socket-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = materialize_and_promote_model_parity_v4(
            project_root=args.project_root,
            image_patch_path=args.image_patch,
            source_execution_config_path=args.source_execution_config,
            source_manifest_path=args.source_manifest,
            dataset_manifest_path=args.datasets,
            runtime_probe_dir=args.runtime_probe_dir,
            versioned_execution_config_path=args.versioned_execution_config,
            base_manifest_v4_path=args.base_v4_manifest,
            binding_set_dir=args.binding_set,
            materialization_dir=args.materialization_dir,
            accepted_manifest_path=args.accepted_manifest,
            accepted_assessment_path=args.accepted_assessment,
            acceptance_receipt_path=args.acceptance_receipt,
            acceptance_binding_path=args.acceptance_binding,
            ffmpeg_executable=args.ffmpeg,
            socket_dir=args.socket_dir,
        )
    except (OSError, ModelParityMaterializerV4Error, parity_v4.ModelParityV4Error) as error:
        print(str(error), file=os.sys.stderr)
        return 2
    print(_canonical(result.parity_acceptance or {}).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ModelParityMaterializerV4Error", "RefreshFoundationV4",
    "build_versioned_execution_config_v4", "capture_live_runtime_probes_v4",
    "materialize_and_promote_model_parity_v4", "materialize_binding_set_v4",
    "prepare_refresh_foundation_v4", "promote_model_parity_evidence_v4",
    "validate_resolved_worker_projection_v4", "write_base_manifest_v4",
]
