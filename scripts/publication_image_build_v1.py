#!/usr/bin/env python3
"""Fail-closed deterministic build and refreeze for publication images."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


REGISTRY_RELATIVE_PATH = "configs/publication_image_build_v1.json"
ARTIFACT_KIND = "vast_publication_image_build_registry_v1"
RECEIPT_KIND = "vast_publication_image_freeze_receipt_v1"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REMOTE_DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_IMAGE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_TARGET_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9./_-]*:[a-zA-Z0-9_.-]+$")
_FORBIDDEN_DOCKERFILE_TOKENS = (
    "apt-get",
    "apk add",
    "dnf install",
    "yum install",
    "curl ",
    "wget ",
    "git clone",
)
_STANDARD_LABELS = (
    "org.vast.publication-image.source-set-sha256",
    "org.vast.publication-image.dependency-set-sha256",
    "org.vast.publication-image.build-context-sha256",
    "org.vast.publication-image.base-image-id",
    "org.vast.publication-image.build-image-id",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _canonical_relative(value: str) -> str:
    _require(type(value) is str and bool(value) and value == value.strip(), "path is empty or padded")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"path is not canonical and relative: {value}",
    )
    return value


def _physical_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(_canonical_relative(relative)).parts)
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f"publication image input is absent: {relative}") from error
    _require(
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and int(info.st_nlink) == 1,
        f"publication image input must be a physical single-link file: {relative}",
    )
    try:
        path.resolve(strict=True).relative_to(root)
    except ValueError as error:
        raise ValueError(f"publication image input escapes project root: {relative}") from error
    return path


def _read_allowlist(root: Path, relative: str) -> tuple[str, ...]:
    path = _physical_file(root, relative)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"allowlist is not UTF-8: {relative}") from error
    _require(raw and raw.endswith(b"\n") and b"\r" not in raw, f"allowlist is not canonical LF text: {relative}")
    rows = tuple(text.splitlines())
    _require(rows == tuple(sorted(set(rows))) and all(rows), f"allowlist must be sorted, unique, and non-empty: {relative}")
    for row in rows:
        _physical_file(root, row)
    return rows


def _set_sha256(root: Path, relative_paths: Sequence[str]) -> str:
    rows = bytearray()
    for relative in sorted(relative_paths):
        digest = hashlib.sha256(_physical_file(root, relative).read_bytes()).hexdigest()
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))
    return hashlib.sha256(rows).hexdigest()


def _logical_dockerfile_lines(source: str) -> tuple[str, ...]:
    logical: list[str] = []
    pending = ""
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending = f"{pending} {stripped}".strip() if pending else stripped
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(pending)
        pending = ""
    _require(not pending, "Dockerfile has an unterminated continuation")
    return tuple(logical)


def dockerfile_context_sources(
    *, project_root: Path, dockerfile_relative: str,
) -> set[str]:
    root = Path(project_root).resolve(strict=True)
    dockerfile = _physical_file(root, dockerfile_relative)
    try:
        source = dockerfile.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Dockerfile is not canonical UTF-8: {dockerfile_relative}") from error
    lowered = source.lower()
    _require("\nadd " not in f"\n{lowered}", "Dockerfile ADD is forbidden")
    for token in _FORBIDDEN_DOCKERFILE_TOKENS:
        _require(token not in lowered, f"Dockerfile has unpinned network/package behavior: {token.strip()}")

    result = {_canonical_relative(dockerfile_relative)}
    for line in _logical_dockerfile_lines(source):
        tokens = shlex.split(line, posix=True)
        if not tokens or tokens[0].upper() != "COPY":
            continue
        args = tokens[1:]
        if any(value.startswith("--from=") for value in args):
            continue
        while args and args[0].startswith("--"):
            args.pop(0)
        _require(len(args) >= 2, "Dockerfile COPY has no source")
        for value in args[:-1]:
            _require(
                not any(character in value for character in "*?[]")
                and not value.endswith("/")
                and value != ".",
                f"Dockerfile COPY source is not exact: {value}",
            )
            result.add(_canonical_relative(value))
    return result


def _validate_dockerfile_contract(root: Path, image: Mapping[str, object]) -> None:
    dockerfile = _physical_file(root, str(image["dockerfile"]))
    source = dockerfile.read_text(encoding="utf-8")
    base = image["base"]
    _require(isinstance(base, dict), "image base contract is invalid")
    expected_arg = f"ARG BASE_IMAGE={base['reference']}"
    _require(expected_arg in source, f"Dockerfile BASE_IMAGE default drifted: {image['name']}")
    builder = image["builder"]
    _require(isinstance(builder, dict), "image builder contract is invalid")
    build_reference = base["reference"] if builder["kind"] == "base" else builder["reference"]
    expected_builder_arg = f"ARG BUILD_IMAGE={build_reference}"
    _require(expected_builder_arg in source, f"Dockerfile BUILD_IMAGE default drifted: {image['name']}")
    _require(source.count("FROM ${BUILD_IMAGE}") == 1, f"Dockerfile must use one explicit build stage: {image['name']}")
    _require(source.count("FROM ${BASE_IMAGE}") == 1, f"Dockerfile must use one explicit runtime stage: {image['name']}")
    for argument in (
        "ARG VAST_SOURCE_SET_SHA256",
        "ARG VAST_DEPENDENCY_SET_SHA256",
        "ARG VAST_BUILD_CONTEXT_SHA256",
        "ARG VAST_BASE_IMAGE_ID",
        "ARG VAST_BUILD_IMAGE_ID",
    ):
        _require(argument in source, f"Dockerfile identity argument is absent: {argument}")
    for label in _STANDARD_LABELS:
        _require(label in source, f"Dockerfile identity label is absent: {label}")
    expected_entrypoint = "ENTRYPOINT " + json.dumps(image["entrypoint"], separators=(",", ":"))
    _require(expected_entrypoint in source, f"Dockerfile entrypoint drifted: {image['name']}")
    _require("COPY --from=" in source, f"Dockerfile has no normalized final copy: {image['name']}")
    dockerfile_context_sources(project_root=root, dockerfile_relative=str(image["dockerfile"]))


def _validate_image_shape(image: object, prior_names: set[str]) -> dict[str, object]:
    _require(isinstance(image, dict), "image registry row is not an object")
    required = {
        "accepted_image_id", "base", "builder", "dependency_allowlist", "dockerfile",
        "entrypoint", "group", "name", "source_allowlist", "source_date_epoch",
        "target_reference", "user",
    }
    _require(set(image) == required, f"image registry keys drifted: {image.get('name', '<unknown>')}")
    name = image["name"]
    _require(type(name) is str and _IMAGE_NAME.fullmatch(name) is not None, "image name is invalid")
    _require(name not in prior_names, f"duplicate image name: {name}")
    _require(image["group"] in {"native_probe", "analytics_worker"}, f"image group is invalid: {name}")
    _require(type(image["accepted_image_id"]) is str and _SHA256.fullmatch(image["accepted_image_id"]) is not None, f"accepted image ID is invalid: {name}")
    _require(type(image["source_date_epoch"]) is int and 0 <= image["source_date_epoch"] <= 2_147_483_647, f"SOURCE_DATE_EPOCH is invalid: {name}")
    _require(type(image["target_reference"]) is str and _TARGET_REFERENCE.fullmatch(image["target_reference"]) is not None, f"target reference is invalid: {name}")
    _require(type(image["user"]) is str and image["user"] in {"root", "dlstreamer"}, f"image user is invalid: {name}")
    entrypoint = image["entrypoint"]
    _require(isinstance(entrypoint, list) and len(entrypoint) == 1 and type(entrypoint[0]) is str and entrypoint[0].startswith("/"), f"entrypoint is invalid: {name}")
    for key in ("dockerfile", "source_allowlist", "dependency_allowlist"):
        _canonical_relative(image[key])
    base = image["base"]
    _require(isinstance(base, dict), f"image base is invalid: {name}")
    if base.get("kind") == "remote_digest":
        _require(set(base) == {"kind", "reference"}, f"remote base keys drifted: {name}")
        _require(type(base["reference"]) is str and _REMOTE_DIGEST.fullmatch(base["reference"]) is not None, f"remote base is not digest-pinned: {name}")
    elif base.get("kind") == "produced_image":
        _require(set(base) == {"kind", "producer", "reference"}, f"produced base keys drifted: {name}")
        _require(base["producer"] in prior_names, f"produced base is not ordered before consumer: {name}")
        _require(type(base["reference"]) is str and _TARGET_REFERENCE.fullmatch(base["reference"]) is not None, f"produced base reference is invalid: {name}")
    else:
        raise ValueError(f"image base kind is invalid: {name}")
    builder = image["builder"]
    _require(isinstance(builder, dict), f"image builder is invalid: {name}")
    if builder.get("kind") == "remote_digest":
        _require(set(builder) == {"kind", "reference"}, f"remote builder keys drifted: {name}")
        _require(
            type(builder["reference"]) is str
            and _REMOTE_DIGEST.fullmatch(builder["reference"]) is not None,
            f"remote builder is not digest-pinned: {name}",
        )
    elif builder.get("kind") == "base":
        _require(set(builder) == {"kind"}, f"base builder keys drifted: {name}")
    else:
        raise ValueError(f"image builder kind is invalid: {name}")
    return image


def load_publication_image_registry(
    *, project_root: Path, registry_path: Path, validate_files: bool = True,
) -> dict[str, object]:
    root_input = Path(project_root)
    _require(root_input.is_dir() and not root_input.is_symlink(), "project root is unsafe")
    root = root_input.resolve(strict=True)
    registry_input = Path(registry_path)
    try:
        registry = registry_input.resolve(strict=True)
    except OSError as error:
        raise ValueError("publication image registry is absent") from error
    try:
        relative = registry.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("publication image registry escapes project root") from error
    _require(relative == REGISTRY_RELATIVE_PATH, "publication image registry path drifted")
    info = registry.lstat()
    _require(stat.S_ISREG(info.st_mode) and not registry.is_symlink() and int(info.st_nlink) == 1, "publication image registry must be a physical single-link file")
    raw = registry.read_bytes()
    _require(raw.endswith(b"\n") and b"\r" not in raw, "publication image registry is not canonical LF text")
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("publication image registry is not valid JSON") from error
    _require(
        isinstance(data, dict)
        and set(data) == {"artifact_kind", "images", "schema_version"}
        and data["artifact_kind"] == ARTIFACT_KIND
        and data["schema_version"] == 1
        and isinstance(data["images"], list)
        and len(data["images"]) == 5,
        "publication image registry envelope drifted",
    )
    names: set[str] = set()
    images: list[dict[str, object]] = []
    for raw_image in data["images"]:
        image = _validate_image_shape(raw_image, names)
        names.add(image["name"])
        images.append(image)
    _require(
        tuple(image["group"] for image in images)
        == ("native_probe", "native_probe", "native_probe", "analytics_worker", "analytics_worker"),
        "publication image build order drifted",
    )
    if validate_files:
        for image in images:
            _validate_dockerfile_contract(root, image)
            sources = _read_allowlist(root, image["source_allowlist"])
            dependencies = _read_allowlist(root, image["dependency_allowlist"])
            _require(not set(sources).intersection(dependencies), f"source/dependency allowlists overlap: {image['name']}")
            expected = dockerfile_context_sources(
                project_root=root,
                dockerfile_relative=image["dockerfile"],
            )
            _require(set(sources).union(dependencies) == expected, f"build context is not the exact Docker COPY closure: {image['name']}")
    return {
        "artifact_kind": data["artifact_kind"],
        "schema_version": data["schema_version"],
        "images": tuple(images),
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _load_materializer():
    path = Path(__file__).resolve().with_name("materialize_runtime_build_context_v3.py")
    spec = importlib.util.spec_from_file_location("publication_image_context_materializer_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load exact build-context materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def materialize_image_context(
    *, project_root: Path, image: Mapping[str, object], output_dir: Path,
) -> dict[str, object]:
    root = Path(project_root).resolve(strict=True)
    sources = _read_allowlist(root, str(image["source_allowlist"]))
    dependencies = _read_allowlist(root, str(image["dependency_allowlist"]))
    _require(not set(sources).intersection(dependencies), "source/dependency allowlists overlap")
    result = _load_materializer().materialize_runtime_build_context(
        project_root=root,
        output_dir=Path(output_dir),
        manifest_paths=(
            root / str(image["source_allowlist"]),
            root / str(image["dependency_allowlist"]),
        ),
        source_date_epoch=int(image["source_date_epoch"]),
    )
    expected = dockerfile_context_sources(
        project_root=root,
        dockerfile_relative=str(image["dockerfile"]),
    )
    _require(set(result["relative_paths"]) == expected, "materialized build context is not exact")
    return {
        "relative_paths": result["relative_paths"],
        "source_set_sha256": _set_sha256(root, sources),
        "dependency_set_sha256": _set_sha256(root, dependencies),
        "build_context_sha256": result["aggregate_sha256"],
        "source_date_epoch": result["source_date_epoch"],
    }


def publication_image_build_plan(
    *, project_root: Path, registry_path: Path,
) -> dict[str, object]:
    root = Path(project_root).resolve(strict=True)
    registry = load_publication_image_registry(project_root=root, registry_path=registry_path)
    rows = []
    for image in registry["images"]:
        sources = _read_allowlist(root, image["source_allowlist"])
        dependencies = _read_allowlist(root, image["dependency_allowlist"])
        union = tuple(sorted(set(sources).union(dependencies)))
        rows.append({
            "name": image["name"],
            "group": image["group"],
            "base": image["base"],
            "builder": image["builder"],
            "target_reference": image["target_reference"],
            "previous_accepted_image_id": image["accepted_image_id"],
            "relative_paths": union,
            "source_set_sha256": _set_sha256(root, sources),
            "dependency_set_sha256": _set_sha256(root, dependencies),
            "build_context_sha256": _set_sha256(root, union),
            "source_date_epoch": image["source_date_epoch"],
        })
    return {
        "artifact_kind": "vast_publication_image_build_plan_v1",
        "schema_version": 1,
        "registry_sha256": registry["registry_sha256"],
        "images": rows,
    }


def _run(command: Sequence[str], *, env: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=None if env is None else dict(env),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"command failed ({completed.returncode}): {command[0]}: {detail}")
    return completed.stdout


def _inspect(docker: str, reference: str) -> dict[str, object]:
    try:
        payload = json.loads(_run((docker, "image", "inspect", reference)))
    except json.JSONDecodeError as error:
        raise ValueError(f"Docker inspect is not JSON: {reference}") from error
    _require(isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict), f"Docker inspect cardinality drifted: {reference}")
    return payload[0]


def _inspect_projection(record: Mapping[str, object]) -> dict[str, object]:
    config = record.get("Config")
    _require(isinstance(config, dict), "Docker inspect Config is absent")
    labels = config.get("Labels") or {}
    _require(isinstance(labels, dict), "Docker inspect labels are invalid")
    repo_digests = record.get("RepoDigests") or []
    _require(isinstance(repo_digests, list) and all(type(value) is str for value in repo_digests), "Docker RepoDigests are invalid")
    return {
        "id": record.get("Id"),
        "repo_digests": sorted(repo_digests),
        "architecture": record.get("Architecture"),
        "os": record.get("Os"),
        "created": record.get("Created"),
        "config": {
            "entrypoint": config.get("Entrypoint"),
            "user": config.get("User") or "root",
            "labels": {key: labels[key] for key in sorted(labels)},
        },
    }


def _receipt_sha256(payload: Mapping[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_json(unsigned)).hexdigest()


def load_publication_image_freeze_receipt(path: Path) -> dict[str, object]:
    receipt_path = Path(path)
    info = receipt_path.lstat()
    _require(stat.S_ISREG(info.st_mode) and not receipt_path.is_symlink() and int(info.st_nlink) == 1, "producer receipt must be a physical single-link file")
    try:
        data = json.loads(receipt_path.read_bytes())
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("producer receipt is not valid JSON") from error
    _require(isinstance(data, dict) and data.get("artifact_kind") == RECEIPT_KIND and data.get("schema_version") == 1, "producer receipt envelope drifted")
    _require(type(data.get("receipt_sha256")) is str and data["receipt_sha256"] == _receipt_sha256(data), "producer receipt self-identity drifted")
    _require(isinstance(data.get("images"), list), "producer receipt images are invalid")
    return data


def _write_exclusive_json(path: Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    parent = target.parent.resolve(strict=True)
    _require(parent.is_dir() and not parent.is_symlink(), "receipt parent is unsafe")
    _require(not target.exists() and not target.is_symlink(), "receipt output already exists")
    raw = _canonical_json(payload) + b"\n"
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o444,
    )
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "receipt write stalled")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(target, 0o444, follow_symlinks=False)


def _expected_created(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_built_image(
    *, record: Mapping[str, object], image: Mapping[str, object], base_id: str,
    build_id: str,
    context: Mapping[str, object],
) -> None:
    _require(type(record.get("Id")) is str and _SHA256.fullmatch(record["Id"]) is not None, "built image ID is invalid")
    config = record.get("Config")
    _require(isinstance(config, dict), "built image Config is absent")
    _require(config.get("Entrypoint") == image["entrypoint"], "built image entrypoint drifted")
    _require((config.get("User") or "root") == image["user"], "built image user drifted")
    labels = config.get("Labels") or {}
    _require(isinstance(labels, dict), "built image labels are invalid")
    expected_labels = {
        "org.vast.publication-image.source-set-sha256": context["source_set_sha256"],
        "org.vast.publication-image.dependency-set-sha256": context["dependency_set_sha256"],
        "org.vast.publication-image.build-context-sha256": context["build_context_sha256"],
        "org.vast.publication-image.base-image-id": base_id,
        "org.vast.publication-image.build-image-id": build_id,
    }
    for key, value in expected_labels.items():
        _require(labels.get(key) == value, f"built image label drifted: {key}")
    _require(record.get("Created") == _expected_created(int(image["source_date_epoch"])), "built image creation time drifted")


def build_publication_image_group(
    *,
    project_root: Path,
    registry_path: Path,
    group: str,
    work_root: Path,
    receipt_output: Path,
    docker: str = "docker",
    producer_receipt: Path | None = None,
) -> dict[str, object]:
    _require(group in {"native_probe", "analytics_worker"}, "publication image group is invalid")
    root = Path(project_root).resolve(strict=True)
    registry = load_publication_image_registry(project_root=root, registry_path=registry_path)
    work_input = Path(work_root)
    _require(work_input.is_dir() and not work_input.is_symlink(), "build work root is unsafe")
    work = work_input.resolve(strict=True)
    try:
        work.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("build work root must be outside project root")
    _require(not any(work.iterdir()), "build work root must be empty")
    _require(type(docker) is str and bool(docker) and not any(character.isspace() for character in docker), "Docker executable is invalid")

    producer_rows: dict[str, dict[str, object]] = {}
    if group == "analytics_worker":
        _require(producer_receipt is not None, "analytics worker build requires a native-probe freeze receipt")
        producer_data = load_publication_image_freeze_receipt(Path(producer_receipt))
        _require(producer_data.get("registry_sha256") == registry["registry_sha256"], "producer receipt registry identity drifted")
        for row in producer_data["images"]:
            _require(isinstance(row, dict) and type(row.get("name")) is str, "producer receipt row is invalid")
            producer_rows[row["name"]] = row

    selected = [image for image in registry["images"] if image["group"] == group]
    receipt_rows: list[dict[str, object]] = []
    environment = dict(os.environ)
    environment["DOCKER_BUILDKIT"] = "1"
    for image in selected:
        context_root = work / image["name"]
        context_root.mkdir(mode=0o700)
        context = materialize_image_context(
            project_root=root,
            image=image,
            output_dir=context_root,
        )
        base = image["base"]
        base_reference = base["reference"]
        base_record = _inspect(docker, base_reference)
        base_id = base_record.get("Id")
        _require(type(base_id) is str and _SHA256.fullmatch(base_id) is not None, f"base image ID is invalid: {image['name']}")
        if base["kind"] == "remote_digest":
            repo_digests = base_record.get("RepoDigests") or []
            _require(base_reference in repo_digests, f"remote base RepoDigest is not physically present: {image['name']}")
        else:
            producer = producer_rows.get(base["producer"])
            _require(producer is not None, f"producer image is absent from freeze receipt: {image['name']}")
            _require(producer.get("target_reference") == base_reference and producer.get("image_id") == base_id, f"produced base physical identity drifted: {image['name']}")

        builder = image["builder"]
        if builder["kind"] == "base":
            build_reference = base_reference
            build_id = base_id
        else:
            build_reference = builder["reference"]
            build_record = _inspect(docker, build_reference)
            build_id = build_record.get("Id")
            _require(
                type(build_id) is str and _SHA256.fullmatch(build_id) is not None,
                f"build image ID is invalid: {image['name']}",
            )
            build_repo_digests = build_record.get("RepoDigests") or []
            _require(
                build_reference in build_repo_digests,
                f"remote build image RepoDigest is not physically present: {image['name']}",
            )

        first_ref = image["target_reference"] + "-determinism-a"
        second_ref = image["target_reference"] + "-determinism-b"
        build_args = (
            ("BASE_IMAGE", base_reference),
            ("BUILD_IMAGE", build_reference),
            ("SOURCE_DATE_EPOCH", str(image["source_date_epoch"])),
            ("VAST_SOURCE_SET_SHA256", context["source_set_sha256"]),
            ("VAST_DEPENDENCY_SET_SHA256", context["dependency_set_sha256"]),
            ("VAST_BUILD_CONTEXT_SHA256", context["build_context_sha256"]),
            ("VAST_BASE_IMAGE_ID", base_id),
            ("VAST_BUILD_IMAGE_ID", build_id),
        )
        if group == "analytics_worker":
            build_args = build_args + (("EXPECTED_BASE_IMAGE_ID", base_id),)

        def build_one(target: str) -> None:
            command = [docker, "buildx", "build"]
            command.extend([
                "--no-cache",
                "--pull=false",
                "--network=none",
                "--provenance=false",
                "--sbom=false",
                "--output",
                "type=docker,rewrite-timestamp=true,unpack=false",
            ])
            for key, value in build_args:
                command.extend(("--build-arg", f"{key}={value}"))
            command.extend((
                "--tag", target,
                "--file", str(context_root / image["dockerfile"]),
                str(context_root),
            ))
            _run(command, env=environment)

        build_one(first_ref)
        build_one(second_ref)
        first = _inspect(docker, first_ref)
        second = _inspect(docker, second_ref)
        first_id = first.get("Id")
        second_id = second.get("Id")
        _require(first_id == second_id, f"deterministic image IDs differ: {first_id} != {second_id}")
        _validate_built_image(record=first, image=image, base_id=base_id, build_id=build_id, context=context)
        _validate_built_image(record=second, image=image, base_id=base_id, build_id=build_id, context=context)
        _require(_set_sha256(root, _read_allowlist(root, image["source_allowlist"])) == context["source_set_sha256"], "workspace source changed during image build")
        _require(_set_sha256(root, _read_allowlist(root, image["dependency_allowlist"])) == context["dependency_set_sha256"], "workspace dependency changed during image build")
        _require(_set_sha256(context_root, context["relative_paths"]) == context["build_context_sha256"], "materialized context changed during image build")
        _run((docker, "tag", first_id, image["target_reference"]))
        _run((docker, "run", "--rm", "--network", "none", first_id, "--help"))
        final_record = _inspect(docker, image["target_reference"])
        _require(final_record.get("Id") == first_id, "final image tag identity drifted")
        projection = _inspect_projection(final_record)
        labels = projection["config"]["labels"]
        receipt_rows.append({
            "name": image["name"],
            "group": image["group"],
            "target_reference": image["target_reference"],
            "image_id": first_id,
            "repo_digests": projection["repo_digests"],
            "image_inspect_sha256": hashlib.sha256(_canonical_json(projection)).hexdigest(),
            "base_reference": base_reference,
            "base_image_id": base_id,
            "build_reference": build_reference,
            "build_image_id": build_id,
            "source_set_sha256": context["source_set_sha256"],
            "dependency_set_sha256": context["dependency_set_sha256"],
            "build_context_sha256": context["build_context_sha256"],
            "source_date_epoch": image["source_date_epoch"],
            "entrypoint": image["entrypoint"],
            "user": image["user"],
            "labels": {key: labels[key] for key in _STANDARD_LABELS},
            "previous_accepted_image_id": image["accepted_image_id"],
            "identity_changed": first_id != image["accepted_image_id"],
        })

    receipt: dict[str, object] = {
        "artifact_kind": RECEIPT_KIND,
        "schema_version": 1,
        "group": group,
        "registry_path": REGISTRY_RELATIVE_PATH,
        "registry_sha256": registry["registry_sha256"],
        "images": receipt_rows,
    }
    receipt["receipt_sha256"] = _receipt_sha256(receipt)
    _write_exclusive_json(Path(receipt_output), receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--project-root", type=Path, required=True)
    plan_parser.add_argument("--registry", type=Path, required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--project-root", type=Path, required=True)
    build_parser.add_argument("--registry", type=Path, required=True)
    build_parser.add_argument("--group", choices=("native_probe", "analytics_worker"), required=True)
    build_parser.add_argument("--work-root", type=Path, required=True)
    build_parser.add_argument("--receipt-output", type=Path, required=True)
    build_parser.add_argument("--producer-receipt", type=Path)
    build_parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    if args.command == "plan":
        result = publication_image_build_plan(
            project_root=args.project_root,
            registry_path=args.registry,
        )
    else:
        result = build_publication_image_group(
            project_root=args.project_root,
            registry_path=args.registry,
            group=args.group,
            work_root=args.work_root,
            receipt_output=args.receipt_output,
            docker=args.docker,
            producer_receipt=args.producer_receipt,
        )
    print(_canonical_json(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
