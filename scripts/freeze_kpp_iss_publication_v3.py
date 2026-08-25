#!/usr/bin/env python3
"""Freeze a distinct, receipt-bound publication corpus from KPP ISS v2 bytes.

The source receipts remain immutable non-publication v2 evidence.  This module
adds a new v3 authorization and corpus identity for performance/topology
publication only.  It copies already-frozen H.264/H.265 bytes, validates every
copy with the pinned receipt graph and ffprobe contract, and publishes the
complete directory with an atomic no-replace rename.  It never invokes ffmpeg.
"""

from __future__ import annotations

import argparse
import copy
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

from extract_kpp_legacy_iss import _create_private_working_directory
from freeze_kpp_legacy_iss_v2_transcodes import (
    TranscodeFreezeError,
    _atomic_publish_directory,
    _copy_pinned_snapshot,
    _probe,
    _read_tool_version,
    _validate_output_probe,
    _validate_tool,
)


GENERATION_ID = "kpp_iss_publication_v3"
SOURCE_GENERATION_ID = "kpp_legacy_iss_v2"
DATASET_IDS = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
SOURCE_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
TARGET_ROOT = "data/videos/kpp/kpp_iss_publication_v3"
AUTHORIZATION_BASIS_ID = (
    "explicit_user_instruction_2026-08-24_distinct_v3_performance_publication"
)
AUTHORIZATION_RECEIPT_NAME = (
    "kpp_iss_publication_v3_authorization_receipt.json"
)
MANIFEST_NAME = "kpp_iss_publication_v3_manifest.json"
AUTHORIZATION_RECEIPT_DOMAIN = (
    b"VAST:kpp-iss-publication-v3-authorization-receipt:v1\0"
)
MANIFEST_DOMAIN = b"VAST:kpp-iss-publication-v3-manifest:v1\0"
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

_RECEIPT_DOMAINS = {
    "extraction": b"VAST:kpp-legacy-iss-extraction-receipt:v1\0",
    "transcode": b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0",
    "metadata": b"VAST:kpp-legacy-iss-metadata:v1\0",
    "materialization": (
        b"VAST:kpp-legacy-iss-v2-materialization-receipt:v1\0"
    ),
}

FROZEN_SOURCE_ARCHIVES = [
    {
        "archive_logical_id": "13._03",
        "size_bytes": 2464770411,
        "sha256": (
            "52845eb3e95446bf015844b79578b78596a3c594270fab85fc1363862c95bd53"
        ),
        "role": "underbody",
        "payload_offset": 1313,
    },
    {
        "archive_logical_id": "13._03_2",
        "size_bytes": 33049105,
        "sha256": (
            "dfd4519dea0b6d8a23230347810dc697c2560d8b6a83db81a3e9b49e2bc2ef0b"
        ),
        "role": "front_gate",
        "payload_offset": 278,
    },
]

FROZEN_SOURCE_RECEIPTS: dict[str, dict[str, object]] = {
    "extraction": {
        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_extraction_receipt.json",
        "size_bytes": 2495,
        "sha256": (
            "f160ce153804f92dd02068ad48547b396636bd2cb7dfc8fb39114210f23a0e05"
        ),
        "self_hash_field": "extraction_receipt_sha256",
        "self_hash": (
            "e944d7bb0de69fff94f7c2a8ea4cd84379dcd73af665c8be28bcce419bac2d48"
        ),
    },
    "transcode": {
        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_transcode_receipt.json",
        "size_bytes": 7092,
        "sha256": (
            "f78406237d539224a25c38bf40f913f18069e120e8e66e9d11270ff88ceb5470"
        ),
        "self_hash_field": "transcode_receipt_sha256",
        "self_hash": (
            "ef41fe97a19690faec4f02c48d34f889b98e2f929ae9d391bbd55d6d112e93f7"
        ),
    },
    "metadata": {
        "source_path": f"{SOURCE_ROOT}/metadata/iss_v2_underbody_metadata.json",
        "size_bytes": 12731945,
        "sha256": (
            "d23872d4b4706ef7d804f917a72407f82326eb3cdd5d39d347913f20cc65b0d4"
        ),
        "self_hash_field": "normalization_receipt_sha256",
        "self_hash": (
            "f0227c867e2399816b4d4eb76ca32eb628c42c004a1136cf2447e4579315fce8"
        ),
    },
    "materialization": {
        "source_path": f"{SOURCE_ROOT}/kpp_iss_v2_materialization_receipt.json",
        "size_bytes": 28131,
        "sha256": (
            "dd0d2aa38da1281a750806858b555b994a9dcf3c9bcd35e8379dbc9d339f2b33"
        ),
        "self_hash_field": "materialization_receipt_sha256",
        "self_hash": (
            "56e09fd82ab83d4f3e0a711d93658a1cfc69f3bee9fd381df41713ac5b42bda4"
        ),
    },
}

FROZEN_MEDIA: dict[tuple[str, str], dict[str, object]] = {
    ("h264", "underbody"): {
        "source_path": f"{SOURCE_ROOT}/h264/iss_v2_underbody.mp4",
        "size_bytes": 1079445865,
        "sha256": (
            "b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102"
        ),
    },
    ("h264", "front_gate"): {
        "source_path": f"{SOURCE_ROOT}/h264/iss_v2_front_gate.mp4",
        "size_bytes": 63131711,
        "sha256": (
            "08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273"
        ),
    },
    ("h265", "underbody"): {
        "source_path": f"{SOURCE_ROOT}/h265/iss_v2_underbody.mp4",
        "size_bytes": 223684192,
        "sha256": (
            "5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839"
        ),
    },
    ("h265", "front_gate"): {
        "source_path": f"{SOURCE_ROOT}/h265/iss_v2_front_gate.mp4",
        "size_bytes": 14910770,
        "sha256": (
            "fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728"
        ),
    },
}

FROZEN_FFPROBE = {
    "executable_sha256": (
        "012bddded3cbc5204055210d7ff4f0b3f7521bca441a694939856d01909f5756"
    ),
    "version_output_sha256": (
        "f5e78bacf30bec256004273331c8473cc595fcb383dc390c17bc2ece32d42cab"
    ),
}

_RECEIPT_EXPECTATIONS = {
    "extraction": (
        "vast_kpp_legacy_iss_extraction_receipt",
        "headless_stream_copy_candidate",
    ),
    "transcode": (
        "vast_kpp_legacy_iss_v2_transcode_receipt",
        "pinned_codec_transcode_candidate",
    ),
    "metadata": (
        "vast_kpp_legacy_iss_metadata",
        "authoritative_windows_candidate",
    ),
    "materialization": (
        "vast_kpp_legacy_iss_v2_materialization_receipt",
        "physically_assessed_candidate",
    ),
}


class PublicationCorpusFreezeError(RuntimeError):
    """Raised when the distinct v3 corpus cannot be frozen safely."""


Prober = Callable[[Path], dict[str, object]]


@dataclass(frozen=True)
class _TestAdapters:
    source_pins: Mapping[str, object]
    prober: Prober
    ffprobe_descriptor: Mapping[str, object]


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
        raise PublicationCorpusFreezeError(
            "publication artifact is not canonical-JSON serializable"
        ) from exc
    return (encoded + "\n").encode("ascii")


def _require_sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or _SHA256_RE.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PublicationCorpusFreezeError(
            f"{label} must be an exact nonzero lowercase SHA-256"
        )
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise PublicationCorpusFreezeError(f"{label} must be a positive integer")
    return value


def _plain_relative(value: object, *, label: str) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise PublicationCorpusFreezeError(
            f"{label} must be a nonempty project-relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in ("", ".", "..") or ":" in part for part in path.parts)
    ):
        raise PublicationCorpusFreezeError(
            f"{label} must be a canonical project-relative POSIX path"
        )
    return value


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if bool(is_junction(path)):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except FileNotFoundError:
        return False
    return bool(attributes & 0x400)


def _lexists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _validated_root(value: Path) -> Path:
    root = value.absolute()
    if not root.is_dir() or _is_link_or_reparse(root):
        raise PublicationCorpusFreezeError(
            "project_root must be a plain existing directory"
        )
    return root


def _require_plain_chain(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PublicationCorpusFreezeError("artifact escapes project_root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if _lexists(current) and _is_link_or_reparse(current):
            raise PublicationCorpusFreezeError(
                f"artifact path contains a link or reparse point: {current}"
            )


def _stable_payload(
    path: Path,
    *,
    label: str,
    retain: bool,
) -> tuple[int, str, bytes | None]:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(path)
            or int(before.st_nlink) != 1
        ):
            raise PublicationCorpusFreezeError(
                f"{label} must be a plain single-link regular file"
            )
        if retain and int(before.st_size) > MAX_RECEIPT_BYTES:
            raise PublicationCorpusFreezeError(f"{label} exceeds its size bound")
        digest = hashlib.sha256()
        chunks: list[bytes] | None = [] if retain else None
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            opened = os.fstat(stream.fileno())
        after = path.lstat()
    except FileNotFoundError as exc:
        raise PublicationCorpusFreezeError(f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise PublicationCorpusFreezeError(f"cannot read {label}: {exc}") from exc
    identity_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    if any(
        getattr(before, field) != getattr(opened, field)
        or getattr(before, field) != getattr(after, field)
        for field in identity_fields
    ):
        raise PublicationCorpusFreezeError(f"{label} changed while it was read")
    return (
        int(before.st_size),
        digest.hexdigest(),
        b"".join(chunks) if chunks is not None else None,
    )


def _strict_json(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PublicationCorpusFreezeError(
            f"{label} must be canonical ASCII JSON"
        ) from exc

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationCorpusFreezeError(
                    f"{label} contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=lambda item: (_ for _ in ()).throw(
                PublicationCorpusFreezeError(
                    f"{label} contains invalid constant {item}"
                )
            ),
        )
    except PublicationCorpusFreezeError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationCorpusFreezeError(f"{label} is invalid JSON") from exc
    if type(value) is not dict or _canonical_bytes(value) != payload:
        raise PublicationCorpusFreezeError(
            f"{label} is not one canonical JSON object"
        )
    return value


def _receipt_self_hash(
    value: Mapping[str, object],
    *,
    field: str,
    domain: bytes,
) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return hashlib.sha256(domain + _canonical_bytes(unsigned)).hexdigest()


def _pins_from(value: Mapping[str, object]) -> dict[str, object]:
    return copy.deepcopy(dict(value))


def _production_pins() -> dict[str, object]:
    return {
        "source_archives": copy.deepcopy(FROZEN_SOURCE_ARCHIVES),
        "receipts": copy.deepcopy(FROZEN_SOURCE_RECEIPTS),
        "media": copy.deepcopy(FROZEN_MEDIA),
        "ffprobe": copy.deepcopy(FROZEN_FFPROBE),
    }


def _read_source_receipts(
    root: Path,
    *,
    pins: Mapping[str, object],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, object]]]:
    raw_pins = pins.get("receipts")
    if not isinstance(raw_pins, Mapping) or set(raw_pins) != set(
        _RECEIPT_EXPECTATIONS
    ):
        raise PublicationCorpusFreezeError("source receipt pin set is not exact")
    values: dict[str, dict[str, Any]] = {}
    descriptors: dict[str, dict[str, object]] = {}
    for role in ("extraction", "transcode", "metadata", "materialization"):
        raw_descriptor = raw_pins[role]
        if not isinstance(raw_descriptor, Mapping):
            raise PublicationCorpusFreezeError(f"{role} receipt pin is invalid")
        descriptor = dict(raw_descriptor)
        expected_keys = {
            "source_path",
            "size_bytes",
            "sha256",
            "self_hash_field",
            "self_hash",
        }
        if set(descriptor) != expected_keys:
            raise PublicationCorpusFreezeError(
                f"{role} receipt pin schema is not exact"
            )
        source_path = _plain_relative(
            descriptor["source_path"], label=f"{role} receipt source_path"
        )
        source = root.joinpath(*PurePosixPath(source_path).parts)
        _require_plain_chain(root, source)
        size, file_hash, payload = _stable_payload(
            source, label=f"{role} receipt", retain=True
        )
        expected_size = _require_positive_int(
            descriptor["size_bytes"], label=f"{role} receipt size_bytes"
        )
        expected_file_hash = _require_sha256(
            descriptor["sha256"], label=f"{role} receipt file SHA-256"
        )
        if size != expected_size:
            raise PublicationCorpusFreezeError(
                f"{role} receipt size does not match its external pin"
            )
        if file_hash != expected_file_hash:
            raise PublicationCorpusFreezeError(
                f"{role} receipt SHA-256 does not match its external pin"
            )
        assert payload is not None
        value = _strict_json(payload, label=f"{role} receipt")
        artifact_kind, status = _RECEIPT_EXPECTATIONS[role]
        if (
            value.get("schema_version") != 1
            or type(value.get("schema_version")) is not int
            or value.get("artifact_kind") != artifact_kind
            or value.get("generation_id") != SOURCE_GENERATION_ID
            or value.get("status") != status
        ):
            raise PublicationCorpusFreezeError(
                f"{role} receipt identity or status drifted"
            )
        self_field = descriptor["self_hash_field"]
        if type(self_field) is not str:
            raise PublicationCorpusFreezeError(
                f"{role} receipt self hash field is invalid"
            )
        expected_self_hash = _require_sha256(
            descriptor["self_hash"], label=f"{role} receipt self hash pin"
        )
        observed_self_hash = _require_sha256(
            value.get(self_field), label=f"{role} receipt self hash"
        )
        computed_self_hash = _receipt_self_hash(
            value, field=self_field, domain=_RECEIPT_DOMAINS[role]
        )
        if observed_self_hash != expected_self_hash or observed_self_hash != computed_self_hash:
            raise PublicationCorpusFreezeError(
                f"{role} receipt self hash does not match its claims and pin"
            )
        claims = value.get("claims")
        if not isinstance(claims, Mapping):
            raise PublicationCorpusFreezeError(f"{role} receipt claims are invalid")
        for field in (
            "publication_authorized",
            "v1_dataset_identity_equivalent",
            "accuracy_ground_truth_validated",
        ):
            if field in claims and claims.get(field) is not False:
                wording = {
                    "publication_authorized": "publication authorization",
                    "v1_dataset_identity_equivalent": "v1 identity equivalence",
                    "accuracy_ground_truth_validated": "accuracy ground truth",
                }[field]
                raise PublicationCorpusFreezeError(
                    f"{role} source receipt makes a forbidden {wording} claim"
                )
        if role != "materialization":
            for required_false in (
                "publication_authorized",
                "v1_dataset_identity_equivalent",
                "accuracy_ground_truth_validated",
            ):
                if claims.get(required_false) is not False:
                    raise PublicationCorpusFreezeError(
                        f"{role} receipt omits a required false claim"
                    )
        else:
            if (
                value.get("publishable") is not False
                or value.get("publication_authorized") is not False
                or claims.get("publishable") is not False
                or claims.get("publication_authorized") is not False
            ):
                raise PublicationCorpusFreezeError(
                    "materialization receipt old publication claims drifted"
                )
        values[role] = value
        descriptors[role] = {
            "role": role,
            "source_path": source_path,
            "size_bytes": size,
            "sha256": file_hash,
            "self_hash_field": self_field,
            "self_hash": observed_self_hash,
        }
    return values, descriptors


def _records_by(
    value: object,
    *,
    keys: tuple[str, ...],
    label: str,
) -> dict[tuple[str, ...], dict[str, Any]]:
    if type(value) is not list:
        raise PublicationCorpusFreezeError(f"{label} must be an array")
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, raw in enumerate(value):
        if type(raw) is not dict:
            raise PublicationCorpusFreezeError(f"{label}[{index}] is invalid")
        identity = tuple(str(raw.get(key, "")) for key in keys)
        if any(not item for item in identity) or identity in result:
            raise PublicationCorpusFreezeError(
                f"{label} has duplicate or invalid identities"
            )
        result[identity] = dict(raw)
    return result


def _validate_source_graph(
    receipts: Mapping[str, Mapping[str, Any]],
    *,
    pins: Mapping[str, object],
    receipt_descriptors: Mapping[str, Mapping[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    source_archives = pins.get("source_archives")
    if source_archives != receipts["extraction"].get("source_archives"):
        raise PublicationCorpusFreezeError(
            "extraction source archive pins or order drifted"
        )
    if source_archives != FROZEN_SOURCE_ARCHIVES and pins is not FROZEN_SOURCE_ARCHIVES:
        if type(source_archives) is not list or len(source_archives) != 2:
            raise PublicationCorpusFreezeError("source archive pin set is invalid")

    extraction = receipt_descriptors["extraction"]
    source_extraction = receipts["transcode"].get("source_extraction")
    if not isinstance(source_extraction, Mapping):
        raise PublicationCorpusFreezeError(
            "transcode receipt source_extraction binding is invalid"
        )
    if (
        source_extraction.get("file_sha256") != extraction["sha256"]
        or source_extraction.get("extraction_receipt_sha256")
        != extraction["self_hash"]
    ):
        raise PublicationCorpusFreezeError(
            "transcode receipt is not bound to the extraction receipt"
        )

    ffprobe_pin = pins.get("ffprobe")
    if not isinstance(ffprobe_pin, Mapping):
        raise PublicationCorpusFreezeError("ffprobe pin is invalid")
    ffprobe_records = _records_by(
        receipts["transcode"].get("tools"), keys=("role",), label="transcode tools"
    )
    ffprobe_record = ffprobe_records.get(("ffprobe",))
    if ffprobe_record is None or any(
        ffprobe_record.get(field) != ffprobe_pin.get(field)
        for field in ("executable_sha256", "version_output_sha256")
    ):
        raise PublicationCorpusFreezeError(
            "transcode receipt ffprobe identity drifted"
        )

    raw_media = pins.get("media")
    if not isinstance(raw_media, Mapping) or set(raw_media) != {
        (variant, role)
        for variant in ("h264", "h265")
        for role in ("underbody", "front_gate")
    }:
        raise PublicationCorpusFreezeError("four-media pin set is not exact")
    outputs = _records_by(
        receipts["transcode"].get("outputs"),
        keys=("codec_variant", "role"),
        label="transcode outputs",
    )
    if set(outputs) != set(raw_media):
        raise PublicationCorpusFreezeError(
            "transcode receipt does not describe exactly four media outputs"
        )
    normalized_media: dict[tuple[str, str], dict[str, object]] = {}
    for identity in sorted(raw_media):
        raw_pin = raw_media[identity]
        if not isinstance(raw_pin, Mapping):
            raise PublicationCorpusFreezeError("media pin is invalid")
        pin = copy.deepcopy(dict(raw_pin))
        source_path = _plain_relative(
            pin.get("source_path"), label=f"{identity} source_path"
        )
        size = _require_positive_int(
            pin.get("size_bytes"), label=f"{identity} size_bytes"
        )
        digest = _require_sha256(pin.get("sha256"), label=f"{identity} SHA-256")
        output = outputs[identity]
        if output.get("size_bytes") != size or output.get("sha256") != digest:
            raise PublicationCorpusFreezeError(
                f"{identity} media pin is not bound to transcode receipt"
            )
        receipt_media = output.get("media")
        pinned_media = pin.get("media", receipt_media)
        if type(receipt_media) is not dict or receipt_media != pinned_media:
            raise PublicationCorpusFreezeError(
                f"{identity} ffprobe contract pin drifted"
            )
        normalized_media[identity] = {
            "source_path": source_path,
            "size_bytes": size,
            "sha256": digest,
            "media": copy.deepcopy(receipt_media),
        }

    materialization_pins = receipts["materialization"].get(
        "source_receipt_external_pins"
    )
    if not isinstance(materialization_pins, Mapping):
        raise PublicationCorpusFreezeError(
            "materialization source receipt pins are invalid"
        )
    for role in ("extraction", "transcode", "metadata"):
        if materialization_pins.get(role) != receipt_descriptors[role]["sha256"]:
            raise PublicationCorpusFreezeError(
                f"materialization receipt {role} file pin drifted"
            )
    installed = _records_by(
        receipts["materialization"].get("installed_artifacts"),
        keys=("installed_path",),
        label="materialization installed_artifacts",
    )
    for identity, media in normalized_media.items():
        installed_record = installed.get((str(media["source_path"]),))
        if installed_record is None or any(
            installed_record.get(field) != media[field]
            for field in ("size_bytes", "sha256")
        ):
            raise PublicationCorpusFreezeError(
                f"{identity} media is not bound by materialization receipt"
            )

    source_records = _records_by(
        receipts["extraction"].get("source_archives"),
        keys=("role",),
        label="extraction source_archives",
    )
    extraction_outputs = _records_by(
        receipts["extraction"].get("outputs"),
        keys=("role",),
        label="extraction outputs",
    )
    metadata_source = receipts["metadata"].get("source_archive")
    metadata_avi = receipts["metadata"].get("exported_avi")
    if not isinstance(metadata_source, Mapping) or not isinstance(metadata_avi, Mapping):
        raise PublicationCorpusFreezeError("metadata source bindings are invalid")
    underbody_source = source_records.get(("underbody",))
    underbody_avi = extraction_outputs.get(("underbody",))
    if underbody_source is None or underbody_avi is None:
        raise PublicationCorpusFreezeError("underbody source binding is missing")
    for field in ("archive_logical_id", "size_bytes", "sha256"):
        if metadata_source.get(field) != underbody_source.get(field):
            raise PublicationCorpusFreezeError(
                "metadata source archive binding drifted"
            )
    for field in ("size_bytes", "sha256"):
        if metadata_avi.get(field) != underbody_avi.get(field):
            raise PublicationCorpusFreezeError(
                "metadata exported AVI binding drifted"
            )
    return normalized_media


def _publication_claims() -> dict[str, bool]:
    return {
        "publication_authorized": True,
        "publication_scope_performance_and_topology_only": True,
        "accuracy_ground_truth_validated": False,
        "production_routing_validated": False,
        "v1_dataset_identity_equivalent": False,
        "source_timestamps_preserved": False,
        "media_reused_without_retranscode": True,
        "source_receipt_graph_exactly_pinned": True,
        "all_media_bytes_and_ffprobe_contracts_verified": True,
        "output_set_directory_published_atomically": True,
    }


def _write_canonical(path: Path, value: Mapping[str, object]) -> bytes:
    payload = _canonical_bytes(value)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != payload:
        raise PublicationCorpusFreezeError(
            f"canonical publication artifact changed after write: {path.name}"
        )
    return payload


def _installed_receipt_name(role: str) -> str:
    return {
        "extraction": "kpp_iss_v2_extraction_receipt.json",
        "transcode": "kpp_iss_v2_transcode_receipt.json",
        "metadata": "iss_v2_underbody_metadata.json",
        "materialization": "kpp_iss_v2_materialization_receipt.json",
    }[role]


def _target_media_relative(variant: str, role: str) -> str:
    return f"{variant}/iss_v2_{role}.mp4"


def _expected_tree_files() -> set[str]:
    return {
        *(
            _target_media_relative(variant, role)
            for variant in ("h264", "h265")
            for role in ("underbody", "front_gate")
        ),
        *(
            f"receipts/{_installed_receipt_name(role)}"
            for role in _RECEIPT_EXPECTATIONS
        ),
        AUTHORIZATION_RECEIPT_NAME,
        MANIFEST_NAME,
    }


def _validate_exact_tree(root: Path) -> None:
    if not root.is_dir() or _is_link_or_reparse(root):
        raise PublicationCorpusFreezeError(
            "publication corpus root must be a plain directory"
        )
    directories: set[str] = set()
    files: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            if _is_link_or_reparse(child):
                raise PublicationCorpusFreezeError(
                    "publication corpus contains a link or reparse point"
                )
            relative = child.relative_to(root).as_posix()
            observed = child.lstat()
            if stat.S_ISDIR(observed.st_mode):
                directories.add(relative)
                pending.append(child)
            elif stat.S_ISREG(observed.st_mode) and int(observed.st_nlink) == 1:
                files.add(relative)
            else:
                raise PublicationCorpusFreezeError(
                    "publication corpus contains a non-regular entry"
                )
    if directories != {"h264", "h265", "receipts"}:
        raise PublicationCorpusFreezeError(
            "publication corpus directory set is not exact"
        )
    if files != _expected_tree_files():
        raise PublicationCorpusFreezeError(
            "publication corpus file set is not exact"
        )


def _cleanup_owned_candidate(working: Path, target_parent: Path) -> None:
    if (
        working.parent != target_parent
        or not working.name.startswith(".kpp_iss_publication_v3.")
        or not working.name.endswith(".candidate")
        or not working.is_dir()
        or _is_link_or_reparse(working)
    ):
        return
    for relative in sorted(_expected_tree_files()):
        path = working.joinpath(*PurePosixPath(relative).parts)
        if _lexists(path):
            if _is_link_or_reparse(path) or not path.is_file():
                return
            path.unlink()
    for directory in (working / "receipts", working / "h265", working / "h264"):
        if _lexists(directory):
            directory.rmdir()
    working.rmdir()


def _freeze_publication_corpus_impl(
    *,
    project_root: Path,
    authorization_basis: str,
    ffprobe: Path | None,
    test_adapters: _TestAdapters | None,
) -> dict[str, object]:
    if authorization_basis != AUTHORIZATION_BASIS_ID:
        raise PublicationCorpusFreezeError(
            "explicit v3 publication authorization basis is missing or invalid"
        )
    root = _validated_root(project_root)
    target = root.joinpath(*PurePosixPath(TARGET_ROOT).parts)
    _require_plain_chain(root, target)
    if _lexists(target):
        raise PublicationCorpusFreezeError(
            f"publication corpus target already exists: {TARGET_ROOT}"
        )
    target_parent = target.parent
    if not target_parent.is_dir() or _is_link_or_reparse(target_parent):
        raise PublicationCorpusFreezeError(
            "publication corpus parent must already be a plain directory"
        )
    pins = (
        _production_pins()
        if test_adapters is None
        else _pins_from(test_adapters.source_pins)
    )
    receipts, receipt_descriptors = _read_source_receipts(root, pins=pins)
    media = _validate_source_graph(
        receipts,
        pins=pins,
        receipt_descriptors=receipt_descriptors,
    )

    ffprobe_pin = pins.get("ffprobe")
    if not isinstance(ffprobe_pin, Mapping):
        raise PublicationCorpusFreezeError("ffprobe pin is invalid")
    if test_adapters is None:
        if ffprobe is None:
            raise PublicationCorpusFreezeError(
                "authoritative freeze requires the pinned ffprobe executable"
            )
        tool = ffprobe.absolute()
        try:
            ffprobe_descriptor = _validate_tool(
                role="ffprobe",
                path=tool,
                expected_sha256=_require_sha256(
                    ffprobe_pin.get("executable_sha256"),
                    label="ffprobe executable pin",
                ),
                expected_version_sha256=_require_sha256(
                    ffprobe_pin.get("version_output_sha256"),
                    label="ffprobe version pin",
                ),
                version_reader=_read_tool_version,
            )
        except TranscodeFreezeError as exc:
            raise PublicationCorpusFreezeError(str(exc)) from exc
        prober: Prober = lambda path: _probe(path, ffprobe=tool)
    else:
        ffprobe_descriptor = copy.deepcopy(dict(test_adapters.ffprobe_descriptor))
        prober = test_adapters.prober
    if any(
        ffprobe_descriptor.get(field) != ffprobe_pin.get(field)
        for field in ("executable_sha256", "version_output_sha256")
    ):
        raise PublicationCorpusFreezeError(
            "active ffprobe identity does not match the frozen receipt graph"
        )

    working = _create_private_working_directory(
        parent=target_parent,
        prefix=".kpp_iss_publication_v3.",
        suffix=".candidate",
    )
    published = False
    try:
        for name in ("h264", "h265", "receipts"):
            (working / name).mkdir()
        installed_receipts: list[dict[str, object]] = []
        for role in ("extraction", "transcode", "metadata", "materialization"):
            descriptor = receipt_descriptors[role]
            source = root.joinpath(
                *PurePosixPath(str(descriptor["source_path"])).parts
            )
            relative = f"receipts/{_installed_receipt_name(role)}"
            destination = working.joinpath(*PurePosixPath(relative).parts)
            try:
                _copy_pinned_snapshot(
                    source=source,
                    target=destination,
                    expected_sha256=str(descriptor["sha256"]),
                    expected_size_bytes=int(descriptor["size_bytes"]),
                    label=f"{role} source receipt",
                )
            except TranscodeFreezeError as exc:
                raise PublicationCorpusFreezeError(str(exc)) from exc
            installed_receipts.append(
                {
                    **copy.deepcopy(dict(descriptor)),
                    "path": f"{TARGET_ROOT}/{relative}",
                }
            )

        installed_media: list[dict[str, object]] = []
        for variant in ("h264", "h265"):
            for role in ("underbody", "front_gate"):
                descriptor = media[(variant, role)]
                source = root.joinpath(
                    *PurePosixPath(str(descriptor["source_path"])).parts
                )
                relative = _target_media_relative(variant, role)
                destination = working.joinpath(*PurePosixPath(relative).parts)
                try:
                    _copy_pinned_snapshot(
                        source=source,
                        target=destination,
                        expected_sha256=str(descriptor["sha256"]),
                        expected_size_bytes=int(descriptor["size_bytes"]),
                        label=f"{variant}/{role} frozen media",
                    )
                    observed_probe = _validate_output_probe(
                        role, variant, prober(destination)
                    )
                except TranscodeFreezeError as exc:
                    raise PublicationCorpusFreezeError(
                        f"{variant}/{role} ffprobe contract failed: {exc}"
                    ) from exc
                if observed_probe != descriptor["media"]:
                    raise PublicationCorpusFreezeError(
                        f"{variant}/{role} ffprobe contract drifted from receipt"
                    )
                final_size, final_sha, _ = _stable_payload(
                    destination,
                    label=f"{variant}/{role} frozen media after ffprobe",
                    retain=False,
                )
                if (
                    final_size != descriptor["size_bytes"]
                    or final_sha != descriptor["sha256"]
                ):
                    raise PublicationCorpusFreezeError(
                        f"{variant}/{role} media changed during ffprobe"
                    )
                installed_media.append(
                    {
                        "codec_variant": variant,
                        "role": role,
                        "source_path": descriptor["source_path"],
                        "path": f"{TARGET_ROOT}/{relative}",
                        "size_bytes": final_size,
                        "sha256": final_sha,
                        "ffprobe": observed_probe,
                    }
                )

        claims = _publication_claims()
        authorization: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_kpp_iss_publication_v3_authorization_receipt"
            ),
            "generation_id": GENERATION_ID,
            "dataset_ids": copy.deepcopy(DATASET_IDS),
            "status": "authorized_for_performance_publication",
            "authorization_basis": {
                "kind": "explicit_user_instruction",
                "basis_id": AUTHORIZATION_BASIS_ID,
                "authorized_scope": (
                    "performance_and_topology_benchmark_results_only"
                ),
                "excluded_scopes": [
                    "accuracy_evaluation",
                    "production_routing_validation",
                    "v1_dataset_equivalence",
                ],
            },
            "source_generation": {
                "generation_id": SOURCE_GENERATION_ID,
                "identity_equivalent": False,
            },
            "source_archives": copy.deepcopy(pins["source_archives"]),
            "source_receipts": copy.deepcopy(installed_receipts),
            "claims": copy.deepcopy(claims),
        }
        authorization["authorization_receipt_sha256"] = _receipt_self_hash(
            authorization,
            field="authorization_receipt_sha256",
            domain=AUTHORIZATION_RECEIPT_DOMAIN,
        )
        authorization_payload = _write_canonical(
            working / AUTHORIZATION_RECEIPT_NAME, authorization
        )
        authorization_descriptor = {
            "path": f"{TARGET_ROOT}/{AUTHORIZATION_RECEIPT_NAME}",
            "size_bytes": len(authorization_payload),
            "sha256": hashlib.sha256(authorization_payload).hexdigest(),
            "authorization_receipt_sha256": authorization[
                "authorization_receipt_sha256"
            ],
        }

        datasets = [
            {
                "dataset_id": DATASET_IDS[variant],
                "codec_variant": variant,
                "publication_scope": (
                    "performance_and_topology_benchmark_results_only"
                ),
                "analytics_routing": "unresolved",
                "accuracy_ground_truth": False,
                "physical_stream_paths": [
                    f"{TARGET_ROOT}/{_target_media_relative(variant, role)}"
                    for role in ("underbody", "front_gate")
                ],
            }
            for variant in ("h264", "h265")
        ]
        manifest: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_iss_publication_v3_manifest",
            "generation_id": GENERATION_ID,
            "status": "frozen_publication_corpus",
            "dataset_root": TARGET_ROOT,
            "dataset_ids": copy.deepcopy(DATASET_IDS),
            "datasets": datasets,
            "source_generation": {
                "generation_id": SOURCE_GENERATION_ID,
                "identity_equivalent": False,
            },
            "source_archives": copy.deepcopy(pins["source_archives"]),
            "source_receipts": copy.deepcopy(installed_receipts),
            "ffprobe": copy.deepcopy(ffprobe_descriptor),
            "media_artifacts": installed_media,
            "authorization_receipt": authorization_descriptor,
            "claims": copy.deepcopy(claims),
        }
        manifest["manifest_sha256"] = _receipt_self_hash(
            manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
        )
        manifest_payload = _write_canonical(working / MANIFEST_NAME, manifest)

        _validate_exact_tree(working)
        try:
            _atomic_publish_directory(working, target)
        except TranscodeFreezeError as exc:
            raise PublicationCorpusFreezeError(str(exc)) from exc
        published = True
        _validate_exact_tree(target)
        if (target / MANIFEST_NAME).read_bytes() != manifest_payload:
            raise PublicationCorpusFreezeError(
                "published manifest bytes changed after atomic publication"
            )
        if (
            target / AUTHORIZATION_RECEIPT_NAME
        ).read_bytes() != authorization_payload:
            raise PublicationCorpusFreezeError(
                "published authorization receipt bytes changed"
            )
        for descriptor in installed_media:
            relative = PurePosixPath(str(descriptor["path"])).relative_to(
                TARGET_ROOT
            )
            path = target.joinpath(*relative.parts)
            size, digest, _ = _stable_payload(
                path,
                label=f"published {descriptor['codec_variant']}/{descriptor['role']}",
                retain=False,
            )
            if size != descriptor["size_bytes"] or digest != descriptor["sha256"]:
                raise PublicationCorpusFreezeError(
                    "published media bytes drifted from manifest"
                )
        return manifest
    except Exception:
        if not published and _lexists(working):
            try:
                _cleanup_owned_candidate(working, target_parent)
            except OSError:
                pass
        raise


def freeze_publication_corpus(
    *,
    project_root: Path,
    authorization_basis: str,
    ffprobe: Path,
) -> dict[str, object]:
    """Authoritatively freeze the exact production v3 publication corpus."""

    return _freeze_publication_corpus_impl(
        project_root=project_root,
        authorization_basis=authorization_basis,
        ffprobe=ffprobe,
        test_adapters=None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--authorization-basis", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        manifest = freeze_publication_corpus(
            project_root=args.project_root,
            authorization_basis=args.authorization_basis,
            ffprobe=args.ffprobe,
        )
    except PublicationCorpusFreezeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 78
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORIZATION_BASIS_ID",
    "AUTHORIZATION_RECEIPT_DOMAIN",
    "DATASET_IDS",
    "FROZEN_FFPROBE",
    "FROZEN_MEDIA",
    "FROZEN_SOURCE_ARCHIVES",
    "FROZEN_SOURCE_RECEIPTS",
    "GENERATION_ID",
    "MANIFEST_DOMAIN",
    "PublicationCorpusFreezeError",
    "freeze_publication_corpus",
]
