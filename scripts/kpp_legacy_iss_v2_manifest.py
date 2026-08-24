#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


GENERATION_ID = "kpp_legacy_iss_v2"
DATASET_CONTRACT_VERSION = 2
CHECK_ONLY_PREPARATION_MODE = "check_only_materialized_v1"
DATASET_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
MATERIALIZATION_RECEIPT_PATH = (
    f"{DATASET_ROOT}/kpp_iss_v2_materialization_receipt.json"
)
MATERIALIZATION_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_materialization_receipt"
)
MATERIALIZATION_RECEIPT_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-materialization-receipt:v1\0"
)
EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES = 28131
EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256 = (
    "dd0d2aa38da1281a750806858b555b994a9dcf3c9bcd35e8379dbc9d339f2b33"
)
EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256 = (
    "56e09fd82ab83d4f3e0a711d93658a1cfc69f3bee9fd381df41713ac5b42bda4"
)

DATASET_NAMES = frozenset(
    {
        "kpp_legacy_iss_v2_avi",
        "kpp_legacy_iss_v2_h264",
        "kpp_legacy_iss_v2_h265",
    }
)
_VARIANT_BY_DATASET = {
    "kpp_legacy_iss_v2_avi": "avi",
    "kpp_legacy_iss_v2_h264": "h264",
    "kpp_legacy_iss_v2_h265": "h265",
}
_ROLES = ("underbody", "front_gate")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_PATHS = {
    (variant, role): (
        f"{DATASET_ROOT}/{variant}/iss_v2_{role}."
        f"{'avi' if variant == 'avi' else 'mp4'}"
    )
    for variant in ("avi", "h264", "h265")
    for role in _ROLES
}
_RECEIPT_ARTIFACT_PATHS = {
    "metadata": f"{DATASET_ROOT}/metadata/iss_v2_underbody_metadata.json",
    "extraction": (
        f"{DATASET_ROOT}/receipts/kpp_iss_v2_extraction_receipt.json"
    ),
    "transcode": (
        f"{DATASET_ROOT}/receipts/kpp_iss_v2_transcode_receipt.json"
    ),
}
_EXPECTED_INSTALLED_PATHS = frozenset(
    {*_MEDIA_PATHS.values(), *_RECEIPT_ARTIFACT_PATHS.values()}
)
_EXPECTED_TREE_DIRECTORIES = frozenset(
    {"avi", "h264", "h265", "metadata", "receipts"}
)
_EXPECTED_TREE_FILES = frozenset(
    {
        *(
            str(PurePosixPath(path).relative_to(DATASET_ROOT))
            for path in _EXPECTED_INSTALLED_PATHS
        ),
        "kpp_iss_v2_materialization_receipt.json",
    }
)
_EXPECTED_CLAIMS = {
    "source_receipts_externally_pinned": True,
    "authoritative_receipt_graph_validated": True,
    "media_sources_derived_from_validated_receipts": True,
    "source_and_installed_bytes_stably_rehashed": True,
    "physical_artifact_bytes_assessed": True,
    "exact_output_tree_validated": True,
    "output_set_directory_published_atomically": True,
    (
        "windows_project_root_data_videos_kpp_and_working_directory_"
        "handle_custody_validated"
    ): True,
    "publishable": False,
    "publication_authorized": False,
}
_EXPECTED_DATASET_ENTRY_CANONICAL_SHA256 = {
    "kpp_legacy_iss_v2_avi": (
        "3d8103f9889d4fe866da39f5e2e7977146712d393605bd51f40d427c3c0e2927"
    ),
    "kpp_legacy_iss_v2_h264": (
        "1c825d900d86bc0e9a569965ee9ead42f83b093b476861ae0baa77d1543b1bb5"
    ),
    "kpp_legacy_iss_v2_h265": (
        "5d09936fa103b61caff4b7b9b14e3cf013cad0202d2c809fc47b6093bff60037"
    ),
}
_TOP_LEVEL_RECEIPT_KEYS = {
    "schema_version",
    "artifact_kind",
    "generation_id",
    "status",
    "dataset_root",
    "publishable",
    "publication_authorized",
    "source_receipt_external_pins",
    "installed_artifacts",
    "dataset_entries",
    "claims",
    "materialization_receipt_sha256",
}
_PREPARATION_KEYS = {"mode", "materialization_receipt"}
_RECEIPT_DESCRIPTOR_KEYS = {
    "path",
    "size_bytes",
    "sha256",
    "materialization_receipt_sha256",
}
_MEDIA_ARTIFACT_KEYS = {
    "artifact_kind",
    "codec_variant",
    "role",
    "source_path",
    "installed_path",
    "size_bytes",
    "sha256",
}
_RECEIPT_ARTIFACT_KEYS = {
    "artifact_kind",
    "receipt_role",
    "source_path",
    "installed_path",
    "size_bytes",
    "sha256",
}


class KppLegacyIssV2ManifestError(RuntimeError):
    """Raised when the v2 manifest is not bound to its frozen materialization."""


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KppLegacyIssV2ManifestError(f"{label} must be a mapping")
    return value


def _sequence(value: object, *, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise KppLegacyIssV2ManifestError(f"{label} must be a list")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise KppLegacyIssV2ManifestError(
            f"{label} keys are not exact (missing={missing}, extra={extra})"
        )


def _sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or _SHA256_RE.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise KppLegacyIssV2ManifestError(
            f"{label} must be an exact nonzero lowercase SHA-256"
        )
    return value


def _positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise KppLegacyIssV2ManifestError(f"{label} must be a positive integer")
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
        raise KppLegacyIssV2ManifestError(
            "materialization receipt is not canonical-JSON serializable"
        ) from exc
    return (encoded + "\n").encode("ascii")


def _receipt_self_sha256(value: Mapping[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("materialization_receipt_sha256", None)
    return hashlib.sha256(
        MATERIALIZATION_RECEIPT_DOMAIN + _canonical_bytes(unsigned)
    ).hexdigest()


def _plain_posix_path(value: object, *, label: str) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise KppLegacyIssV2ManifestError(
            f"{label} must be a nonempty relative POSIX path"
        )
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise KppLegacyIssV2ManifestError(
            f"{label} must be a plain project-relative POSIX path"
        )
    if any(":" in part for part in relative.parts):
        raise KppLegacyIssV2ManifestError(f"{label} is not portable")
    return value


def _expected_descriptor() -> dict[str, object]:
    return {
        "path": MATERIALIZATION_RECEIPT_PATH,
        "size_bytes": EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES,
        "sha256": EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
        "materialization_receipt_sha256": (
            EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
        ),
    }


def _validate_assessed_entry(dataset_name: str, dataset: Mapping[str, Any]) -> None:
    if dataset_name not in DATASET_NAMES:
        raise KppLegacyIssV2ManifestError(
            f"generation {GENERATION_ID!r} uses unexpected dataset name {dataset_name!r}"
        )
    if (
        type(dataset.get("dataset_contract_version")) is not int
        or dataset.get("dataset_contract_version") != DATASET_CONTRACT_VERSION
    ):
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' must use dataset_contract_version=2"
        )
    if dataset.get("generation_id") != GENERATION_ID:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' generation_id is not {GENERATION_ID!r}"
        )
    if dataset.get("status") != "physically_assessed_candidate":
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' is not physically assessed"
        )
    if dataset.get("publishable") is not False:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' must remain nonpublishable"
        )

    provenance = _mapping(
        dataset.get("provenance"), label=f"dataset '{dataset_name}' provenance"
    )
    if type(provenance.get("schema_version")) is not int or provenance.get(
        "schema_version"
    ) != 1:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' provenance schema_version must be 1"
        )
    if provenance.get("generation_id") != GENERATION_ID:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' provenance generation_id drifted"
        )
    if provenance.get("physical_artifact_bytes_assessed") is not True:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' lacks physical byte assessment"
        )
    if provenance.get("publication_authorized") is not False:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' must not claim publication authorization"
        )

    variant = _VARIANT_BY_DATASET[dataset_name]
    streams = _sequence(
        dataset.get("streams"), label=f"dataset '{dataset_name}' streams"
    )
    if not streams:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' must contain streams"
        )
    expected_paths = {_MEDIA_PATHS[(variant, role)] for role in _ROLES}
    observed_paths: set[str] = set()
    for index, raw_stream in enumerate(streams):
        stream = _mapping(raw_stream, label=f"dataset '{dataset_name}' stream {index}")
        path = _plain_posix_path(
            stream.get("path"), label=f"dataset '{dataset_name}' stream {index} path"
        )
        if path not in expected_paths:
            raise KppLegacyIssV2ManifestError(
                f"dataset '{dataset_name}' stream escapes its fixed codec subtree"
            )
        observed_paths.add(path)
        _sha256(
            stream.get("sha256"),
            label=f"dataset '{dataset_name}' stream {index} SHA-256",
        )
    if observed_paths != expected_paths:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' does not bind both fixed physical streams"
        )

    annotations = _mapping(
        dataset.get("annotations"), label=f"dataset '{dataset_name}' annotations"
    )
    if annotations.get("path") != _RECEIPT_ARTIFACT_PATHS["metadata"]:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' metadata path is not in the fixed subtree"
        )
    _sha256(
        annotations.get("sha256"),
        label=f"dataset '{dataset_name}' metadata SHA-256",
    )

    if variant != "avi":
        if dataset.get("source_dataset") != "kpp_legacy_iss_v2_avi":
            raise KppLegacyIssV2ManifestError(
                f"dataset '{dataset_name}' source_dataset drifted"
            )
        if dataset.get("codec_variant") != variant:
            raise KppLegacyIssV2ManifestError(
                f"dataset '{dataset_name}' codec_variant drifted"
            )


def _validate_preparation(dataset: Mapping[str, Any]) -> None:
    preparation = _mapping(dataset.get("preparation"), label="v2 preparation")
    _exact_keys(preparation, _PREPARATION_KEYS, label="v2 preparation")
    if preparation.get("mode") != CHECK_ONLY_PREPARATION_MODE:
        raise KppLegacyIssV2ManifestError(
            f"v2 preparation.mode must be {CHECK_ONLY_PREPARATION_MODE!r}"
        )
    descriptor = _mapping(
        preparation.get("materialization_receipt"),
        label="v2 materialization receipt descriptor",
    )
    _exact_keys(
        descriptor,
        _RECEIPT_DESCRIPTOR_KEYS,
        label="v2 materialization receipt descriptor",
    )
    _plain_posix_path(descriptor.get("path"), label="materialization receipt path")
    _positive_int(
        descriptor.get("size_bytes"), label="materialization receipt size_bytes"
    )
    _sha256(descriptor.get("sha256"), label="materialization receipt file SHA-256")
    _sha256(
        descriptor.get("materialization_receipt_sha256"),
        label="materialization receipt self SHA-256",
    )
    if dict(descriptor) != _expected_descriptor():
        raise KppLegacyIssV2ManifestError(
            "v2 materialization receipt descriptor does not match the frozen receipt"
        )


def _snapshot(
    observed: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(observed.st_dev),
        int(observed.st_ino),
        int(observed.st_mode),
        int(observed.st_size),
        int(observed.st_mtime_ns),
        int(observed.st_ctime_ns),
        int(observed.st_nlink),
    )


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if bool(is_junction(path)):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError as exc:
        raise KppLegacyIssV2ManifestError(
            f"cannot inspect materialized path {path}: {exc}"
        ) from exc
    return bool(attributes & 0x400)


def _require_plain_chain(project_root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(project_root)
    except ValueError as exc:
        raise KppLegacyIssV2ManifestError(
            "materialized artifact escapes project root"
        ) from exc
    current = project_root
    for component in relative.parts:
        current = current / component
        if _is_link_or_reparse(current):
            raise KppLegacyIssV2ManifestError(
                f"materialized artifact path contains a link or reparse point: {current}"
            )


def _directory_snapshot(dataset_root: Path) -> tuple[int, int, int, int, int, int]:
    try:
        observed = dataset_root.lstat()
    except OSError as exc:
        raise KppLegacyIssV2ManifestError(
            f"cannot inspect materialization root {dataset_root}: {exc}"
        ) from exc
    if not stat.S_ISDIR(observed.st_mode) or _is_link_or_reparse(dataset_root):
        raise KppLegacyIssV2ManifestError(
            "materialization root must be a plain directory"
        )
    return (
        int(observed.st_dev),
        int(observed.st_ino),
        int(observed.st_mode),
        int(observed.st_size),
        int(observed.st_mtime_ns),
        int(observed.st_ctime_ns),
    )


def _validate_exact_tree(
    dataset_root: Path,
) -> tuple[int, int, int, int, int, int]:
    root_before = _directory_snapshot(dataset_root)
    observed_directories: set[str] = set()
    observed_files: set[str] = set()
    pending = [dataset_root]
    try:
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if _is_link_or_reparse(path):
                        raise KppLegacyIssV2ManifestError(
                            f"materialization tree contains a link or reparse point: {path}"
                        )
                    observed = entry.stat(follow_symlinks=False)
                    relative = path.relative_to(dataset_root).as_posix()
                    if stat.S_ISDIR(observed.st_mode):
                        observed_directories.add(relative)
                        pending.append(path)
                    elif stat.S_ISREG(observed.st_mode):
                        observed_files.add(relative)
                    else:
                        raise KppLegacyIssV2ManifestError(
                            f"materialization tree contains a non-file entry: {relative}"
                        )
    except OSError as exc:
        raise KppLegacyIssV2ManifestError(
            f"cannot enumerate materialization tree {dataset_root}: {exc}"
        ) from exc
    if observed_directories != set(_EXPECTED_TREE_DIRECTORIES):
        raise KppLegacyIssV2ManifestError(
            "materialization tree directory set is not exact"
        )
    if observed_files != set(_EXPECTED_TREE_FILES):
        raise KppLegacyIssV2ManifestError(
            "materialization tree file set is not exact"
        )
    root_after = _directory_snapshot(dataset_root)
    if root_after != root_before:
        raise KppLegacyIssV2ManifestError(
            "materialization root changed while its exact tree was scanned"
        )
    return root_after


def _stable_file(path: Path, *, label: str) -> tuple[int, str, bytes | None]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or _is_link_or_reparse(path):
            raise KppLegacyIssV2ManifestError(f"{label} is not a plain regular file")
        digest = hashlib.sha256()
        retained: list[bytes] | None = [] if label == "materialization receipt" else None
        with path.open("rb") as source:
            opened_before = source.fileno()
            descriptor_before = os.fstat(opened_before)
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
                if retained is not None:
                    retained.append(block)
            descriptor_after = os.fstat(source.fileno())
        after = path.lstat()
    except FileNotFoundError as exc:
        raise KppLegacyIssV2ManifestError(f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise KppLegacyIssV2ManifestError(f"cannot read {label} {path}: {exc}") from exc
    path_before = _snapshot(before)
    path_after = _snapshot(after)
    descriptor_before_snapshot = _snapshot(descriptor_before)
    descriptor_after_snapshot = _snapshot(descriptor_after)
    observations = (before, descriptor_before, descriptor_after, after)
    if any(not stat.S_ISREG(observed.st_mode) for observed in observations):
        raise KppLegacyIssV2ManifestError(f"{label} is not a stable regular file")
    if any(int(observed.st_nlink) != 1 for observed in observations):
        raise KppLegacyIssV2ManifestError(
            f"{label} has an invalid link count; hardlinks are forbidden"
        )
    if (
        path_before != path_after
        or descriptor_before_snapshot != descriptor_after_snapshot
        or path_before[:5] != descriptor_before_snapshot[:5]
    ):
        raise KppLegacyIssV2ManifestError(f"{label} changed while it was hashed")
    payload = b"".join(retained) if retained is not None else None
    return int(after.st_size), digest.hexdigest(), payload


def _validate_installed_artifacts(
    value: object,
) -> dict[str, Mapping[str, Any]]:
    artifacts = _sequence(value, label="installed_artifacts")
    if len(artifacts) != 9:
        raise KppLegacyIssV2ManifestError(
            "materialization receipt must describe exactly nine installed artifacts"
        )
    by_path: dict[str, Mapping[str, Any]] = {}
    for index, raw_artifact in enumerate(artifacts):
        artifact = _mapping(raw_artifact, label=f"installed artifact {index}")
        kind = artifact.get("artifact_kind")
        if kind == "media":
            _exact_keys(artifact, _MEDIA_ARTIFACT_KEYS, label=f"installed artifact {index}")
            variant = artifact.get("codec_variant")
            role = artifact.get("role")
            if (variant, role) not in _MEDIA_PATHS:
                raise KppLegacyIssV2ManifestError(
                    f"installed media artifact {index} role/variant is invalid"
                )
            expected_path = _MEDIA_PATHS[(str(variant), str(role))]
        elif kind == "receipt":
            _exact_keys(
                artifact,
                _RECEIPT_ARTIFACT_KEYS,
                label=f"installed artifact {index}",
            )
            role = artifact.get("receipt_role")
            if role not in _RECEIPT_ARTIFACT_PATHS:
                raise KppLegacyIssV2ManifestError(
                    f"installed receipt artifact {index} role is invalid"
                )
            expected_path = _RECEIPT_ARTIFACT_PATHS[str(role)]
        else:
            raise KppLegacyIssV2ManifestError(
                f"installed artifact {index} has unsupported artifact_kind"
            )
        _plain_posix_path(
            artifact.get("source_path"), label=f"installed artifact {index} source_path"
        )
        installed_path = _plain_posix_path(
            artifact.get("installed_path"),
            label=f"installed artifact {index} installed_path",
        )
        if installed_path != expected_path:
            raise KppLegacyIssV2ManifestError(
                f"installed artifact {index} is not at its fixed path"
            )
        _positive_int(
            artifact.get("size_bytes"), label=f"installed artifact {index} size_bytes"
        )
        _sha256(
            artifact.get("sha256"), label=f"installed artifact {index} SHA-256"
        )
        if installed_path in by_path:
            raise KppLegacyIssV2ManifestError(
                f"installed artifact path is duplicated: {installed_path}"
            )
        by_path[installed_path] = artifact
    if set(by_path) != set(_EXPECTED_INSTALLED_PATHS):
        raise KppLegacyIssV2ManifestError(
            "installed artifact path set does not match the fixed v2 subtree"
        )
    return by_path


def _validate_entry_artifact_bindings(
    entries: Mapping[str, Any],
    installed: Mapping[str, Mapping[str, Any]],
) -> None:
    if set(entries) != set(DATASET_NAMES):
        raise KppLegacyIssV2ManifestError(
            "materialization receipt dataset entry set is not exact"
        )
    for dataset_name in sorted(DATASET_NAMES):
        entry = _mapping(
            entries[dataset_name], label=f"receipt dataset entry '{dataset_name}'"
        )
        _validate_assessed_entry(dataset_name, entry)
        for index, raw_stream in enumerate(
            _sequence(entry.get("streams"), label=f"dataset '{dataset_name}' streams")
        ):
            stream = _mapping(raw_stream, label=f"dataset '{dataset_name}' stream {index}")
            artifact = installed[str(stream["path"])]
            if artifact.get("sha256") != stream.get("sha256"):
                raise KppLegacyIssV2ManifestError(
                    f"dataset '{dataset_name}' stream is not bound to installed artifact"
                )
        annotations = _mapping(
            entry.get("annotations"), label=f"dataset '{dataset_name}' annotations"
        )
        metadata = installed[_RECEIPT_ARTIFACT_PATHS["metadata"]]
        if metadata.get("sha256") != annotations.get("sha256"):
            raise KppLegacyIssV2ManifestError(
                f"dataset '{dataset_name}' metadata is not bound to installed artifact"
            )


def _validate_receipt(
    *,
    dataset_name: str,
    configured_dataset: Mapping[str, Any],
    project_root: Path,
) -> None:
    root = Path(project_root).absolute()
    if not root.is_dir():
        raise KppLegacyIssV2ManifestError("project_root is not an existing directory")
    if _is_link_or_reparse(root):
        raise KppLegacyIssV2ManifestError(
            "project_root must be a plain directory, not a link or reparse point"
        )
    receipt_path = root / Path(*PurePosixPath(MATERIALIZATION_RECEIPT_PATH).parts)
    _require_plain_chain(root, receipt_path)
    dataset_root = receipt_path.parent
    root_snapshot = _validate_exact_tree(dataset_root)
    size, file_sha256, retained = _stable_file(
        receipt_path, label="materialization receipt"
    )
    if size != EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES:
        raise KppLegacyIssV2ManifestError(
            "materialization receipt size does not match its frozen descriptor"
        )
    if file_sha256 != EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256:
        raise KppLegacyIssV2ManifestError(
            "materialization receipt file SHA-256 does not match its frozen descriptor"
        )
    assert retained is not None
    try:
        receipt = json.loads(retained.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KppLegacyIssV2ManifestError(
            "materialization receipt is not canonical ASCII JSON"
        ) from exc
    receipt = _mapping(receipt, label="materialization receipt")
    if retained != _canonical_bytes(receipt):
        raise KppLegacyIssV2ManifestError(
            "materialization receipt bytes are not canonical ASCII JSON"
        )
    _exact_keys(receipt, _TOP_LEVEL_RECEIPT_KEYS, label="materialization receipt")
    expected_scalars = {
        "schema_version": 1,
        "artifact_kind": MATERIALIZATION_ARTIFACT_KIND,
        "generation_id": GENERATION_ID,
        "status": "physically_assessed_candidate",
        "dataset_root": DATASET_ROOT,
        "publishable": False,
        "publication_authorized": False,
    }
    for key, expected in expected_scalars.items():
        if receipt.get(key) != expected or type(receipt.get(key)) is not type(expected):
            raise KppLegacyIssV2ManifestError(
                f"materialization receipt {key} does not match the fixed contract"
            )
    if _canonical_bytes(receipt.get("claims")) != _canonical_bytes(
        _EXPECTED_CLAIMS
    ):
        raise KppLegacyIssV2ManifestError(
            "materialization receipt claims are not authoritative and exact"
        )
    declared_self_hash = _sha256(
        receipt.get("materialization_receipt_sha256"),
        label="materialization receipt self SHA-256",
    )
    if declared_self_hash != EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256:
        raise KppLegacyIssV2ManifestError(
            "materialization receipt self SHA-256 is not the frozen value"
        )
    if declared_self_hash != _receipt_self_sha256(receipt):
        raise KppLegacyIssV2ManifestError(
            "materialization receipt self SHA-256 does not match its claims"
        )

    installed = _validate_installed_artifacts(receipt.get("installed_artifacts"))
    pins = _mapping(
        receipt.get("source_receipt_external_pins"),
        label="source_receipt_external_pins",
    )
    _exact_keys(
        pins,
        {"extraction", "transcode", "metadata"},
        label="source_receipt_external_pins",
    )
    for role in ("extraction", "transcode", "metadata"):
        digest = _sha256(pins.get(role), label=f"{role} external receipt pin")
        if digest != installed[_RECEIPT_ARTIFACT_PATHS[role]].get("sha256"):
            raise KppLegacyIssV2ManifestError(
                f"{role} external receipt pin is not bound to its installed artifact"
            )

    entries = _mapping(receipt.get("dataset_entries"), label="receipt dataset_entries")
    _validate_entry_artifact_bindings(entries, installed)
    configured = copy.deepcopy(dict(configured_dataset))
    configured.pop("preparation", None)
    if _canonical_bytes(configured) != _canonical_bytes(entries[dataset_name]):
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' does not exactly match its embedded receipt entry"
        )

    for installed_path, descriptor in installed.items():
        artifact_path = root / Path(*PurePosixPath(installed_path).parts)
        _require_plain_chain(root, artifact_path)
        artifact_size, artifact_sha256, _ = _stable_file(
            artifact_path, label=f"materialized artifact {installed_path}"
        )
        if artifact_size != descriptor.get("size_bytes"):
            raise KppLegacyIssV2ManifestError(
                f"materialized artifact {installed_path} size does not match receipt"
            )
        if artifact_sha256 != descriptor.get("sha256"):
            raise KppLegacyIssV2ManifestError(
                f"materialized artifact {installed_path} SHA-256 does not match receipt"
            )
    final_root_snapshot = _validate_exact_tree(dataset_root)
    if final_root_snapshot != root_snapshot:
        raise KppLegacyIssV2ManifestError(
            "materialization root identity changed during validation"
        )


def validate_kpp_legacy_iss_v2_manifest_entry(
    dataset_name: str,
    dataset: Mapping[str, Any],
    *,
    project_root: Path,
    require_files: bool,
) -> bool:
    """Validate the v2 receipt gate; return False for unrelated v1 datasets."""

    candidate = dataset_name in DATASET_NAMES or dataset.get("generation_id") == GENERATION_ID
    if not candidate:
        return False
    _validate_assessed_entry(dataset_name, dataset)
    _validate_preparation(dataset)
    frozen_entry = copy.deepcopy(dict(dataset))
    frozen_entry.pop("preparation", None)
    entry_sha256 = hashlib.sha256(_canonical_bytes(frozen_entry)).hexdigest()
    if entry_sha256 != _EXPECTED_DATASET_ENTRY_CANONICAL_SHA256[dataset_name]:
        raise KppLegacyIssV2ManifestError(
            f"dataset '{dataset_name}' entry does not match its frozen receipt entry"
        )
    if require_files:
        _validate_receipt(
            dataset_name=dataset_name,
            configured_dataset=dataset,
            project_root=project_root,
        )
    return True


__all__ = [
    "CHECK_ONLY_PREPARATION_MODE",
    "DATASET_NAMES",
    "DATASET_ROOT",
    "EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256",
    "EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256",
    "EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES",
    "KppLegacyIssV2ManifestError",
    "MATERIALIZATION_RECEIPT_DOMAIN",
    "MATERIALIZATION_RECEIPT_PATH",
    "validate_kpp_legacy_iss_v2_manifest_entry",
]
