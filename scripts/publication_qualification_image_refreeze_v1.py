#!/usr/bin/env python3
"""Capture and assemble non-authorizing qualification image identities.

The four runtime images are built by their existing deterministic builders.
This tool only verifies the surviving A/B/final image identities, captures
their embedded files, and joins those receipts with the native-probe and
analytics-worker freeze receipts.  Its patch is derived physical evidence;
it never supersedes a candidate/bootstrap transaction or live Docker inspect.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


REGISTRY_RELATIVE_PATH = "configs/publication_qualification_image_refreeze_v1.json"
REGISTRY_KIND = "vast_publication_qualification_image_refreeze_registry_v1"
PLAN_KIND = "vast_publication_qualification_image_refreeze_plan_v1"
RUNTIME_RECEIPT_KIND = "vast_publication_qualification_runtime_image_freeze_receipt_v1"
PATCH_KIND = "vast_publication_qualification_image_identity_patch_v1"
BUILD_REGISTRY_RELATIVE_PATH = "configs/publication_image_build_v1.json"
BUILD_RECEIPT_KIND = "vast_publication_image_freeze_receipt_v1"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
PROJECTION_KINDS = (
    "deepstream_v1", "savant_v3", "openvino_v3", "gstreamer_v3",
)
MAX_COMMAND_BYTES = 8 * 1024 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_REMOTE_DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_IMAGE_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_.-]+$")
_TEMPLATE = re.compile(r"^\$[a-z][a-z0-9_]*$")
_FORBIDDEN_SOURCE_TOKENS = (
    "docker pull", "curl ", "wget ", "apt-get", "apk add",
    "dnf install", "yum install", "--network host",
)


class QualificationImageRefreezeV1Error(ValueError):
    """An image identity, physical input, or receipt failed closed."""


CommandRunner = Callable[[Sequence[str]], bytes | str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationImageRefreezeV1Error(message)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise QualificationImageRefreezeV1Error(
            "qualification image evidence is not canonical JSON",
        ) from error


def self_sha256(value: Mapping[str, object], field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _canonical_relative(value: object) -> str:
    _require(
        type(value) is str and bool(value) and value == value.strip(),
        "relative path is empty or padded",
    )
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"path is not canonical and relative: {value}",
    )
    return value


def _root(project_root: Path) -> Path:
    value = Path(project_root)
    _require(value.is_dir() and not value.is_symlink(), "project_root is unsafe")
    return value.resolve(strict=True)


def _physical_file(root: Path, value: str | Path, *, exact_relative: str | None = None) -> Path:
    path = Path(value)
    if not path.is_absolute():
        relative = _canonical_relative(path.as_posix())
        path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError) as error:
        raise QualificationImageRefreezeV1Error(
            f"physical project input is missing or escapes project_root: {value}",
        ) from error
    _require(
        stat.S_ISREG(before.st_mode)
        and not path.is_symlink()
        and int(before.st_nlink) == 1
        and resolved == path.absolute(),
        f"project input must be one unaliased physical file: {value}",
    )
    if exact_relative is not None:
        _require(relative == exact_relative, f"project input path drifted: {relative}")
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    _require(
        (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        == (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        ),
        f"physical input changed while hashing: {path}",
    )
    return digest.hexdigest()


def _descriptor(root: Path, path: Path) -> dict[str, object]:
    physical = _physical_file(root, path)
    return {
        "path": physical.relative_to(root).as_posix(),
        "size_bytes": physical.stat().st_size,
        "sha256": _file_sha256(physical),
    }


def _fragment_descriptor(root: Path, relative: str) -> dict[str, object]:
    descriptor = _descriptor(root, _physical_file(root, relative))
    return {
        "path": descriptor["path"],
        "size": descriptor["size_bytes"],
        "sha256": descriptor["sha256"],
    }


def _load_json_file(root: Path, value: str | Path, *, exact_relative: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = _physical_file(root, value, exact_relative=exact_relative)
    raw = path.read_bytes()
    _require(raw.endswith(b"\n") and b"\r" not in raw, f"JSON is not canonical LF text: {path}")
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationImageRefreezeV1Error(f"invalid JSON: {path}") from error
    _require(type(data) is dict, f"JSON root must be an object: {path}")
    return path, data


def _read_allowlist(root: Path, relative: str) -> tuple[str, ...]:
    path = _physical_file(root, relative)
    raw = path.read_bytes()
    _require(raw and raw.endswith(b"\n") and b"\r" not in raw, f"allowlist is not canonical LF text: {relative}")
    try:
        rows = tuple(raw.decode("utf-8").splitlines())
    except UnicodeError as error:
        raise QualificationImageRefreezeV1Error(f"allowlist is not UTF-8: {relative}") from error
    _require(
        rows == tuple(sorted(set(rows))) and all(rows),
        f"allowlist must be sorted, unique, and non-empty: {relative}",
    )
    for row in rows:
        _canonical_relative(row)
        _physical_file(root, row)
    return rows


def _set_sha256(root: Path, relative_paths: Sequence[str]) -> str:
    rows = bytearray()
    for relative in sorted(relative_paths):
        digest = _file_sha256(_physical_file(root, relative))
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))
    _require(bool(rows), "identity set is empty")
    return hashlib.sha256(rows).hexdigest()


def _validate_base(value: object, *, allow_remote: bool) -> dict[str, Any]:
    _require(type(value) is dict, "image base is not an object")
    kind = value.get("kind")
    if kind == "remote_digest":
        _require(allow_remote, "native builder cannot be a remote base")
        _require(set(value) == {"kind", "reference", "evidence_producer"}, "remote base fields drifted")
        _require(_REMOTE_DIGEST.fullmatch(str(value["reference"])) is not None, "remote base is not digest-pinned")
        _require(
            type(value["evidence_producer"]) is str
            and value["evidence_producer"]
            in {"native_probe_deepstream", "native_probe_savant"},
            "remote base evidence producer is invalid",
        )
    elif kind == "produced_image":
        _require(set(value) == {"kind", "producer", "reference"}, "produced base fields drifted")
        _require(type(value["producer"]) is str and bool(value["producer"]), "produced base name is invalid")
        _require(_IMAGE_REFERENCE.fullmatch(str(value["reference"])) is not None, "produced base reference is invalid")
    else:
        raise QualificationImageRefreezeV1Error("image base kind is invalid")
    return dict(value)


def _validate_system(root: Path, raw: object, expected_system: str) -> dict[str, Any]:
    _require(type(raw) is dict, f"{expected_system} registry row is not an object")
    fields = {
        "base", "created", "dependency_allowlist", "deterministic_references",
        "dockerfile", "embedded_aliases", "embedded_paths", "entrypoint",
        "final_reference", "native_builder", "native_source_prefix",
        "projection_kind", "projection_label_keys", "repository",
        "required_labels", "smoke_args", "source_allowlist", "system", "user",
    }
    _require(set(raw) == fields, f"{expected_system} registry fields drifted")
    _require(raw["system"] == expected_system, f"system order/identity drifted: {expected_system}")
    _require(raw["projection_kind"] in PROJECTION_KINDS, f"projection kind is invalid: {expected_system}")
    _require(_REPOSITORY.fullmatch(str(raw["repository"])) is not None, f"repository is invalid: {expected_system}")
    _require(_IMAGE_REFERENCE.fullmatch(str(raw["final_reference"])) is not None, f"final reference is invalid: {expected_system}")
    deterministic = raw["deterministic_references"]
    _require(
        type(deterministic) is list
        and deterministic == [str(raw["final_reference"]) + "-determinism-a", str(raw["final_reference"]) + "-determinism-b"],
        f"deterministic reference pair drifted: {expected_system}",
    )
    _require(
        type(raw["created"]) is str
        and re.fullmatch(r"(?:1970-01-01T00:00:00Z|2024-08-01T00:00:00Z)", raw["created"]) is not None,
        f"Created identity is invalid: {expected_system}",
    )
    _require(raw["user"] in {"root", "dlstreamer"}, f"image user is invalid: {expected_system}")
    _require(
        type(raw["entrypoint"]) is list
        and len(raw["entrypoint"]) == 1
        and type(raw["entrypoint"][0]) is str
        and raw["entrypoint"][0].startswith("/"),
        f"entrypoint is invalid: {expected_system}",
    )
    _require(
        type(raw["smoke_args"]) is list
        and bool(raw["smoke_args"])
        and all(type(value) is str and value and "\x00" not in value for value in raw["smoke_args"]),
        f"smoke arguments are invalid: {expected_system}",
    )
    for field in ("source_allowlist", "dependency_allowlist", "dockerfile"):
        _canonical_relative(raw[field])
        _physical_file(root, raw[field])
    sources = _read_allowlist(root, raw["source_allowlist"])
    dependencies = _read_allowlist(root, raw["dependency_allowlist"])
    _require(not set(sources).intersection(dependencies), f"source/dependency overlap: {expected_system}")
    dockerfile_source = _physical_file(root, raw["dockerfile"]).read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_SOURCE_TOKENS:
        _require(token not in dockerfile_source, f"Dockerfile has network/package behavior: {expected_system}: {token.strip()}")
    base = _validate_base(raw["base"], allow_remote=True)
    native_builder = raw["native_builder"]
    if native_builder is not None:
        native_builder = _validate_base(native_builder, allow_remote=False)
    _require((expected_system == "savant") == (native_builder is not None), "only Savant may have a native builder")
    native_prefix = raw["native_source_prefix"]
    _require(
        native_prefix is None
        or (
            type(native_prefix) is str
            and native_prefix.endswith("/")
            and _canonical_relative(native_prefix[:-1]) == native_prefix[:-1]
        ),
        f"native source prefix is invalid: {expected_system}",
    )
    required_labels = raw["required_labels"]
    _require(
        type(required_labels) is dict
        and required_labels
        and list(required_labels) == sorted(required_labels)
        and all(
            type(key) is str
            and key.startswith("org.")
            and type(value) is str
            and bool(value)
            and (not value.startswith("$") or _TEMPLATE.fullmatch(value) is not None)
            for key, value in required_labels.items()
        ),
        f"required label contract is invalid: {expected_system}",
    )
    projection_keys = raw["projection_label_keys"]
    _require(
        type(projection_keys) is list
        and projection_keys == sorted(set(projection_keys))
        and set(projection_keys).issubset(required_labels),
        f"projection label set is invalid: {expected_system}",
    )
    embedded_paths = raw["embedded_paths"]
    _require(
        type(embedded_paths) is list
        and embedded_paths == list(dict.fromkeys(embedded_paths))
        and all(type(value) is str and value.startswith("/") and "\x00" not in value for value in embedded_paths),
        f"embedded path set is invalid: {expected_system}",
    )
    aliases = raw["embedded_aliases"]
    _require(
        type(aliases) is dict
        and aliases
        and list(aliases) == sorted(aliases)
        and all(type(key) is str and value in embedded_paths for key, value in aliases.items()),
        f"embedded aliases are invalid: {expected_system}",
    )
    result = dict(raw)
    result["base"] = base
    result["native_builder"] = native_builder
    return result


def load_refreeze_registry(*, project_root: Path, registry_path: Path) -> dict[str, Any]:
    root = _root(project_root)
    path, value = _load_json_file(
        root, registry_path, exact_relative=REGISTRY_RELATIVE_PATH,
    )
    _require(
        set(value) == {"artifact_kind", "build_registry", "schema_version", "systems"}
        and value.get("schema_version") == 1
        and value.get("artifact_kind") == REGISTRY_KIND
        and value.get("build_registry") == BUILD_REGISTRY_RELATIVE_PATH
        and type(value.get("systems")) is list
        and len(value["systems"]) == len(SYSTEMS),
        "qualification image refreeze registry envelope drifted",
    )
    build_registry = _physical_file(root, value["build_registry"], exact_relative=BUILD_REGISTRY_RELATIVE_PATH)
    systems = tuple(
        _validate_system(root, raw, expected)
        for raw, expected in zip(value["systems"], SYSTEMS, strict=True)
    )
    _require(
        tuple(row["projection_kind"] for row in systems) == PROJECTION_KINDS,
        "qualification image projection order drifted",
    )
    return {
        "schema_version": 1,
        "artifact_kind": REGISTRY_KIND,
        "build_registry": BUILD_REGISTRY_RELATIVE_PATH,
        "build_registry_sha256": _file_sha256(build_registry),
        "systems": systems,
        "registry_sha256": _file_sha256(path),
    }


def _source_identity(root: Path, system: Mapping[str, Any]) -> dict[str, Any]:
    source_allowlist = str(system["source_allowlist"])
    dependency_allowlist = str(system["dependency_allowlist"])
    sources = _read_allowlist(root, source_allowlist)
    dependencies = _read_allowlist(root, dependency_allowlist)
    native_prefix = system["native_source_prefix"]
    native_sources = tuple(
        row for row in sources
        if type(native_prefix) is str and row.startswith(native_prefix)
    )
    return {
        "runtime_source_sha256": _set_sha256(root, sources),
        "runtime_source_count": len(sources),
        "dependency_set_sha256": _set_sha256(root, dependencies),
        "dependency_count": len(dependencies),
        "source_allowlist_sha256": _file_sha256(_physical_file(root, source_allowlist)),
        "source_allowlist": _fragment_descriptor(root, source_allowlist),
        "native_source_sha256": _set_sha256(root, native_sources) if native_sources else None,
        "native_source_count": len(native_sources),
    }


def qualification_image_refreeze_plan(*, project_root: Path, registry_path: Path) -> dict[str, Any]:
    root = _root(project_root)
    registry = load_refreeze_registry(project_root=root, registry_path=registry_path)
    rows = []
    for system in registry["systems"]:
        rows.append({
            "system": system["system"],
            "final_reference": system["final_reference"],
            "deterministic_references": list(system["deterministic_references"]),
            "base": system["base"],
            "native_builder": system["native_builder"],
            **_source_identity(root, system),
        })
    return {
        "schema_version": 1,
        "artifact_kind": PLAN_KIND,
        "build_registry_sha256": registry["build_registry_sha256"],
        "refreeze_registry_sha256": registry["registry_sha256"],
        "systems": rows,
    }


def _runtime_capture_references(
    system: Mapping[str, Any], candidate_final_reference: str | None,
) -> tuple[str, tuple[str, str]]:
    canonical = (
        str(system["final_reference"]),
        *tuple(str(value) for value in system["deterministic_references"]),
    )
    if candidate_final_reference is None:
        return canonical[0], (canonical[1], canonical[2])
    _require(
        type(candidate_final_reference) is str
        and _IMAGE_REFERENCE.fullmatch(candidate_final_reference) is not None,
        "candidate final runtime reference is invalid",
    )
    _require(
        candidate_final_reference.startswith(str(system["repository"]) + ":"),
        "candidate final runtime reference must use the system repository",
    )
    candidate = (
        candidate_final_reference,
        candidate_final_reference + "-determinism-a",
        candidate_final_reference + "-determinism-b",
    )
    _require(
        len(set(candidate)) == 3 and set(candidate).isdisjoint(canonical),
        "candidate runtime references overlap canonical runtime references",
    )
    return candidate[0], (candidate[1], candidate[2])


def _load_build_module():
    path = Path(__file__).resolve().with_name("publication_image_build_v1.py")
    spec = importlib.util.spec_from_file_location("publication_image_build_for_qualification_refreeze_v1", path)
    _require(spec is not None and spec.loader is not None, "publication image build module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_build_receipt(root: Path, path: Path, *, group: str, registry_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    physical = _physical_file(root, path)
    try:
        value = _load_build_module().load_publication_image_freeze_receipt(physical)
    except (OSError, ValueError) as error:
        raise QualificationImageRefreezeV1Error(f"invalid {group} image receipt") from error
    _require(
        value.get("artifact_kind") == BUILD_RECEIPT_KIND
        and value.get("group") == group
        and value.get("registry_path") == BUILD_REGISTRY_RELATIVE_PATH
        and value.get("registry_sha256") == registry_sha256,
        f"{group} image receipt identity drifted",
    )
    descriptor = _descriptor(root, physical)
    descriptor["receipt_sha256"] = value["receipt_sha256"]
    return value, descriptor


def _build_receipt_rows(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    images = value.get("images")
    _require(type(images) is list and bool(images), "publication image receipt rows are missing")
    rows: dict[str, dict[str, Any]] = {}
    for row in images:
        _require(type(row) is dict and type(row.get("name")) is str, "publication image receipt row is invalid")
        name = row["name"]
        _require(name not in rows and _IMAGE_ID.fullmatch(str(row.get("image_id", ""))) is not None, "publication image receipt row identity is invalid")
        rows[name] = row
    return rows


def worker_acceptance_blockers(
    rows: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    expected = (
        ("analytics_worker_openvino", "cpu"),
        ("analytics_worker_tensorrt", "gpu"),
    )
    _require(set(rows) == {name for name, _ in expected}, "analytics worker receipt coverage drifted")
    blockers: list[str] = []
    for name, resource in expected:
        changed = rows[name].get("identity_changed")
        _require(type(changed) is bool, f"analytics worker {resource} identity_changed state is absent")
        if changed:
            blockers.append(
                f"analytics_worker:{resource}_identity_changed_requires_parity_refresh",
            )
    return blockers


def _default_runner(command: Sequence[str]) -> bytes:
    try:
        completed = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise QualificationImageRefreezeV1Error(f"command unavailable or timed out: {command[0]}") from error
    _require(
        completed.returncode == 0
        and len(completed.stdout) <= MAX_COMMAND_BYTES
        and len(completed.stderr) <= MAX_COMMAND_BYTES,
        f"command failed or exceeded capture bound: {' '.join(command[:3])}",
    )
    return completed.stdout


def _run(runner: CommandRunner, command: Sequence[str]) -> bytes:
    value = runner(tuple(command))
    if type(value) is str:
        try:
            raw = value.encode("utf-8")
        except UnicodeError as error:
            raise QualificationImageRefreezeV1Error("command output is not UTF-8") from error
    else:
        _require(type(value) is bytes, "command runner returned an invalid value")
        raw = value
    _require(len(raw) <= MAX_COMMAND_BYTES, "command output exceeded capture bound")
    return raw


def _inspect(runner: CommandRunner, docker: str, reference: str) -> dict[str, Any]:
    raw = _run(runner, (docker, "image", "inspect", reference))
    try:
        values = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationImageRefreezeV1Error(f"Docker inspect is not JSON: {reference}") from error
    _require(type(values) is list and len(values) == 1 and type(values[0]) is dict, f"Docker inspect cardinality drifted: {reference}")
    return values[0]


def _resolve_producer(
    *, producer: str, receipt_rows: Mapping[str, dict[str, Any]],
    overrides: Mapping[str, str] | None, injected_runner: bool,
) -> dict[str, Any]:
    row = receipt_rows.get(producer)
    if row is not None:
        return row
    if overrides is not None and producer in overrides:
        _require(injected_runner, "producer overrides are test-only dependency injection")
        image_id = overrides[producer]
        _require(_IMAGE_ID.fullmatch(str(image_id)) is not None, "producer override image ID is invalid")
        return {
            "name": producer,
            "image_id": image_id,
            "source_set_sha256": None,
            "receipt_sha256": None,
        }
    raise QualificationImageRefreezeV1Error(f"producer image is absent from native freeze receipt: {producer}")


def resolved_expected_labels(
    *, system: Mapping[str, Any], source_identity: Mapping[str, Any],
    base_image_id: str, native_builder: Mapping[str, Any] | None,
) -> dict[str, str]:
    values: dict[str, object] = {
        "base_reference": system["base"]["reference"],
        "base_image_id": base_image_id,
        "runtime_source_sha256": source_identity["runtime_source_sha256"],
        "dependency_set_sha256": source_identity["dependency_set_sha256"],
        "source_allowlist_sha256": source_identity["source_allowlist_sha256"],
        "native_source_sha256": source_identity["native_source_sha256"],
        "native_builder_image_id": None if native_builder is None else native_builder.get("image_id"),
        "native_builder_source_sha256": None if native_builder is None else native_builder.get("source_set_sha256"),
    }
    result: dict[str, str] = {}
    for key, template in system["required_labels"].items():
        if template.startswith("$"):
            field = template[1:]
            value = values.get(field)
            _require(type(value) is str and bool(value), f"label template has no physical value: {template}")
            result[key] = value
        else:
            result[key] = template
    return result


def _repo_digests(value: object) -> list[str]:
    values = [] if value is None else value
    _require(
        type(values) is list
        and len(values) == len(set(values))
        and all(type(item) is str and _REMOTE_DIGEST.fullmatch(item) is not None for item in values),
        "runtime image repository digest set is invalid",
    )
    return sorted(values)


def _image_projection(system: Mapping[str, Any], inspect: Mapping[str, Any]) -> dict[str, Any]:
    config = inspect.get("Config")
    _require(type(config) is dict and type(config.get("Labels")) is dict, "runtime image Config/Labels are missing")
    selected = {
        key: config["Labels"].get(key)
        for key in system["projection_label_keys"]
    }
    kind = system["projection_kind"]
    projection: dict[str, Any] = {
        "Architecture": inspect.get("Architecture"),
        "Config": {
            "Entrypoint": config.get("Entrypoint"),
            "Labels": selected,
        },
        "Id": inspect.get("Id"),
        "Os": inspect.get("Os"),
        "RepoDigests": _repo_digests(inspect.get("RepoDigests")),
    }
    if kind in {"openvino_v3", "gstreamer_v3", "deepstream_v1"}:
        projection["Config"]["User"] = config.get("User")
    if kind in {"gstreamer_v3", "deepstream_v1"}:
        projection["Created"] = inspect.get("Created")
    return projection


def embedded_set_sha256(embedded: Mapping[str, str], paths: Sequence[str]) -> str:
    rows = bytearray()
    _require(set(embedded) == set(paths), "embedded artifact set is not exact")
    for path in paths:
        digest = embedded.get(path)
        _require(type(digest) is str and _SHA.fullmatch(digest) is not None, f"embedded artifact digest is invalid: {path}")
        rows.extend(f"{digest}  {path}\n".encode("ascii"))
    return hashlib.sha256(rows).hexdigest()


def _capture_embedded(
    *, runner: CommandRunner, docker: str, image_id: str, paths: Sequence[str],
) -> dict[str, str]:
    command = (
        docker, "run", "--rm", "--network", "none", "--entrypoint",
        "/usr/bin/sha256sum", image_id, *paths,
    )
    raw = _run(runner, command)
    _require(raw.endswith(b"\n") and b"\r" not in raw, "embedded digest probe is not canonical LF text")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as error:
        raise QualificationImageRefreezeV1Error("embedded digest probe is not ASCII") from error
    _require(len(lines) == len(paths), "embedded digest probe cardinality drifted")
    result: dict[str, str] = {}
    for line, expected_path in zip(lines, paths, strict=True):
        match = re.fullmatch(r"([0-9a-f]{64})  (/[^\x00\r\n]+)", line)
        _require(match is not None and match.group(2) == expected_path, f"embedded digest probe path/order drifted: {expected_path}")
        _require(expected_path not in result, "embedded digest probe duplicated a path")
        result[expected_path] = match.group(1)
    return result


def _source_set_fragment(root: Path, system: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = dict(source["source_allowlist"])
    descriptor["runtime_source_sha256"] = source["runtime_source_sha256"]
    if system["system"] == "openvino_gva":
        descriptor.update({
            "native_source_sha256": source["native_source_sha256"],
            "self_reference_forbidden": True,
        })
    elif system["system"] == "gstreamer_custom":
        validator_relative = str(PurePosixPath(str(system["source_allowlist"])).with_name("validate_runtime_source_closure_v3.py"))
        descriptor.update({
            "validator": _fragment_descriptor(root, validator_relative),
            "native_source_sha256": source["native_source_sha256"],
            "validated_source_count": source["runtime_source_count"],
        })
    return descriptor


def _fragment_identity(
    *, root: Path, system: Mapping[str, Any], inspect: Mapping[str, Any],
    projection_sha256: str, canonical_repository_digest: str,
    base_image_id: str, native_builder: Mapping[str, Any] | None,
    source: Mapping[str, Any], embedded: Mapping[str, str], embedded_sha256: str,
) -> dict[str, Any]:
    name = system["system"]
    image_id = inspect["Id"]
    if name == "deepstream":
        return {
            "image_id": image_id,
            "repository_digest": canonical_repository_digest,
            "base_image_digest": system["base"]["reference"],
            "runtime_source_sha256": source["runtime_source_sha256"],
            "deepstream_version": "7.0.0",
            "entrypoint": system["entrypoint"][0],
        }
    if name == "savant":
        _require(native_builder is not None, "Savant native builder binding is missing")
        return {
            "schema_version": 3,
            "artifact_kind": "vast_savant_runtime_image_materialization_v3",
            "image_id": image_id,
            "repository_digests": _repo_digests(inspect.get("RepoDigests")),
            "inspect_projection_sha256": projection_sha256,
            "entrypoint": list(system["entrypoint"]),
            "architecture": "amd64",
            "os": "linux",
            "savant_version": "0.5.17",
            "deepstream_version": "7.0",
            "base_image_id": base_image_id,
            "native_builder_image_id": native_builder["image_id"],
            "native_builder_source_sha256": native_builder["source_set_sha256"],
            "runtime_source_sha256": source["runtime_source_sha256"],
            "runtime_bundle_sha256": source["dependency_set_sha256"],
            "publication_ready_label": "false",
        }
    source_set = _source_set_fragment(root, system, source)
    if name == "openvino_gva":
        return {
            "image_id": image_id,
            "repository_digest": canonical_repository_digest,
            "inspect_projection_sha256": projection_sha256,
            "base_image_id": base_image_id,
            "runtime_source_sha256": source["runtime_source_sha256"],
            "native_source_sha256": source["native_source_sha256"],
            "dependency_set_sha256": source["dependency_set_sha256"],
            "source_allowlist_sha256": source["source_allowlist_sha256"],
            "embedded_set_sha256": embedded_sha256,
            "entrypoint": list(system["entrypoint"]),
            "publication_ready_label": "false",
            "source_set": source_set,
        }
    _require(name == "gstreamer_custom", "unsupported qualification image system")
    aliases = system["embedded_aliases"]
    return {
        "image_id": image_id,
        "repository_digest": canonical_repository_digest,
        "inspect_projection_sha256": projection_sha256,
        "base_image_id": base_image_id,
        "runtime_source_sha256": source["runtime_source_sha256"],
        "native_probe_source_sha256": source["native_source_sha256"],
        "dependency_set_sha256": source["dependency_set_sha256"],
        "runtime_source_allowlist_sha256": source["source_allowlist_sha256"],
        "embedded_native_probe_sha256": embedded[aliases["native_probe"]],
        "embedded_analytics_terminal_sha256": embedded[aliases["analytics_terminal"]],
        "source_set": source_set,
    }


def _write_exclusive_json(
    root: Path,
    output: Path,
    payload: Mapping[str, Any],
    *,
    _fault_hook: Callable[[str], None] | None = None,
) -> None:
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    try:
        target.parent.resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise QualificationImageRefreezeV1Error("receipt output parent is absent or escapes project_root") from error
    _require(target.parent.is_dir() and not target.parent.is_symlink(), "receipt output parent is unsafe")
    raw = _canonical(payload) + b"\n"
    custody: PhysicalRootCustodyV1 | None = None
    try:
        custody = PhysicalRootCustodyV1.open(
            root, label="qualification image refreeze output root"
        )
        custody.commit_or_adopt_exact_identity(
            target.relative_to(root).as_posix(),
            raw,
            label="qualification image refreeze receipt",
            mode=0o444,
            create_parents=False,
            after_publish_step=_fault_hook,
        )
        custody.verify()
    except PublicationPhysicalIoV1Error as error:
        raise QualificationImageRefreezeV1Error(
            "receipt output atomic commit/adoption failed"
        ) from error
    finally:
        if custody is not None:
            custody.close()


def capture_runtime_image(
    *, project_root: Path, registry_path: Path, system_name: str,
    native_receipt: Path | None, receipt_output: Path, docker: str = "docker",
    candidate_final_reference: str | None = None,
    command_runner: CommandRunner | None = None,
    producer_image_overrides: Mapping[str, str] | None = None,
    base_image_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = _root(project_root)
    registry = load_refreeze_registry(project_root=root, registry_path=registry_path)
    _require(system_name in SYSTEMS, "qualification image system is invalid")
    system = next(row for row in registry["systems"] if row["system"] == system_name)
    final_reference, deterministic_references = _runtime_capture_references(
        system, candidate_final_reference,
    )
    source = _source_identity(root, system)
    runner = _default_runner if command_runner is None else command_runner
    native_rows: dict[str, dict[str, Any]] = {}
    native_descriptor: dict[str, Any] | None = None
    if native_receipt is not None:
        native_value, native_descriptor = _load_build_receipt(
            root, native_receipt, group="native_probe",
            registry_sha256=registry["build_registry_sha256"],
        )
        native_rows = _build_receipt_rows(native_value)

    base = system["base"]
    if base["kind"] == "remote_digest":
        evidence = native_rows.get(base["evidence_producer"])
        if evidence is not None:
            _require(
                evidence.get("base_reference") == base["reference"]
                and _IMAGE_ID.fullmatch(str(evidence.get("base_image_id", "")))
                is not None,
                f"{system_name} remote base evidence drifted",
            )
            base_image_id = evidence["base_image_id"]
        else:
            _require(
                command_runner is not None
                and base_image_overrides is not None
                and set(base_image_overrides).issubset(SYSTEMS)
                and _IMAGE_ID.fullmatch(
                    str(base_image_overrides.get(system_name, "")),
                )
                is not None,
                f"{system_name} remote base requires native freeze evidence",
            )
            base_image_id = base_image_overrides[system_name]
        base_binding: dict[str, Any] = {
            "kind": "remote_digest",
            "reference": base["reference"],
            "image_id": base_image_id,
            "evidence_producer": base["evidence_producer"],
            "producer_receipt_sha256": (
                None
                if native_descriptor is None
                else native_descriptor["receipt_sha256"]
            ),
        }
    else:
        producer = _resolve_producer(
            producer=base["producer"], receipt_rows=native_rows,
            overrides=producer_image_overrides,
            injected_runner=command_runner is not None,
        )
        base_image_id = producer["image_id"]
        base_binding = {
            "kind": "produced_image",
            "producer": base["producer"],
            "reference": base["reference"],
            "image_id": base_image_id,
            "producer_receipt_sha256": None if native_descriptor is None else native_descriptor["receipt_sha256"],
        }
    observed_base = _inspect(runner, docker, base["reference"])
    _require(observed_base.get("Id") == base_image_id, f"{system_name} physical base image ID drifted")
    if base["kind"] == "remote_digest":
        _require(base["reference"] in _repo_digests(observed_base.get("RepoDigests")), f"{system_name} pinned base RepoDigest is not physically present")

    native_builder: dict[str, Any] | None = None
    if system["native_builder"] is not None:
        builder_spec = system["native_builder"]
        producer = _resolve_producer(
            producer=builder_spec["producer"], receipt_rows=native_rows,
            overrides=producer_image_overrides,
            injected_runner=command_runner is not None,
        )
        _require(_SHA.fullmatch(str(producer.get("source_set_sha256", ""))) is not None, "native builder source identity is absent")
        native_builder = {
            "producer": builder_spec["producer"],
            "reference": builder_spec["reference"],
            "image_id": producer["image_id"],
            "source_set_sha256": producer["source_set_sha256"],
            "producer_receipt_sha256": None if native_descriptor is None else native_descriptor["receipt_sha256"],
        }
        observed_builder = _inspect(runner, docker, builder_spec["reference"])
        _require(observed_builder.get("Id") == producer["image_id"], "Savant physical native-builder image ID drifted")

    inspections = {
        reference: _inspect(runner, docker, reference)
        for reference in (
            final_reference, *deterministic_references,
        )
    }
    ids = [inspections[reference].get("Id") for reference in deterministic_references]
    _require(ids[0] == ids[1], f"deterministic runtime image IDs differ: {ids[0]} != {ids[1]}")
    final = inspections[final_reference]
    _require(final.get("Id") == ids[0], "final runtime image tag differs from deterministic pair")
    image_id = final.get("Id")
    _require(_IMAGE_ID.fullmatch(str(image_id)) is not None, "runtime image ID is invalid")
    expected_labels = resolved_expected_labels(
        system=system, source_identity=source,
        base_image_id=base_image_id, native_builder=native_builder,
    )
    expected_projection: bytes | None = None
    for reference, inspect in inspections.items():
        config = inspect.get("Config")
        _require(
            inspect.get("Id") == image_id
            and inspect.get("Architecture") == "amd64"
            and inspect.get("Os") == "linux"
            and inspect.get("Created") == system["created"]
            and type(config) is dict
            and config.get("Entrypoint") == system["entrypoint"],
            f"runtime image platform/Created/entrypoint drifted: {reference}",
        )
        observed_user = config.get("User") or "root"
        _require(observed_user == system["user"], f"runtime image user drifted: {reference}")
        labels = config.get("Labels")
        _require(
            type(labels) is dict
            and all(labels.get(key) == value for key, value in expected_labels.items()),
            f"runtime image labels drifted: {reference}",
        )
        projection = _canonical(_image_projection(system, inspect))
        if expected_projection is None:
            expected_projection = projection
        _require(projection == expected_projection, "runtime image inspect projections differ across A/B/final")
    _require(expected_projection is not None, "runtime image projection is absent")
    projection_sha = hashlib.sha256(expected_projection).hexdigest()
    repository_digests = _repo_digests(final.get("RepoDigests"))
    canonical_repository_digest = system["repository"] + "@" + image_id
    canonical_observed = canonical_repository_digest in repository_digests

    embedded = _capture_embedded(
        runner=runner, docker=docker, image_id=image_id,
        paths=system["embedded_paths"],
    )
    embedded_sha = embedded_set_sha256(embedded, system["embedded_paths"])
    _run(
        runner,
        (docker, "run", "--rm", "--network", "none", image_id, *system["smoke_args"]),
    )
    _require(_source_identity(root, system) == source, "workspace image inputs changed during capture")
    fragment = _fragment_identity(
        root=root, system=system, inspect=final,
        projection_sha256=projection_sha,
        canonical_repository_digest=canonical_repository_digest,
        base_image_id=base_image_id, native_builder=native_builder,
        source=source, embedded=embedded, embedded_sha256=embedded_sha,
    )
    blockers = [] if canonical_observed else ["canonical_repository_digest_not_observed"]
    physical = {
        "final_reference": final_reference,
        "deterministic_references": list(deterministic_references),
        "image_id": image_id,
        "observed_repository_digests": repository_digests,
        "canonical_repository_digest": canonical_repository_digest,
        "canonical_repository_digest_observed": canonical_observed,
        "inspect_projection_sha256": projection_sha,
        "inspect_full_sha256": hashlib.sha256(_canonical(final)).hexdigest(),
        "architecture": "amd64",
        "os": "linux",
        "created": system["created"],
        "entrypoint": list(system["entrypoint"]),
        "user": system["user"],
        "labels": expected_labels,
        "base": base_binding,
        "native_builder": native_builder,
        "native_receipt": native_descriptor,
        "source_identity": source,
        "embedded_files": {key: embedded[key] for key in system["embedded_paths"]},
        "embedded_aliases": {
            key: {"path": path, "sha256": embedded[path]}
            for key, path in system["embedded_aliases"].items()
        },
        "embedded_set_sha256": embedded_sha,
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": RUNTIME_RECEIPT_KIND,
        "system": system_name,
        "build_registry_sha256": registry["build_registry_sha256"],
        "refreeze_registry_sha256": registry["registry_sha256"],
        "candidate_binding_eligible": not blockers,
        "blockers": blockers,
        "fragment_identity": fragment,
        "physical_identity": physical,
    }
    receipt["receipt_sha256"] = self_sha256(receipt, "receipt_sha256")
    _write_exclusive_json(root, receipt_output, receipt)
    return receipt


def load_runtime_image_receipt(path: Path) -> dict[str, Any]:
    receipt_path = Path(path)
    try:
        info = receipt_path.lstat()
        raw = receipt_path.read_bytes()
    except OSError as error:
        raise QualificationImageRefreezeV1Error("runtime image receipt is absent") from error
    _require(
        stat.S_ISREG(info.st_mode)
        and not receipt_path.is_symlink()
        and int(info.st_nlink) == 1,
        "runtime image receipt must be a physical single-link file",
    )
    _require(raw.endswith(b"\n") and b"\r" not in raw, "runtime image receipt is not canonical LF JSON")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationImageRefreezeV1Error("runtime image receipt is invalid JSON") from error
    fields = {
        "schema_version", "artifact_kind", "system", "build_registry_sha256",
        "refreeze_registry_sha256", "candidate_binding_eligible", "blockers",
        "fragment_identity", "physical_identity", "receipt_sha256",
    }
    _require(type(value) is dict and set(value) == fields, "runtime image receipt fields drifted")
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind") == RUNTIME_RECEIPT_KIND
        and value.get("system") in SYSTEMS
        and _SHA.fullmatch(str(value.get("build_registry_sha256", ""))) is not None
        and _SHA.fullmatch(str(value.get("refreeze_registry_sha256", ""))) is not None
        and type(value.get("candidate_binding_eligible")) is bool
        and type(value.get("blockers")) is list
        and all(type(item) is str and bool(item) for item in value["blockers"])
        and type(value.get("fragment_identity")) is dict
        and type(value.get("physical_identity")) is dict,
        "runtime image receipt envelope drifted",
    )
    _require(
        type(value.get("receipt_sha256")) is str
        and value["receipt_sha256"] == self_sha256(value, "receipt_sha256"),
        "runtime image receipt self-identity drifted",
    )
    physical = value["physical_identity"]
    physical_fields = {
        "final_reference", "deterministic_references", "image_id",
        "observed_repository_digests", "canonical_repository_digest",
        "canonical_repository_digest_observed", "inspect_projection_sha256",
        "inspect_full_sha256", "architecture", "os", "created", "entrypoint",
        "user", "labels", "base", "native_builder", "native_receipt",
        "source_identity", "embedded_files", "embedded_aliases",
        "embedded_set_sha256",
    }
    _require(set(physical) == physical_fields, "runtime image receipt physical identity drifted")
    image_id = str(physical.get("image_id", ""))
    final_reference = physical.get("final_reference")
    deterministic = physical.get("deterministic_references")
    repositories = physical.get("observed_repository_digests")
    canonical_repository = physical.get("canonical_repository_digest")
    canonical_observed = physical.get("canonical_repository_digest_observed")
    _require(
        _IMAGE_ID.fullmatch(image_id) is not None
        and type(final_reference) is str
        and _IMAGE_REFERENCE.fullmatch(final_reference) is not None
        and deterministic == [
            final_reference + "-determinism-a",
            final_reference + "-determinism-b",
        ]
        and type(repositories) is list
        and repositories == sorted(set(repositories))
        and all(type(item) is str and _REMOTE_DIGEST.fullmatch(item) is not None for item in repositories)
        and type(canonical_repository) is str
        and _REMOTE_DIGEST.fullmatch(canonical_repository) is not None
        and canonical_repository.endswith(image_id)
        and type(canonical_observed) is bool
        and canonical_observed == (canonical_repository in repositories)
        and _SHA.fullmatch(str(physical.get("inspect_projection_sha256", ""))) is not None
        and _SHA.fullmatch(str(physical.get("inspect_full_sha256", ""))) is not None
        and physical.get("architecture") == "amd64"
        and physical.get("os") == "linux"
        and type(physical.get("created")) is str
        and type(physical.get("entrypoint")) is list
        and len(physical["entrypoint"]) == 1
        and type(physical["entrypoint"][0]) is str
        and physical["entrypoint"][0].startswith("/")
        and physical.get("user") in {"root", "dlstreamer"}
        and type(physical.get("labels")) is dict
        and all(type(key) is str and type(item) is str for key, item in physical["labels"].items())
        and type(physical.get("base")) is dict
        and _IMAGE_ID.fullmatch(str(physical["base"].get("image_id", ""))) is not None,
        "runtime image receipt physical identity drifted",
    )
    expected_blockers = [] if canonical_observed else ["canonical_repository_digest_not_observed"]
    _require(
        value["blockers"] == expected_blockers
        and value["candidate_binding_eligible"] is (not expected_blockers),
        "runtime image receipt candidate-binding state drifted",
    )
    source = physical.get("source_identity")
    source_fields = {
        "runtime_source_sha256", "runtime_source_count",
        "dependency_set_sha256", "dependency_count",
        "source_allowlist_sha256", "source_allowlist",
        "native_source_sha256", "native_source_count",
    }
    _require(
        type(source) is dict
        and set(source) == source_fields
        and _SHA.fullmatch(str(source.get("runtime_source_sha256", ""))) is not None
        and type(source.get("runtime_source_count")) is int
        and source["runtime_source_count"] > 0
        and _SHA.fullmatch(str(source.get("dependency_set_sha256", ""))) is not None
        and type(source.get("dependency_count")) is int
        and source["dependency_count"] > 0
        and _SHA.fullmatch(str(source.get("source_allowlist_sha256", ""))) is not None
        and type(source.get("source_allowlist")) is dict
        and set(source["source_allowlist"]) == {"path", "size", "sha256"}
        and _SHA.fullmatch(str(source["source_allowlist"].get("sha256", ""))) is not None
        and source["source_allowlist"]["sha256"] == source["source_allowlist_sha256"]
        and type(source.get("native_source_count")) is int
        and source["native_source_count"] >= 0
        and (
            (source["native_source_count"] == 0 and source.get("native_source_sha256") is None)
            or (
                source["native_source_count"] > 0
                and _SHA.fullmatch(str(source.get("native_source_sha256", ""))) is not None
            )
        ),
        "runtime image receipt source identity drifted",
    )
    embedded = physical.get("embedded_files")
    aliases = physical.get("embedded_aliases")
    _require(
        type(embedded) is dict
        and bool(embedded)
        and all(
            type(path) is str and path.startswith("/")
            and type(digest) is str and _SHA.fullmatch(digest) is not None
            for path, digest in embedded.items()
        )
        and type(aliases) is dict
        and bool(aliases)
        and all(
            type(alias) is str
            and type(binding) is dict
            and set(binding) == {"path", "sha256"}
            and binding.get("path") in embedded
            and binding.get("sha256") == embedded[binding["path"]]
            for alias, binding in aliases.items()
        )
        and _SHA.fullmatch(str(physical.get("embedded_set_sha256", ""))) is not None,
        "runtime image receipt embedded identity drifted",
    )
    fragment = value["fragment_identity"]
    _require(fragment.get("image_id") == image_id, "runtime image receipt fragment/physical image ID drifted")
    if "inspect_projection_sha256" in fragment:
        _require(
            fragment["inspect_projection_sha256"] == physical["inspect_projection_sha256"],
            "runtime image receipt fragment/physical projection drifted",
        )
    if "repository_digest" in fragment:
        _require(
            fragment["repository_digest"] == canonical_repository,
            "runtime image receipt fragment/physical repository drifted",
        )
    if "repository_digests" in fragment:
        _require(
            fragment["repository_digests"] == repositories,
            "runtime image receipt fragment/physical repository set drifted",
        )
    return value


def _receipt_mapping(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        _require(separator == "=" and name in SYSTEMS and raw_path, "runtime receipt argument must be SYSTEM=PATH")
        _require(name not in result, f"runtime receipt argument duplicated: {name}")
        result[name] = Path(raw_path)
    _require(tuple(result) == SYSTEMS, "runtime receipt arguments must follow exact four-system order")
    return result


def assemble_identity_patch(
    *, project_root: Path, registry_path: Path, native_receipt: Path,
    worker_receipt: Path, runtime_receipts: Mapping[str, Path], output: Path,
) -> dict[str, Any]:
    root = _root(project_root)
    registry = load_refreeze_registry(project_root=root, registry_path=registry_path)
    native, native_descriptor = _load_build_receipt(
        root, native_receipt, group="native_probe",
        registry_sha256=registry["build_registry_sha256"],
    )
    workers, worker_descriptor = _load_build_receipt(
        root, worker_receipt, group="analytics_worker",
        registry_sha256=registry["build_registry_sha256"],
    )
    native_rows = _build_receipt_rows(native)
    worker_rows = _build_receipt_rows(workers)
    _require(set(native_rows) == {"native_probe_deepstream", "native_probe_openvino", "native_probe_savant"}, "native image receipt coverage drifted")
    _require(set(worker_rows) == {"analytics_worker_openvino", "analytics_worker_tensorrt"}, "worker image receipt coverage drifted")
    _require(
        worker_rows["analytics_worker_openvino"].get("base_image_id") == native_rows["native_probe_openvino"].get("image_id")
        and worker_rows["analytics_worker_tensorrt"].get("base_image_id") == native_rows["native_probe_deepstream"].get("image_id"),
        "analytics worker/native-probe producer binding drifted",
    )
    _require(set(runtime_receipts) == set(SYSTEMS), "runtime image receipt coverage drifted")
    runtime_values: dict[str, dict[str, Any]] = {}
    runtime_descriptors: dict[str, dict[str, Any]] = {}
    blockers = worker_acceptance_blockers(worker_rows)
    for system in SYSTEMS:
        path = _physical_file(root, runtime_receipts[system])
        receipt = load_runtime_image_receipt(path)
        _require(
            receipt["system"] == system
            and receipt["build_registry_sha256"] == registry["build_registry_sha256"]
            and receipt["refreeze_registry_sha256"] == registry["registry_sha256"],
            f"runtime image receipt registry/system identity drifted: {system}",
        )
        runtime_values[system] = receipt
        descriptor = _descriptor(root, path)
        descriptor["receipt_sha256"] = receipt["receipt_sha256"]
        runtime_descriptors[system] = descriptor
        blockers.extend(f"{system}:{item}" for item in receipt["blockers"])
    patch: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": PATCH_KIND,
        "authority": "derived_physical_evidence_only",
        "build_registry": {
            **_descriptor(root, _physical_file(root, BUILD_REGISTRY_RELATIVE_PATH)),
            "registry_sha256": registry["build_registry_sha256"],
        },
        "refreeze_registry": {
            **_descriptor(root, _physical_file(root, REGISTRY_RELATIVE_PATH)),
            "registry_sha256": registry["registry_sha256"],
        },
        "receipts": {
            "native_probe": native_descriptor,
            "analytics_worker": worker_descriptor,
            "runtime_images": runtime_descriptors,
        },
        "workers": {
            "cpu": dict(worker_rows["analytics_worker_openvino"]),
            "gpu": dict(worker_rows["analytics_worker_tensorrt"]),
        },
        "systems": {
            system: {
                "fragment_identity": runtime_values[system]["fragment_identity"],
                "physical_identity": runtime_values[system]["physical_identity"],
            }
            for system in SYSTEMS
        },
        "candidate_binding_requirements": {
            "patch_supersedes_acceptance": False,
            "requires_bootstrap_descriptor_binding": True,
            "requires_candidate_resource_binding_equality": True,
            "requires_live_docker_inspect_equality": True,
        },
        "candidate_binding_eligible": not blockers,
        "blockers": blockers,
    }
    patch["patch_sha256"] = self_sha256(patch, "patch_sha256")
    _write_exclusive_json(root, output, patch)
    return patch


def load_identity_patch(
    *, project_root: Path, patch_path: Path,
    require_candidate_eligible: bool = False,
) -> dict[str, Any]:
    root = _root(project_root)
    path, value = _load_json_file(root, patch_path)
    fields = {
        "schema_version", "artifact_kind", "authority", "build_registry",
        "refreeze_registry", "receipts", "workers", "systems",
        "candidate_binding_requirements", "candidate_binding_eligible",
        "blockers", "patch_sha256",
    }
    _require(type(value) is dict and set(value) == fields, "qualification identity patch fields drifted")
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind") == PATCH_KIND
        and value.get("authority") == "derived_physical_evidence_only"
        and value.get("patch_sha256") == self_sha256(value, "patch_sha256")
        and type(value.get("candidate_binding_eligible")) is bool
        and type(value.get("blockers")) is list
        and type(value.get("workers")) is dict
        and set(value["workers"]) == {"cpu", "gpu"}
        and type(value.get("systems")) is dict
        and set(value["systems"]) == set(SYSTEMS),
        "qualification identity patch envelope/self-identity drifted",
    )
    requirements = value.get("candidate_binding_requirements")
    _require(
        requirements == {
            "patch_supersedes_acceptance": False,
            "requires_bootstrap_descriptor_binding": True,
            "requires_candidate_resource_binding_equality": True,
            "requires_live_docker_inspect_equality": True,
        },
        "qualification identity patch authority boundary drifted",
    )
    descriptors = [value["build_registry"], value["refreeze_registry"]]
    receipts = value.get("receipts")
    _require(type(receipts) is dict and set(receipts) == {"native_probe", "analytics_worker", "runtime_images"}, "qualification identity patch receipt set drifted")
    descriptors.extend((receipts["native_probe"], receipts["analytics_worker"]))
    runtime_descriptors = receipts["runtime_images"]
    _require(type(runtime_descriptors) is dict and set(runtime_descriptors) == set(SYSTEMS), "qualification identity patch runtime receipt set drifted")
    descriptors.extend(runtime_descriptors[system] for system in SYSTEMS)
    for descriptor in descriptors:
        _require(type(descriptor) is dict and type(descriptor.get("path")) is str, "qualification identity patch descriptor is invalid")
        observed = _descriptor(root, _physical_file(root, descriptor["path"]))
        _require(
            all(descriptor.get(key) == observed[key] for key in ("path", "size_bytes", "sha256")),
            f"qualification identity patch descriptor drifted: {descriptor.get('path')}",
        )
    registry = load_refreeze_registry(
        project_root=root,
        registry_path=root / REGISTRY_RELATIVE_PATH,
    )
    _require(
        value["build_registry"].get("registry_sha256")
        == registry["build_registry_sha256"]
        and value["refreeze_registry"].get("registry_sha256")
        == registry["registry_sha256"],
        "qualification identity patch registry binding drifted",
    )
    native, native_descriptor = _load_build_receipt(
        root,
        _physical_file(root, receipts["native_probe"]["path"]),
        group="native_probe",
        registry_sha256=registry["build_registry_sha256"],
    )
    workers, worker_descriptor = _load_build_receipt(
        root,
        _physical_file(root, receipts["analytics_worker"]["path"]),
        group="analytics_worker",
        registry_sha256=registry["build_registry_sha256"],
    )
    _require(
        receipts["native_probe"].get("receipt_sha256")
        == native_descriptor["receipt_sha256"]
        and receipts["analytics_worker"].get("receipt_sha256")
        == worker_descriptor["receipt_sha256"],
        "qualification identity patch build receipt self-binding drifted",
    )
    worker_rows = _build_receipt_rows(workers)
    _require(
        value["workers"] == {
            "cpu": worker_rows.get("analytics_worker_openvino"),
            "gpu": worker_rows.get("analytics_worker_tensorrt"),
        },
        "qualification identity patch worker projection drifted",
    )
    native_rows = _build_receipt_rows(native)
    _require(
        worker_rows["analytics_worker_openvino"].get("base_image_id")
        == native_rows.get("native_probe_openvino", {}).get("image_id")
        and worker_rows["analytics_worker_tensorrt"].get("base_image_id")
        == native_rows.get("native_probe_deepstream", {}).get("image_id"),
        "qualification identity patch worker producer binding drifted",
    )
    expected_blockers = worker_acceptance_blockers(worker_rows)
    for system in SYSTEMS:
        receipt = load_runtime_image_receipt(
            _physical_file(root, runtime_descriptors[system]["path"]),
        )
        _require(
            receipt["system"] == system
            and receipt["build_registry_sha256"]
            == registry["build_registry_sha256"]
            and receipt["refreeze_registry_sha256"]
            == registry["registry_sha256"]
            and runtime_descriptors[system].get("receipt_sha256")
            == receipt["receipt_sha256"]
            and value["systems"][system]
            == {
                "fragment_identity": receipt["fragment_identity"],
                "physical_identity": receipt["physical_identity"],
            },
            f"qualification identity patch runtime projection drifted: {system}",
        )
        expected_blockers.extend(
            f"{system}:{item}" for item in receipt["blockers"]
        )
    _require(
        value["blockers"] == expected_blockers
        and value["candidate_binding_eligible"] is (not expected_blockers),
        "qualification identity patch candidate-binding state drifted",
    )
    if require_candidate_eligible:
        _require(value["candidate_binding_eligible"] is True and value["blockers"] == [], "qualification identity patch is not candidate-binding eligible")
    _require(_descriptor(root, path)["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(), "qualification identity patch changed during verification")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture deterministic qualification image identities")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--project-root", type=Path, required=True)
    plan.add_argument("--registry", type=Path, required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--project-root", type=Path, required=True)
    capture.add_argument("--registry", type=Path, required=True)
    capture.add_argument("--system", choices=SYSTEMS, required=True)
    capture.add_argument("--native-receipt", type=Path)
    capture.add_argument("--receipt-output", type=Path, required=True)
    capture.add_argument("--docker", default="docker")
    capture.add_argument("--candidate-final-reference")
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--project-root", type=Path, required=True)
    assemble.add_argument("--registry", type=Path, required=True)
    assemble.add_argument("--native-receipt", type=Path, required=True)
    assemble.add_argument("--worker-receipt", type=Path, required=True)
    assemble.add_argument("--runtime-receipt", action="append", default=[], required=True)
    assemble.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-patch")
    verify.add_argument("--project-root", type=Path, required=True)
    verify.add_argument("--patch", type=Path, required=True)
    verify.add_argument("--require-candidate-eligible", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = qualification_image_refreeze_plan(
                project_root=args.project_root, registry_path=args.registry,
            )
        elif args.command == "capture":
            result = capture_runtime_image(
                project_root=args.project_root, registry_path=args.registry,
                system_name=args.system, native_receipt=args.native_receipt,
                receipt_output=args.receipt_output, docker=args.docker,
                candidate_final_reference=args.candidate_final_reference,
            )
        elif args.command == "assemble":
            result = assemble_identity_patch(
                project_root=args.project_root, registry_path=args.registry,
                native_receipt=args.native_receipt,
                worker_receipt=args.worker_receipt,
                runtime_receipts=_receipt_mapping(args.runtime_receipt),
                output=args.output,
            )
        else:
            result = load_identity_patch(
                project_root=args.project_root, patch_path=args.patch,
                require_candidate_eligible=args.require_candidate_eligible,
            )
    except (OSError, QualificationImageRefreezeV1Error) as error:
        print(str(error), file=os.sys.stderr)
        return 2
    print(_canonical(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PATCH_KIND", "RUNTIME_RECEIPT_KIND", "QualificationImageRefreezeV1Error",
    "assemble_identity_patch", "capture_runtime_image", "embedded_set_sha256",
    "load_identity_patch", "load_refreeze_registry", "load_runtime_image_receipt",
    "qualification_image_refreeze_plan", "resolved_expected_labels", "self_sha256",
    "worker_acceptance_blockers",
]
