#!/usr/bin/env python3
"""Fail-closed WSL systemd-user lifecycle for the full publication supervisor.

Materialization and installation never start the benchmark.  ``start`` first
executes the exact full-publication preflight; the installed unit repeats that
gate after every WSL/user-manager restart and then execs the existing durable
supervisor with the same run root and state path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from publication_immutable_directory_v1 import (
    JOURNAL_KIND as DIRECTORY_JOURNAL_KIND,
    JOURNAL_ROOT as DIRECTORY_JOURNAL_ROOT,
    PublicationImmutableDirectoryV1Error,
    commit_or_adopt_immutable_directory_v1,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_owned_staging_cleanup_v1 import (
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
)


SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 2
EXIT_COMPLETE = 0
EXIT_TRANSIENT = 75
EXIT_PERMANENT = 78
MANIFEST_NAME = "full_publication_wsl_user_service_manifest.v1.json"
UNIT_NAME = "full_publication_wsl_user_service.v1.service"
RECEIPT_NAME = "full_publication_wsl_user_service_materialization.v1.json"
EXTERNAL_UNIT_JOURNAL = ".vast-full-publication-systemd-unit-journal-v1"
PHYSICAL_ATOMIC_STAGING_ROOT = ".publication-atomic-staging-v1"
EXTERNAL_UNIT_INTENT_KIND = "vast_full_publication_systemd_unit_intent_v1"
EXTERNAL_UNIT_RECEIPT_KIND = "vast_full_publication_systemd_unit_receipt_v1"
SYSTEMCTL = "/usr/bin/systemctl"
_PINNED_PYTHON_SOURCE_BOOTSTRAP_BODY_V1 = (
    "import hashlib,os,stat,sys\n"
    "p=sys.argv[1];n=int(sys.argv[2]);h=sys.argv[3]\n"
    "d=os.path.dirname(p);b=os.path.basename(p)\n"
    "df=os.open(d,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0))\n"
    "f=os.open(b,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0),dir_fd=df)\n"
    "s=os.fstat(f);q=b''\n"
    "while True:\n"
    " c=os.read(f,1048576)\n"
    " if not c: break\n"
    " q+=c\n"
    "a=os.fstat(f);z=os.stat(b,dir_fd=df,follow_symlinks=False)\n"
    "assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==n and "
    "(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)=="
    "(a.st_dev,a.st_ino,a.st_mode,a.st_nlink,a.st_size,a.st_mtime_ns,a.st_ctime_ns)=="
    "(z.st_dev,z.st_ino,z.st_mode,z.st_nlink,z.st_size,z.st_mtime_ns,z.st_ctime_ns) "
    "and len(q)==n and hashlib.sha256(q).hexdigest()==h\n"
    "os.close(f);os.close(df);sys.path.insert(0,d);sys.argv=[p,*sys.argv[4:]]\n"
    "g={'__name__':'__main__','__file__':p,'__package__':None,'__cached__':None}\n"
    "exec(compile(q,p,'exec'),g,g)\n"
)
_PINNED_PYTHON_SOURCE_BOOTSTRAP_V1 = (
    f"exec({_PINNED_PYTHON_SOURCE_BOOTSTRAP_BODY_V1!r})"
)
LOGINCTL = "/usr/bin/loginctl"
DOCKER_SOCKET = "/run/docker.sock"
DEFAULT_BACKOFF = (30.0, 60.0, 120.0, 300.0, 600.0, 900.0)
FROZEN_FULL_PUBLICATION_MATRIX_SCHEMA_VERSION = 4
FROZEN_FULL_PUBLICATION_MATRIX_SHA256 = (
    "a1115ea9fa5f496f45d75636b8376366a48413cdc4c9787cb7ca4baac04b230e"
)
FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256 = (
    "4168818527ced4b3611c9aeabff6b04a7962314f4d80beb3da9dc814ba369016"
)
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_ATTEMPT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
_UNIT_RE = re.compile(r"vast-full-publication-[a-z0-9][a-z0-9._-]{0,79}\.service")
_URL_RE = re.compile(r"https://[^\s]+")
_SUPERVISOR_STATE_FIELDS = {
    "schema_version",
    "artifact_kind",
    "command_identity_sha256",
    "phase",
    "attempt_seq",
    "transient_streak",
    "unexpected_streak",
    "last_exit_code",
    "last_artifact_kind",
    "last_payload_sha256",
    "updated_at",
    "completed_at",
}


class ServiceContractError(RuntimeError):
    """The persistent service contract is invalid or has drifted."""


@dataclass(frozen=True)
class ValidatedBundleV1:
    receipt_path: Path
    manifest_path: Path
    unit_path: Path
    receipt: dict[str, Any]
    manifest: dict[str, Any]
    unit_bytes: bytes


CommandRunner = Callable[..., Any]
PhysicalFaultHook = Callable[[str, Path], None]


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ServiceContractError(f"value is not canonical JSON: {error}") from error


def _semantic_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path))))


def _exact_existing_file(path: Path | str, *, label: str) -> Path:
    lexical = _lexical_absolute(path)
    if lexical.is_symlink():
        raise ServiceContractError(f"{label} must not be a symlink")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise ServiceContractError(f"{label} is missing: {lexical}") from error
    if resolved != lexical:
        raise ServiceContractError(f"{label} path is a symlink or alias")
    try:
        mode = resolved.stat().st_mode
    except OSError as error:
        raise ServiceContractError(f"{label} cannot be inspected") from error
    if not stat.S_ISREG(mode):
        raise ServiceContractError(f"{label} is not a regular file")
    return resolved


def _exact_existing_directory(path: Path | str, *, label: str) -> Path:
    lexical = _lexical_absolute(path)
    if lexical.is_symlink():
        raise ServiceContractError(f"{label} must not be a symlink")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise ServiceContractError(f"{label} is missing: {lexical}") from error
    if resolved != lexical or not resolved.is_dir():
        raise ServiceContractError(f"{label} is not an exact regular directory")
    return resolved


def _stable_file_descriptor(path: Path | str, *, label: str) -> dict[str, Any]:
    exact = _exact_existing_file(path, label=label)
    before = exact.stat()
    digest = _file_sha256(exact)
    after = exact.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
    ):
        raise ServiceContractError(f"{label} changed while hashing")
    return {
        "path": str(exact),
        "size_bytes": int(after.st_size),
        "sha256": digest,
    }


def _validate_descriptor(value: Any, *, label: str) -> Path:
    if type(value) is not dict or set(value) != {"path", "size_bytes", "sha256"}:
        raise ServiceContractError(f"{label} descriptor is invalid")
    if type(value["path"]) is not str or not value["path"]:
        raise ServiceContractError(f"{label} descriptor path is invalid")
    if type(value["size_bytes"]) is not int or value["size_bytes"] < 0:
        raise ServiceContractError(f"{label} descriptor size is invalid")
    if type(value["sha256"]) is not str or _SHA_RE.fullmatch(value["sha256"]) is None:
        raise ServiceContractError(f"{label} descriptor SHA-256 is invalid")
    path = _exact_existing_file(value["path"], label=label)
    observed = _stable_file_descriptor(path, label=label)
    if observed != value:
        raise ServiceContractError(f"{label} identity drift")
    return path


def _self_hashed(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    if field in result:
        raise ServiceContractError(f"self-hash field already exists: {field}")
    result[field] = _semantic_sha256(result)
    return result


def _validate_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    actual = value.get(field)
    if type(actual) is not str or _SHA_RE.fullmatch(actual) is None:
        raise ServiceContractError(f"{label} self-hash is invalid")
    material = dict(value)
    material.pop(field, None)
    if _semantic_sha256(material) != actual:
        raise ServiceContractError(f"{label} self-hash drift")


def _snapshot(info: os.stat_result) -> dict[str, int]:
    return {
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
        "st_mode": int(info.st_mode),
        "st_nlink": int(info.st_nlink),
        "st_size": int(info.st_size),
        "st_mtime_ns": int(info.st_mtime_ns),
        "st_ctime_ns": int(info.st_ctime_ns),
        "st_file_attributes": int(getattr(info, "st_file_attributes", 0)),
    }


def _stable_directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _is_link_or_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    observed = path.lstat() if info is None else info
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(observed.st_mode) or bool(
        int(getattr(observed, "st_file_attributes", 0)) & reparse
    )


def _fsync_directory(path: Path) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        os.fsync(descriptor)
    except OSError as error:
        raise ServiceContractError(
            f"directory durability barrier failed: {path}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _payload_descriptor(path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _directory_tree(
    path: Path, *, label: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        root_info = path.lstat()
    except OSError as error:
        raise ServiceContractError(f"{label} is unavailable") from error
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or _is_link_or_reparse(path, root_info)
    ):
        raise ServiceContractError(f"{label} root is unsafe")
    logical: list[dict[str, Any]] = []
    physical: list[dict[str, Any]] = []
    entries = [
        path,
        *sorted(
            path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()
        ),
    ]
    for entry in entries:
        try:
            before = entry.lstat()
        except OSError as error:
            raise ServiceContractError(f"{label} entry is unavailable") from error
        if _is_link_or_reparse(entry, before):
            raise ServiceContractError(f"{label} contains a link/reparse point")
        relative = "." if entry == path else entry.relative_to(path).as_posix()
        if stat.S_ISDIR(before.st_mode):
            record: dict[str, Any] = {
                "path": relative,
                "kind": "directory",
                "mode": stat.S_IMODE(before.st_mode),
            }
        else:
            if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1:
                raise ServiceContractError(
                    f"{label} contains a non-regular or aliased file"
                )
            try:
                payload = entry.read_bytes()
                after = entry.lstat()
            except OSError as error:
                raise ServiceContractError(f"{label} file is unreadable") from error
            if _snapshot(before) != _snapshot(after):
                raise ServiceContractError(f"{label} changed while hashing")
            record = {
                "path": relative,
                "kind": "file",
                "mode": stat.S_IMODE(after.st_mode),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            before = after
        logical.append(record)
        physical.append({**record, "snapshot": _snapshot(before)})
    return logical, physical


def _directory_intent_path(parent: Path, target: Path) -> Path:
    relative = target.relative_to(parent).as_posix()
    key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
    return parent / DIRECTORY_JOURNAL_ROOT / f"{key}.json"


def _directory_intent_anchors_staging(
    *, parent: Path, target: Path, staging: Path
) -> bool:
    intent_path = _directory_intent_path(parent, target)
    if not os.path.lexists(intent_path):
        return False
    try:
        value = _read_canonical_object(
            intent_path, label="service bundle directory intent"
        )
    except ServiceContractError:
        return True
    return value.get("staging") == staging.relative_to(parent).as_posix()


def _validate_bundle_directory_anchor(target: Path) -> None:
    parent = _exact_existing_directory(
        target.parent, label="service bundle publication parent"
    )
    if target.parent != parent or target.parent.parent.name == "":
        raise ServiceContractError("service bundle publication parent is not exact")
    relative = target.relative_to(parent).as_posix()
    intent_relative = _directory_intent_path(parent, target).relative_to(
        parent
    ).as_posix()
    try:
        with PhysicalRootCustodyV1.open(
            parent, label="service bundle publication parent"
        ) as custody:
            _descriptor, payload = custody.read_descriptor(
                intent_relative,
                label="service bundle directory intent",
                maximum=64 * 1024 * 1024,
                capture=True,
            )
            assert payload is not None
            try:
                intent = json.loads(payload.decode("ascii"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ServiceContractError(
                    "service bundle directory intent is invalid"
                ) from error
            if payload != canonical_json_bytes(intent) + b"\n":
                raise ServiceContractError(
                    "service bundle directory intent is noncanonical"
                )
            core = {key: value for key, value in intent.items() if key != "intent_sha256"}
            if (
                type(intent) is not dict
                or intent.get("schema_version") != 1
                or intent.get("artifact_kind") != DIRECTORY_JOURNAL_KIND
                or intent.get("target") != relative
                or intent.get("intent_sha256")
                != hashlib.sha256(canonical_json_bytes(core) + b"\n").hexdigest()
                or type(intent.get("logical_tree")) is not list
                or type(intent.get("physical_tree")) is not list
            ):
                raise ServiceContractError(
                    "service bundle directory intent identity drift"
                )
            logical, physical = _directory_tree(
                target, label="materialized service bundle"
            )
            if logical != intent["logical_tree"] or len(physical) != len(
                intent["physical_tree"]
            ):
                raise ServiceContractError(
                    "materialized service bundle differs from its directory intent"
                )
            for observed, anchored in zip(
                physical, intent["physical_tree"], strict=True
            ):
                observed_core = {
                    key: value for key, value in observed.items() if key != "snapshot"
                }
                anchored_core = {
                    key: value for key, value in anchored.items() if key != "snapshot"
                }
                if observed_core != anchored_core:
                    raise ServiceContractError(
                        "materialized service bundle logical identity drift"
                    )
                current = observed.get("snapshot")
                expected = anchored.get("snapshot")
                if type(current) is not dict or type(expected) is not dict:
                    raise ServiceContractError(
                        "materialized service bundle physical intent drift"
                    )
                if observed["path"] == ".":
                    stable = (
                        "st_dev",
                        "st_ino",
                        "st_mode",
                        "st_nlink",
                        "st_file_attributes",
                    )
                    matches = all(current.get(key) == expected.get(key) for key in stable)
                else:
                    matches = current == expected
                if not matches:
                    raise ServiceContractError(
                        "materialized service bundle was tampered, rebound, or ABA-restored"
                    )
            custody.verify()
    except PublicationPhysicalIoV1Error as error:
        raise ServiceContractError(
            "service bundle directory intent custody failed"
        ) from error


def _remove_owned_staging(
    staging: Path,
    *,
    parent: Path,
    expected_identity: tuple[int, ...],
) -> None:
    if not os.path.lexists(staging):
        return
    try:
        parent_exact = _exact_existing_directory(
            parent, label="service bundle staging parent"
        )
        info = staging.lstat()
    except OSError as error:
        raise ServiceContractError("service bundle staging is unavailable") from error
    if (
        staging.parent != parent_exact
        or not staging.name.startswith(".wsl-service-")
        or not staging.name.endswith(".staging")
        or _stable_directory_identity(info) != expected_identity
        or not stat.S_ISDIR(info.st_mode)
        or _is_link_or_reparse(staging, info)
    ):
        raise ServiceContractError(
            "refusing unsafe service bundle staging cleanup"
        )
    if os.name == "posix":
        anchor: OwnedStagingDirectoryV1 | None = None
        try:
            anchor = OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=parent_exact,
                expected_prefix=".wsl-service-",
                label="service bundle staging cleanup",
            )
            anchored_identity = (
                anchor.root_snapshot[0],
                anchor.root_snapshot[1],
                anchor.root_snapshot[2],
                anchor.root_snapshot[3],
                anchor.root_snapshot[7],
            )
            if anchored_identity != expected_identity:
                raise ServiceContractError(
                    "refusing rebound service bundle staging cleanup"
                )
            anchor.seal_tree()
            anchor.cleanup_after_publication(
                final_target=staging.with_name(
                    f".{staging.name}.cleanup-sentinel"
                )
            )
        except OwnedStagingCleanupV1Error as error:
            raise ServiceContractError(
                "service bundle staging cleanup custody failed"
            ) from error
        finally:
            if anchor is not None:
                anchor.close()
        return
    _directory_tree(staging, label="service bundle staging cleanup")
    shutil.rmtree(staging)
    _fsync_directory(parent_exact)


def _commit_staged_leaf(
    custody: PhysicalRootCustodyV1,
    *,
    staging: Path,
    final: Path,
    payload: bytes,
    label: str,
    after_physical_commit_step: PhysicalFaultHook | None,
) -> None:
    relative = staging.relative_to(custody.root).as_posix() + "/" + final.name

    def physical_step(step: str) -> None:
        if after_physical_commit_step is not None:
            after_physical_commit_step(f"{label}:{step}", final)

    try:
        descriptor, _identity, _disposition = custody.commit_or_adopt_exact_identity(
            relative,
            payload,
            label=f"service bundle {label}",
            mode=0o600,
            create_parents=False,
            after_publish_step=physical_step,
        )
    except PublicationPhysicalIoV1Error as error:
        raise ServiceContractError(
            f"service bundle {label} atomic commit failed"
        ) from error
    expected = _payload_descriptor(final, payload)
    if (
        descriptor.get("size_bytes") != expected["size_bytes"]
        or descriptor.get("sha256") != expected["sha256"]
    ):
        raise ServiceContractError(f"service bundle {label} descriptor drift")


def _read_canonical_object(path: Path, *, label: str) -> dict[str, Any]:
    exact = _exact_existing_file(path, label=label)
    try:
        payload = exact.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ServiceContractError(f"{label} is invalid JSON") from error
    if type(value) is not dict or payload != canonical_json_bytes(value) + b"\n":
        raise ServiceContractError(f"{label} is not canonical JSON with one trailing LF")
    return value


def unit_name_for_attempt(attempt_id: str) -> str:
    if type(attempt_id) is not str or _ATTEMPT_RE.fullmatch(attempt_id) is None:
        raise ServiceContractError("attempt_id is invalid")
    name = f"vast-full-publication-{attempt_id}.service"
    if _UNIT_RE.fullmatch(name) is None:
        raise ServiceContractError("derived unit name is invalid")
    return name


def _format_positive_float(value: float, *, label: str) -> str:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ServiceContractError(f"{label} must be finite and positive")
    return format(number, ".15g")


def _validated_backoff(values: Sequence[float]) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or any(not math.isfinite(value) or value < 0 for value in result):
        raise ServiceContractError("backoff must contain finite non-negative seconds")
    return result


def _validated_frozen_publication_contract(
    *,
    expected_matrix_sha256: Any,
    expected_policy_contract_sha256: Any,
) -> dict[str, Any]:
    if expected_matrix_sha256 != FROZEN_FULL_PUBLICATION_MATRIX_SHA256:
        raise ServiceContractError(
            "expected matrix SHA-256 must equal the frozen full publication v4 pin"
        )
    if (
        expected_policy_contract_sha256
        != FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256
    ):
        raise ServiceContractError(
            "expected policy contract SHA-256 must equal the frozen publication pin"
        )
    return {
        "matrix_schema_version": FROZEN_FULL_PUBLICATION_MATRIX_SCHEMA_VERSION,
        "matrix_sha256": FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
        "policy_contract_sha256": FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256,
    }


def _backoff_text(values: Sequence[float]) -> str:
    return ",".join(format(value, ".15g") for value in _validated_backoff(values))


def _systemd_quote(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ServiceContractError("systemd argument contains a forbidden character")
    escaped = value.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _systemd_working_directory(value: str) -> str:
    if value.startswith("/") and re.fullmatch(r"/[A-Za-z0-9_./:@+-]+", value):
        return value
    if os.name == "nt":  # Allows filesystem-backed unit fixtures on Windows.
        return _systemd_quote(value)
    raise ServiceContractError(
        "WSL project_root contains characters unsupported by the frozen unit contract"
    )


def _entrypoint_args_from_manifest_fields(
    *,
    project_root: Path,
    run_root: Path,
    sources: Mapping[str, Mapping[str, Any]],
    cloud_destination_id: str,
    minimum_free_gib: float,
    cloud_timeout_s: float,
    expected_matrix_sha256: str,
    expected_policy_contract_sha256: str,
) -> list[str]:
    return [
        "--project-root",
        str(project_root),
        "--run-root",
        str(run_root),
        "--expected-matrix-sha256",
        expected_matrix_sha256,
        "--expected-policy-contract-sha256",
        expected_policy_contract_sha256,
        "--config",
        str(sources["config"]["path"]),
        "--datasets",
        str(sources["datasets"]["path"]),
        "--models",
        str(sources["models"]["path"]),
        "--identity-artifacts",
        str(sources["identity_artifacts"]["path"]),
        "--capacity-attestation",
        str(sources["capacity_attestation"]["path"]),
        "--cloud-links-file",
        str(sources["cloud_links_file"]["path"]),
        "--cloud-destination-id",
        cloud_destination_id,
        "--minimum-free-gib",
        _format_positive_float(minimum_free_gib, label="minimum_free_gib"),
        "--cloud-timeout-s",
        _format_positive_float(cloud_timeout_s, label="cloud_timeout_s"),
    ]


def _pinned_python_source_command_v1(
    manifest: Mapping[str, Any],
    *,
    source_label: str,
    arguments: Sequence[str],
) -> list[str]:
    sources = manifest["sources"]
    descriptor = sources[source_label]
    return [
        str(sources["python_executable"]["path"]),
        "-I",
        "-B",
        "-c",
        _PINNED_PYTHON_SOURCE_BOOTSTRAP_V1,
        str(descriptor["path"]),
        str(descriptor["size_bytes"]),
        str(descriptor["sha256"]),
        *[str(value) for value in arguments],
    ]


def render_unit_v1(manifest: Mapping[str, Any], *, receipt_path: Path | str) -> bytes:
    receipt = _lexical_absolute(receipt_path)
    command = _pinned_python_source_command_v1(
        manifest,
        source_label="manager",
        arguments=("launch", "--receipt", str(receipt)),
    )
    rendered_command = " ".join(_systemd_quote(value) for value in command)
    text = (
        "[Unit]\n"
        f"Description=VAST full publication benchmark ({manifest['attempt_id']})\n"
        "After=default.target\n"
        "StartLimitIntervalSec=0\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={_systemd_working_directory(str(manifest['project_root']))}\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        f"ExecStart={rendered_command}\n"
        "Restart=on-failure\n"
        "RestartSec=30s\n"
        "RestartPreventExitStatus=78\n"
        "TimeoutStopSec=5min\n"
        "KillMode=control-group\n"
        "SendSIGKILL=yes\n"
        "UMask=0077\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    return text.encode("utf-8")


def materialize_bundle_v1(
    *,
    project_root: Path | str,
    run_root: Path | str,
    state_path: Path | str,
    output_dir: Path | str,
    attempt_id: str,
    user_uid: int,
    user_unit_dir: Path | str,
    manager_path: Path | str,
    supervisor_path: Path | str,
    entrypoint_path: Path | str,
    python_executable: Path | str,
    docker_executable: Path | str,
    config_path: Path | str,
    dataset_manifest_path: Path | str,
    model_manifest_path: Path | str,
    identity_artifact_manifest_path: Path | str,
    capacity_attestation_path: Path | str,
    cloud_links_file: Path | str,
    cloud_destination_id: str,
    expected_matrix_sha256: str = FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
    expected_policy_contract_sha256: str = (
        FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256
    ),
    minimum_free_gib: float = 20.0,
    cloud_timeout_s: float = 120.0,
    preflight_timeout_s: float = 900.0,
    backoff_s: Sequence[float] = DEFAULT_BACKOFF,
    max_unexpected_retries: int = 3,
    after_physical_commit_step: PhysicalFaultHook | None = None,
) -> dict[str, object]:
    root = _exact_existing_directory(project_root, label="project_root")
    if type(attempt_id) is not str or _ATTEMPT_RE.fullmatch(attempt_id) is None:
        raise ServiceContractError("attempt_id is invalid")
    if type(user_uid) is not int or user_uid < 0:
        raise ServiceContractError("user_uid is invalid")
    unit_name = unit_name_for_attempt(attempt_id)
    namespace = _exact_existing_directory(
        root / "runs" / "full_publication", label="full publication run namespace"
    )
    run = _lexical_absolute(run_root)
    if run.resolve(strict=False) != run:
        raise ServiceContractError("run_root is a symlink or alias")
    try:
        relative_run = run.relative_to(namespace)
    except ValueError:
        raise ServiceContractError("run_root escaped runs/full_publication") from None
    if len(relative_run.parts) != 1 or run.name != attempt_id:
        raise ServiceContractError("run_root must be the exact dedicated attempt directory")
    if run.exists() and (run.is_symlink() or not run.is_dir()):
        raise ServiceContractError("run_root exists with an invalid type")
    state_path_value = _lexical_absolute(state_path)
    if state_path_value.parent != run or state_path_value.name != "full_publication_supervisor_state.v1.json":
        raise ServiceContractError("state_path must be the exact supervisor state file in run_root")
    if state_path_value.exists() and (
        state_path_value.is_symlink() or not state_path_value.is_file()
    ):
        raise ServiceContractError("state_path exists with an invalid type")
    artifacts = _exact_existing_directory(root / "artifacts", label="artifact namespace")
    output = _lexical_absolute(output_dir)
    if output.parent != artifacts or output.name in {"", ".", ".."}:
        raise ServiceContractError("output_dir must be a direct child of artifacts")
    if os.path.lexists(output):
        info = output.lstat()
        if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(output, info):
            raise ServiceContractError("output_dir has an invalid existing type")
    unit_dir = _lexical_absolute(user_unit_dir)
    if unit_dir.exists() and (unit_dir.is_symlink() or not unit_dir.is_dir()):
        raise ServiceContractError("user_unit_dir has an invalid type")
    if type(cloud_destination_id) is not str or not cloud_destination_id.strip():
        raise ServiceContractError("cloud_destination_id is invalid")
    if any(character in cloud_destination_id for character in "\r\n\x00"):
        raise ServiceContractError("cloud_destination_id contains a forbidden character")
    if type(max_unexpected_retries) is not int or max_unexpected_retries < 0:
        raise ServiceContractError("max_unexpected_retries must be a non-negative integer")
    backoff = _validated_backoff(backoff_s)
    frozen_contract = _validated_frozen_publication_contract(
        expected_matrix_sha256=expected_matrix_sha256,
        expected_policy_contract_sha256=expected_policy_contract_sha256,
    )
    exact_cloud_links = _exact_existing_file(
        cloud_links_file, label="Seafile link file"
    )
    if exact_cloud_links != root / "seafile.txt":
        raise ServiceContractError(
            "service Seafile links must come only from project_root/seafile.txt"
        )
    sources = {
        "manager": _stable_file_descriptor(manager_path, label="manager source"),
        "supervisor": _stable_file_descriptor(supervisor_path, label="supervisor source"),
        "entrypoint": _stable_file_descriptor(entrypoint_path, label="entrypoint source"),
        "python_executable": _stable_file_descriptor(
            python_executable, label="Python executable"
        ),
        "docker_executable": _stable_file_descriptor(
            docker_executable, label="Docker executable"
        ),
        "config": _stable_file_descriptor(config_path, label="benchmark config"),
        "datasets": _stable_file_descriptor(
            dataset_manifest_path, label="dataset manifest"
        ),
        "models": _stable_file_descriptor(model_manifest_path, label="model manifest"),
        "identity_artifacts": _stable_file_descriptor(
            identity_artifact_manifest_path, label="identity artifact manifest"
        ),
        "capacity_attestation": _stable_file_descriptor(
            capacity_attestation_path, label="capacity attestation"
        ),
        "cloud_links_file": _stable_file_descriptor(
            exact_cloud_links, label="Seafile link file"
        ),
    }
    entrypoint_args = _entrypoint_args_from_manifest_fields(
        project_root=root,
        run_root=run,
        sources=sources,
        cloud_destination_id=cloud_destination_id,
        minimum_free_gib=minimum_free_gib,
        cloud_timeout_s=cloud_timeout_s,
        expected_matrix_sha256=frozen_contract["matrix_sha256"],
        expected_policy_contract_sha256=frozen_contract[
            "policy_contract_sha256"
        ],
    )
    manifest = _self_hashed(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_wsl_user_service_manifest",
            "attempt_id": attempt_id,
            "unit_name": unit_name,
            "user_uid": user_uid,
            "user_unit_dir": str(unit_dir),
            "project_root": str(root),
            "run_root": str(run),
            "state_path": str(state_path_value),
            "platform_contract": {
                "execution_environment": "wsl_systemd_user",
                "windows_boot_integration": "forbidden",
                "wsl_memory_configuration": "external_unchanged",
                "docker_socket": DOCKER_SOCKET,
                "docker_host": f"unix://{DOCKER_SOCKET}",
                "production_runtime_source": str(
                    Path(sources["python_executable"]["path"]).parent.parent
                ),
            },
            "frozen_publication_contract": frozen_contract,
            "sources": sources,
            "entrypoint_args": entrypoint_args,
            "supervisor_contract": {
                "backoff_s": list(backoff),
                "max_unexpected_retries": max_unexpected_retries,
            },
            "preflight_timeout_s": float(
                _format_positive_float(preflight_timeout_s, label="preflight_timeout_s")
            ),
        },
        "manifest_sha256",
    )
    manifest_path = output / MANIFEST_NAME
    unit_path = output / UNIT_NAME
    receipt_path = output / RECEIPT_NAME
    manifest_payload = canonical_json_bytes(manifest) + b"\n"
    unit_bytes = render_unit_v1(manifest, receipt_path=receipt_path)
    receipt = _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_wsl_user_service_materialization",
            "attempt_id": attempt_id,
            "unit_name": unit_name,
            "manifest": _payload_descriptor(manifest_path, manifest_payload),
            "unit": _payload_descriptor(unit_path, unit_bytes),
            "activation_state": "not_installed_not_enabled_not_started",
        },
        "receipt_sha256",
    )
    receipt_payload = canonical_json_bytes(receipt) + b"\n"
    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=".wsl-service-", suffix=".staging", dir=artifacts)
    )
    staging_identity = _stable_directory_identity(staging.lstat())
    try:
        with PhysicalRootCustodyV1.open(
            artifacts, label="service bundle artifact parent"
        ) as custody:
            for label, final, payload in (
                ("manifest", manifest_path, manifest_payload),
                ("unit", unit_path, unit_bytes),
                ("receipt", receipt_path, receipt_payload),
            ):
                _commit_staged_leaf(
                    custody,
                    staging=staging,
                    final=final,
                    payload=payload,
                    label=label,
                    after_physical_commit_step=after_physical_commit_step,
                )
            custody.verify()
        if set(path.name for path in staging.iterdir()) != {
            MANIFEST_NAME,
            UNIT_NAME,
            RECEIPT_NAME,
        }:
            raise ServiceContractError("service bundle staging namespace drift")
        for path in staging.iterdir():
            path.chmod(0o600)
        staging.chmod(0o700)

        def directory_step(step: str) -> None:
            if after_physical_commit_step is not None:
                after_physical_commit_step(f"bundle:{step}", output)

        try:
            publication = commit_or_adopt_immutable_directory_v1(
                project_root=artifacts,
                staging=staging,
                target=output,
                after_publish_step=directory_step,
            )
        except PublicationImmutableDirectoryV1Error as error:
            raise ServiceContractError(
                "service bundle directory publication failed"
            ) from error
        if os.path.lexists(staging):
            _remove_owned_staging(
                staging,
                parent=artifacts,
                expected_identity=staging_identity,
            )
        staging = None
        if publication.get("disposition") not in {"published", "adopted"}:
            raise ServiceContractError("service bundle publication disposition drift")
    finally:
        if staging is not None and os.path.lexists(staging):
            if not _directory_intent_anchors_staging(
                parent=artifacts, target=output, staging=staging
            ):
                _remove_owned_staging(
                    staging,
                    parent=artifacts,
                    expected_identity=staging_identity,
                )
    validated = validate_bundle_v1(receipt_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_wsl_user_service_materialized",
        "receipt_path": str(validated.receipt_path),
        "manifest_path": str(validated.manifest_path),
        "unit_path": str(validated.unit_path),
        "unit_name": unit_name,
        "installed": False,
        "enabled": False,
        "started": False,
    }


def _validate_manifest_v1(manifest: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "artifact_kind",
        "attempt_id",
        "unit_name",
        "user_uid",
        "user_unit_dir",
        "project_root",
        "run_root",
        "state_path",
        "platform_contract",
        "frozen_publication_contract",
        "sources",
        "entrypoint_args",
        "supervisor_contract",
        "preflight_timeout_s",
        "manifest_sha256",
    }
    if set(manifest) != expected:
        raise ServiceContractError("service manifest fields have drifted")
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("artifact_kind")
        != "vast_full_publication_wsl_user_service_manifest"
    ):
        raise ServiceContractError("service manifest schema has drifted")
    _validate_self_hash(manifest, "manifest_sha256", label="service manifest")
    attempt_id = manifest.get("attempt_id")
    if manifest.get("unit_name") != unit_name_for_attempt(attempt_id):
        raise ServiceContractError("service manifest unit identity drift")
    if type(manifest.get("user_uid")) is not int or manifest["user_uid"] < 0:
        raise ServiceContractError("service manifest user identity is invalid")
    root = _exact_existing_directory(manifest.get("project_root"), label="project_root")
    namespace = _exact_existing_directory(
        root / "runs" / "full_publication", label="full publication run namespace"
    )
    run = _lexical_absolute(manifest.get("run_root"))
    if run.resolve(strict=False) != run or run.parent != namespace or run.name != attempt_id:
        raise ServiceContractError("service manifest run_root identity drift")
    state_path = _lexical_absolute(manifest.get("state_path"))
    if state_path.parent != run or state_path.name != "full_publication_supervisor_state.v1.json":
        raise ServiceContractError("service manifest state_path identity drift")
    unit_dir = _lexical_absolute(manifest.get("user_unit_dir"))
    if str(unit_dir) != manifest.get("user_unit_dir"):
        raise ServiceContractError("service manifest unit directory is not exact")
    sources = manifest.get("sources")
    required_sources = {
        "manager",
        "supervisor",
        "entrypoint",
        "python_executable",
        "docker_executable",
        "config",
        "datasets",
        "models",
        "identity_artifacts",
        "capacity_attestation",
        "cloud_links_file",
    }
    if type(sources) is not dict or set(sources) != required_sources:
        raise ServiceContractError("service source closure has drifted")
    platform = manifest.get("platform_contract")
    expected_platform = {
        "execution_environment": "wsl_systemd_user",
        "windows_boot_integration": "forbidden",
        "wsl_memory_configuration": "external_unchanged",
        "docker_socket": DOCKER_SOCKET,
        "docker_host": f"unix://{DOCKER_SOCKET}",
        "production_runtime_source": str(
            Path(sources["python_executable"]["path"]).parent.parent
        ),
    }
    if platform != expected_platform:
        raise ServiceContractError("service platform contract drift")
    frozen_contract = manifest.get("frozen_publication_contract")
    if frozen_contract != _validated_frozen_publication_contract(
        expected_matrix_sha256=(
            frozen_contract.get("matrix_sha256")
            if type(frozen_contract) is dict
            else None
        ),
        expected_policy_contract_sha256=(
            frozen_contract.get("policy_contract_sha256")
            if type(frozen_contract) is dict
            else None
        ),
    ):
        raise ServiceContractError("service frozen publication contract drift")
    for name in sorted(required_sources):
        source_path = _validate_descriptor(
            sources[name], label=f"service source {name}"
        )
        if (
            sys.platform.startswith("linux")
            and name in {"python_executable", "docker_executable"}
            and not os.access(source_path, os.X_OK)
        ):
            raise ServiceContractError(f"service source {name} is not executable")
    if Path(sources["cloud_links_file"]["path"]) != root / "seafile.txt":
        raise ServiceContractError(
            "service Seafile links must remain project_root/seafile.txt"
        )
    supervisor_contract = manifest.get("supervisor_contract")
    if type(supervisor_contract) is not dict or set(supervisor_contract) != {
        "backoff_s",
        "max_unexpected_retries",
    }:
        raise ServiceContractError("supervisor service contract is invalid")
    backoff = _validated_backoff(supervisor_contract["backoff_s"])
    retries = supervisor_contract["max_unexpected_retries"]
    if type(retries) is not int or retries < 0:
        raise ServiceContractError("supervisor retry contract is invalid")
    timeout = manifest.get("preflight_timeout_s")
    _format_positive_float(timeout, label="preflight_timeout_s")
    args = _entrypoint_args_from_manifest_fields(
        project_root=root,
        run_root=run,
        sources=sources,
        cloud_destination_id=_single_option_value(
            manifest.get("entrypoint_args"), "--cloud-destination-id"
        ),
        minimum_free_gib=float(
            _single_option_value(manifest.get("entrypoint_args"), "--minimum-free-gib")
        ),
        cloud_timeout_s=float(
            _single_option_value(manifest.get("entrypoint_args"), "--cloud-timeout-s")
        ),
        expected_matrix_sha256=FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
        expected_policy_contract_sha256=(
            FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256
        ),
    )
    if manifest.get("entrypoint_args") != args:
        raise ServiceContractError("entrypoint argument identity drift")
    _backoff_text(backoff)


def _single_option_value(arguments: Any, option: str) -> str:
    if type(arguments) is not list or any(type(item) is not str for item in arguments):
        raise ServiceContractError("entrypoint arguments are invalid")
    positions = [index for index, item in enumerate(arguments) if item == option]
    if len(positions) != 1 or positions[0] + 1 >= len(arguments):
        raise ServiceContractError(f"entrypoint option is ambiguous: {option}")
    return arguments[positions[0] + 1]


def validate_bundle_v1(receipt_path: Path | str) -> ValidatedBundleV1:
    receipt_exact = _exact_existing_file(receipt_path, label="materialization receipt")
    _validate_bundle_directory_anchor(receipt_exact.parent)
    try:
        bundle_entries = {path.name for path in receipt_exact.parent.iterdir()}
    except OSError as error:
        raise ServiceContractError("materialized bundle cannot be enumerated") from error
    if bundle_entries != {MANIFEST_NAME, UNIT_NAME, RECEIPT_NAME}:
        raise ServiceContractError("materialized bundle contains unexpected entries")
    receipt = _read_canonical_object(receipt_exact, label="materialization receipt")
    expected_receipt = {
        "schema_version",
        "artifact_kind",
        "attempt_id",
        "unit_name",
        "manifest",
        "unit",
        "activation_state",
        "receipt_sha256",
    }
    if set(receipt) != expected_receipt:
        raise ServiceContractError("materialization receipt fields have drifted")
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("artifact_kind")
        != "vast_full_publication_wsl_user_service_materialization"
        or receipt.get("activation_state")
        != "not_installed_not_enabled_not_started"
    ):
        raise ServiceContractError("materialization receipt schema has drifted")
    _validate_self_hash(receipt, "receipt_sha256", label="materialization receipt")
    manifest_path = _validate_descriptor(
        receipt.get("manifest"), label="materialized manifest"
    )
    unit_path = _validate_descriptor(receipt.get("unit"), label="materialized unit")
    if (
        manifest_path.parent != receipt_exact.parent
        or unit_path.parent != receipt_exact.parent
        or manifest_path.name != MANIFEST_NAME
        or unit_path.name != UNIT_NAME
    ):
        raise ServiceContractError("materialized bundle paths have drifted")
    manifest = _read_canonical_object(manifest_path, label="service manifest")
    _validate_manifest_v1(manifest)
    if (
        receipt.get("attempt_id") != manifest.get("attempt_id")
        or receipt.get("unit_name") != manifest.get("unit_name")
    ):
        raise ServiceContractError("receipt-to-manifest identity drift")
    unit_bytes = unit_path.read_bytes()
    expected_unit = render_unit_v1(manifest, receipt_path=receipt_exact)
    if unit_bytes != expected_unit:
        raise ServiceContractError("materialized unit content drift")
    return ValidatedBundleV1(
        receipt_path=receipt_exact,
        manifest_path=manifest_path,
        unit_path=unit_path,
        receipt=receipt,
        manifest=manifest,
        unit_bytes=unit_bytes,
    )


def is_wsl() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
    except OSError:
        version = ""
    return (
        "microsoft" in version.lower()
        or Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()
    )


def require_wsl() -> None:
    if not is_wsl():
        raise ServiceContractError("full publication user service is WSL-only")


def _current_uid() -> int:
    if not hasattr(os, "getuid"):
        raise ServiceContractError("POSIX user identity is unavailable")
    return int(os.getuid())


def _validate_user(manifest: Mapping[str, Any], current_uid: int | None) -> int:
    uid = _current_uid() if current_uid is None else current_uid
    if type(uid) is not int or uid != manifest.get("user_uid"):
        raise ServiceContractError("current user UID differs from materialized owner")
    return uid


def _stable_identity_record(info: os.stat_result) -> dict[str, int]:
    return {
        key: value
        for key, value in _snapshot(info).items()
        if key
        in {
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_file_attributes",
        }
    }


def _ensure_external_unit_directory(path: Path | str) -> Path:
    lexical = _lexical_absolute(path)
    if lexical == Path(lexical.anchor) or lexical.name in {"", ".", ".."}:
        raise ServiceContractError("user unit directory is too broad")
    missing: list[Path] = []
    cursor = lexical
    while not os.path.lexists(cursor):
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            raise ServiceContractError("user unit directory has no physical parent")
        cursor = parent
    try:
        info = cursor.lstat()
    except OSError as error:
        raise ServiceContractError("user unit directory parent is unavailable") from error
    if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(cursor, info):
        raise ServiceContractError("user unit directory parent is unsafe")
    if cursor.resolve(strict=True) != cursor:
        raise ServiceContractError("user unit directory parent is an alias")
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
            _fsync_directory(directory.parent)
        except OSError as error:
            raise ServiceContractError(
                "user unit directory cannot be created safely"
            ) from error
        created = directory.lstat()
        if (
            not stat.S_ISDIR(created.st_mode)
            or _is_link_or_reparse(directory, created)
            or directory.resolve(strict=True) != directory
        ):
            raise ServiceContractError("created user unit directory is unsafe")
    return _exact_existing_directory(lexical, label="user unit directory")


def _external_unit_key(unit_name: str, payload: bytes) -> str:
    material = (
        unit_name.encode("utf-8")
        + b"\0"
        + len(payload).to_bytes(8, "big")
        + hashlib.sha256(payload).digest()
    )
    return hashlib.sha256(material).hexdigest()


def _read_exact_external_unit_leaf(
    path: Path,
    payload: bytes,
    *,
    label: str,
    allowed_links: frozenset[int],
) -> tuple[dict[str, int], tuple[int, int]]:
    descriptor = -1
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(path, before)
            or int(before.st_nlink) not in allowed_links
            or int(before.st_size) != len(payload)
        ):
            raise OSError("invalid physical leaf")
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = len(payload)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise OSError("short read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1) or b"".join(chunks) != payload:
            raise OSError("content drift")
        after = path.lstat()
        if _snapshot(before) != _snapshot(opened) or _snapshot(opened) != _snapshot(after):
            raise OSError("physical identity drift")
        return _snapshot(after), (int(after.st_dev), int(after.st_ino))
    except OSError as error:
        raise ServiceContractError(f"{label} identity drift") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _external_unit_paths(
    unit_dir: Path, unit_name: str, payload: bytes
) -> tuple[Path, Path, Path, Path]:
    key = _external_unit_key(unit_name, payload)
    journal = unit_dir / EXTERNAL_UNIT_JOURNAL
    return (
        journal,
        journal / f"{key}.intent.json",
        journal / f"{key}.unit",
        journal / f"{key}.receipt.json",
    )


def _read_external_journal_object(
    custody: PhysicalRootCustodyV1, relative: str, *, label: str
) -> dict[str, Any]:
    try:
        _descriptor, payload = custody.read_descriptor(
            relative,
            label=label,
            maximum=16 * 1024 * 1024,
            capture=True,
        )
    except PublicationPhysicalIoV1Error as error:
        raise ServiceContractError(f"{label} custody failed") from error
    assert payload is not None
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ServiceContractError(f"{label} is invalid") from error
    if type(value) is not dict or payload != canonical_json_bytes(value) + b"\n":
        raise ServiceContractError(f"{label} is noncanonical")
    return value


def _validate_external_unit_receipt(
    *,
    custody: PhysicalRootCustodyV1,
    unit_dir: Path,
    unit_name: str,
    payload: bytes,
    intent: Mapping[str, Any],
    receipt_relative: str,
    anchor: Path,
    installed: Path,
) -> Path:
    receipt = _read_external_journal_object(
        custody, receipt_relative, label="installed systemd unit receipt"
    )
    core = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (
        set(receipt)
        != {
            "schema_version",
            "artifact_kind",
            "unit_name",
            "unit_payload",
            "unit_dir_identity",
            "anchor",
            "installed",
            "physical_snapshot",
            "receipt_sha256",
        }
        or receipt.get("schema_version") != 1
        or receipt.get("artifact_kind") != EXTERNAL_UNIT_RECEIPT_KIND
        or receipt.get("unit_name") != unit_name
        or receipt.get("unit_payload") != intent.get("unit_payload")
        or receipt.get("unit_dir_identity") != intent.get("unit_dir_identity")
        or receipt.get("anchor") != anchor.relative_to(unit_dir).as_posix()
        or receipt.get("installed") != installed.name
        or receipt.get("receipt_sha256") != _semantic_sha256(core)
    ):
        raise ServiceContractError("installed systemd unit receipt drift")
    current_root = _stable_identity_record(unit_dir.lstat())
    anchor_snapshot, anchor_identity = _read_exact_external_unit_leaf(
        anchor,
        payload,
        label="installed systemd unit anchor",
        allowed_links=frozenset({2}),
    )
    installed_snapshot, installed_identity = _read_exact_external_unit_leaf(
        installed,
        payload,
        label="installed systemd unit",
        allowed_links=frozenset({2}),
    )
    if (
        current_root != intent.get("unit_dir_identity")
        or anchor_identity != installed_identity
        or anchor_snapshot != installed_snapshot
        or receipt.get("physical_snapshot") != installed_snapshot
    ):
        raise ServiceContractError(
            "installed systemd unit was tampered, rebound, or ABA-restored"
        )
    custody.verify()
    return installed


def _commit_or_adopt_external_unit(
    *,
    unit_dir: Path,
    unit_name: str,
    payload: bytes,
    after_physical_commit_step: PhysicalFaultHook | None,
) -> Path:
    journal, intent_path, anchor, receipt_path = _external_unit_paths(
        unit_dir, unit_name, payload
    )
    installed = unit_dir / unit_name
    try:
        with PhysicalRootCustodyV1.open(
            unit_dir, label="external systemd user unit directory"
        ) as custody:
            custody.ensure_directory(
                EXTERNAL_UNIT_JOURNAL,
                label="external systemd unit journal",
            )
            # The shared atomic writer owns this deterministic control
            # directory.  Create it before pinning the external root so its
            # legitimate first-use link-count change cannot look like a rebind
            # and cannot make the immutable intent differ on retry.
            custody.ensure_directory(
                PHYSICAL_ATOMIC_STAGING_ROOT,
                label="external systemd unit atomic staging root",
            )
            root_identity = _stable_identity_record(unit_dir.lstat())
            intent_core = {
                "schema_version": 1,
                "artifact_kind": EXTERNAL_UNIT_INTENT_KIND,
                "unit_name": unit_name,
                "unit_payload": {
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                "unit_dir_identity": root_identity,
                "anchor": anchor.relative_to(unit_dir).as_posix(),
                "installed": installed.name,
            }
            intent = {**intent_core, "intent_sha256": _semantic_sha256(intent_core)}
            intent_payload = canonical_json_bytes(intent) + b"\n"
            intent_relative = intent_path.relative_to(unit_dir).as_posix()
            custody.commit_or_adopt_exact_identity(
                intent_relative,
                intent_payload,
                label="external systemd unit intent",
                mode=0o600,
                create_parents=False,
            )
            observed_intent = _read_external_journal_object(
                custody, intent_relative, label="external systemd unit intent"
            )
            if observed_intent != intent:
                raise ServiceContractError("external systemd unit intent drift")

            anchor_relative = anchor.relative_to(unit_dir).as_posix()
            if not os.path.lexists(installed):

                def anchor_step(step: str) -> None:
                    if after_physical_commit_step is not None:
                        after_physical_commit_step(
                            f"install_anchor:{step}", installed
                        )

                custody.commit_or_adopt_exact_identity(
                    anchor_relative,
                    payload,
                    label="external systemd unit anchor",
                    mode=0o600,
                    create_parents=False,
                    after_publish_step=anchor_step,
                )
            elif not os.path.lexists(anchor):
                raise ServiceContractError(
                    "installed systemd unit exists without its journal anchor"
                )
            anchor_snapshot, anchor_identity = _read_exact_external_unit_leaf(
                anchor,
                payload,
                label="external systemd unit anchor",
                allowed_links=frozenset({1, 2}),
            )
            if after_physical_commit_step is not None:
                after_physical_commit_step("install_unit:mid_write", installed)
            anchor_fd = os.open(
                anchor,
                os.O_RDONLY
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            try:
                os.fsync(anchor_fd)
            finally:
                os.close(anchor_fd)
            _fsync_directory(journal)
            if after_physical_commit_step is not None:
                after_physical_commit_step(
                    "install_unit:post_fsync_pre_publish", installed
                )
            if not os.path.lexists(installed):
                try:
                    os.link(anchor, installed, follow_symlinks=False)
                except FileExistsError:
                    pass
                except OSError as error:
                    raise ServiceContractError(
                        "installed systemd unit no-replace publication failed"
                    ) from error
            installed_snapshot, installed_identity = _read_exact_external_unit_leaf(
                installed,
                payload,
                label="installed systemd unit",
                allowed_links=frozenset({2}),
            )
            anchor_after, anchor_identity_after = _read_exact_external_unit_leaf(
                anchor,
                payload,
                label="installed systemd unit anchor",
                allowed_links=frozenset({2}),
            )
            if (
                anchor_identity_after != anchor_identity
                or installed_identity != anchor_identity
                or installed_snapshot != anchor_after
            ):
                raise ServiceContractError(
                    "installed systemd unit is not the journal-owned inode"
                )
            if after_physical_commit_step is not None:
                after_physical_commit_step(
                    "install_unit:post_publish_pre_parent_fsync", installed
                )
            installed_fd = os.open(
                installed,
                os.O_RDONLY
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            try:
                os.fsync(installed_fd)
            finally:
                os.close(installed_fd)
            _fsync_directory(journal)
            _fsync_directory(unit_dir)
            if _stable_identity_record(unit_dir.lstat()) != root_identity:
                raise ServiceContractError("external systemd unit directory rebound")

            receipt_core = {
                "schema_version": 1,
                "artifact_kind": EXTERNAL_UNIT_RECEIPT_KIND,
                "unit_name": unit_name,
                "unit_payload": intent["unit_payload"],
                "unit_dir_identity": root_identity,
                "anchor": anchor.relative_to(unit_dir).as_posix(),
                "installed": installed.name,
                "physical_snapshot": installed_snapshot,
            }
            receipt = {
                **receipt_core,
                "receipt_sha256": _semantic_sha256(receipt_core),
            }
            receipt_payload = canonical_json_bytes(receipt) + b"\n"
            receipt_relative = receipt_path.relative_to(unit_dir).as_posix()

            def receipt_step(step: str) -> None:
                if after_physical_commit_step is not None:
                    after_physical_commit_step(
                        f"install_receipt:{step}", installed
                    )

            custody.commit_or_adopt_exact_identity(
                receipt_relative,
                receipt_payload,
                label="installed systemd unit receipt",
                mode=0o600,
                create_parents=False,
                after_publish_step=receipt_step,
            )
            return _validate_external_unit_receipt(
                custody=custody,
                unit_dir=unit_dir,
                unit_name=unit_name,
                payload=payload,
                intent=intent,
                receipt_relative=receipt_relative,
                anchor=anchor,
                installed=installed,
            )
    except PublicationPhysicalIoV1Error as error:
        raise ServiceContractError(
            "external systemd unit physical custody failed"
        ) from error


def _installed_unit_path(manifest: Mapping[str, Any]) -> Path:
    return _lexical_absolute(manifest["user_unit_dir"]) / str(manifest["unit_name"])


def _validate_installed_unit(bundle: ValidatedBundleV1) -> Path:
    unit_dir = _exact_existing_directory(
        bundle.manifest["user_unit_dir"], label="user unit directory"
    )
    installed = _installed_unit_path(bundle.manifest)
    if installed.parent != unit_dir or not os.path.lexists(installed):
        raise ServiceContractError("exact installed unit is missing")
    journal, intent_path, anchor, receipt_path = _external_unit_paths(
        unit_dir, installed.name, bundle.unit_bytes
    )
    if journal.parent != unit_dir or not os.path.lexists(receipt_path):
        raise ServiceContractError("installed systemd unit journal is incomplete")
    try:
        with PhysicalRootCustodyV1.open(
            unit_dir, label="external systemd user unit directory"
        ) as custody:
            intent_relative = intent_path.relative_to(unit_dir).as_posix()
            intent = _read_external_journal_object(
                custody, intent_relative, label="external systemd unit intent"
            )
            core = {
                key: value for key, value in intent.items() if key != "intent_sha256"
            }
            if (
                intent.get("schema_version") != 1
                or intent.get("artifact_kind") != EXTERNAL_UNIT_INTENT_KIND
                or intent.get("unit_name") != installed.name
                or intent.get("unit_payload")
                != {
                    "size_bytes": len(bundle.unit_bytes),
                    "sha256": hashlib.sha256(bundle.unit_bytes).hexdigest(),
                }
                or intent.get("anchor") != anchor.relative_to(unit_dir).as_posix()
                or intent.get("installed") != installed.name
                or intent.get("intent_sha256") != _semantic_sha256(core)
            ):
                raise ServiceContractError("external systemd unit intent drift")
            return _validate_external_unit_receipt(
                custody=custody,
                unit_dir=unit_dir,
                unit_name=installed.name,
                payload=bundle.unit_bytes,
                intent=intent,
                receipt_relative=receipt_path.relative_to(unit_dir).as_posix(),
                anchor=anchor,
                installed=installed,
            )
    except PublicationPhysicalIoV1Error as error:
        raise ServiceContractError(
            "installed systemd unit journal custody failed"
        ) from error


def _run_control_command(
    command: list[str],
    *,
    command_runner: CommandRunner,
    timeout: float = 60.0,
) -> Any:
    try:
        return command_runner(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ServiceContractError(f"control command failed: {command[0]}") from error


def _require_linger(
    uid: int, *, command_runner: CommandRunner
) -> None:
    completed = _run_control_command(
        [LOGINCTL, "show-user", str(uid), "--property", "Linger", "--value"],
        command_runner=command_runner,
    )
    if int(completed.returncode) != 0 or str(completed.stdout).strip() != "yes":
        raise ServiceContractError(
            "systemd user linger is not enabled; WSL-only persistence is unavailable"
        )


def install_bundle_v1(
    receipt_path: Path | str,
    *,
    command_runner: CommandRunner = subprocess.run,
    current_uid: int | None = None,
    require_wsl: bool = True,
    after_physical_commit_step: PhysicalFaultHook | None = None,
) -> dict[str, Any]:
    if require_wsl:
        globals()["require_wsl"]()
    bundle = validate_bundle_v1(receipt_path)
    uid = _validate_user(bundle.manifest, current_uid)
    _require_linger(uid, command_runner=command_runner)
    unit_dir = _ensure_external_unit_directory(
        bundle.manifest["user_unit_dir"]
    )
    installed = _commit_or_adopt_external_unit(
        unit_dir=unit_dir,
        unit_name=str(bundle.manifest["unit_name"]),
        payload=bundle.unit_bytes,
        after_physical_commit_step=after_physical_commit_step,
    )
    completed = _run_control_command(
        [SYSTEMCTL, "--user", "daemon-reload"], command_runner=command_runner
    )
    if int(completed.returncode) != 0:
        raise ServiceContractError("systemd user daemon-reload failed")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_wsl_user_service_installation",
        "unit_name": bundle.manifest["unit_name"],
        "installed_unit_path": str(installed),
        "installed": True,
        "enabled": False,
        "started": False,
    }


def entrypoint_command_v1(manifest: Mapping[str, Any], command: str) -> list[str]:
    if command not in {"preflight", "status"}:
        raise ServiceContractError("unsupported lifecycle entrypoint command")
    return _pinned_python_source_command_v1(
        manifest,
        source_label="entrypoint",
        arguments=(
            *[str(value) for value in manifest["entrypoint_args"]],
            command,
        ),
    )


def supervisor_command_v1(manifest: Mapping[str, Any]) -> list[str]:
    contract = manifest["supervisor_contract"]
    entrypoint = manifest["sources"]["entrypoint"]
    supervisor = manifest["sources"]["supervisor"]
    return _pinned_python_source_command_v1(
        manifest,
        source_label="supervisor",
        arguments=(
            "--entrypoint",
            str(entrypoint["path"]),
            "--entrypoint-size-bytes",
            str(entrypoint["size_bytes"]),
            "--entrypoint-sha256",
            str(entrypoint["sha256"]),
            "--supervisor-sha256",
            str(supervisor["sha256"]),
            "--state-path",
            str(manifest["state_path"]),
            "--python-executable",
            str(manifest["sources"]["python_executable"]["path"]),
            "--backoff-s",
            _backoff_text(contract["backoff_s"]),
            "--max-unexpected-retries",
            str(contract["max_unexpected_retries"]),
            "--",
            *[str(value) for value in manifest["entrypoint_args"]],
        ),
    )


def expected_supervisor_command_identity_sha256_v1(
    manifest: Mapping[str, Any]
) -> str:
    identity = {
        "schema_version": 2,
        "entrypoint": str(manifest["sources"]["entrypoint"]["path"]),
        "entrypoint_sha256": str(manifest["sources"]["entrypoint"]["sha256"]),
        "python_executable": str(
            Path(manifest["sources"]["python_executable"]["path"]).resolve()
        ),
        "entrypoint_args": [str(value) for value in manifest["entrypoint_args"]],
        "frozen_publication_contract": dict(
            manifest["frozen_publication_contract"]
        ),
        "supervisor_sha256": str(manifest["sources"]["supervisor"]["sha256"]),
    }
    return _semantic_sha256(identity)


def _sanitized_environment(
    environment: Mapping[str, str] | None,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    for name in (
        "VAST_SEAFILE_UPLOAD_LINK",
        "VAST_SEAFILE_READ_LINK",
        "VAST_SEAFILE_CAPACITY_ATTESTATION",
        "VAST_SEAFILE_DESTINATION_ID",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
    ):
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["PYTHONUNBUFFERED"] = "1"
    result["PYTHONNOUSERSITE"] = "1"
    if manifest is not None:
        platform = manifest["platform_contract"]
        result["DOCKER_HOST"] = str(platform["docker_host"])
        result["VAST_PUBLICATION_RUNTIME_SOURCE"] = str(
            platform["production_runtime_source"]
        )
    return result


def _secret_markers(manifest: Mapping[str, Any]) -> set[str]:
    path = Path(manifest["sources"]["cloud_links_file"]["path"])
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ServiceContractError("Seafile link file cannot be read") from error
    markers: set[str] = set()
    for url in _URL_RE.findall(content):
        value = url.rstrip(".,;)]}'\"")
        markers.add(value)
        token = value.rstrip("/").rsplit("/", 1)[-1]
        if len(token) >= 8:
            markers.add(token)
    if not markers:
        raise ServiceContractError("Seafile link file contains no HTTPS capability links")
    return markers


def docker_ready_v1(
    manifest: Mapping[str, Any],
    *,
    command_runner: CommandRunner = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> bool:
    command = [
        str(manifest["sources"]["docker_executable"]["path"]),
        "info",
        "--format",
        "{{.ServerVersion}}",
    ]
    try:
        completed = command_runner(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=30.0,
            env=_sanitized_environment(environment, manifest=manifest),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    version = str(completed.stdout).strip()
    return int(completed.returncode) == 0 and re.fullmatch(
        r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}", version
    ) is not None


def run_preflight_v1(
    manifest: Mapping[str, Any],
    *,
    command_runner: CommandRunner = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    command = entrypoint_command_v1(manifest, "preflight")
    try:
        completed = command_runner(
            command,
            cwd=str(manifest["project_root"]),
            text=True,
            capture_output=True,
            check=False,
            timeout=float(manifest["preflight_timeout_s"]),
            env=_sanitized_environment(environment, manifest=manifest),
        )
    except subprocess.TimeoutExpired:
        return EXIT_TRANSIENT, {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_wsl_user_service_gate",
            "status": "preflight_timeout",
            "exit_code": EXIT_TRANSIENT,
        }
    except OSError as error:
        raise ServiceContractError("full publication preflight could not start") from error
    stdout = str(completed.stdout).strip()
    stderr = str(completed.stderr)
    for secret in _secret_markers(manifest):
        if secret in stdout or secret in stderr:
            raise ServiceContractError("preflight output exposed a Seafile capability secret")
    code = int(completed.returncode)
    if code not in {EXIT_COMPLETE, EXIT_TRANSIENT, EXIT_PERMANENT}:
        raise ServiceContractError("preflight returned an unsupported exit code")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ServiceContractError("preflight stdout is not one JSON object") from error
    if type(payload) is not dict:
        raise ServiceContractError("preflight stdout is not a JSON object")
    canonical_json_bytes(payload)
    if payload.get("artifact_kind") != "vast_full_publication_external_preflight":
        raise ServiceContractError("preflight artifact kind is invalid")
    if code == EXIT_COMPLETE:
        if not (
            set(payload)
            == {"schema_version", "artifact_kind", "status", "passed", "retryable", "details"}
            and
            payload.get("schema_version") == 1
            and payload.get("status") == "ready"
            and payload.get("passed") is True
            and payload.get("retryable") is False
            and type(payload.get("details")) is dict
        ):
            raise ServiceContractError("successful preflight payload is not exactly ready")
    else:
        expected_retryable = code == EXIT_TRANSIENT
        if not (
            set(payload)
            == {
                "schema_version",
                "artifact_kind",
                "status",
                "passed",
                "retryable",
                "reason",
                "details",
            }
            and
            payload.get("schema_version") == 1
            and payload.get("status") == "blocked_preflight"
            and payload.get("passed") is False
            and payload.get("retryable") is expected_retryable
            and type(payload.get("reason")) is str
            and bool(payload.get("reason"))
            and type(payload.get("details")) is dict
        ):
            raise ServiceContractError("blocked preflight payload has invalid exit semantics")
    return code, payload


def start_bundle_v1(
    receipt_path: Path | str,
    *,
    command_runner: CommandRunner = subprocess.run,
    current_uid: int | None = None,
    require_wsl: bool = True,
    require_docker: bool = True,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if require_wsl:
        globals()["require_wsl"]()
    bundle = validate_bundle_v1(receipt_path)
    uid = _validate_user(bundle.manifest, current_uid)
    _validate_installed_unit(bundle)
    _require_linger(uid, command_runner=command_runner)
    if require_docker and not docker_ready_v1(
        bundle.manifest, command_runner=command_runner, environment=environment
    ):
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_wsl_user_service_start",
            "status": "docker_unavailable",
            "exit_code": EXIT_TRANSIENT,
            "enabled": False,
            "started": False,
        }
    code, preflight = run_preflight_v1(
        bundle.manifest, command_runner=command_runner, environment=environment
    )
    if code != EXIT_COMPLETE:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_wsl_user_service_start",
            "status": "preflight_blocked",
            "exit_code": code,
            "enabled": False,
            "started": False,
            "preflight": preflight,
        }
    completed = _run_control_command(
        [SYSTEMCTL, "--user", "enable", "--now", str(bundle.manifest["unit_name"])],
        command_runner=command_runner,
        timeout=120.0,
    )
    if int(completed.returncode) != 0:
        raise ServiceContractError("systemd user unit activation failed")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_wsl_user_service_start",
        "status": "activated_after_preflight",
        "exit_code": EXIT_COMPLETE,
        "enabled": True,
        "started": True,
        "preflight_sha256": _semantic_sha256(preflight),
    }


def launch_bundle_v1(
    receipt_path: Path | str,
    *,
    command_runner: CommandRunner = subprocess.run,
    current_uid: int | None = None,
    require_wsl: bool = True,
    environment: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    if require_wsl:
        globals()["require_wsl"]()
    bundle = validate_bundle_v1(receipt_path)
    _validate_user(bundle.manifest, current_uid)
    _validate_installed_unit(bundle)
    if not docker_ready_v1(
        bundle.manifest, command_runner=command_runner, environment=environment
    ):
        return EXIT_TRANSIENT, {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_wsl_user_service_gate",
            "status": "docker_unavailable",
            "exit_code": EXIT_TRANSIENT,
        }
    code, payload = run_preflight_v1(
        bundle.manifest, command_runner=command_runner, environment=environment
    )
    if code != EXIT_COMPLETE:
        return code, payload
    command = supervisor_command_v1(bundle.manifest)
    os.execve(
        command[0],
        command,
        _sanitized_environment(environment, manifest=bundle.manifest),
    )
    raise ServiceContractError("supervisor exec unexpectedly returned")


def _validate_supervisor_state(
    path: Path, *, expected_command_identity_sha256: str
) -> dict[str, Any]:
    exact = _exact_existing_file(path, label="supervisor state")
    try:
        state = json.loads(exact.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ServiceContractError("supervisor state is invalid JSON") from error
    if type(state) is not dict or set(state) != _SUPERVISOR_STATE_FIELDS:
        raise ServiceContractError("supervisor state fields have drifted")
    if (
        state.get("schema_version") != 1
        or state.get("artifact_kind") != "vast_full_publication_supervisor_state"
    ):
        raise ServiceContractError("supervisor state schema has drifted")
    if state.get("command_identity_sha256") != expected_command_identity_sha256:
        raise ServiceContractError("supervisor state command identity drift")
    if state.get("phase") not in {"run", "verify", "finalize", "export", "complete", "failed_permanent"}:
        raise ServiceContractError("supervisor state phase is invalid")
    for field in ("attempt_seq", "transient_streak", "unexpected_streak"):
        if type(state.get(field)) is not int or state[field] < 0:
            raise ServiceContractError(f"supervisor state {field} is invalid")
    return state


def _parse_systemctl_show(stdout: str) -> dict[str, str]:
    allowed = {
        "LoadState",
        "ActiveState",
        "SubState",
        "UnitFileState",
        "Result",
        "MainPID",
    }
    result: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            raise ServiceContractError("systemctl show output is invalid")
        name, value = line.split("=", 1)
        if name not in allowed or name in result:
            raise ServiceContractError("systemctl show fields have drifted")
        result[name] = value
    if set(result) != allowed:
        raise ServiceContractError("systemctl show fields are incomplete")
    if not result["MainPID"].isdigit():
        raise ServiceContractError("systemctl MainPID is invalid")
    return result


def status_bundle_v1(
    receipt_path: Path | str,
    *,
    command_runner: CommandRunner = subprocess.run,
    current_uid: int | None = None,
    require_wsl: bool = True,
) -> dict[str, Any]:
    if require_wsl:
        globals()["require_wsl"]()
    bundle = validate_bundle_v1(receipt_path)
    _validate_user(bundle.manifest, current_uid)
    _validate_installed_unit(bundle)
    properties = "LoadState,ActiveState,SubState,UnitFileState,Result,MainPID"
    completed = _run_control_command(
        [
            SYSTEMCTL,
            "--user",
            "show",
            str(bundle.manifest["unit_name"]),
            "--no-pager",
            f"--property={properties}",
        ],
        command_runner=command_runner,
    )
    if int(completed.returncode) != 0:
        raise ServiceContractError("systemd user unit status failed")
    unit = _parse_systemctl_show(str(completed.stdout))
    state_path = Path(bundle.manifest["state_path"])
    state = None
    if state_path.exists() or state_path.is_symlink():
        state = _validate_supervisor_state(
            state_path,
            expected_command_identity_sha256=(
                expected_supervisor_command_identity_sha256_v1(bundle.manifest)
            ),
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_wsl_user_service_status",
        "attempt_id": bundle.manifest["attempt_id"],
        "unit_name": bundle.manifest["unit_name"],
        "run_root": bundle.manifest["run_root"],
        "state_path": bundle.manifest["state_path"],
        "unit": unit,
        "supervisor_state": state,
    }


def stop_bundle_v1(
    receipt_path: Path | str,
    *,
    command_runner: CommandRunner = subprocess.run,
    current_uid: int | None = None,
    require_wsl: bool = True,
) -> dict[str, Any]:
    if require_wsl:
        globals()["require_wsl"]()
    bundle = validate_bundle_v1(receipt_path)
    _validate_user(bundle.manifest, current_uid)
    _validate_installed_unit(bundle)
    completed = _run_control_command(
        [SYSTEMCTL, "--user", "disable", "--now", str(bundle.manifest["unit_name"])],
        command_runner=command_runner,
        timeout=120.0,
    )
    if int(completed.returncode) != 0:
        raise ServiceContractError("systemd user unit stop/disable failed")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_wsl_user_service_stop",
        "unit_name": bundle.manifest["unit_name"],
        "stopped": True,
        "disabled": True,
    }


def _default_user_unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "systemd" / "user"
    return Path.home() / ".config" / "systemd" / "user"


def _parse_backoff(value: str) -> tuple[float, ...]:
    try:
        return _validated_backoff(
            tuple(float(item.strip()) for item in value.split(",") if item.strip())
        )
    except (ValueError, ServiceContractError) as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the WSL-only persistent full publication user service."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    project_root = Path(__file__).resolve().parents[1]
    materialize.add_argument("--project-root", type=Path, default=project_root)
    materialize.add_argument("--attempt-id", required=True)
    materialize.add_argument("--run-root", type=Path, required=True)
    materialize.add_argument("--state-path", type=Path)
    materialize.add_argument("--output-dir", type=Path, required=True)
    materialize.add_argument("--user-unit-dir", type=Path, default=_default_user_unit_dir())
    materialize.add_argument("--python-executable", type=Path, required=True)
    materialize.add_argument("--docker-executable", type=Path, default=Path("/usr/bin/docker"))
    materialize.add_argument("--supervisor", type=Path, default=project_root / "scripts" / "full_publication_supervisor.py")
    materialize.add_argument("--entrypoint", type=Path, default=project_root / "scripts" / "full_publication_entrypoint.py")
    materialize.add_argument("--config", type=Path, default=project_root / "configs" / "experiments.yaml")
    materialize.add_argument("--datasets", type=Path, default=project_root / "configs" / "datasets.yaml")
    materialize.add_argument("--models", type=Path, default=project_root / "configs" / "checkpoint_analytics_models_openvino.yaml")
    materialize.add_argument("--identity-artifacts", type=Path, required=True)
    materialize.add_argument("--capacity-attestation", type=Path, required=True)
    materialize.add_argument("--cloud-links-file", type=Path, required=True)
    materialize.add_argument("--cloud-destination-id", required=True)
    materialize.add_argument(
        "--expected-matrix-sha256",
        default=FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
    )
    materialize.add_argument(
        "--expected-policy-contract-sha256",
        default=FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256,
    )
    materialize.add_argument("--minimum-free-gib", type=float, default=20.0)
    materialize.add_argument("--cloud-timeout-s", type=float, default=120.0)
    materialize.add_argument("--preflight-timeout-s", type=float, default=900.0)
    materialize.add_argument("--backoff-s", type=_parse_backoff, default=DEFAULT_BACKOFF)
    materialize.add_argument("--max-unexpected-retries", type=int, default=3)
    for command in ("validate", "install", "start", "status", "stop", "launch"):
        target = subparsers.add_parser(command)
        target.add_argument("--receipt", type=Path, required=True)
        if command == "validate":
            target.add_argument("--installed", action="store_true")
    return parser


def _error_payload(error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_wsl_user_service_error",
        "status": "permanent_error",
        "exit_code": EXIT_PERMANENT,
        "error_type": type(error).__name__,
        "message": str(error),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        require_wsl()
        if args.command == "materialize":
            state_path = args.state_path or (
                args.run_root / "full_publication_supervisor_state.v1.json"
            )
            payload = materialize_bundle_v1(
                project_root=args.project_root,
                run_root=args.run_root,
                state_path=state_path,
                output_dir=args.output_dir,
                attempt_id=args.attempt_id,
                user_uid=_current_uid(),
                user_unit_dir=args.user_unit_dir,
                manager_path=Path(__file__),
                supervisor_path=args.supervisor,
                entrypoint_path=args.entrypoint,
                python_executable=args.python_executable,
                docker_executable=args.docker_executable,
                config_path=args.config,
                dataset_manifest_path=args.datasets,
                model_manifest_path=args.models,
                identity_artifact_manifest_path=args.identity_artifacts,
                capacity_attestation_path=args.capacity_attestation,
                cloud_links_file=args.cloud_links_file,
                cloud_destination_id=args.cloud_destination_id,
                expected_matrix_sha256=args.expected_matrix_sha256,
                expected_policy_contract_sha256=(
                    args.expected_policy_contract_sha256
                ),
                minimum_free_gib=args.minimum_free_gib,
                cloud_timeout_s=args.cloud_timeout_s,
                preflight_timeout_s=args.preflight_timeout_s,
                backoff_s=args.backoff_s,
                max_unexpected_retries=args.max_unexpected_retries,
            )
            exit_code = EXIT_COMPLETE
        elif args.command == "validate":
            bundle = validate_bundle_v1(args.receipt)
            _validate_user(bundle.manifest, None)
            if args.installed:
                _validate_installed_unit(bundle)
            payload = {
                "schema_version": SCHEMA_VERSION,
                "artifact_kind": "vast_full_publication_wsl_user_service_validation",
                "passed": True,
                "installed_checked": bool(args.installed),
                "unit_name": bundle.manifest["unit_name"],
                "manifest_sha256": bundle.manifest["manifest_sha256"],
            }
            exit_code = EXIT_COMPLETE
        elif args.command == "install":
            payload = install_bundle_v1(args.receipt)
            exit_code = EXIT_COMPLETE
        elif args.command == "start":
            payload = start_bundle_v1(args.receipt)
            exit_code = int(payload["exit_code"])
        elif args.command == "status":
            payload = status_bundle_v1(args.receipt)
            exit_code = EXIT_COMPLETE
        elif args.command == "stop":
            payload = stop_bundle_v1(args.receipt)
            exit_code = EXIT_COMPLETE
        else:
            exit_code, payload = launch_bundle_v1(args.receipt)
    except ServiceContractError as error:
        exit_code = EXIT_PERMANENT
        payload = _error_payload(error)
    print(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_COMPLETE",
    "EXIT_PERMANENT",
    "EXIT_TRANSIENT",
    "FROZEN_FULL_PUBLICATION_MATRIX_SCHEMA_VERSION",
    "FROZEN_FULL_PUBLICATION_MATRIX_SHA256",
    "FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256",
    "MANIFEST_SCHEMA_VERSION",
    "ServiceContractError",
    "ValidatedBundleV1",
    "canonical_json_bytes",
    "docker_ready_v1",
    "entrypoint_command_v1",
    "expected_supervisor_command_identity_sha256_v1",
    "install_bundle_v1",
    "is_wsl",
    "launch_bundle_v1",
    "main",
    "materialize_bundle_v1",
    "render_unit_v1",
    "require_wsl",
    "run_preflight_v1",
    "start_bundle_v1",
    "status_bundle_v1",
    "stop_bundle_v1",
    "supervisor_command_v1",
    "unit_name_for_attempt",
    "validate_bundle_v1",
]
