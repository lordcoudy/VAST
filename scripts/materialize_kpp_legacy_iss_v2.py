#!/usr/bin/env python3
"""Materialize the receipt-bound legacy ISS v2 dataset as one fixed subtree.

The production route is Windows-only.  It holds directory-handle custody from
the project root through ``data/videos/kpp``, creates every missing destination
ancestor privately with ``NtCreateFile``, and publishes the completed dataset
directory with a no-replace handle rename.  Source media paths are accepted
only from the three externally pinned receipts after the complete graph has
been validated by :mod:`kpp_dataset_contract`.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ctypes import wintypes

from extract_kpp_legacy_iss import (
    ExtractionError,
    _WindowsDirectoryCustody,
    _atomic_publish_directory,
    _copy_pinned_snapshot,
    _create_private_working_directory,
    _create_windows_private_working_directory_with_custody,
    _is_reparse_or_symlink,
    _open_windows_directory_custody,
    _validate_private_publication_set,
    _validate_windows_direct_child_custody,
    _windows_directory_final_path,
    _windows_directory_information,
    _windows_private_directory_acl_is_exact,
    _windows_private_directory_sddl,
    _windows_publish_directory_by_handle,
)
from kpp_dataset_contract import (
    DATASET_NAMES,
    GENERATION_ID,
    KppDatasetContractError,
    build_dataset_entries,
)


DATASET_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
MATERIALIZATION_RECEIPT_NAME = "kpp_iss_v2_materialization_receipt.json"
MATERIALIZATION_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_materialization_receipt"
)
MATERIALIZATION_RECEIPT_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-materialization-receipt:v1\0"
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ROLES = ("underbody", "front_gate")
_VARIANTS = ("avi", "h264", "h265")
_DATASET_ROOT_PARTS = tuple(PurePosixPath(DATASET_ROOT).parts)
_EXPECTED_DIRECTORIES = frozenset(
    {"avi", "h264", "h265", "metadata", "receipts"}
)
_EXPECTED_FILES = frozenset(
    {
        "avi/iss_v2_underbody.avi",
        "avi/iss_v2_front_gate.avi",
        "h264/iss_v2_underbody.mp4",
        "h264/iss_v2_front_gate.mp4",
        "h265/iss_v2_underbody.mp4",
        "h265/iss_v2_front_gate.mp4",
        "metadata/iss_v2_underbody_metadata.json",
        "receipts/kpp_iss_v2_extraction_receipt.json",
        "receipts/kpp_iss_v2_transcode_receipt.json",
        MATERIALIZATION_RECEIPT_NAME,
    }
)
_RECEIPT_DESTINATIONS = {
    "extraction": "receipts/kpp_iss_v2_extraction_receipt.json",
    "transcode": "receipts/kpp_iss_v2_transcode_receipt.json",
    "metadata": "metadata/iss_v2_underbody_metadata.json",
}


class MaterializationError(RuntimeError):
    """Raised when the v2 dataset cannot be materialized without ambiguity."""


@dataclass(frozen=True)
class _TestAdapters:
    """Path-only test seam; the public entry point never accepts this value."""

    after_copies: Callable[[Path], None] | None = None
    after_receipt: Callable[[Path], None] | None = None


@dataclass(frozen=True)
class _ReceiptInput:
    role: str
    path: Path
    relative_path: str
    value: dict[str, Any]
    payload: bytes
    file_sha256: str

    @property
    def artifact(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "size_bytes": len(self.payload),
            "sha256": self.file_sha256,
        }


@dataclass(frozen=True)
class _FrozenFile:
    relative_path: str
    identity: tuple[int, int]
    size_bytes: int
    sha256: str
    label: str


def _require_sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or _SHA256_RE.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise MaterializationError(
            f"{label} must be an exact nonzero lowercase SHA-256"
        )
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MaterializationError(
            "materialization receipt must be canonical-JSON serializable"
        ) from exc
    return (encoded + "\n").encode("ascii")


def _materialization_receipt_sha256(value: Mapping[str, object]) -> str:
    unsigned = dict(value)
    unsigned.pop("materialization_receipt_sha256", None)
    return hashlib.sha256(
        MATERIALIZATION_RECEIPT_DOMAIN + _canonical_bytes(unsigned)
    ).hexdigest()


def _validated_project_root(value: Path) -> Path:
    root = value.absolute()
    try:
        if not root.is_dir() or _is_reparse_or_symlink(root):
            raise MaterializationError(
                "project_root must be a plain existing directory"
            )
    except OSError as exc:
        raise MaterializationError(f"could not inspect project_root: {exc}") from exc
    return root


def _path_exists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _require_plain_source_path(
    root: Path,
    value: Path,
    *,
    label: str,
) -> tuple[Path, str]:
    candidate = value if value.is_absolute() else root / value
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise MaterializationError(f"{label} must stay inside project_root") from exc
    if not relative.parts:
        raise MaterializationError(f"{label} must name a file")
    first = relative.parts[0]
    staging_matches = (
        first.casefold() == "staging" if os.name == "nt" else first == "staging"
    )
    if not staging_matches:
        raise MaterializationError(f"{label} must stay inside project_root/staging")

    current = root
    try:
        for component in relative.parts[:-1]:
            current = current / component
            if (
                not current.is_dir()
                or _is_reparse_or_symlink(current)
            ):
                raise MaterializationError(
                    f"{label} parent chain must contain only plain directories"
                )
        if not _path_exists(candidate):
            raise MaterializationError(f"{label} does not exist")
        if _is_reparse_or_symlink(candidate):
            raise MaterializationError(
                f"{label} must not be a symlink or reparse point"
            )
        observed = candidate.stat()
    except FileNotFoundError as exc:
        raise MaterializationError(f"{label} does not exist") from exc
    except OSError as exc:
        raise MaterializationError(f"could not inspect {label}: {exc}") from exc
    if not stat.S_ISREG(observed.st_mode) or observed.st_size <= 0:
        raise MaterializationError(f"{label} must be a non-empty regular file")
    return candidate, relative.as_posix()


def _stable_read_receipt(
    root: Path,
    path_value: Path,
    *,
    role: str,
    expected_sha256: str,
) -> _ReceiptInput:
    expected = _require_sha256(
        expected_sha256,
        label=f"{role} receipt external SHA-256 pin",
    )
    path, relative = _require_plain_source_path(
        root,
        path_value,
        label=f"{role} receipt",
    )
    before = path.stat()
    payload_parts: list[bytes] = []
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(8 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                payload_parts.append(chunk)
            handle_state = os.fstat(source.fileno())
        after = path.stat()
    except OSError as exc:
        raise MaterializationError(f"could not read {role} receipt: {exc}") from exc
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(handle_state, field) for field in fields):
        raise MaterializationError(f"{role} receipt changed while it was read")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise MaterializationError(f"{role} receipt changed after it was read")
    observed_hash = digest.hexdigest()
    if observed_hash != expected:
        raise MaterializationError(
            f"{role} receipt SHA-256 does not match its external pin"
        )
    payload = b"".join(payload_parts)
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(
            f"{role} receipt is not canonical ASCII JSON"
        ) from exc
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise MaterializationError(f"{role} receipt must be a JSON object")
    return _ReceiptInput(
        role=role,
        path=path,
        relative_path=relative,
        value=value,
        payload=payload,
        file_sha256=observed_hash,
    )


def _plain_relative_source(
    root: Path,
    value: object,
    *,
    label: str,
    require_file: bool,
) -> tuple[Path, str]:
    if type(value) is not str:
        raise MaterializationError(f"{label} path must be a string")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in ("", ".", "..") for part in pure.parts)
        or "\\" in value
    ):
        raise MaterializationError(f"{label} path must be a safe relative path")
    path_value = Path(*pure.parts)
    if require_file:
        return _require_plain_source_path(root, path_value, label=label)
    candidate = (root / path_value).absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise MaterializationError(f"{label} must stay inside project_root") from exc
    first = relative.parts[0]
    staging_matches = (
        first.casefold() == "staging" if os.name == "nt" else first == "staging"
    )
    if not staging_matches:
        raise MaterializationError(f"{label} must stay inside project_root/staging")
    return candidate, relative.as_posix()


def _require_mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MaterializationError(f"{label} must be an object")
    result = dict(value)
    if any(type(key) is not str for key in result):
        raise MaterializationError(f"{label} keys must be strings")
    return result


def _require_array(value: object, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise MaterializationError(f"{label} must be an array")
    return list(value)


def _media_destination(variant: str, role: str) -> str:
    suffix = "avi" if variant == "avi" else "mp4"
    return f"{variant}/iss_v2_{role}.{suffix}"


def _validated_installation_plan(
    *,
    root: Path,
    receipts: Mapping[str, _ReceiptInput],
    dataset_entries: Mapping[str, Mapping[str, object]],
    require_source_files: bool,
) -> list[dict[str, object]]:
    extraction_outputs: dict[str, dict[str, Any]] = {}
    for raw in _require_array(
        receipts["extraction"].value.get("outputs"),
        label="extraction outputs",
    ):
        item = _require_mapping(raw, label="extraction output")
        role = item.get("role")
        if type(role) is not str or role in extraction_outputs:
            raise MaterializationError("extraction output role set is invalid")
        extraction_outputs[role] = item
    if set(extraction_outputs) != set(_ROLES):
        raise MaterializationError("extraction output role set is not exact")

    transcode_outputs: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in _require_array(
        receipts["transcode"].value.get("outputs"),
        label="transcode outputs",
    ):
        item = _require_mapping(raw, label="transcode output")
        variant = item.get("codec_variant")
        role = item.get("role")
        key = (variant, role)
        if (
            type(variant) is not str
            or type(role) is not str
            or key in transcode_outputs
        ):
            raise MaterializationError("transcode output key set is invalid")
        transcode_outputs[(variant, role)] = item
    expected_transcodes = {
        (variant, role)
        for variant in ("h264", "h265")
        for role in _ROLES
    }
    if set(transcode_outputs) != expected_transcodes:
        raise MaterializationError("transcode output key set is not exact")

    contract_media: dict[tuple[str, str], dict[str, Any]] = {}
    for variant in _VARIANTS:
        entry = _require_mapping(
            dataset_entries[DATASET_NAMES[variant]],
            label=f"{variant} dataset entry",
        )
        provenance = _require_mapping(
            entry.get("provenance"),
            label=f"{variant} dataset provenance",
        )
        for raw in _require_array(
            provenance.get("media_artifacts"),
            label=f"{variant} media artifacts",
        ):
            item = _require_mapping(raw, label=f"{variant} media artifact")
            role = item.get("role")
            if type(role) is not str or (variant, role) in contract_media:
                raise MaterializationError(
                    f"{variant} contract media role set is invalid"
                )
            contract_media[(variant, role)] = item
    if set(contract_media) != {
        (variant, role) for variant in _VARIANTS for role in _ROLES
    }:
        raise MaterializationError("contract media artifact set is not exact")

    plan: list[dict[str, object]] = []
    for variant in _VARIANTS:
        for role in _ROLES:
            source_item = (
                extraction_outputs[role]
                if variant == "avi"
                else transcode_outputs[(variant, role)]
            )
            contract_item = contract_media[(variant, role)]
            relative_destination = _media_destination(variant, role)
            expected_contract_path = f"{DATASET_ROOT}/{relative_destination}"
            if contract_item.get("path") != expected_contract_path:
                raise MaterializationError(
                    f"{variant}/{role} contract destination is not the fixed subtree"
                )
            for key in ("size_bytes", "sha256"):
                if source_item.get(key) != contract_item.get(key):
                    raise MaterializationError(
                        f"{variant}/{role} receipt-to-contract {key} binding drifted"
                    )
            source_path, source_relative = _plain_relative_source(
                root,
                source_item.get("path"),
                label=f"{variant}/{role} media source",
                require_file=require_source_files,
            )
            size = source_item.get("size_bytes")
            if type(size) is not int or size <= 0:
                raise MaterializationError(
                    f"{variant}/{role} media size_bytes must be positive"
                )
            plan.append(
                {
                    "artifact_kind": "media",
                    "codec_variant": variant,
                    "role": role,
                    "source": source_path,
                    "source_path": source_relative,
                    "installed_path": f"{DATASET_ROOT}/{relative_destination}",
                    "candidate_path": relative_destination,
                    "size_bytes": size,
                    "sha256": _require_sha256(
                        source_item.get("sha256"),
                        label=f"{variant}/{role} media SHA-256",
                    ),
                }
            )

    metadata_entry = _require_mapping(
        dataset_entries[DATASET_NAMES["avi"]],
        label="AVI dataset entry",
    )
    annotations = _require_mapping(
        metadata_entry.get("annotations"),
        label="AVI annotations",
    )
    metadata_destination = f"{DATASET_ROOT}/{_RECEIPT_DESTINATIONS['metadata']}"
    if annotations.get("path") != metadata_destination:
        raise MaterializationError(
            "metadata contract destination is not the fixed subtree"
        )
    if annotations.get("sha256") != receipts["metadata"].file_sha256:
        raise MaterializationError(
            "metadata receipt-to-contract file SHA-256 binding drifted"
        )
    return plan


def _assessed_dataset_entries(
    value: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    assessed = copy.deepcopy(dict(value))
    for dataset_name in DATASET_NAMES.values():
        entry = assessed[dataset_name]
        entry["status"] = "physically_assessed_candidate"
        entry["publishable"] = False
        provenance = entry["provenance"]
        provenance["physical_artifact_bytes_assessed"] = True
        provenance["publication_authorized"] = False
    return assessed


def _copy_verified(
    *,
    source: Path,
    target: Path,
    expected_sha256: str,
    expected_size_bytes: int,
    label: str,
) -> dict[str, object]:
    try:
        descriptor, _ = _copy_pinned_snapshot(
            source=source,
            target=target,
            expected_sha256=expected_sha256,
            label=label,
        )
    except ExtractionError as exc:
        raise MaterializationError(str(exc)) from exc
    if descriptor.get("size_bytes") != expected_size_bytes:
        raise MaterializationError(f"{label} size does not match its receipt")
    try:
        source_state = source.stat()
        target_state = target.stat()
    except OSError as exc:
        raise MaterializationError(f"could not inspect copied {label}: {exc}") from exc
    if (source_state.st_dev, source_state.st_ino) == (
        target_state.st_dev,
        target_state.st_ino,
    ):
        raise MaterializationError(f"{label} was not copied to distinct bytes")
    return {
        "size_bytes": expected_size_bytes,
        "sha256": expected_sha256,
    }


def _observe_verified_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    label: str,
) -> os.stat_result:
    try:
        if _is_reparse_or_symlink(path):
            raise MaterializationError(
                f"installed {label} must not be a link or reparse point"
            )
        before_lstat = path.lstat()
        if not stat.S_ISREG(before_lstat.st_mode):
            raise MaterializationError(
                f"installed {label} must remain a regular file"
            )
        before = path.stat()
        if int(before.st_nlink) != 1:
            raise MaterializationError(
                f"installed {label} link count must remain exactly one"
            )
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
            handle_state = os.fstat(source.fileno())
        after = path.stat()
    except FileNotFoundError as exc:
        raise MaterializationError(f"installed {label} is missing") from exc
    except OSError as exc:
        raise MaterializationError(f"could not verify installed {label}: {exc}") from exc
    fields = ("st_dev", "st_ino", "st_nlink", "st_size", "st_mtime_ns")
    stable = all(
        getattr(before, field) == getattr(handle_state, field) == getattr(after, field)
        for field in fields
    )
    if (
        not stable
        or int(after.st_size) != expected_size_bytes
        or digest.hexdigest() != expected_sha256
    ):
        raise MaterializationError(f"installed {label} does not match its receipt")
    if int(after.st_nlink) != 1:
        raise MaterializationError(
            f"installed {label} link count must remain exactly one"
        )
    return after


def _stable_verify_installed(
    path: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    label: str,
) -> None:
    _observe_verified_file(
        path,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
        label=label,
    )


def _freeze_installed_file(
    root: Path,
    path: Path,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    label: str,
) -> _FrozenFile:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise MaterializationError(
            f"installed {label} escaped the materialization root"
        ) from exc
    observed = _observe_verified_file(
        path,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
        label=label,
    )
    return _FrozenFile(
        relative_path=relative,
        identity=(int(observed.st_dev), int(observed.st_ino)),
        size_bytes=expected_size_bytes,
        sha256=expected_sha256,
        label=label,
    )


def _verify_frozen_file(root: Path, frozen: _FrozenFile) -> None:
    observed = _observe_verified_file(
        root / Path(*PurePosixPath(frozen.relative_path).parts),
        expected_sha256=frozen.sha256,
        expected_size_bytes=frozen.size_bytes,
        label=frozen.label,
    )
    identity = (int(observed.st_dev), int(observed.st_ino))
    if identity != frozen.identity:
        raise MaterializationError(
            f"installed {frozen.label} identity changed after it was frozen"
        )


def _verify_frozen_set(
    root: Path,
    frozen_files: Sequence[_FrozenFile],
    *,
    expected_count: int = 10,
) -> None:
    if len(frozen_files) != expected_count:
        raise MaterializationError("frozen materialization file set is not exact")
    identities = [item.identity for item in frozen_files]
    if len(set(identities)) != len(identities):
        raise MaterializationError(
            "frozen materialization files must have unique physical identities"
        )
    relative_paths = [item.relative_path for item in frozen_files]
    if len(set(relative_paths)) != len(relative_paths):
        raise MaterializationError("frozen materialization paths are not unique")
    for frozen in frozen_files:
        _verify_frozen_file(root, frozen)


def _write_verified_receipt(path: Path, value: Mapping[str, object]) -> bytes:
    payload = _canonical_bytes(value)
    expected_hash = hashlib.sha256(payload).hexdigest()
    try:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise MaterializationError(
            f"could not write materialization receipt: {exc}"
        ) from exc
    _stable_verify_installed(
        path,
        expected_sha256=expected_hash,
        expected_size_bytes=len(payload),
        label="materialization receipt",
    )
    return payload


def _validate_exact_tree(root: Path) -> None:
    observed_directories: set[str] = set()
    observed_files: set[str] = set()
    try:
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if _is_reparse_or_symlink(path):
                raise MaterializationError(
                    "materialization tree must not contain links or reparse points"
                )
            observed = path.lstat()
            if stat.S_ISDIR(observed.st_mode):
                observed_directories.add(relative)
            elif stat.S_ISREG(observed.st_mode):
                observed_files.add(relative)
            else:
                raise MaterializationError(
                    "materialization tree contains a non-file object"
                )
    except OSError as exc:
        raise MaterializationError(
            f"could not validate materialization tree: {exc}"
        ) from exc
    if observed_directories != set(_EXPECTED_DIRECTORIES):
        raise MaterializationError("materialization directory set is not exact")
    if observed_files != set(_EXPECTED_FILES):
        raise MaterializationError("materialization file set is not exact")


def _installed_artifact_descriptors(
    *,
    installation_plan: Sequence[Mapping[str, object]],
    receipts: Mapping[str, _ReceiptInput],
) -> list[dict[str, object]]:
    artifacts = [
        {
            key: item[key]
            for key in (
                "artifact_kind",
                "codec_variant",
                "role",
                "source_path",
                "installed_path",
                "size_bytes",
                "sha256",
            )
        }
        for item in installation_plan
    ]
    for role in ("metadata", "extraction", "transcode"):
        receipt = receipts[role]
        relative_destination = _RECEIPT_DESTINATIONS[role]
        artifacts.append(
            {
                "artifact_kind": "receipt",
                "receipt_role": role,
                "source_path": receipt.relative_path,
                "installed_path": f"{DATASET_ROOT}/{relative_destination}",
                "size_bytes": len(receipt.payload),
                "sha256": receipt.file_sha256,
            }
        )
    return artifacts


def _build_materialization_receipt(
    *,
    assessed_entries: Mapping[str, Mapping[str, object]],
    installation_plan: Sequence[Mapping[str, object]],
    receipts: Mapping[str, _ReceiptInput],
    authoritative: bool,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": MATERIALIZATION_ARTIFACT_KIND,
        "generation_id": GENERATION_ID,
        "status": "physically_assessed_candidate",
        "dataset_root": DATASET_ROOT,
        "publishable": False,
        "publication_authorized": False,
        "source_receipt_external_pins": {
            role: receipts[role].file_sha256
            for role in ("extraction", "transcode", "metadata")
        },
        "installed_artifacts": _installed_artifact_descriptors(
            installation_plan=installation_plan,
            receipts=receipts,
        ),
        "dataset_entries": copy.deepcopy(dict(assessed_entries)),
        "claims": {
            "source_receipts_externally_pinned": True,
            "authoritative_receipt_graph_validated": True,
            "media_sources_derived_from_validated_receipts": True,
            "source_and_installed_bytes_stably_rehashed": True,
            "physical_artifact_bytes_assessed": True,
            "exact_output_tree_validated": True,
            "output_set_directory_published_atomically": True,
            "windows_project_root_data_videos_kpp_and_working_directory_"
            "handle_custody_validated": authoritative,
            "publishable": False,
            "publication_authorized": False,
        },
    }
    receipt["materialization_receipt_sha256"] = (
        _materialization_receipt_sha256(receipt)
    )
    return receipt


def _expected_installed_file_specs(
    *,
    installation_plan: Sequence[Mapping[str, object]],
    receipts: Mapping[str, _ReceiptInput],
    materialization_receipt: Mapping[str, object],
) -> list[tuple[str, str, int, str]]:
    specs = [
        (
            str(item["candidate_path"]),
            str(item["sha256"]),
            int(item["size_bytes"]),
            f"{item['codec_variant']}/{item['role']} media",
        )
        for item in installation_plan
    ]
    for role in ("metadata", "extraction", "transcode"):
        receipt = receipts[role]
        specs.append(
            (
                _RECEIPT_DESTINATIONS[role],
                receipt.file_sha256,
                len(receipt.payload),
                f"{role} receipt",
            )
        )
    payload = _canonical_bytes(materialization_receipt)
    specs.append(
        (
            MATERIALIZATION_RECEIPT_NAME,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            "materialization receipt",
        )
    )
    return specs


def _validate_existing_materialization(
    target: Path,
    *,
    installation_plan: Sequence[Mapping[str, object]],
    receipts: Mapping[str, _ReceiptInput],
    expected_receipt: Mapping[str, object],
) -> dict[str, object]:
    try:
        if not target.is_dir() or _is_reparse_or_symlink(target):
            raise MaterializationError("target is not a plain directory")
        _validate_exact_tree(target)
        frozen_files = [
            _freeze_installed_file(
                target,
                target / Path(*PurePosixPath(relative).parts),
                expected_sha256=digest,
                expected_size_bytes=size,
                label=label,
            )
            for relative, digest, size, label in _expected_installed_file_specs(
                installation_plan=installation_plan,
                receipts=receipts,
                materialization_receipt=expected_receipt,
            )
        ]
        _verify_frozen_set(target, frozen_files)
        receipt_path = target / MATERIALIZATION_RECEIPT_NAME
        actual_receipt = json.loads(receipt_path.read_text("ascii"))
        if actual_receipt != expected_receipt:
            raise MaterializationError(
                "receipt graph or claims do not match the pinned inputs"
            )
        if (
            actual_receipt.get("materialization_receipt_sha256")
            != _materialization_receipt_sha256(actual_receipt)
        ):
            raise MaterializationError("receipt self-hash does not match")
        _verify_frozen_set(target, frozen_files)
        return copy.deepcopy(dict(actual_receipt))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializationError("receipt is not canonical JSON") from exc
    except MaterializationError as exc:
        raise MaterializationError(f"existing materialization {exc}") from exc


def _bootstrap_test_dataset_parent(root: Path) -> Path:
    current = root
    for component in _DATASET_ROOT_PARTS[:-1]:
        current = current / component
        if _path_exists(current):
            if not current.is_dir() or _is_reparse_or_symlink(current):
                raise MaterializationError(
                    "dataset parent chain must contain only plain directories"
                )
            continue
        try:
            current.mkdir()
        except OSError as exc:
            raise MaterializationError(
                f"could not create test dataset parent: {exc}"
            ) from exc
    return current


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


def _open_windows_target_custody_with_acl(
    path: Path,
    *,
    label: str,
) -> _WindowsDirectoryCustody:
    """Open a verified no-delete-share directory handle with READ_CONTROL."""

    baseline = _open_windows_directory_custody(
        path,
        label=label,
        require_delete_access=False,
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    raw_handle: int | None = None
    enhanced: _WindowsDirectoryCustody | None = None
    try:
        handle = create_file(
            str(path.absolute()),
            0x00020000 | 0x00000080 | 0x00000020 | 0x00000004,
            0x00000001 | 0x00000002,
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in (None, invalid_handle):
            raise MaterializationError(
                "could not acquire target ACL custody: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        raw_handle = int(handle)
        identity = _windows_directory_information(raw_handle, label=label)
        _windows_directory_final_path(raw_handle, label=label)
        if identity != baseline.identity:
            raise MaterializationError(
                "target identity changed while ACL custody was acquired"
            )
        enhanced = _WindowsDirectoryCustody(
            handle=raw_handle,
            identity=identity,
            label=label,
        )
        raw_handle = None
        baseline.close()
        return enhanced
    except Exception:
        if enhanced is not None:
            enhanced.close()
        elif raw_handle is not None:
            close_handle(wintypes.HANDLE(raw_handle))
        if baseline._handle is not None:
            baseline.close()
        raise


def _windows_private_directory_custody_acl_is_exact(
    custody: _WindowsDirectoryCustody,
) -> bool:
    """Compare owner+DACL through the held directory handle, never its path."""

    if os.name != "nt":
        return False
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi32.GetSecurityInfo
    get_security.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security.restype = wintypes.DWORD
    convert = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    result = get_security(
        wintypes.HANDLE(custody.handle),
        1,
        0x00000005,
        None,
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result != 0 or not descriptor.value:
        raise MaterializationError(
            "could not read custodied target ACL: "
            f"Win32 error {result}"
        )
    rendered = ctypes.c_wchar_p()
    rendered_length = wintypes.DWORD()
    try:
        if not convert(
            descriptor,
            1,
            0x00000005,
            ctypes.byref(rendered),
            ctypes.byref(rendered_length),
        ):
            raise MaterializationError(
                "could not render custodied target ACL: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        try:
            return rendered.value == _windows_private_directory_sddl()
        finally:
            if rendered:
                local_free(ctypes.cast(rendered, ctypes.c_void_p))
    finally:
        local_free(descriptor)


def _discard_empty_windows_directory_by_handle(
    *,
    parent: _WindowsDirectoryCustody,
    child: _WindowsDirectoryCustody,
    expected_name: str,
) -> None:
    """Mark one unpublished, empty, identity-held bootstrap child for deletion."""

    _validate_windows_direct_child_custody(
        parent=parent,
        child=child,
        expected_name=expected_name,
    )
    information = _FileDispositionInfo(True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    if not set_information(
        wintypes.HANDLE(child.handle),
        4,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise MaterializationError(
            "could not discard unpublished bootstrap candidate by handle: "
            f"Win32 error {ctypes.get_last_error()}"
        )


def _bootstrap_windows_dataset_parent(
    *,
    root: Path,
    root_custody: _WindowsDirectoryCustody,
) -> tuple[Path, list[_WindowsDirectoryCustody]]:
    """Create/open ``data/videos/kpp`` under held custody, one edge at a time."""

    current_path = root
    parent_custody = root_custody
    acquired: list[_WindowsDirectoryCustody] = []
    labels = {
        "data": "materialization data directory",
        "videos": "materialization videos directory",
        "kpp": "materialization kpp directory",
    }
    unpublished: tuple[
        _WindowsDirectoryCustody,
        _WindowsDirectoryCustody,
        str,
    ] | None = None
    try:
        for component in _DATASET_ROOT_PARTS[:-1]:
            child_path = current_path / component
            label = labels[component]
            created = False
            if _path_exists(child_path):
                if not child_path.is_dir() or _is_reparse_or_symlink(child_path):
                    raise MaterializationError(
                        "dataset parent chain must contain only plain directories"
                    )
                child_custody = _open_windows_directory_custody(
                    child_path,
                    label=label,
                    require_delete_access=False,
                )
            else:
                candidate_path, child_custody = (
                    _create_windows_private_working_directory_with_custody(
                        parent=parent_custody,
                        prefix=f".{component}.",
                        suffix=".bootstrap-candidate",
                        label=label,
                    )
                )
                created = True
            # Ownership transfers to this local list before any later operation
            # can fail.  On success the caller receives it; on failure this
            # helper closes every locally acquired handle itself.
            acquired.append(child_custody)
            if created:
                unpublished = (
                    parent_custody,
                    child_custody,
                    candidate_path.name,
                )
                _windows_publish_directory_by_handle(
                    source=child_custody,
                    parent=parent_custody,
                    target_name=component,
                )
                unpublished = None
                if not _windows_private_directory_acl_is_exact(child_path):
                    raise MaterializationError(
                        f"new {component} directory ACL does not match its policy"
                    )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=child_custody,
                expected_name=component,
            )
            parent_custody = child_custody
            current_path = child_path
        return current_path, acquired
    except Exception as exc:
        if unpublished is not None:
            cleanup_parent, cleanup_child, cleanup_name = unpublished
            try:
                _discard_empty_windows_directory_by_handle(
                    parent=cleanup_parent,
                    child=cleanup_child,
                    expected_name=cleanup_name,
                )
            except Exception as cleanup_exc:
                exc.add_note(
                    "unpublished bootstrap candidate cleanup failed: "
                    f"{cleanup_exc}"
                )
        for custody in reversed(acquired):
            try:
                custody.close()
            except Exception as close_exc:
                exc.add_note(
                    f"bootstrap custody cleanup failed for {custody.label}: "
                    f"{close_exc}"
                )
        raise


def _cleanup_test_candidate(working: Path) -> None:
    """Remove only a path-fallback candidate allocated by this invocation."""

    if not _path_exists(working):
        return
    if (
        working.parent.name != "kpp"
        or not working.name.startswith(".kpp_legacy_iss_v2.")
        or not working.name.endswith(".candidate")
        or _is_reparse_or_symlink(working)
    ):
        raise MaterializationError("refusing to clean an unowned candidate")
    for relative in _EXPECTED_FILES:
        path = working / Path(*PurePosixPath(relative).parts)
        if _path_exists(path):
            if _is_reparse_or_symlink(path) or not path.is_file():
                raise MaterializationError(
                    "refusing to clean a non-file candidate entry"
                )
            path.unlink()
    for relative in sorted(_EXPECTED_DIRECTORIES, key=lambda item: -len(item)):
        path = working / relative
        if _path_exists(path):
            path.rmdir()
    working.rmdir()


def _materialize_kpp_legacy_iss_v2_impl(
    *,
    project_root: Path,
    extraction_receipt: Path,
    expected_extraction_receipt_sha256: str,
    transcode_receipt: Path,
    expected_transcode_receipt_sha256: str,
    metadata_receipt: Path,
    expected_metadata_receipt_sha256: str,
    test_adapters: _TestAdapters | None,
) -> dict[str, object]:
    root = _validated_project_root(project_root)
    authoritative = test_adapters is None
    if authoritative and os.name != "nt":
        raise MaterializationError(
            "authoritative KPP v2 materialization requires Windows"
        )

    root_custody: _WindowsDirectoryCustody | None = None
    parent_custodies: list[_WindowsDirectoryCustody] = []
    working_custody: _WindowsDirectoryCustody | None = None
    working: Path | None = None
    published = False
    try:
        if authoritative:
            root_custody = _open_windows_directory_custody(
                root,
                label="materialization project root",
                require_delete_access=False,
            )

        receipts = {
            "extraction": _stable_read_receipt(
                root,
                extraction_receipt,
                role="extraction",
                expected_sha256=expected_extraction_receipt_sha256,
            ),
            "transcode": _stable_read_receipt(
                root,
                transcode_receipt,
                role="transcode",
                expected_sha256=expected_transcode_receipt_sha256,
            ),
            "metadata": _stable_read_receipt(
                root,
                metadata_receipt,
                role="metadata",
                expected_sha256=expected_metadata_receipt_sha256,
            ),
        }
        identities = {
            (item.path.stat().st_dev, item.path.stat().st_ino)
            for item in receipts.values()
        }
        if len(identities) != 3:
            raise MaterializationError(
                "the three receipt inputs must be physically distinct files"
            )

        try:
            unassessed_entries = build_dataset_entries(
                extraction_receipt=receipts["extraction"].value,
                extraction_receipt_artifact=receipts["extraction"].artifact,
                transcode_receipt=receipts["transcode"].value,
                transcode_receipt_artifact=receipts["transcode"].artifact,
                metadata_receipt=receipts["metadata"].value,
                metadata_receipt_artifact=receipts["metadata"].artifact,
            )
        except KppDatasetContractError as exc:
            raise MaterializationError(
                f"authoritative receipt graph is invalid: {exc}"
            ) from exc
        target = root.joinpath(*_DATASET_ROOT_PARTS)
        target_preexists = _path_exists(target)
        installation_plan = _validated_installation_plan(
            root=root,
            receipts=receipts,
            dataset_entries=unassessed_entries,
            require_source_files=not target_preexists,
        )
        assessed_entries = _assessed_dataset_entries(unassessed_entries)
        materialization_receipt = _build_materialization_receipt(
            assessed_entries=assessed_entries,
            installation_plan=installation_plan,
            receipts=receipts,
            authoritative=authoritative,
        )

        if authoritative:
            if root_custody is None:
                raise MaterializationError(
                    "materialization project-root custody was not acquired"
                )
            parent, parent_custodies = _bootstrap_windows_dataset_parent(
                root=root,
                root_custody=root_custody,
            )
        else:
            parent = _bootstrap_test_dataset_parent(root)

        if _path_exists(target):
            if authoritative:
                working_custody = _open_windows_target_custody_with_acl(
                    target,
                    label="existing materialization directory",
                )
                _validate_windows_direct_child_custody(
                    parent=parent_custodies[-1],
                    child=working_custody,
                    expected_name=_DATASET_ROOT_PARTS[-1],
                )
                # The private-set policy is an exact protected, inheritable ACL
                # on the held subtree root.  Child SDDL legitimately renders
                # inherited ACE flags differently; their object/type/link and
                # byte identities are covered by the exact-tree verification.
                if not _windows_private_directory_custody_acl_is_exact(
                    working_custody
                ):
                    raise MaterializationError(
                        "existing materialization target ACL is not private-exact"
                    )
            existing_receipt = _validate_existing_materialization(
                target,
                installation_plan=installation_plan,
                receipts=receipts,
                expected_receipt=materialization_receipt,
            )
            if authoritative:
                if working_custody is None:
                    raise MaterializationError(
                        "existing materialization custody was not acquired"
                    )
                _validate_windows_direct_child_custody(
                    parent=parent_custodies[-1],
                    child=working_custody,
                    expected_name=_DATASET_ROOT_PARTS[-1],
                )
                if not _windows_private_directory_custody_acl_is_exact(
                    working_custody
                ):
                    raise MaterializationError(
                        "existing materialization target ACL changed during "
                        "verification"
                    )
            return existing_receipt

        if authoritative:
            working, working_custody = (
                _create_windows_private_working_directory_with_custody(
                    parent=parent_custodies[-1],
                    prefix=".kpp_legacy_iss_v2.",
                    suffix=".candidate",
                    label="materialization working directory",
                )
            )
        else:
            working = _create_private_working_directory(
                parent=parent,
                prefix=".kpp_legacy_iss_v2.",
                suffix=".candidate",
            )

        if working is None:
            raise MaterializationError("materialization candidate was not created")
        if _is_reparse_or_symlink(working):
            raise MaterializationError(
                "materialization candidate must not be a reparse point"
            )
        if authoritative:
            if (
                root_custody is None
                or len(parent_custodies) != 3
                or working_custody is None
            ):
                raise MaterializationError(
                    "Windows materialization custody chain is incomplete"
                )
            chain = [root_custody, *parent_custodies, working_custody]
            for index, name in enumerate((*_DATASET_ROOT_PARTS[:-1], working.name)):
                _validate_windows_direct_child_custody(
                    parent=chain[index],
                    child=chain[index + 1],
                    expected_name=name,
                )
            if not _windows_private_directory_acl_is_exact(working):
                raise MaterializationError(
                    "materialization candidate ACL does not match its policy"
                )

        try:
            for directory in sorted(_EXPECTED_DIRECTORIES):
                (working / directory).mkdir()
        except OSError as exc:
            raise MaterializationError(
                f"could not create private materialization tree: {exc}"
            ) from exc

        frozen_files: list[_FrozenFile] = []
        for item in installation_plan:
            target_file = working / Path(
                *PurePosixPath(str(item["candidate_path"])).parts
            )
            _copy_verified(
                source=Path(item["source"]),
                target=target_file,
                expected_sha256=str(item["sha256"]),
                expected_size_bytes=int(item["size_bytes"]),
                label=f"{item['codec_variant']}/{item['role']} media",
            )
            frozen_files.append(
                _freeze_installed_file(
                    working,
                    target_file,
                    expected_sha256=str(item["sha256"]),
                    expected_size_bytes=int(item["size_bytes"]),
                    label=f"{item['codec_variant']}/{item['role']} media",
                )
            )

        for role in ("metadata", "extraction", "transcode"):
            receipt_input = receipts[role]
            relative_destination = _RECEIPT_DESTINATIONS[role]
            target_file = working / Path(
                *PurePosixPath(relative_destination).parts
            )
            _copy_verified(
                source=receipt_input.path,
                target=target_file,
                expected_sha256=receipt_input.file_sha256,
                expected_size_bytes=len(receipt_input.payload),
                label=f"{role} receipt",
            )
            frozen_files.append(
                _freeze_installed_file(
                    working,
                    target_file,
                    expected_sha256=receipt_input.file_sha256,
                    expected_size_bytes=len(receipt_input.payload),
                    label=f"{role} receipt",
                )
            )

        if test_adapters is not None and test_adapters.after_copies is not None:
            test_adapters.after_copies(working)
        _verify_frozen_set(working, frozen_files, expected_count=9)
        receipt_payload = _write_verified_receipt(
            working / MATERIALIZATION_RECEIPT_NAME,
            materialization_receipt,
        )
        frozen_files.append(
            _freeze_installed_file(
                working,
                working / MATERIALIZATION_RECEIPT_NAME,
                expected_sha256=hashlib.sha256(receipt_payload).hexdigest(),
                expected_size_bytes=len(receipt_payload),
                label="materialization receipt",
            )
        )
        if test_adapters is not None and test_adapters.after_receipt is not None:
            test_adapters.after_receipt(working)
        _verify_frozen_set(working, frozen_files)
        _validate_exact_tree(working)
        try:
            _validate_private_publication_set(
                working,
                [
                    working / Path(*PurePosixPath(item.relative_path).parts)
                    for item in frozen_files
                ],
            )
        except ExtractionError as exc:
            raise MaterializationError(str(exc)) from exc
        _verify_frozen_set(working, frozen_files)

        if authoritative:
            if working_custody is None or not parent_custodies:
                raise MaterializationError(
                    "Windows materialization publication custody is incomplete"
                )
            _validate_windows_direct_child_custody(
                parent=parent_custodies[-1],
                child=working_custody,
                expected_name=working.name,
            )
            try:
                _windows_publish_directory_by_handle(
                    source=working_custody,
                    parent=parent_custodies[-1],
                    target_name=_DATASET_ROOT_PARTS[-1],
                )
            except ExtractionError as exc:
                raise MaterializationError(str(exc)) from exc
            published = True
            _validate_windows_direct_child_custody(
                parent=parent_custodies[-1],
                child=working_custody,
                expected_name=_DATASET_ROOT_PARTS[-1],
            )
        else:
            try:
                _atomic_publish_directory(working, target)
            except ExtractionError as exc:
                raise MaterializationError(str(exc)) from exc
            published = True

        _validate_exact_tree(target)
        _verify_frozen_set(target, frozen_files)
        return materialization_receipt
    except Exception as exc:
        cleanup_error: Exception | None = None
        if working is not None and not published and not authoritative:
            try:
                _cleanup_test_candidate(working)
            except Exception as cleanup_exc:
                cleanup_error = cleanup_exc
        if cleanup_error is not None:
            exc.add_note(
                f"owned materialization candidate cleanup failed: {cleanup_error}"
            )
        if isinstance(exc, ExtractionError):
            raise MaterializationError(str(exc)) from exc
        raise
    finally:
        close_errors: list[Exception] = []
        if working_custody is not None:
            try:
                working_custody.close()
            except Exception as exc:
                close_errors.append(exc)
        for custody in reversed(parent_custodies):
            try:
                custody.close()
            except Exception as exc:
                close_errors.append(exc)
        if root_custody is not None:
            try:
                root_custody.close()
            except Exception as exc:
                close_errors.append(exc)
        if close_errors and sys.exc_info()[0] is None:
            raise MaterializationError(
                f"could not release Windows materialization custody: {close_errors[0]}"
            ) from close_errors[0]


def materialize_kpp_legacy_iss_v2(
    *,
    project_root: Path,
    extraction_receipt: Path,
    expected_extraction_receipt_sha256: str,
    transcode_receipt: Path,
    expected_transcode_receipt_sha256: str,
    metadata_receipt: Path,
    expected_metadata_receipt_sha256: str,
) -> dict[str, object]:
    """Run the Windows-authoritative materializer without test adapters."""

    return _materialize_kpp_legacy_iss_v2_impl(
        project_root=project_root,
        extraction_receipt=extraction_receipt,
        expected_extraction_receipt_sha256=expected_extraction_receipt_sha256,
        transcode_receipt=transcode_receipt,
        expected_transcode_receipt_sha256=expected_transcode_receipt_sha256,
        metadata_receipt=metadata_receipt,
        expected_metadata_receipt_sha256=expected_metadata_receipt_sha256,
        test_adapters=None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the externally pinned KPP legacy ISS v2 receipt graph "
            "as one fixed, non-publishable dataset subtree."
        )
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--extraction-receipt", required=True, type=Path)
    parser.add_argument("--expected-extraction-receipt-sha256", required=True)
    parser.add_argument("--transcode-receipt", required=True, type=Path)
    parser.add_argument("--expected-transcode-receipt-sha256", required=True)
    parser.add_argument("--metadata-receipt", required=True, type=Path)
    parser.add_argument("--expected-metadata-receipt-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        receipt = materialize_kpp_legacy_iss_v2(
            project_root=arguments.project_root,
            extraction_receipt=arguments.extraction_receipt,
            expected_extraction_receipt_sha256=(
                arguments.expected_extraction_receipt_sha256
            ),
            transcode_receipt=arguments.transcode_receipt,
            expected_transcode_receipt_sha256=(
                arguments.expected_transcode_receipt_sha256
            ),
            metadata_receipt=arguments.metadata_receipt,
            expected_metadata_receipt_sha256=(
                arguments.expected_metadata_receipt_sha256
            ),
        )
    except MaterializationError as exc:
        print(f"KPP legacy ISS v2 materialization blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DATASET_ROOT",
    "MATERIALIZATION_RECEIPT_NAME",
    "MaterializationError",
    "materialize_kpp_legacy_iss_v2",
]
