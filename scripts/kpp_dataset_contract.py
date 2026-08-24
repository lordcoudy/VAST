#!/usr/bin/env python3
"""Build the distinct KPP legacy ISS v2 dataset manifest entries.

This module is deliberately write-free.  It accepts only cross-bound,
authoritative extraction, transcode, and metadata receipts and returns new v2
dataset entries.  It does not edit ``configs/datasets.yaml`` or grant either
receipt independent publication authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any


GENERATION_ID = "kpp_legacy_iss_v2"
DATASET_CONTRACT_VERSION = 2
TIMESTAMP_CONTRACT_VERSION = 1
PROVENANCE_CONTRACT_VERSION = 1

DATASET_NAMES = MappingProxyType(
    {
        "avi": "kpp_legacy_iss_v2_avi",
        "h264": "kpp_legacy_iss_v2_h264",
        "h265": "kpp_legacy_iss_v2_h265",
    }
)
PREDECESSOR_MANIFEST_IDENTITIES = MappingProxyType(
    {
        "kpp_real_avi": (
            "940cf02d9f7fd7b0179fd4eaf858fb7f095bc860df1dfb72681a4f86ca69379f"
        ),
        "kpp_real_h264": (
            "1d3b7a0c7e4b9b0a51c901371763e6f52019d69f257fd78a6c74664f4e233951"
        ),
        "kpp_real_h265": (
            "0f166e745e36ae979a3cb89fb3214636422a4a55f5255664d9b5089af7ec59db"
        ),
    }
)

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
HEADER_CALENDAR_RE = re.compile(
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\Z"
)
DATED_EVENT_RE = re.compile(
    r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3}\Z"
)
TIME_ONLY_EVENT_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\Z")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
PACKETIZATION_CONTRACT = (
    "iss_record_media_start_to_next_record_media_start_or_eof_v1"
)
_FINAL_DATASET_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
METADATA_DESTINATION = (
    f"{_FINAL_DATASET_ROOT}/metadata/iss_v2_underbody_metadata.json"
)
_OUTPUT_FPS = 600

_RECEIPT_DOMAINS = {
    "extraction_receipt_sha256": (
        b"VAST:kpp-legacy-iss-extraction-receipt:v1\0"
    ),
    "transcode_receipt_sha256": (
        b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0"
    ),
    "normalization_receipt_sha256": b"VAST:kpp-legacy-iss-metadata:v1\0",
}

_SOURCE_MEDIA: dict[str, dict[str, object]] = {
    "underbody": {
        "codec_name": "mjpeg",
        "width": 1700,
        "height": 236,
        "r_frame_rate": "200/1",
        "avg_frame_rate": "200/1",
        "frame_count": 11882,
        "duration_ns": 59_410_000_000,
    },
    "front_gate": {
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "r_frame_rate": "25/1",
        "avg_frame_rate": "25/1",
        "frame_count": 1380,
        "duration_ns": 55_200_000_000,
    },
}

_TRANSCODE_CODEC_PROFILES: dict[str, dict[str, object]] = {
    "h264": {
        "encoder": "libx264",
        "preset": "veryfast",
        "crf": 23,
        "pix_fmt": "yuv420p",
        "codec_name": "h264",
        "bitstream_filter": "h264_metadata=video_full_range_flag=0",
    },
    "h265": {
        "encoder": "libx265",
        "preset": "ultrafast",
        "crf": 30,
        "pix_fmt": "yuv420p",
        "codec_name": "hevc",
        "bitstream_filter": "hevc_metadata=video_full_range_flag=0",
    },
}

_EXTRACTION_TRUE_CLAIMS = frozenset(
    {
        "source_bytes_externally_pinned",
        "source_private_snapshots_verified",
        "tool_bytes_and_version_outputs_externally_pinned",
        "payload_offsets_detected",
        "video_payloads_stream_copied",
        "output_set_directory_published_atomically",
        "windows_project_root_staging_and_working_directory_handle_custody_validated",
    }
)
_EXTRACTION_FALSE_CLAIMS = frozenset(
    {
        "source_timestamps_preserved",
        "archiveplayer_export_reproduced",
        "v1_dataset_identity_equivalent",
        "accuracy_ground_truth_validated",
        "publication_authorized",
    }
)
_TRANSCODE_TRUE_CLAIMS = frozenset(
    {
        "authoritative_extraction_receipt_consumed",
        "source_avi_bytes_verified_against_extraction_receipt",
        "source_avi_private_snapshots_verified",
        "tool_bytes_and_version_outputs_externally_pinned",
        "transcodes_executed_by_pinned_ffmpeg",
        "outputs_validated_by_pinned_ffprobe",
        "output_bytes_post_hashed",
        "output_set_directory_published_atomically",
        "windows_project_root_staging_and_working_directory_handle_custody_validated",
    }
)
_TRANSCODE_FALSE_CLAIMS = frozenset(
    {
        "source_timestamps_preserved",
        "accuracy_ground_truth_validated",
        "v1_dataset_identity_equivalent",
        "publication_authorized",
    }
)
_METADATA_TRUE_CLAIMS = frozenset(
    {
        "avi_packet_source_interval_binding_validated",
        "avi_physical_movi_packet_index_alignment_validated",
        "avi_packet_jpeg_prefix_binding_validated",
        "source_and_avi_private_snapshots_verified",
        "output_set_directory_published_atomically",
        "windows_project_root_staging_and_working_directory_handle_custody_validated",
    }
)
_METADATA_FALSE_CLAIMS = frozenset(
    {
        "timestamps_interpolated",
        "clock_domains_equated",
        "timezone_validated",
        "frame_clock_unit_validated",
        "frame_clock_epoch_validated",
        "event_semantics_validated",
        "avi_demuxed_or_decoded_frame_index_alignment_validated",
        "avi_packet_equals_declared_media_without_trailer",
        "avi_packet_payload_is_clean_jpeg",
        "accuracy_ground_truth_validated",
        "v1_dataset_identity_equivalent",
        "publication_authorized",
    }
)

_CLOCK_DOMAINS: dict[str, dict[str, object]] = {
    "header_clock": {
        "source": "record_header_8xu16_calendar_fields",
        "resolution": "millisecond",
        "timezone": None,
    },
    "frame_clock": {
        "source": "tag_4_frame_time_and_magnet_time_integers",
        "unit": None,
        "epoch": None,
        "present_only_when_observed": True,
    },
}

_LOGICAL_STREAMS = (
    (0, "front_gate", "plate_number"),
    (1, "front_gate", "plate_number"),
    (2, "front_gate", "vehicle_type"),
    (3, "front_gate", "damage"),
    (4, "front_gate", "damage"),
    (5, "underbody", "foreign_object"),
)


class KppDatasetContractError(RuntimeError):
    """Raised when candidate receipts cannot support a v2 dataset entry."""


def _require_exact_keys(
    value: Mapping[str, object], *, expected: set[str] | frozenset[str], label: str
) -> None:
    if set(value) != set(expected):
        raise KppDatasetContractError(f"{label} schema mismatch")


def _require_schema_version(value: object, *, label: str) -> int:
    if type(value) is not int or value != 1:
        raise KppDatasetContractError(f"{label} schema_version mismatch")
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
        raise KppDatasetContractError(
            "receipt must be canonical-JSON serializable"
        ) from exc
    return (encoded + "\n").encode("ascii")


def _require_mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise KppDatasetContractError(f"{label} must be an object")
    result = dict(value)
    if any(type(key) is not str for key in result):
        raise KppDatasetContractError(f"{label} keys must be strings")
    return result


def _require_list(value: object, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise KppDatasetContractError(f"{label} must be an array")
    return list(value)


def _require_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise KppDatasetContractError(
            f"{label} must be an exact lowercase SHA-256"
        )
    if value == "0" * 64:
        raise KppDatasetContractError(f"{label} must not be an all-zero SHA-256")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise KppDatasetContractError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise KppDatasetContractError(f"{label} must be a non-negative integer")
    return value


def _require_relative_path(value: object, *, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise KppDatasetContractError(f"{label} must be a non-empty relative path")
    if "\\" in value or "\x00" in value or "//" in value or ":" in value:
        raise KppDatasetContractError(f"{label} must use a canonical POSIX path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or any(part in ("", ".", "..") for part in candidate.parts)
        or candidate.as_posix() != value
    ):
        raise KppDatasetContractError(f"{label} must use a canonical POSIX path")
    return value


def _validate_self_hash(
    receipt: dict[str, Any],
    *,
    field: str,
    label: str,
) -> str:
    claimed = _require_sha256(receipt.get(field), label=f"{label} self hash")
    unsigned = dict(receipt)
    unsigned.pop(field, None)
    observed = hashlib.sha256(
        _RECEIPT_DOMAINS[field] + _canonical_bytes(unsigned)
    ).hexdigest()
    if claimed != observed:
        raise KppDatasetContractError(f"{label} self hash does not match")
    return claimed


def _validate_artifact_descriptor(
    artifact: object,
    receipt: dict[str, Any],
    *,
    label: str,
) -> dict[str, object]:
    descriptor = _require_mapping(artifact, label=f"{label} artifact")
    if set(descriptor) != {"path", "size_bytes", "sha256"}:
        raise KppDatasetContractError(f"{label} artifact schema mismatch")
    path = _require_relative_path(descriptor["path"], label=f"{label} artifact path")
    if PurePosixPath(path).suffix.lower() != ".json":
        raise KppDatasetContractError(f"{label} artifact must be a JSON file")
    expected_payload = _canonical_bytes(receipt)
    size = _require_positive_int(
        descriptor["size_bytes"], label=f"{label} artifact size_bytes"
    )
    if size != len(expected_payload):
        raise KppDatasetContractError(f"{label} artifact size does not match receipt")
    digest = _require_sha256(
        descriptor["sha256"], label=f"{label} artifact SHA-256"
    )
    if digest != hashlib.sha256(expected_payload).hexdigest():
        raise KppDatasetContractError(
            f"{label} artifact SHA-256 does not match receipt bytes"
        )
    return {"path": path, "size_bytes": size, "sha256": digest}


def _validate_claims(
    value: object,
    *,
    label: str,
    true_claims: frozenset[str],
    false_claims: frozenset[str],
) -> dict[str, bool]:
    claims = _require_mapping(value, label=f"{label} claims")
    expected_fields = true_claims | false_claims
    if set(claims) != set(expected_fields):
        raise KppDatasetContractError(f"{label} claims schema mismatch")
    if any(type(item) is not bool for item in claims.values()):
        raise KppDatasetContractError(f"{label} claims must be booleans")
    for name in sorted(true_claims):
        if claims.get(name) is not True:
            raise KppDatasetContractError(
                f"{label} claim {name!r} must be true"
            )
    for name in sorted(false_claims):
        if claims.get(name) is not False:
            raise KppDatasetContractError(
                f"{label} claim {name!r} must be false"
            )
    return dict(claims)


def _expected_transcode_frame_count(role: str) -> int:
    source = _SOURCE_MEDIA[role]
    duration_ns = int(source["duration_ns"])
    numerator = duration_ns * _OUTPUT_FPS
    frame_count, remainder = divmod(numerator, 1_000_000_000)
    if remainder:
        raise KppDatasetContractError(
            f"{role} duration cannot map exactly to a 600/1 timeline"
        )
    return frame_count


def _expected_transcode_recipe(role: str, variant: str) -> dict[str, object]:
    source = _SOURCE_MEDIA[role]
    profile = _TRANSCODE_CODEC_PROFILES[variant]
    return {
        "codec_variant": variant,
        "role": role,
        "ffmpeg_filter": (
            f"scale=w={source['width']}:h={source['height']}:"
            "in_range=auto:out_range=tv,format=pix_fmts=yuv420p,"
            "fps=fps=600:start_time=0:round=near:eof_action=round"
        ),
        "reinit_filter": 0,
        "encoder": profile["encoder"],
        "preset": profile["preset"],
        "crf": profile["crf"],
        "pix_fmt": profile["pix_fmt"],
        "color_range": "tv",
        "output_frame_rate": f"{_OUTPUT_FPS}/1",
        "fps_mode": "cfr",
        "encoder_time_base": f"1/{_OUTPUT_FPS}",
        "expected_frame_count": _expected_transcode_frame_count(role),
        "video_track_timescale": _OUTPUT_FPS,
        "bitstream_filter": profile["bitstream_filter"],
        "container": "mp4",
    }


def _expected_transcode_media(role: str, variant: str) -> dict[str, object]:
    source = _SOURCE_MEDIA[role]
    profile = _TRANSCODE_CODEC_PROFILES[variant]
    frame_count = _expected_transcode_frame_count(role)
    frame_signature = {
        "width": source["width"],
        "height": source["height"],
        "pix_fmt": profile["pix_fmt"],
        "color_range": "tv",
    }
    return {
        "codec_name": profile["codec_name"],
        "pix_fmt": profile["pix_fmt"],
        "width": source["width"],
        "height": source["height"],
        "r_frame_rate": f"{_OUTPUT_FPS}/1",
        "avg_frame_rate": f"{_OUTPUT_FPS}/1",
        "frame_count": frame_count,
        "duration_ns": source["duration_ns"],
        "color_range": "tv",
        "stream_time_base": f"1/{_OUTPUT_FPS}",
        "stream_duration_ts": frame_count,
        "decoded_frame_count": frame_count,
        "decoded_first_pts": 0,
        "decoded_last_pts": frame_count - 1,
        "decoded_pts_steps": [1],
        "decoded_frame_signatures": [frame_signature],
    }


def _strict_value_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if type(expected) is dict:
        observed_mapping = observed
        expected_mapping = expected
        return set(observed_mapping) == set(expected_mapping) and all(
            _strict_value_equal(observed_mapping[key], expected_mapping[key])
            for key in expected_mapping
        )
    if type(expected) is list:
        observed_items = observed
        expected_items = expected
        return len(observed_items) == len(expected_items) and all(
            _strict_value_equal(observed_item, expected_item)
            for observed_item, expected_item in zip(
                observed_items, expected_items
            )
        )
    return observed == expected


def _validate_media(
    value: object,
    *,
    expected: Mapping[str, object],
    label: str,
) -> dict[str, object]:
    media = _require_mapping(value, label=label)
    if set(media) != set(expected):
        raise KppDatasetContractError(f"{label} schema mismatch")
    for key, expected_value in expected.items():
        observed = media[key]
        if type(expected_value) is int and type(observed) is not int:
            raise KppDatasetContractError(f"{label} {key} type mismatch")
        if not _strict_value_equal(observed, expected_value):
            raise KppDatasetContractError(
                f"{label} {key} mismatch: expected {expected_value!r}, "
                f"got {observed!r}"
            )
    return copy.deepcopy(media)


def _index_records(
    value: object,
    *,
    keys: tuple[str, ...],
    expected: set[tuple[str, ...]],
    label: str,
) -> dict[tuple[str, ...], dict[str, Any]]:
    records = _require_list(value, label=label)
    indexed: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, raw in enumerate(records):
        record = _require_mapping(raw, label=f"{label}[{index}]")
        identity = tuple(str(record.get(key, "")) for key in keys)
        if any(not part for part in identity) or identity in indexed:
            raise KppDatasetContractError(f"{label} has invalid or duplicate keys")
        indexed[identity] = record
    if set(indexed) != expected:
        raise KppDatasetContractError(f"{label} role/variant set mismatch")
    return indexed


def _validate_tools(
    value: object,
    *,
    label: str,
) -> dict[str, dict[str, str]]:
    records = _index_records(
        value,
        keys=("role",),
        expected={("ffmpeg",), ("ffprobe",)},
        label=f"{label} tools",
    )
    tools: dict[str, dict[str, str]] = {}
    for role in ("ffmpeg", "ffprobe"):
        record = records[(role,)]
        if set(record) != {
            "role",
            "executable_sha256",
            "version_output_sha256",
        }:
            raise KppDatasetContractError(f"{label} {role} tool schema mismatch")
        tools[role] = {
            "role": role,
            "executable_sha256": _require_sha256(
                record["executable_sha256"],
                label=f"{label} {role} executable SHA-256",
            ),
            "version_output_sha256": _require_sha256(
                record["version_output_sha256"],
                label=f"{label} {role} version output SHA-256",
            ),
        }
    return tools


def _validate_extraction_receipt(
    receipt_value: object,
    artifact_value: object,
) -> tuple[
    dict[str, Any],
    dict[str, object],
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, dict[str, str]],
]:
    receipt = _require_mapping(receipt_value, label="extraction receipt")
    _require_exact_keys(
        receipt,
        expected={
            "schema_version",
            "artifact_kind",
            "generation_id",
            "status",
            "source_archives",
            "tools",
            "recipes",
            "outputs",
            "claims",
            "extraction_receipt_sha256",
        },
        label="extraction receipt",
    )
    _require_schema_version(
        receipt.get("schema_version"), label="extraction receipt"
    )
    if receipt.get("artifact_kind") != "vast_kpp_legacy_iss_extraction_receipt":
        raise KppDatasetContractError("extraction receipt artifact_kind mismatch")
    if receipt.get("generation_id") != GENERATION_ID:
        raise KppDatasetContractError("extraction receipt generation mismatch")
    if receipt.get("status") != "headless_stream_copy_candidate":
        raise KppDatasetContractError("extraction receipt is not authoritative")
    self_hash = _validate_self_hash(
        receipt,
        field="extraction_receipt_sha256",
        label="extraction receipt",
    )
    artifact = _validate_artifact_descriptor(
        artifact_value, receipt, label="extraction receipt"
    )
    _validate_claims(
        receipt.get("claims"),
        label="extraction receipt",
        true_claims=_EXTRACTION_TRUE_CLAIMS,
        false_claims=_EXTRACTION_FALSE_CLAIMS,
    )
    tools = _validate_tools(receipt.get("tools"), label="extraction")

    source_records = _index_records(
        receipt.get("source_archives"),
        keys=("role",),
        expected={("underbody",), ("front_gate",)},
        label="extraction source archives",
    )
    sources: dict[str, dict[str, object]] = {}
    for role in ("underbody", "front_gate"):
        record = source_records[(role,)]
        _require_exact_keys(
            record,
            expected={
                "archive_logical_id",
                "size_bytes",
                "sha256",
                "role",
                "payload_offset",
            },
            label=f"extraction {role} source archive",
        )
        logical_id = record.get("archive_logical_id")
        if type(logical_id) is not str or not logical_id:
            raise KppDatasetContractError(
                f"extraction {role} source archive logical ID is missing"
            )
        source_size = _require_positive_int(
            record.get("size_bytes"),
            label=f"extraction {role} source archive size_bytes",
        )
        payload_offset = _require_positive_int(
            record.get("payload_offset"),
            label=f"extraction {role} payload_offset",
        )
        if payload_offset >= source_size:
            raise KppDatasetContractError(
                f"extraction {role} payload_offset must be smaller than source size"
            )
        sources[role] = {
            "role": role,
            "archive_logical_id": logical_id,
            "size_bytes": source_size,
            "sha256": _require_sha256(
                record.get("sha256"),
                label=f"extraction {role} source archive SHA-256",
            ),
            "payload_offset": payload_offset,
        }

    recipes = _index_records(
        receipt.get("recipes"),
        keys=("role",),
        expected={("underbody",), ("front_gate",)},
        label="extraction recipes",
    )
    expected_recipes = {
        "underbody": {
            "role": "underbody",
            "demuxer": "mjpeg",
            "source_fps": 200,
            "payload_offset": sources["underbody"]["payload_offset"],
            "codec_mode": "stream_copy",
            "container": "avi",
        },
        "front_gate": {
            "role": "front_gate",
            "demuxer": "h264",
            "source_fps": 25,
            "payload_offset": sources["front_gate"]["payload_offset"],
            "codec_mode": "stream_copy",
            "container": "avi",
        },
    }
    for role, expected_recipe in expected_recipes.items():
        if recipes[(role,)] != expected_recipe:
            raise KppDatasetContractError(
                f"extraction {role} recipe does not match the frozen contract"
            )

    output_records = _index_records(
        receipt.get("outputs"),
        keys=("role",),
        expected={("underbody",), ("front_gate",)},
        label="extraction outputs",
    )
    outputs: dict[str, dict[str, object]] = {}
    for role in ("underbody", "front_gate"):
        record = output_records[(role,)]
        if set(record) != {"role", "path", "size_bytes", "sha256", "media"}:
            raise KppDatasetContractError(
                f"extraction {role} output schema mismatch"
            )
        path = _require_relative_path(
            record["path"], label=f"extraction {role} output path"
        )
        if PurePosixPath(path).name != f"iss_v2_{role}.avi":
            raise KppDatasetContractError(
                f"extraction {role} output logical name mismatch"
            )
        outputs[role] = {
            "role": role,
            "path": path,
            "size_bytes": _require_positive_int(
                record["size_bytes"],
                label=f"extraction {role} output size_bytes",
            ),
            "sha256": _require_sha256(
                record["sha256"], label=f"extraction {role} output SHA-256"
            ),
            "media": _validate_media(
                record["media"],
                expected=_SOURCE_MEDIA[role],
                label=f"extraction {role} output media",
            ),
        }
    if outputs["underbody"]["sha256"] == outputs["front_gate"]["sha256"]:
        raise KppDatasetContractError(
            "underbody and front-gate AVI outputs must be distinct"
        )
    artifact["artifact_kind"] = receipt["artifact_kind"]
    artifact["receipt_sha256"] = self_hash
    artifact["status"] = receipt["status"]
    return receipt, artifact, sources, outputs, tools


def _validate_transcode_receipt(
    receipt_value: object,
    artifact_value: object,
    *,
    extraction_receipt: dict[str, Any],
    extraction_artifact: dict[str, object],
    extraction_outputs: dict[str, dict[str, object]],
    extraction_tools: dict[str, dict[str, str]],
) -> tuple[
    dict[str, Any],
    dict[str, object],
    dict[tuple[str, str], dict[str, object]],
]:
    receipt = _require_mapping(receipt_value, label="transcode receipt")
    _require_exact_keys(
        receipt,
        expected={
            "schema_version",
            "artifact_kind",
            "generation_id",
            "status",
            "source_extraction",
            "sources",
            "tools",
            "recipes",
            "outputs",
            "claims",
            "transcode_receipt_sha256",
        },
        label="transcode receipt",
    )
    _require_schema_version(
        receipt.get("schema_version"), label="transcode receipt"
    )
    if receipt.get("artifact_kind") != "vast_kpp_legacy_iss_v2_transcode_receipt":
        raise KppDatasetContractError("transcode receipt artifact_kind mismatch")
    if receipt.get("generation_id") != GENERATION_ID:
        raise KppDatasetContractError("transcode receipt generation mismatch")
    if receipt.get("status") != "pinned_codec_transcode_candidate":
        raise KppDatasetContractError("transcode receipt is not authoritative")
    self_hash = _validate_self_hash(
        receipt,
        field="transcode_receipt_sha256",
        label="transcode receipt",
    )
    artifact = _validate_artifact_descriptor(
        artifact_value, receipt, label="transcode receipt"
    )
    _validate_claims(
        receipt.get("claims"),
        label="transcode receipt",
        true_claims=_TRANSCODE_TRUE_CLAIMS,
        false_claims=_TRANSCODE_FALSE_CLAIMS,
    )
    tools = _validate_tools(receipt.get("tools"), label="transcode")
    if tools != extraction_tools:
        raise KppDatasetContractError(
            "transcode tools do not bind extraction tool provenance"
        )

    source_extraction = _require_mapping(
        receipt.get("source_extraction"),
        label="transcode source extraction",
    )
    expected_source_binding = {
        "artifact_logical_id": PurePosixPath(
            str(extraction_artifact["path"])
        ).name,
        "path": extraction_artifact["path"],
        "size_bytes": extraction_artifact["size_bytes"],
        "file_sha256": extraction_artifact["sha256"],
        "extraction_receipt_sha256": extraction_receipt[
            "extraction_receipt_sha256"
        ],
        "status": extraction_receipt["status"],
    }
    if source_extraction != expected_source_binding:
        raise KppDatasetContractError(
            "transcode receipt does not bind the extraction receipt artifact"
        )

    source_records = _index_records(
        receipt.get("sources"),
        keys=("role",),
        expected={("underbody",), ("front_gate",)},
        label="transcode sources",
    )
    for role in ("underbody", "front_gate"):
        source = source_records[(role,)]
        extraction_output = extraction_outputs[role]
        expected = {
            "role": role,
            "artifact_logical_id": PurePosixPath(
                str(extraction_output["path"])
            ).name,
            "path": extraction_output["path"],
            "size_bytes": extraction_output["size_bytes"],
            "sha256": extraction_output["sha256"],
            "media": extraction_output["media"],
        }
        if source != expected:
            raise KppDatasetContractError(
                f"transcode {role} source does not bind the extraction output"
            )

    recipe_records = _index_records(
        receipt.get("recipes"),
        keys=("codec_variant", "role"),
        expected={
            (variant, role)
            for variant in ("h264", "h265")
            for role in ("underbody", "front_gate")
        },
        label="transcode recipes",
    )
    for variant in ("h264", "h265"):
        for role in ("underbody", "front_gate"):
            _validate_media(
                recipe_records[(variant, role)],
                expected=_expected_transcode_recipe(role, variant),
                label=f"{variant}/{role} recipe",
            )

    output_records = _index_records(
        receipt.get("outputs"),
        keys=("codec_variant", "role"),
        expected={
            (variant, role)
            for variant in ("h264", "h265")
            for role in ("underbody", "front_gate")
        },
        label="transcode outputs",
    )
    outputs: dict[tuple[str, str], dict[str, object]] = {}
    for variant in ("h264", "h265"):
        for role in ("underbody", "front_gate"):
            record = output_records[(variant, role)]
            if set(record) != {
                "codec_variant",
                "role",
                "path",
                "size_bytes",
                "sha256",
                "media",
            }:
                raise KppDatasetContractError(
                    f"{variant}/{role} transcode output schema mismatch"
                )
            path = _require_relative_path(
                record["path"], label=f"{variant}/{role} output path"
            )
            path_value = PurePosixPath(path)
            if (
                path_value.name != f"iss_v2_{role}.mp4"
                or path_value.parent.name != variant
            ):
                raise KppDatasetContractError(
                    f"{variant}/{role} transcode output logical path mismatch"
                )
            outputs[(variant, role)] = {
                "codec_variant": variant,
                "role": role,
                "path": path,
                "size_bytes": _require_positive_int(
                    record["size_bytes"],
                    label=f"{variant}/{role} output size_bytes",
                ),
                "sha256": _require_sha256(
                    record["sha256"],
                    label=f"{variant}/{role} output SHA-256",
                ),
                "media": _validate_media(
                    record["media"],
                    expected=_expected_transcode_media(role, variant),
                    label=f"{variant}/{role} output media",
                ),
            }
    artifact["artifact_kind"] = receipt["artifact_kind"]
    artifact["receipt_sha256"] = self_hash
    artifact["status"] = receipt["status"]
    return receipt, artifact, outputs


def _validate_metadata_header_clock(
    value: object, *, frame_index: int
) -> datetime:
    label = f"metadata frame {frame_index} header_clock"
    clock = _require_mapping(value, label=label)
    _require_exact_keys(
        clock, expected={"calendar_text", "fields"}, label=label
    )
    text = clock["calendar_text"]
    if type(text) is not str or HEADER_CALENDAR_RE.fullmatch(text) is None:
        raise KppDatasetContractError(f"{label} calendar_text is invalid")
    fields = _require_mapping(clock["fields"], label=f"{label} fields")
    names = (
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "millisecond",
    )
    _require_exact_keys(fields, expected=set(names), label=f"{label} fields")
    if any(type(fields[name]) is not int for name in names):
        raise KppDatasetContractError(f"{label} fields must be integers")
    try:
        observed = datetime(
            int(fields["year"]),
            int(fields["month"]),
            int(fields["day"]),
            int(fields["hour"]),
            int(fields["minute"]),
            int(fields["second"]),
            int(fields["millisecond"]) * 1000,
        )
    except ValueError as exc:
        raise KppDatasetContractError(f"{label} fields are invalid") from exc
    canonical = observed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if canonical != text:
        raise KppDatasetContractError(
            f"{label} calendar_text does not match its fields"
        )
    return observed


def _validate_metadata_frame_clock(
    value: object,
    sensor_value: object,
    status_value: object,
    *,
    frame_index: int,
) -> tuple[int, int] | None:
    label = f"metadata frame {frame_index}"
    if value is None:
        if type(status_value) is not int or status_value != 1:
            raise KppDatasetContractError(
                f"{label} status-only tag4_status must be integer 1"
            )
        if sensor_value is not None:
            raise KppDatasetContractError(
                f"{label} status-only sensor_data_8x3 must be null"
            )
        return None
    if status_value is not None:
        raise KppDatasetContractError(f"{label} rich tag4_status must be null")
    clock = _require_mapping(value, label=f"{label} frame_clock")
    _require_exact_keys(
        clock,
        expected={"frame_time", "magnet_time"},
        label=f"{label} frame_clock",
    )
    times: list[int] = []
    for name in ("frame_time", "magnet_time"):
        observed = clock[name]
        if (
            type(observed) is not int
            or observed < 1_000_000_000_000_000
            or observed > 9_999_999_999_999_999
        ):
            raise KppDatasetContractError(
                f"{label} frame_clock {name} must be a 16-digit integer"
            )
        times.append(observed)
    matrix = _require_list(sensor_value, label=f"{label} sensor_data_8x3")
    if len(matrix) != 8:
        raise KppDatasetContractError(f"{label} sensor_data_8x3 must be 8x3")
    for row in matrix:
        if type(row) is not list or len(row) != 3:
            raise KppDatasetContractError(
                f"{label} sensor_data_8x3 must be 8x3"
            )
        if any(
            type(item) is not int or not -(2**31) <= item < 2**31
            for item in row
        ):
            raise KppDatasetContractError(
                f"{label} sensor_data_8x3 values must be int32"
            )
    return times[0], times[1]


def _validate_metadata_frames(
    value: object,
    *,
    expected_count: int,
    source_size_bytes: int,
    source_payload_offset: int,
) -> None:
    frames = _require_list(value, label="metadata frames")
    if len(frames) != expected_count:
        raise KppDatasetContractError(
            "metadata frame count does not bind the underbody AVI"
        )
    previous_record_offset = -1
    previous_media_offset = -1
    previous_header_clock: datetime | None = None
    previous_frame_time: int | None = None
    previous_magnet_time: int | None = None
    interval_ends: list[int] = []
    media_offsets: list[int] = []
    frame_fields = {
        "frame_index",
        "record_offset_bytes",
        "header_clock",
        "frame_clock",
        "tag4_status",
        "sensor_data_8x3",
        "source_fields_u32",
        "aux",
        "primary_event_snapshot",
        "media",
    }
    for index, raw in enumerate(frames):
        frame = _require_mapping(raw, label=f"metadata frame {index}")
        _require_exact_keys(
            frame, expected=frame_fields, label=f"metadata frame {index}"
        )
        frame_index = frame["frame_index"]
        if type(frame_index) is not int or frame_index != index:
            raise KppDatasetContractError(
                f"metadata frame {index} frame_index must equal its array index"
            )
        record_offset = _require_nonnegative_int(
            frame["record_offset_bytes"],
            label=f"metadata frame {index} record_offset_bytes",
        )
        if record_offset <= previous_record_offset or record_offset >= source_size_bytes:
            raise KppDatasetContractError(
                f"metadata frame {index} record_offset_bytes is not strictly ordered"
            )
        previous_record_offset = record_offset
        header_clock = _validate_metadata_header_clock(
            frame["header_clock"], frame_index=index
        )
        if previous_header_clock is not None and header_clock <= previous_header_clock:
            raise KppDatasetContractError(
                "metadata frame header clocks must be strictly monotonic"
            )
        previous_header_clock = header_clock
        frame_clock = _validate_metadata_frame_clock(
            frame["frame_clock"],
            frame["sensor_data_8x3"],
            frame["tag4_status"],
            frame_index=index,
        )
        if frame_clock is not None:
            frame_time, magnet_time = frame_clock
            if (
                previous_frame_time is not None
                and frame_time <= previous_frame_time
            ) or (
                previous_magnet_time is not None
                and magnet_time <= previous_magnet_time
            ):
                raise KppDatasetContractError(
                    "metadata rich frame clocks must be strictly monotonic"
                )
            previous_frame_time = frame_time
            previous_magnet_time = magnet_time

        source_fields = _require_list(
            frame["source_fields_u32"],
            label=f"metadata frame {index} source_fields_u32",
        )
        if len(source_fields) != 7 or any(
            type(item) is not int or not 0 <= item < 2**32
            for item in source_fields
        ):
            raise KppDatasetContractError(
                f"metadata frame {index} source_fields_u32 must contain 7 uint32 values"
            )

        aux = _require_mapping(frame["aux"], label=f"metadata frame {index} aux")
        _require_exact_keys(
            aux,
            expected={"size_bytes", "sha256"},
            label=f"metadata frame {index} aux",
        )
        if type(aux["size_bytes"]) is not int or aux["size_bytes"] != 0:
            raise KppDatasetContractError(
                f"metadata frame {index} aux size_bytes must be integer zero"
            )
        if _require_sha256(
            aux["sha256"], label=f"metadata frame {index} aux SHA-256"
        ) != EMPTY_SHA256:
            raise KppDatasetContractError(
                f"metadata frame {index} empty aux SHA-256 mismatch"
            )

        primary = _require_mapping(
            frame["primary_event_snapshot"],
            label=f"metadata frame {index} primary_event_snapshot",
        )
        _require_exact_keys(
            primary,
            expected={"size_bytes", "sha256"},
            label=f"metadata frame {index} primary_event_snapshot",
        )
        _require_positive_int(
            primary["size_bytes"],
            label=f"metadata frame {index} primary_event_snapshot size_bytes",
        )
        _require_sha256(
            primary["sha256"],
            label=f"metadata frame {index} primary_event_snapshot SHA-256",
        )

        media = _require_mapping(
            frame["media"], label=f"metadata frame {index} media"
        )
        _require_exact_keys(
            media,
            expected={
                "offset_bytes",
                "size_bytes",
                "sha256",
                "jpeg_payload_size_bytes",
                "jpeg_payload_sha256",
                "avi_packet_source_interval",
            },
            label=f"metadata frame {index} media",
        )
        media_offset = _require_nonnegative_int(
            media["offset_bytes"],
            label=f"metadata frame {index} media offset_bytes",
        )
        media_size = _require_positive_int(
            media["size_bytes"],
            label=f"metadata frame {index} media size_bytes",
        )
        if (
            media_offset <= previous_media_offset
            or record_offset >= media_offset
            or media_offset + media_size > source_size_bytes
        ):
            raise KppDatasetContractError(
                f"metadata frame {index} media offsets are invalid"
            )
        if index == 0 and media_offset != source_payload_offset:
            raise KppDatasetContractError(
                "metadata first media offset must equal extraction underbody "
                "payload_offset"
            )
        previous_media_offset = media_offset
        media_offsets.append(media_offset)
        _require_sha256(
            media["sha256"], label=f"metadata frame {index} media SHA-256"
        )
        jpeg_size = _require_positive_int(
            media["jpeg_payload_size_bytes"],
            label=f"metadata frame {index} JPEG payload size_bytes",
        )
        if jpeg_size != media_size - 4:
            raise KppDatasetContractError(
                f"metadata frame {index} JPEG payload size_bytes must equal "
                "media size_bytes minus 4"
            )
        _require_sha256(
            media["jpeg_payload_sha256"],
            label=f"metadata frame {index} JPEG payload SHA-256",
        )
        interval = _require_mapping(
            media["avi_packet_source_interval"],
            label=f"metadata frame {index} AVI packet source interval",
        )
        _require_exact_keys(
            interval,
            expected={"contract", "offset_bytes", "size_bytes", "sha256"},
            label=f"metadata frame {index} AVI packet source interval",
        )
        if interval["contract"] != PACKETIZATION_CONTRACT:
            raise KppDatasetContractError(
                f"metadata frame {index} packetization contract mismatch"
            )
        interval_offset = _require_nonnegative_int(
            interval["offset_bytes"],
            label=f"metadata frame {index} interval offset_bytes",
        )
        interval_size = _require_positive_int(
            interval["size_bytes"],
            label=f"metadata frame {index} interval size_bytes",
        )
        if (
            interval_offset != media_offset
            or interval_size < media_size
            or interval_offset + interval_size > source_size_bytes
        ):
            raise KppDatasetContractError(
                f"metadata frame {index} AVI packet source interval is invalid"
            )
        _require_sha256(
            interval["sha256"],
            label=f"metadata frame {index} interval SHA-256",
        )
        interval_ends.append(interval_offset + interval_size)

    for index, end_offset in enumerate(interval_ends):
        expected_end = (
            media_offsets[index + 1]
            if index + 1 < len(media_offsets)
            else source_size_bytes
        )
        if end_offset != expected_end:
            raise KppDatasetContractError(
                f"metadata frame {index} packet interval does not end at the next media offset or EOF"
            )


def _validate_metadata_events(value: object, *, frame_count: int) -> None:
    events = _require_list(value, label="metadata events")
    previous_frame_index = -1
    for index, raw in enumerate(events):
        event = _require_mapping(raw, label=f"metadata event {index}")
        _require_exact_keys(
            event,
            expected={
                "event_index",
                "kind",
                "timestamp_text",
                "timestamp_has_date",
                "first_observed_frame_index",
            },
            label=f"metadata event {index}",
        )
        if type(event["event_index"]) is not int or event["event_index"] != index:
            raise KppDatasetContractError(
                f"metadata event {index} event_index must equal its array index"
            )
        kind = event["kind"]
        if type(kind) is not str or kind not in {
            "MD_TRUE",
            "MD_FALSE",
            "STITCHING_STARTED",
            "IMAGE",
        }:
            raise KppDatasetContractError(f"metadata event {index} kind is invalid")
        has_date = event["timestamp_has_date"]
        expected_has_date = kind in {"MD_TRUE", "MD_FALSE"}
        if type(has_date) is not bool or has_date is not expected_has_date:
            raise KppDatasetContractError(
                f"metadata event {index} timestamp_has_date is invalid"
            )
        timestamp_text = event["timestamp_text"]
        pattern = DATED_EVENT_RE if expected_has_date else TIME_ONLY_EVENT_RE
        date_format = (
            "%d-%m-%Y %H:%M:%S.%f" if expected_has_date else "%H:%M:%S.%f"
        )
        if (
            type(timestamp_text) is not str
            or pattern.fullmatch(timestamp_text) is None
        ):
            raise KppDatasetContractError(
                f"metadata event {index} timestamp_text is invalid"
            )
        try:
            datetime.strptime(timestamp_text, date_format)
        except ValueError as exc:
            raise KppDatasetContractError(
                f"metadata event {index} timestamp_text is invalid"
            ) from exc
        first_frame = event["first_observed_frame_index"]
        if (
            type(first_frame) is not int
            or not 0 <= first_frame < frame_count
            or first_frame < previous_frame_index
        ):
            raise KppDatasetContractError(
                f"metadata event {index} first_observed_frame_index is invalid"
            )
        previous_frame_index = first_frame


def _validate_metadata_clock_domains(value: object) -> dict[str, object]:
    clock_domains = _require_mapping(value, label="metadata clock_domains")
    _require_exact_keys(
        clock_domains,
        expected={"header_clock", "frame_clock"},
        label="metadata clock_domains",
    )

    header = _require_mapping(
        clock_domains["header_clock"],
        label="metadata clock_domains header_clock",
    )
    _require_exact_keys(
        header,
        expected={"source", "resolution", "timezone"},
        label="metadata clock_domains header_clock",
    )
    if (
        type(header["source"]) is not str
        or header["source"] != "record_header_8xu16_calendar_fields"
        or type(header["resolution"]) is not str
        or header["resolution"] != "millisecond"
        or header["timezone"] is not None
    ):
        raise KppDatasetContractError(
            "metadata timestamp contract clock_domains header_clock mismatch"
        )

    frame = _require_mapping(
        clock_domains["frame_clock"],
        label="metadata clock_domains frame_clock",
    )
    _require_exact_keys(
        frame,
        expected={
            "source",
            "unit",
            "epoch",
            "present_only_when_observed",
        },
        label="metadata clock_domains frame_clock",
    )
    if (
        type(frame["source"]) is not str
        or frame["source"] != "tag_4_frame_time_and_magnet_time_integers"
        or frame["unit"] is not None
        or frame["epoch"] is not None
    ):
        raise KppDatasetContractError(
            "metadata timestamp contract clock_domains frame_clock mismatch"
        )
    if (
        type(frame["present_only_when_observed"]) is not bool
        or frame["present_only_when_observed"] is not True
    ):
        raise KppDatasetContractError(
            "metadata timestamp contract clock_domains frame_clock "
            "present_only_when_observed must be boolean true"
        )
    return copy.deepcopy(clock_domains)


def _validate_metadata_receipt(
    receipt_value: object,
    artifact_value: object,
    *,
    extraction_sources: dict[str, dict[str, object]],
    extraction_outputs: dict[str, dict[str, object]],
) -> tuple[dict[str, Any], dict[str, object]]:
    receipt = _require_mapping(receipt_value, label="metadata receipt")
    _require_exact_keys(
        receipt,
        expected={
            "schema_version",
            "artifact_kind",
            "generation_id",
            "status",
            "source_archive",
            "exported_avi",
            "clock_domains",
            "frames",
            "events",
            "claims",
            "normalization_receipt_sha256",
        },
        label="metadata receipt",
    )
    _require_schema_version(
        receipt.get("schema_version"), label="metadata receipt"
    )
    if receipt.get("artifact_kind") != "vast_kpp_legacy_iss_metadata":
        raise KppDatasetContractError("metadata receipt artifact_kind mismatch")
    if receipt.get("generation_id") != GENERATION_ID:
        raise KppDatasetContractError("metadata receipt generation mismatch")
    if receipt.get("status") != "authoritative_windows_candidate":
        raise KppDatasetContractError("metadata receipt is not authoritative")
    self_hash = _validate_self_hash(
        receipt,
        field="normalization_receipt_sha256",
        label="metadata receipt",
    )
    artifact = _validate_artifact_descriptor(
        artifact_value, receipt, label="metadata receipt"
    )
    claims = _validate_claims(
        receipt.get("claims"),
        label="metadata receipt",
        true_claims=_METADATA_TRUE_CLAIMS,
        false_claims=_METADATA_FALSE_CLAIMS,
    )
    _validate_metadata_clock_domains(receipt.get("clock_domains"))
    if any(
        claims[name] is not expected
        for name, expected in {
            "timestamps_interpolated": False,
            "clock_domains_equated": False,
            "timezone_validated": False,
            "avi_physical_movi_packet_index_alignment_validated": True,
            "avi_demuxed_or_decoded_frame_index_alignment_validated": False,
        }.items()
    ):
        raise KppDatasetContractError("metadata timestamp contract is not truthful")

    source = _require_mapping(
        receipt.get("source_archive"), label="metadata source archive"
    )
    _require_exact_keys(
        source,
        expected={
            "archive_logical_id",
            "sha256",
            "size_bytes",
            "header_size_bytes",
            "header_sha256",
            "record_count",
            "avi_packet_source_interval_sequence_sha256",
        },
        label="metadata source archive",
    )
    source_logical_id = source.get("archive_logical_id")
    if type(source_logical_id) is not str or not source_logical_id:
        raise KppDatasetContractError(
            "metadata source archive logical ID is missing"
        )
    source_size = _require_positive_int(
        source.get("size_bytes"), label="metadata source archive size_bytes"
    )
    source_sha256 = _require_sha256(
        source.get("sha256"), label="metadata source archive SHA-256"
    )
    header_size = source.get("header_size_bytes")
    if type(header_size) is not int or header_size != 65:
        raise KppDatasetContractError(
            "metadata source archive header_size_bytes must be integer 65"
        )
    record_count = source.get("record_count")
    if type(record_count) is not int or record_count != _SOURCE_MEDIA[
        "underbody"
    ]["frame_count"]:
        raise KppDatasetContractError("metadata source record_count mismatch")
    _require_sha256(
        source.get("header_sha256"), label="metadata source header SHA-256"
    )
    _require_sha256(
        source.get("avi_packet_source_interval_sequence_sha256"),
        label="metadata packet interval sequence SHA-256",
    )
    expected_source = extraction_sources["underbody"]
    if (
        source_logical_id != expected_source["archive_logical_id"]
        or source_size != expected_source["size_bytes"]
        or source_sha256 != expected_source["sha256"]
    ):
        raise KppDatasetContractError(
            "metadata receipt does not bind the underbody source archive"
        )
    exported = _require_mapping(
        receipt.get("exported_avi"), label="metadata exported AVI"
    )
    _require_exact_keys(
        exported,
        expected={
            "artifact_logical_id",
            "sha256",
            "size_bytes",
            "frame_count",
            "frame_count_authority",
            "packetization_contract",
        },
        label="metadata exported AVI",
    )
    if type(exported.get("frame_count")) is not int:
        raise KppDatasetContractError(
            "metadata exported AVI frame_count must be an integer"
        )
    _require_positive_int(
        exported.get("size_bytes"),
        label="metadata exported AVI size_bytes",
    )
    _require_sha256(
        exported.get("sha256"), label="metadata exported AVI SHA-256"
    )
    underbody = extraction_outputs["underbody"]
    expected_exported = {
        "artifact_logical_id": PurePosixPath(str(underbody["path"])).name,
        "sha256": underbody["sha256"],
        "size_bytes": underbody["size_bytes"],
        "frame_count": _SOURCE_MEDIA["underbody"]["frame_count"],
        "frame_count_authority": "physical_movi_packet_sequence_validation",
        "packetization_contract": PACKETIZATION_CONTRACT,
    }
    if exported != expected_exported:
        raise KppDatasetContractError(
            "metadata receipt does not bind the underbody AVI"
        )
    _validate_metadata_frames(
        receipt.get("frames"),
        expected_count=record_count,
        source_size_bytes=source_size,
        source_payload_offset=int(expected_source["payload_offset"]),
    )
    _validate_metadata_events(receipt.get("events"), frame_count=record_count)
    artifact["artifact_kind"] = receipt["artifact_kind"]
    artifact["receipt_sha256"] = self_hash
    artifact["status"] = receipt["status"]
    return receipt, artifact


def _final_media_path(variant: str, role: str) -> str:
    suffix = "avi" if variant == "avi" else "mp4"
    return f"{_FINAL_DATASET_ROOT}/{variant}/iss_v2_{role}.{suffix}"


def _receipt_provenance(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "artifact_kind": value["artifact_kind"],
        "path": value["path"],
        "size_bytes": value["size_bytes"],
        "file_sha256": value["sha256"],
        "receipt_sha256": value["receipt_sha256"],
        **({"status": value["status"]} if "status" in value else {}),
    }


def _timestamp_contract(variant: str) -> dict[str, object]:
    return {
        "schema_version": TIMESTAMP_CONTRACT_VERSION,
        "video_timeline_authority": "receipt_bound_pinned_ffprobe_validation",
        "video_timeline_policy": (
            "synthetic_demux_rates_200_underbody_25_front_gate"
            if variant == "avi"
            else "cfr_600_from_source_pts"
        ),
        "source_timestamps_preserved": False,
        "metadata_scope": "underbody_source_avi_only",
        "underbody_avi_physical_movi_packet_index_alignment": (
            "validated_exact_physical_packet_sequence"
        ),
        "demuxed_or_decoded_frame_index_alignment": "not_claimed",
        "derived_codec_frame_index_alignment": (
            "not_applicable" if variant == "avi" else "not_claimed"
        ),
        "timestamps_interpolated": False,
        "clock_domains_equated": False,
        "timezone_validated": False,
        "frame_clock_unit_validated": False,
        "frame_clock_epoch_validated": False,
        "event_semantics_validated": False,
        "accuracy_ground_truth": False,
        "clock_domains": copy.deepcopy(_CLOCK_DOMAINS),
    }


def _lineage(variant: str) -> dict[str, object]:
    predecessor = "kpp_real_avi" if variant == "avi" else f"kpp_real_{variant}"
    return {
        "predecessor_dataset": predecessor,
        "predecessor_manifest_identity_schema_version": 1,
        "predecessor_manifest_identity_sha256": PREDECESSOR_MANIFEST_IDENTITIES[
            predecessor
        ],
        "identity_equivalent": False,
        "reason": (
            "headless_legacy_iss_stream_copy_and_derived_transcodes_are_distinct_"
            "from_the_v1_archiveplayer_generation"
        ),
    }


def _build_streams(
    variant: str,
    *,
    outputs: Mapping[tuple[str, str], Mapping[str, object]],
) -> list[dict[str, object]]:
    streams: list[dict[str, object]] = []
    for stream_id, role, camera_role in _LOGICAL_STREAMS:
        output = outputs[(variant, role)]
        media = _require_mapping(output["media"], label=f"{variant}/{role} media")
        stream: dict[str, object] = {
            "stream_id": stream_id,
            "path": _final_media_path(variant, role),
            "sha256": output["sha256"],
            "camera_role": camera_role,
            "source_id": f"kpp_iss_v2_{role}",
            "container": "avi" if variant == "avi" else "mp4",
            "codec_name": media["codec_name"],
            "width": media["width"],
            "height": media["height"],
            "r_frame_rate": media["r_frame_rate"],
            "avg_frame_rate": media["avg_frame_rate"],
            "fps_policy": (
                "constant" if variant == "avi" else "cfr_600_from_source_pts"
            ),
            "duration_s": int(media["duration_ns"]) / 1_000_000_000,
            "frame_count": media["frame_count"],
        }
        if "pix_fmt" in media:
            stream["pix_fmt"] = media["pix_fmt"]
        if variant != "avi":
            stream["source_path"] = _final_media_path("avi", role)
        streams.append(stream)
    return streams


def build_dataset_entries(
    *,
    extraction_receipt: Mapping[str, object],
    extraction_receipt_artifact: Mapping[str, object],
    transcode_receipt: Mapping[str, object],
    transcode_receipt_artifact: Mapping[str, object],
    metadata_receipt: Mapping[str, object],
    metadata_receipt_artifact: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Return three new v2 entries after validating the complete receipt graph.

    The returned value is detached from caller-owned mappings and is never
    written to disk by this function.
    """

    extraction, extraction_artifact, sources, avi_outputs, extraction_tools = (
        _validate_extraction_receipt(
            extraction_receipt, extraction_receipt_artifact
        )
    )
    _, transcode_artifact, transcode_outputs = _validate_transcode_receipt(
        transcode_receipt,
        transcode_receipt_artifact,
        extraction_receipt=extraction,
        extraction_artifact=extraction_artifact,
        extraction_outputs=avi_outputs,
        extraction_tools=extraction_tools,
    )
    _, metadata_artifact = _validate_metadata_receipt(
        metadata_receipt,
        metadata_receipt_artifact,
        extraction_sources=sources,
        extraction_outputs=avi_outputs,
    )
    if len(
        {
            extraction_artifact["path"],
            transcode_artifact["path"],
            metadata_artifact["path"],
        }
    ) != 3:
        raise KppDatasetContractError("receipt artifact paths must be distinct")

    all_outputs: dict[tuple[str, str], Mapping[str, object]] = {
        ("avi", role): descriptor for role, descriptor in avi_outputs.items()
    }
    all_outputs.update(transcode_outputs)
    annotations = {
        "path": METADATA_DESTINATION,
        "sha256": metadata_artifact["sha256"],
        "use": "underbody_foreign_object_events_and_realism_metadata_only",
        "accuracy_ground_truth": False,
        "normalization_receipt_sha256": metadata_artifact["receipt_sha256"],
    }

    entries: dict[str, dict[str, object]] = {}
    for variant, dataset_name in DATASET_NAMES.items():
        output_descriptors = [
            {
                "role": role,
                "path": _final_media_path(variant, role),
                "size_bytes": all_outputs[(variant, role)]["size_bytes"],
                "sha256": all_outputs[(variant, role)]["sha256"],
                "receipt_path": (
                    extraction_artifact["path"]
                    if variant == "avi"
                    else transcode_artifact["path"]
                ),
                "receipt_sha256": (
                    extraction_artifact["receipt_sha256"]
                    if variant == "avi"
                    else transcode_artifact["receipt_sha256"]
                ),
            }
            for role in ("underbody", "front_gate")
        ]
        provenance: dict[str, object] = {
            "schema_version": PROVENANCE_CONTRACT_VERSION,
            "generation_id": GENERATION_ID,
            "physical_artifact_bytes_assessed": False,
            "publication_authorized": False,
            "extraction_receipt": _receipt_provenance(extraction_artifact),
            "metadata_receipt": _receipt_provenance(metadata_artifact),
            "media_artifacts": output_descriptors,
        }
        if variant != "avi":
            provenance["transcode_receipt"] = _receipt_provenance(
                transcode_artifact
            )

        entry: dict[str, object] = {
            "dataset_contract_version": DATASET_CONTRACT_VERSION,
            "generation_id": GENERATION_ID,
            "status": "physically_unassessed_candidate",
            "kind": "real_avi" if variant == "avi" else "real_codec_transcode",
            "description": (
                "Legacy ISS checkpoint captures extracted headlessly as a "
                "distinct v2 generation."
                if variant == "avi"
                else (
                    f"Legacy ISS v2 checkpoint captures frozen as {variant.upper()} "
                    "at 600 FPS CFR."
                )
            ),
            "publishable": False,
            "workload_scope": (
                "replicated_logical_streams_from_two_recordings"
            ),
            "logical_stream_instances": 6,
            "unique_recorded_sources": 2,
            "analytics_routing": "unresolved",
            "experimental_routing_profiles": [
                {
                    "name": "architecture_reuse_all_branches_v1",
                    "routing_mode": "all_branches_per_stream",
                    "scope": "topology_only_stress",
                    "production_semantics": False,
                }
            ],
            "fps_policy": (
                "receipt_validated_mixed_source_timeline"
                if variant == "avi"
                else "cfr_600_from_source_pts"
            ),
            "annotations": copy.deepcopy(annotations),
            "timestamp_contract": _timestamp_contract(variant),
            "provenance": provenance,
            "lineage": _lineage(variant),
            "streams": _build_streams(variant, outputs=all_outputs),
        }
        if variant != "avi":
            entry["source_dataset"] = DATASET_NAMES["avi"]
            entry["codec_variant"] = variant
            entry["benchmark_playback"] = {
                "contract_version": 1,
                "encoded_timeline_fps": 600,
                "offered_playback_fps": 1,
                "timestamp_scale": 600,
                "selection_basis": (
                    "discarded_prebenchmark_capacity_pilots_positive_completed_"
                    "frames_guardrail_no_effect_estimation"
                ),
            }
            entry["transcode"] = {
                "source_paths": [
                    _final_media_path("avi", "underbody"),
                    _final_media_path("avi", "front_gate"),
                ],
                "recipes": [
                    _expected_transcode_recipe(role, variant)
                    for role in ("underbody", "front_gate")
                ],
            }
        entries[dataset_name] = entry
    return entries


__all__ = [
    "DATASET_CONTRACT_VERSION",
    "DATASET_NAMES",
    "GENERATION_ID",
    "KppDatasetContractError",
    "PREDECESSOR_MANIFEST_IDENTITIES",
    "build_dataset_entries",
]
