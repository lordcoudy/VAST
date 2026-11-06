#!/usr/bin/env python3
"""Read-only physical validation for committed qualification transactions."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCHEMA_VERSION = 2
TRANSACTION_KIND = "vast_publication_policy_qualification_input_transaction_v2"
TRANSACTION_RECEIPT_FILENAME = "qualification_input_transaction.v2.receipt.json"
PATCH_KIND = "vast_publication_qualification_image_identity_patch_v1"
V3_PARITY_BINDING_KIND = "vast_verified_model_parity_acceptance_binding"
V4_PARITY_BINDING_KIND = "vast_verified_model_parity_acceptance_binding_v4"
REFRESH_ONLY_BLOCKERS = (
    "analytics_worker:cpu_identity_changed_requires_parity_refresh",
    "analytics_worker:gpu_identity_changed_requires_parity_refresh",
)
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CELL_COUNT = 32
HARDWARE_RESOURCE_COLLECTOR_PATH = "scripts/collect_metrics.py"
# DrvFS without metadata projects chmod(0444) as 0555.  Both modes deny all
# writes; byte, descriptor, and inode identity are still checked independently.
_IMMUTABLE_OUTPUT_MODES = frozenset({0o444, 0o555})

FRAGMENTS_DIRNAME = "fragments"
CANDIDATE_DIRNAME = "candidate"
BOOTSTRAP_DIRNAME = "bootstrap"
INDEX_FILENAME = "checkpoint_policy_qualification_index.v2.json"
CANDIDATE_MANIFEST_FILENAME = "checkpoint_policy_capability_candidate_manifest.json"
CANDIDATE_RECEIPT_FILENAME = "checkpoint_policy_qualification_candidate_receipt.json"
MAPPING_FILENAME = "checkpoint_policy_qualification_bootstrap_mapping.v2.json"
CALIBRATION_FILENAME = (
    "checkpoint_policy_qualification_bootstrap_calibration.{system}.v2.json"
)
BOOTSTRAP_RECEIPT_FILENAME = "checkpoint_policy_qualification_bootstrap_receipt.v2.json"

_SHA = __import__("re").compile(r"^[0-9a-f]{64}$")
_IMAGE = __import__("re").compile(r"^sha256:[0-9a-f]{64}$")


class QualificationTransactionV2Error(RuntimeError):
    """A physical input, resumable phase, or receipt failed closed."""


_ACTIVE_CUSTODY: ContextVar[PhysicalRootCustodyV1 | None] = ContextVar(
    "qualification_transaction_v2_physical_custody", default=None
)


def _custody(root: Path) -> PhysicalRootCustodyV1 | None:
    held = _ACTIVE_CUSTODY.get()
    if held is None:
        return None
    if held.root != root:
        return None
    try:
        held.verify()
    except PublicationPhysicalIoV1Error as error:
        raise QualificationTransactionV2Error(
            f"transaction physical root custody changed: {error}"
        ) from error
    return held


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationTransactionV2Error(message)


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise QualificationTransactionV2Error(
            "qualification transaction value is not canonical JSON"
        ) from error


def _self_sha(value: Mapping[str, Any], field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return hashlib.sha256(_canonical(unsigned).rstrip(b"\n")).hexdigest()


def _is_link(path: Path, info: os.stat_result | None = None) -> bool:
    observed = info if info is not None else path.lstat()
    attributes = int(getattr(observed, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    junction = getattr(os.path, "isjunction", lambda _value: False)
    return stat.S_ISLNK(observed.st_mode) or bool(attributes & reparse) or junction(path)


def _root(project_root: Path | str) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
        info = root.lstat()
    except OSError as error:
        raise QualificationTransactionV2Error("project_root is unavailable") from error
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link(root, info),
        "project_root must be a physical directory",
    )
    return root


def _under_root(root: Path, value: Path | str, *, label: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        text = raw.as_posix()
        pure = PurePosixPath(text)
        _require(
            bool(text)
            and pure.as_posix() == text
            and not pure.is_absolute()
            and all(part not in {"", ".", ".."} for part in pure.parts),
            f"{label} path is not canonical relative",
        )
        raw = root.joinpath(*pure.parts)
    path = Path(os.path.abspath(os.fspath(raw)))
    try:
        path.relative_to(root)
    except ValueError as error:
        raise QualificationTransactionV2Error(f"{label} escaped project_root") from error
    return path


def _physical_file(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationTransactionV2Error(f"{label} is missing") from error
    _require(
        stat.S_ISREG(info.st_mode)
        and not _is_link(path, info)
        and int(info.st_nlink) == 1
        and resolved == path,
        f"{label} must be one canonical physical file",
    )
    return path


def _physical_directory(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationTransactionV2Error(f"{label} is missing") from error
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link(path, info) and resolved == path,
        f"{label} must be a canonical physical directory",
    )
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    _require(
        (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        f"physical input changed while hashing: {path}",
    )
    return digest.hexdigest()


def file_descriptor(project_root: Path | str, value: Path | str) -> dict[str, Any]:
    """Return the canonical project-relative descriptor of one physical file."""

    root = _root(project_root)
    held = _custody(root)
    if held is not None:
        try:
            descriptor, _payload, _identity = held.read_descriptor_identity(
                value,
                label="descriptor input",
                maximum=1024 * 1024 * 1024,
                capture=False,
            )
        except PublicationPhysicalIoV1Error as error:
            raise QualificationTransactionV2Error(
                f"descriptor input physical custody failed: {error}"
            ) from error
        return descriptor
    path = _physical_file(root, value, label="descriptor input")
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256_file(path),
    }


def _descriptor_matches(root: Path, value: Any, *, label: str) -> bool:
    if type(value) is not dict or set(value) != {"path", "size_bytes", "sha256"}:
        return False
    try:
        observed = file_descriptor(root, str(value["path"]))
    except (OSError, QualificationTransactionV2Error):
        return False
    return observed == value


def _read_json(root: Path, value: Path | str, *, label: str) -> tuple[Path, dict[str, Any]]:
    held = _custody(root)
    if held is None:
        path = _physical_file(root, value, label=label)
        raw = path.read_bytes()
    else:
        try:
            _descriptor, captured, _identity = held.read_descriptor_identity(
                value, label=label, maximum=1024 * 1024 * 1024, capture=True
            )
        except PublicationPhysicalIoV1Error as error:
            raise QualificationTransactionV2Error(
                f"{label} physical custody failed: {error}"
            ) from error
        assert captured is not None
        raw = captured
        path = _under_root(root, value, label=label)
    try:
        parsed = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationTransactionV2Error(f"{label} is not JSON") from error
    _require(type(parsed) is dict and raw == _canonical(parsed), f"{label} is not canonical JSON")
    return path, parsed


def _default_load_identity_patch(**kwargs: Any) -> dict[str, Any]:
    from publication_qualification_image_refreeze_v1 import load_identity_patch

    return load_identity_patch(**kwargs)


def _default_load_parity_acceptance(**kwargs: Any) -> dict[str, Any]:
    receipt_path = Path(kwargs["receipt_path"])
    try:
        receipt = json.loads(receipt_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationTransactionV2Error(
            "model-parity receipt kind cannot be determined"
        ) from error
    if (
        type(receipt) is dict
        and receipt.get("schema_version") == 4
        and receipt.get("artifact_kind")
        == "vast_checkpoint_model_parity_acceptance_receipt_v4"
    ):
        from checkpoint_model_parity_acceptance_v4 import (
            load_verified_model_parity_acceptance_v4,
        )

        return load_verified_model_parity_acceptance_v4(**kwargs)
    from checkpoint_model_parity_acceptance import (
        load_verified_model_parity_acceptance,
    )

    return load_verified_model_parity_acceptance(**kwargs)


def _validate_committed_receipt(
    *,
    root: Path,
    paths: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    _path, value = _read_json(
        root, paths["transaction_receipt"], label="transaction receipt"
    )
    _require(
        value == expected
        and value.get("receipt_sha256") == _self_sha(value, "receipt_sha256"),
        "transaction receipt identity/content drifted",
    )
    for field in (
        "hardware_resource_collector",
        "image_identity_patch",
        "accepted_model_parity_manifest",
        "accepted_model_parity_assessment",
        "accepted_model_parity_receipt",
    ):
        _require(
            _descriptor_matches(root, value.get(field), label=field),
            f"transaction receipt descriptor drifted: {field}",
        )

    artifact_descriptors: list[tuple[str, Any]] = []
    fragments = value.get("fragments")
    candidate = value.get("candidate")
    bootstrap = value.get("bootstrap")
    _require(
        type(fragments) is dict and set(fragments) == set(SYSTEMS),
        "transaction receipt fragment coverage drifted",
    )
    _require(
        type(candidate) is dict
        and set(candidate) == {"index", "manifest", "receipt"},
        "transaction receipt candidate coverage drifted",
    )
    _require(
        type(bootstrap) is dict
        and set(bootstrap) == {"mapping", "calibrations", "receipt"}
        and type(bootstrap.get("calibrations")) is dict
        and set(bootstrap["calibrations"]) == set(SYSTEMS),
        "transaction receipt bootstrap coverage drifted",
    )
    artifact_descriptors.extend(
        (f"fragment {system}", fragments[system]) for system in SYSTEMS
    )
    artifact_descriptors.extend(
        (f"candidate {field}", candidate[field])
        for field in ("index", "manifest", "receipt")
    )
    artifact_descriptors.append(("bootstrap mapping", bootstrap["mapping"]))
    artifact_descriptors.extend(
        (f"bootstrap calibration {system}", bootstrap["calibrations"][system])
        for system in SYSTEMS
    )
    artifact_descriptors.append(("bootstrap receipt", bootstrap["receipt"]))
    for label, descriptor in artifact_descriptors:
        _require(
            _descriptor_matches(root, descriptor, label=label),
            f"transaction receipt descriptor drifted: {label}",
        )


def _cold_validate_committed_transaction(
    *, root: Path, receipt_path: Path
) -> None:
    """Autonomously cold-load every descriptor from a committed receipt."""

    _path, receipt = _read_json(
        root, receipt_path, label="cold transaction receipt"
    )
    _require(
        receipt.get("schema_version") == SCHEMA_VERSION
        and receipt.get("artifact_kind") == TRANSACTION_KIND
        and receipt.get("receipt_sha256") == _self_sha(receipt, "receipt_sha256"),
        "cold transaction receipt identity drifted",
    )
    _validate_committed_receipt(
        root=root,
        paths={"transaction_receipt": receipt_path},
        expected=receipt,
    )


cold_validate_committed_transaction_v2 = _cold_validate_committed_transaction


__all__ = [
    "QualificationTransactionV2Error",
    "TRANSACTION_KIND",
    "TRANSACTION_RECEIPT_FILENAME",
    "cold_validate_committed_transaction_v2",
    "file_descriptor",
]
