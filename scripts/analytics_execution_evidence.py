#!/usr/bin/env python3
"""Atomic raw tensor and receipt bundles for accepted native inference calls."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from publication_immutable_directory_v1 import (
    JOURNAL_ROOT,
    PublicationImmutableDirectoryV1Error,
    commit_or_adopt_immutable_directory_v1,
)
from publication_owned_staging_cleanup_v1 import (
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
)

from analytics_execution_protocol import (
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    canonical_json_bytes,
    canonical_sha256,
    validate_inference_request,
)
from analytics_execution_worker import (
    validate_inference_response,
    validate_worker_capability,
)


EVIDENCE_KIND = "vast_analytics_execution_evidence_bundle"
_FILENAMES = {
    "request": "request.json",
    "response": "response.json",
    "input_tensor": "input.tensor.bin",
    "output_tensor": "output.tensor.bin",
}


class EvidenceError(RuntimeError):
    """An execution evidence bundle is incomplete, mutated, or unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if is_junction(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except (FileNotFoundError, OSError):
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _stable_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(stat.S_IFMT(metadata.st_mode)),
    )


def _directory_identity(path: Path) -> tuple[int, int, int]:
    return _stable_identity(path.lstat())


def _resolved_ambient_cwd() -> Path | None:
    try:
        return Path.cwd().resolve()
    except FileNotFoundError:
        return None


def _assert_canonical_directory(
    path: Path | str,
    *,
    label: str,
    reject_cwd_or_parent: bool,
) -> Path:
    lexical = _absolute_lexical(path)
    _require(lexical != Path(lexical.anchor), f"{label} must not be a filesystem root")
    if reject_cwd_or_parent:
        cwd = _resolved_ambient_cwd()
        if cwd is not None:
            _require(
                lexical != cwd and lexical not in cwd.parents,
                f"{label} must not be the current directory or its parent",
            )
    _require(
        not _is_reparse_point(lexical),
        f"{label} must not be a symlink, junction, or reparse point",
    )
    _require(lexical.is_dir(), f"{label} is missing or not a directory")
    _require(lexical.resolve() == lexical, f"{label} must not be an alias")
    return lexical


def _guard_staging_directory(
    staging: Path,
    *,
    expected_parent: Path,
    expected_parent_identity: tuple[int, int, int],
    expected_prefix: str,
    expected_identity: tuple[int, int, int] | None = None,
) -> Path:
    parent = _assert_canonical_directory(
        expected_parent,
        label="execution evidence staging parent",
        reject_cwd_or_parent=False,
    )
    _require(
        _directory_identity(parent) == expected_parent_identity,
        "execution evidence staging parent identity changed",
    )
    lexical = _absolute_lexical(staging)
    _require(
        lexical.parent == parent,
        "execution evidence staging path escaped its expected parent",
    )
    _require(
        lexical.name.startswith(expected_prefix) and lexical.name != expected_prefix,
        "execution evidence staging path has an unexpected name",
    )
    cwd = _resolved_ambient_cwd()
    if cwd is not None:
        _require(
            lexical != cwd and lexical not in cwd.parents,
            "execution evidence staging path must not be the current directory or its parent",
        )
    _require(lexical != parent, "execution evidence staging path equals its parent")
    _require(
        not _is_reparse_point(lexical),
        "execution evidence staging path is a symlink, junction, or reparse point",
    )
    _require(lexical.is_dir(), "execution evidence staging path is missing or not a directory")
    _require(
        lexical.resolve() == lexical,
        "execution evidence staging path must not be an alias",
    )
    if expected_identity is not None:
        _require(
            _directory_identity(lexical) == expected_identity,
            "execution evidence staging path identity changed",
        )
    return lexical


def _guard_writer_lock(
    lock_path: Path,
    *,
    expected_parent: Path,
    expected_parent_identity: tuple[int, int, int],
    expected_identity: tuple[int, int, int],
) -> Path | None:
    parent = _assert_canonical_directory(
        expected_parent,
        label="execution evidence lock parent",
        reject_cwd_or_parent=False,
    )
    _require(
        _directory_identity(parent) == expected_parent_identity,
        "execution evidence lock parent identity changed",
    )
    lexical = _absolute_lexical(lock_path)
    _require(
        lexical.parent == parent and lexical.name == ".execution-evidence.lock",
        "execution evidence lock path escaped its expected parent",
    )
    if not lexical.exists() and not lexical.is_symlink():
        return None
    _require(
        not _is_reparse_point(lexical),
        "execution evidence lock is a symlink, junction, or reparse point",
    )
    _require(lexical.is_file(), "execution evidence lock is not a regular file")
    _require(lexical.resolve() == lexical, "execution evidence lock must not be an alias")
    _require(
        _stable_identity(lexical.lstat()) == expected_identity,
        "execution evidence lock identity changed",
    )
    return lexical


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)) | int(getattr(os, "O_CLOEXEC", 0))
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_immutable(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_CLOEXEC", 0))
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            _require(written > 0, f"failed to write execution evidence file: {path.name}")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(0o444)


def _json_payload(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _file_record(name: str, payload: bytes) -> dict[str, Any]:
    return {"path": _FILENAMES[name], "bytes": len(payload), "sha256": _sha256(payload)}


def _validate_inputs(
    *,
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    input_tensor: bytes | bytearray | memoryview,
    output_tensor: bytes | bytearray | memoryview,
    capability: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes, dict[str, Any]]:
    try:
        checked_capability = validate_worker_capability(capability)
        checked_request = validate_inference_request(request)
        checked_response = validate_inference_response(
            response,
            request=checked_request,
            capability=checked_capability,
        )
    except ProtocolError as error:
        raise EvidenceError(f"execution evidence contract is invalid: {error}") from error
    input_bytes = bytes(input_tensor)
    output_bytes = bytes(output_tensor)
    _require(len(input_bytes) == checked_request["tensor"]["byte_length"], "execution evidence input byte length mismatch")
    _require(_sha256(input_bytes) == checked_request["tensor"]["sha256"], "execution evidence input SHA-256 mismatch")
    _require(len(output_bytes) == checked_response["output"]["byte_length"], "execution evidence output byte length mismatch")
    _require(_sha256(output_bytes) == checked_response["output"]["sha256"], "execution evidence output SHA-256 mismatch")
    return checked_request, checked_response, input_bytes, output_bytes, checked_capability


def persist_execution_bundle(
    root: Path | str,
    *,
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    input_tensor: bytes | bytearray | memoryview,
    output_tensor: bytes | bytearray | memoryview,
    capability: Mapping[str, Any],
    project_root: Path | str | None = None,
    after_directory_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    checked_request, checked_response, input_bytes, output_bytes, checked_capability = _validate_inputs(
        request=request,
        response=response,
        input_tensor=input_tensor,
        output_tensor=output_tensor,
        capability=capability,
    )
    lexical_root = _absolute_lexical(root)
    if lexical_root.exists() or lexical_root.is_symlink():
        evidence_root = _assert_canonical_directory(
            lexical_root,
            label="execution evidence root",
            reject_cwd_or_parent=True,
        )
    else:
        lexical_root.mkdir(parents=True, exist_ok=False)
        evidence_root = _assert_canonical_directory(
            lexical_root,
            label="execution evidence root",
            reject_cwd_or_parent=True,
        )
    evidence_root_identity = _directory_identity(evidence_root)
    request_id = checked_request["request_id"]
    _require(
        Path(request_id).name == request_id
        and "/" not in request_id
        and "\\" not in request_id
        and request_id not in {".", ".."},
        "execution evidence request ID is unsafe for a bundle directory",
    )
    target = evidence_root / request_id
    _require(target.parent == evidence_root, "execution evidence target escaped its root")
    lock_path = evidence_root / ".execution-evidence.lock"
    _require(not os.path.lexists(lock_path), "foreign legacy execution evidence writer lock exists")
    temporary: Path | None = None
    cleanup_anchor: OwnedStagingDirectoryV1 | None = None
    publication_root = (
        _assert_canonical_directory(
            _absolute_lexical(project_root),
            label="execution evidence project root",
            reject_cwd_or_parent=False,
        )
        if project_root is not None
        else evidence_root.parent
    )
    target_relative = target.relative_to(publication_root).as_posix()
    target_intent_key = hashlib.sha256(target_relative.encode("utf-8")).hexdigest()
    target_intent = publication_root / JOURNAL_ROOT / f"{target_intent_key}.json"
    _require(
        not os.path.lexists(target) or os.path.lexists(target_intent),
        f"execution evidence bundle already exists or is unsafe: {request_id}",
    )
    try:
        staging_prefix = f".{request_id}."
        created_staging = Path(
            tempfile.mkdtemp(prefix=staging_prefix, dir=evidence_root)
        )
        temporary = _guard_staging_directory(
            created_staging,
            expected_parent=evidence_root,
            expected_parent_identity=evidence_root_identity,
            expected_prefix=staging_prefix,
        )
        try:
            cleanup_anchor = OwnedStagingDirectoryV1.capture(
                temporary,
                expected_parent=evidence_root,
                expected_prefix=staging_prefix,
                label="execution evidence staging",
            )
        except OwnedStagingCleanupV1Error as error:
            raise EvidenceError(str(error)) from error
        request_payload = _json_payload(checked_request)
        response_payload = _json_payload(checked_response)
        payloads = {
            "request": request_payload,
            "response": response_payload,
            "input_tensor": input_bytes,
            "output_tensor": output_bytes,
        }
        files = {name: _file_record(name, payload) for name, payload in payloads.items()}
        manifest_core = {
            "schema_version": 1,
            "artifact_kind": EVIDENCE_KIND,
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "request_id": request_id,
            "run_id": checked_request["run_id"],
            "arm_id": checked_request["arm_id"],
            "worker_id": checked_request["worker_id"],
            "frame": checked_request["frame"],
            "capability_sha256": canonical_sha256(checked_capability),
            "files": files,
        }
        manifest = {
            **manifest_core,
            "identity": {"algorithm": "sha256", "sha256": canonical_sha256(manifest_core)},
        }
        for name, payload in payloads.items():
            _write_immutable(temporary / _FILENAMES[name], payload)
        _write_immutable(temporary / "manifest.json", _json_payload(manifest))
        _fsync_directory(temporary)
        try:
            cleanup_anchor.seal_tree()
        except OwnedStagingCleanupV1Error as error:
            raise EvidenceError(str(error)) from error
        try:
            publication = commit_or_adopt_immutable_directory_v1(
                project_root=publication_root,
                staging=temporary,
                target=target,
                after_publish_step=after_directory_publish_step,
            )
        except PublicationImmutableDirectoryV1Error as error:
            raise EvidenceError(str(error)) from error
        try:
            cleanup_anchor.cleanup_after_publication(final_target=target)
        except OwnedStagingCleanupV1Error as error:
            raise EvidenceError(str(error)) from error
        temporary = None
        checked_target = _assert_canonical_directory(
            target,
            label="execution evidence bundle target",
            reject_cwd_or_parent=True,
        )
        _require(
            checked_target.parent == evidence_root,
            "execution evidence bundle target escaped its root",
        )
        _fsync_directory(evidence_root)
        return manifest
    finally:
        try:
            if temporary is not None:
                relative = target.relative_to(publication_root).as_posix()
                intent_key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
                intent_exists = os.path.lexists(
                    publication_root / JOURNAL_ROOT / f"{intent_key}.json"
                )
                if not intent_exists and cleanup_anchor is not None:
                    try:
                        if not cleanup_anchor.sealed:
                            cleanup_anchor.seal_tree()
                        cleanup_anchor.cleanup_after_publication(final_target=target)
                    except OwnedStagingCleanupV1Error as error:
                        raise EvidenceError(str(error)) from error
        finally:
            if cleanup_anchor is not None:
                cleanup_anchor.close()


def _read_canonical_json(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        _require(payload.endswith(b"\n"), f"execution evidence {path.name} lacks canonical newline")
        value = json.loads(payload.decode("utf-8"))
        _require(isinstance(value, dict), f"execution evidence {path.name} must be a mapping")
        _require(_json_payload(value) == payload, f"execution evidence {path.name} is not canonical JSON")
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"cannot read execution evidence {path.name}: {error}") from error


def verify_execution_bundle(
    bundle: Path | str,
    *,
    capability: Mapping[str, Any],
) -> dict[str, Any]:
    path = _assert_canonical_directory(
        bundle,
        label="execution evidence bundle",
        reject_cwd_or_parent=False,
    )
    manifest = _read_canonical_json(path / "manifest.json")
    expected_fields = {
        "schema_version", "artifact_kind", "protocol_identity_sha256", "request_id",
        "run_id", "arm_id", "worker_id", "frame", "capability_sha256", "files",
        "identity",
    }
    _require(set(manifest) == expected_fields, "execution evidence manifest fields have drifted")
    _require(manifest["schema_version"] == 1 and manifest["artifact_kind"] == EVIDENCE_KIND, "execution evidence manifest header is invalid")
    _require(manifest["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "execution evidence protocol identity mismatch")
    checked_capability = validate_worker_capability(capability)
    _require(manifest["capability_sha256"] == canonical_sha256(checked_capability), "execution evidence capability SHA-256 mismatch")
    files = manifest["files"]
    _require(isinstance(files, Mapping) and set(files) == set(_FILENAMES), "execution evidence file inventory has drifted")
    loaded: dict[str, bytes] = {}
    for name, filename in _FILENAMES.items():
        record = files[name]
        _require(isinstance(record, Mapping) and set(record) == {"path", "bytes", "sha256"}, f"execution evidence {name} record fields have drifted")
        _require(record["path"] == filename, f"execution evidence {name} path mismatch")
        file_path = path / filename
        _require(file_path.is_file() and not file_path.is_symlink(), f"execution evidence {name} file is missing or unsafe")
        payload = file_path.read_bytes()
        _require(record["bytes"] == len(payload), f"execution evidence {name} byte length mismatch")
        _require(record["sha256"] == _sha256(payload), f"execution evidence {name} SHA-256 mismatch")
        loaded[name] = payload
    request = _read_canonical_json(path / _FILENAMES["request"])
    response = _read_canonical_json(path / _FILENAMES["response"])
    checked_request, checked_response, _, _, _ = _validate_inputs(
        request=request,
        response=response,
        input_tensor=loaded["input_tensor"],
        output_tensor=loaded["output_tensor"],
        capability=checked_capability,
    )
    for field in ("request_id", "run_id", "arm_id", "worker_id", "frame"):
        _require(manifest[field] == checked_request[field], f"execution evidence manifest {field} binding mismatch")
    identity = manifest["identity"]
    _require(isinstance(identity, Mapping) and set(identity) == {"algorithm", "sha256"}, "execution evidence identity fields have drifted")
    _require(identity["algorithm"] == "sha256", "execution evidence identity algorithm is invalid")
    core = {key: value for key, value in manifest.items() if key != "identity"}
    _require(identity["sha256"] == canonical_sha256(core), "execution evidence manifest identity mismatch")
    return manifest


__all__ = [
    "EVIDENCE_KIND", "EvidenceError", "persist_execution_bundle",
    "verify_execution_bundle",
]
