#!/usr/bin/env python3
"""Materialize immutable per-branch bindings for the two native workers."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from publication_immutable_directory_v1 import (
    JOURNAL_ROOT,
    commit_or_adopt_immutable_directory_v1,
)
from publication_owned_staging_cleanup_v1 import (
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
)

from analytics_execution_protocol import (
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    canonical_json_bytes,
    canonical_sha256,
    valid_gpu_uuid,
    valid_image_id,
)


BINDING_SET_KIND = "vast_analytics_execution_worker_binding_set"
OPENVINO_BINDING_KIND = "vast_openvino_execution_worker_binding"
TENSORRT_BINDING_KIND = "vast_tensorrt_execution_worker_binding"
ENGINES = (ENGINE_OPENVINO_CPU, ENGINE_TENSORRT_CUDA)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    return value


def _verified_artifact(
    value: Any,
    *,
    project_root: Path,
    worker_project_root: PurePosixPath,
    suffix: str,
    label: str,
) -> tuple[str, str]:
    record = _mapping(value, label)
    raw = record.get("path")
    _require(type(raw) is str and raw and "\\" not in raw, f"{label} path is invalid")
    relative = PurePosixPath(raw)
    _require(not relative.is_absolute() and ".." not in relative.parts, f"{label} path is unsafe")
    lexical = Path(os.path.abspath(os.fspath(project_root / Path(*relative.parts))))
    resolved = lexical.resolve()
    root = project_root.resolve()
    try:
        lexical.relative_to(root)
        resolved.relative_to(root)
    except ValueError as error:
        raise ProtocolError(f"{label} path escapes the project root") from error
    _require(lexical == resolved and not lexical.is_symlink(), f"{label} path is a symlink or alias")
    _require(resolved.is_file() and resolved.suffix == suffix, f"{label} artifact is missing or has the wrong suffix")
    expected_sha = record.get("sha256")
    expected_size = record.get("size_bytes")
    _require(type(expected_sha) is str and len(expected_sha) == 64, f"{label} SHA-256 is invalid")
    _require(type(expected_size) is int and expected_size >= 0, f"{label} size is invalid")
    before = resolved.stat()
    actual_sha = _sha_file(resolved)
    after = resolved.stat()
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    _require(before_identity == after_identity, f"{label} changed while it was hashed")
    _require(before.st_size == expected_size, f"{label} size mismatch")
    digest_label = "authoritative TensorRT engine" if suffix == ".engine" else label
    _require(actual_sha == expected_sha, f"{digest_label} SHA-256 mismatch")
    worker_path = worker_project_root.joinpath(*relative.parts)
    return str(worker_path), actual_sha


def _identity(value: Mapping[str, Any], label: str) -> str:
    identity = _mapping(value.get("identity"), f"{label} identity")
    digest = identity.get("sha256")
    _require(identity.get("algorithm") == "sha256" and type(digest) is str and len(digest) == 64, f"{label} identity is invalid")
    return digest


def _worker_implementation_inventory(
    execution_config: Mapping[str, Any],
) -> dict[str, str]:
    workers = _mapping(execution_config.get("workers"), "analytics execution workers")
    result: dict[str, str] = {}
    for resource_name, engine in (
        ("cpu", ENGINE_OPENVINO_CPU),
        ("gpu", ENGINE_TENSORRT_CUDA),
    ):
        worker = _mapping(
            workers.get(resource_name),
            f"analytics execution {resource_name} worker",
        )
        digest = worker.get("worker_implementation_sha256")
        _require(
            type(digest) is str and _SHA256_RE.fullmatch(digest) is not None,
            f"analytics execution {resource_name} worker implementation SHA-256 is invalid",
        )
        result[engine] = digest
    return result


def build_worker_bindings(
    manifest: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    *,
    project_root: Path | str,
    worker_project_root: str = "/workspace",
) -> dict[str, dict[str, dict[str, Any]]]:
    """Build eight adapter-native bindings after rehashing every artifact."""

    root = Path(project_root).resolve()
    _require(root.is_dir() and not root.is_symlink(), "analytics execution project root is unsafe")
    worker_root = PurePosixPath(worker_project_root)
    _require(worker_root.is_absolute() and ".." not in worker_root.parts, "worker project root must be an absolute POSIX path")
    _require(execution_config.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256, "binding config protocol identity mismatch")
    _require(manifest.get("required_branches") == list(BRANCHES), "model parity branch order or membership has drifted")
    sources = _mapping(manifest.get("source_registry"), "model parity source registry")
    slots = _mapping(manifest.get("workload_slots"), "model parity workload slots")
    _require(set(slots) == set(BRANCHES), "model parity workload slots have drifted")
    workers = _mapping(execution_config.get("workers"), "analytics execution workers")
    _worker_implementation_inventory(execution_config)
    cpu_worker = _mapping(workers.get("cpu"), "OpenVINO worker config")
    gpu_worker = _mapping(workers.get("gpu"), "TensorRT worker config")
    _require(cpu_worker.get("engine") == ENGINE_OPENVINO_CPU, "OpenVINO worker engine mismatch")
    _require(gpu_worker.get("engine") == ENGINE_TENSORRT_CUDA, "TensorRT worker engine mismatch")
    _require(valid_image_id(cpu_worker.get("image_id")), "OpenVINO worker image is not pinned")
    _require(valid_image_id(gpu_worker.get("image_id")), "TensorRT worker image is not pinned")
    toolchains = _mapping(manifest.get("toolchain_registry"), "model parity toolchain registry")
    trt_toolchain = _mapping(toolchains.get("tensorrt_cuda"), "TensorRT toolchain")
    gpu_uuid = trt_toolchain.get("gpu_uuid")
    _require(valid_gpu_uuid(gpu_uuid), "TensorRT toolchain GPU UUID is invalid")
    preprocessing = _mapping(manifest.get("preprocessing_contract"), "preprocessing contract")
    classification = _mapping(manifest.get("classification_contract"), "classification contract")
    preprocessing_sha = canonical_sha256(preprocessing)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for branch in BRANCHES:
        slot = _mapping(slots[branch], f"{branch} workload slot")
        source_ref = slot.get("source_ref")
        _require(type(source_ref) is str and source_ref in sources, f"{branch} source reference is invalid")
        source = _mapping(sources[source_ref], f"{branch} source")
        source_path, source_sha = _verified_artifact(
            source, project_root=root, worker_project_root=worker_root,
            suffix=".onnx", label=f"{branch} canonical source",
        )
        openvino = _mapping(slot.get("openvino_ir"), f"{branch} OpenVINO IR")
        model_path, model_sha = _verified_artifact(
            openvino.get("model"), project_root=root, worker_project_root=worker_root,
            suffix=".xml", label=f"{branch} OpenVINO model",
        )
        weights_path, weights_sha = _verified_artifact(
            openvino.get("weights"), project_root=root, worker_project_root=worker_root,
            suffix=".bin", label=f"{branch} OpenVINO weights",
        )
        _require(PurePosixPath(weights_path) == PurePosixPath(model_path).with_suffix(".bin"), f"{branch} OpenVINO XML/BIN are not siblings")
        tensorrt = _mapping(slot.get("tensorrt_engine"), f"{branch} TensorRT engine")
        engine_path, engine_sha = _verified_artifact(
            tensorrt.get("artifact"), project_root=root, worker_project_root=worker_root,
            suffix=".engine", label=f"{branch} TensorRT engine",
        )
        source_input = _mapping(source.get("input"), f"{branch} source input")
        source_output = _mapping(source.get("output"), f"{branch} source output")
        input_contract = {
            "name": source_input.get("name"), "dtype": source_input.get("dtype"),
            "layout": source_input.get("layout"), "shape": source_input.get("execution_shape"),
        }
        output_contract = {
            "name": source_output.get("name"), "dtype": source_output.get("dtype"),
            "shape": source_output.get("execution_shape"),
        }
        _require(input_contract["shape"] == preprocessing.get("execution_shape"), f"{branch} input/preprocessing shape mismatch")
        _require(input_contract["dtype"] == preprocessing.get("output_dtype"), f"{branch} input/preprocessing dtype mismatch")
        _require(input_contract["layout"] == preprocessing.get("output_layout"), f"{branch} input/preprocessing layout mismatch")
        _require(output_contract["dtype"] == classification.get("dtype"), f"{branch} output/classification dtype mismatch")
        _require(output_contract["shape"] == [1, classification.get("class_count")], f"{branch} output/classification shape mismatch")
        output_sha = canonical_sha256({
            "classification_contract": dict(classification),
            "source_output": dict(source_output),
        })
        model_id = slot.get("slot_id")
        _require(type(model_id) is str and model_id, f"{branch} workload slot ID is invalid")
        common = {
            "schema_version": 1,
            "worker_id": f"vast.{branch}",
            "branch": branch,
            "model_id": model_id,
            "source_path": source_path,
            "source_model_sha256": source_sha,
            "input": input_contract,
            "preprocessing_contract_sha256": preprocessing_sha,
            "output_contract_sha256": output_sha,
            "outputs": [output_contract],
        }
        result[branch] = {
            ENGINE_OPENVINO_CPU: {
                **common,
                "artifact_kind": OPENVINO_BINDING_KIND,
                "worker_id": f"vast.{branch}.openvino",
                "model_path": model_path,
                "model_artifact_sha256": model_sha,
                "weights_path": weights_path,
                "runtime_weights_sha256": weights_sha,
                "worker_image_id": cpu_worker["image_id"],
            },
            ENGINE_TENSORRT_CUDA: {
                **common,
                "artifact_kind": TENSORRT_BINDING_KIND,
                "worker_id": f"vast.{branch}.tensorrt",
                "engine_path": engine_path,
                "model_artifact_sha256": engine_sha,
                "worker_image_id": gpu_worker["image_id"],
                "gpu_device_index": 0,
                "gpu_uuid": gpu_uuid,
            },
        }
    return result


def _directory_intent_exists(project_root: Path | str, target: Path) -> bool:
    root = Path(project_root).resolve(strict=True)
    relative = target.relative_to(root).as_posix()
    key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
    return os.path.lexists(root / JOURNAL_ROOT / f"{key}.json")


def materialize_worker_bindings(
    output_dir: Path | str,
    *,
    manifest: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    project_root: Path | str,
    worker_project_root: str = "/workspace",
    after_directory_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    target = Path(output_dir).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    bindings = build_worker_bindings(
        manifest, execution_config, project_root=project_root,
        worker_project_root=worker_project_root,
    )
    staging_prefix = f".{target.name}."
    temporary: Path | None = Path(
        tempfile.mkdtemp(prefix=staging_prefix, dir=target.parent)
    )
    cleanup_anchor: OwnedStagingDirectoryV1 | None = None
    try:
        try:
            cleanup_anchor = OwnedStagingDirectoryV1.capture(
                temporary,
                expected_parent=target.parent,
                expected_prefix=staging_prefix,
                label="analytics binding staging",
            )
        except OwnedStagingCleanupV1Error as error:
            raise ProtocolError(str(error)) from error
        files: list[dict[str, Any]] = []
        binding_identity: dict[str, Any] = {}
        for branch in BRANCHES:
            for engine in ENGINES:
                filename = f"{branch}.{engine}.json"
                payload = canonical_json_bytes(bindings[branch][engine]) + b"\n"
                path = temporary / filename
                path.write_bytes(payload)
                with path.open("rb") as source:
                    os.fsync(source.fileno())
                digest = hashlib.sha256(payload).hexdigest()
                files.append({"path": filename, "bytes": len(payload), "sha256": digest})
                binding_identity[filename] = canonical_sha256(bindings[branch][engine])
        core = {
            "schema_version": 1,
            "artifact_kind": BINDING_SET_KIND,
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "execution_config_identity_sha256": _identity(execution_config, "execution config"),
            "model_parity_manifest_identity_sha256": _identity(manifest, "model parity manifest"),
            "worker_project_root": worker_project_root,
            "worker_implementation_sha256": _worker_implementation_inventory(
                execution_config
            ),
            "bindings_identity_sha256": canonical_sha256(binding_identity),
            "files": files,
        }
        index = {**core, "identity": {"algorithm": "sha256", "sha256": canonical_sha256(core)}}
        index_path = temporary / "index.json"
        index_path.write_bytes(canonical_json_bytes(index) + b"\n")
        with index_path.open("rb") as source:
            os.fsync(source.fileno())
        for path in temporary.iterdir():
            path.chmod(0o444)
        temporary.chmod(0o755)
        try:
            cleanup_anchor.seal_tree()
        except OwnedStagingCleanupV1Error as error:
            raise ProtocolError(str(error)) from error
        publication = commit_or_adopt_immutable_directory_v1(
            project_root=project_root,
            staging=temporary,
            target=target,
            after_publish_step=after_directory_publish_step,
        )
        try:
            cleanup_anchor.cleanup_after_publication(final_target=target)
        except OwnedStagingCleanupV1Error as error:
            raise ProtocolError(str(error)) from error
        temporary = None
        return index
    finally:
        try:
            if (
                temporary is not None
                and cleanup_anchor is not None
                and not _directory_intent_exists(project_root, target)
            ):
                try:
                    if not cleanup_anchor.sealed:
                        cleanup_anchor.seal_tree()
                    cleanup_anchor.cleanup_after_publication(final_target=target)
                except OwnedStagingCleanupV1Error as error:
                    raise ProtocolError(str(error)) from error
        finally:
            if cleanup_anchor is not None:
                cleanup_anchor.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact native analytics worker bindings.")
    parser.add_argument("--config", type=Path, default=Path("configs/analytics_execution_layer.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("configs/checkpoint_analytics_model_parity.yaml"))
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--worker-project-root", default="/workspace")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    from analytics_execution_capability import load_execution_layer_config
    from checkpoint_model_parity import load_parity_manifest

    args = build_parser().parse_args(argv)
    config = load_execution_layer_config(args.config)
    manifest = load_parity_manifest(args.manifest)
    index = materialize_worker_bindings(
        args.output,
        manifest=manifest,
        execution_config=config,
        project_root=args.project_root,
        worker_project_root=args.worker_project_root,
    )
    print((canonical_json_bytes(index) + b"\n").decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BINDING_SET_KIND", "build_worker_bindings", "main",
    "materialize_worker_bindings",
]
