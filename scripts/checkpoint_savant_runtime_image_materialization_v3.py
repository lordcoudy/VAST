#!/usr/bin/env python3
"""Derive one physical Savant runtime-image manifest from Docker inspect."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


ARTIFACT_KIND = "vast_savant_runtime_image_materialization_v3"
BASE_IMAGE_ID = (
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
NATIVE_BUILDER_IMAGE_ID = (
    "sha256:ef70f6fae0558d1d90ae32fc931256bc71169749c15ae00b70a8ca00c0b70513"
)
NATIVE_BUILDER_SOURCE_SHA256 = (
    "e38aa56050381aef7ce9ff6fb934ae3da0d44175f10fb67f4cecea34433ded01"
)
ENTRYPOINT = ["/usr/local/bin/vast_savant_checkpoint_runtime"]
LABELS = {
    "org.vast.savant.version": "0.5.17",
    "org.vast.deepstream.version": "7.0",
    "org.vast.base-image-id": BASE_IMAGE_ID,
    "org.vast.native-builder-image-id": NATIVE_BUILDER_IMAGE_ID,
    "org.vast.native-builder-source-sha256": NATIVE_BUILDER_SOURCE_SHA256,
    "org.vast.publication-ready": "false",
}
_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REPO_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
MAX_INSPECT_BYTES = 8 * 1024 * 1024


class RuntimeImageMaterializationError(RuntimeError):
    """Docker inspect identity or physical output failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeImageMaterializationError(message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise RuntimeImageMaterializationError(
            "runtime image projection is not canonical",
        ) from error


def build_runtime_image_materialization(
    *,
    inspect: Mapping[str, Any],
    runtime_source_sha256: str,
    runtime_bundle_sha256: str,
) -> dict[str, Any]:
    """Validate exact labels and return the fragment-consumable projection."""
    _require(isinstance(inspect, Mapping), "Docker inspect must be an object")
    source_sha = str(runtime_source_sha256)
    bundle_sha = str(runtime_bundle_sha256)
    _require(
        _SHA_RE.fullmatch(source_sha) is not None
        and _SHA_RE.fullmatch(bundle_sha) is not None,
        "runtime source/bundle SHA-256 is invalid",
    )
    image_id = str(inspect.get("Id", ""))
    config = inspect.get("Config")
    _require(
        _IMAGE_RE.fullmatch(image_id) is not None
        and inspect.get("Architecture") == "amd64"
        and inspect.get("Os") == "linux"
        and isinstance(config, Mapping)
        and config.get("Entrypoint") == ENTRYPOINT,
        "Savant image platform/entrypoint identity drifted",
    )
    labels = config.get("Labels")
    _require(isinstance(labels, Mapping), "Savant image labels are missing")
    expected = {
        **LABELS,
        "org.vast.savant.runtime-source-sha256": source_sha,
        "org.vast.savant.runtime-bundle-sha256": bundle_sha,
    }
    _require(
        all(labels.get(key) == value for key, value in expected.items()),
        "Savant image labels drifted",
    )
    repo_digests = inspect.get("RepoDigests") or []
    _require(
        type(repo_digests) is list
        and len(repo_digests) == len(set(repo_digests))
        and all(_REPO_RE.fullmatch(str(value)) is not None for value in repo_digests),
        "Savant image repository digest set drifted",
    )
    selected_labels = {key: str(labels[key]) for key in sorted(expected)}
    projection = {
        "Architecture": "amd64",
        "Config": {"Entrypoint": ENTRYPOINT, "Labels": selected_labels},
        "Id": image_id,
        "Os": "linux",
        "RepoDigests": list(repo_digests),
    }
    return {
        "schema_version": 3,
        "artifact_kind": ARTIFACT_KIND,
        "image_id": image_id,
        "repository_digests": list(repo_digests),
        "inspect_projection_sha256": hashlib.sha256(_canonical(projection)).hexdigest(),
        "entrypoint": list(ENTRYPOINT),
        "architecture": "amd64",
        "os": "linux",
        "savant_version": "0.5.17",
        "deepstream_version": "7.0",
        "base_image_id": BASE_IMAGE_ID,
        "native_builder_image_id": NATIVE_BUILDER_IMAGE_ID,
        "native_builder_source_sha256": NATIVE_BUILDER_SOURCE_SHA256,
        "runtime_source_sha256": source_sha,
        "runtime_bundle_sha256": bundle_sha,
        "publication_ready_label": "false",
    }


def _write_immutable(path: Path, payload: bytes) -> None:
    output = Path(path).resolve(strict=False)
    _require(output.is_absolute(), "runtime image manifest output must be absolute")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.lstat()
    _require(stat.S_ISDIR(parent.st_mode) and not output.parent.is_symlink(),
             "runtime image manifest parent is unsafe")
    if output.exists():
        info = output.lstat()
        _require(
            stat.S_ISREG(info.st_mode) and not output.is_symlink()
            and int(info.st_nlink) == 1 and output.read_bytes() == payload,
            "runtime image manifest collision",
        )
        return
    descriptor, name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def materialize_from_docker(
    *, image_id: str, runtime_source_sha256: str,
    runtime_bundle_sha256: str, output: Path,
) -> dict[str, Any]:
    _require(_IMAGE_RE.fullmatch(image_id) is not None, "image ID is invalid")
    try:
        completed = subprocess.run(
            ("docker", "image", "inspect", image_id),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=60.0, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeImageMaterializationError("Docker inspect unavailable") from error
    _require(
        completed.returncode == 0
        and 0 < len(completed.stdout) <= MAX_INSPECT_BYTES
        and len(completed.stderr) <= MAX_INSPECT_BYTES,
        "Docker inspect failed or exceeded its capture bound",
    )
    try:
        values = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeImageMaterializationError("Docker inspect output is invalid") from error
    _require(type(values) is list and len(values) == 1, "Docker inspect cardinality drifted")
    result = build_runtime_image_materialization(
        inspect=values[0],
        runtime_source_sha256=runtime_source_sha256,
        runtime_bundle_sha256=runtime_bundle_sha256,
    )
    payload = _canonical(result) + b"\n"
    _write_immutable(output, payload)
    return {**result, "manifest_path": str(Path(output).resolve())}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize exact Savant image identity")
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--runtime-source-sha256", required=True)
    parser.add_argument("--runtime-bundle-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = materialize_from_docker(
            image_id=args.image_id,
            runtime_source_sha256=args.runtime_source_sha256,
            runtime_bundle_sha256=args.runtime_bundle_sha256,
            output=args.output,
        )
    except RuntimeImageMaterializationError as error:
        print(str(error), file=os.sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RuntimeImageMaterializationError", "build_runtime_image_materialization",
    "materialize_from_docker",
]
