#!/usr/bin/env python3
"""Freeze four reproducible KPP legacy ISS v2 codec candidates.

The helper consumes only an authoritative extraction receipt and the two AVI
files bound by that receipt.  It publishes a new staging directory; it never
updates the dataset configuration or grants publication authority.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Callable, NamedTuple, Sequence

from extract_kpp_legacy_iss import (
    ExtractionError as _ExtractionSecurityError,
    _WindowsDirectoryCustody,
    _create_private_working_directory,
    _create_windows_private_working_directory_with_custody,
    _open_windows_directory_custody,
    _validate_private_publication_set,
    _validate_windows_direct_child_custody,
    _windows_private_directory_acl_is_exact,
    _windows_publish_directory_by_handle,
)


GENERATION_ID = "kpp_legacy_iss_v2"
EXTRACTION_RECEIPT_NAME = "kpp_iss_v2_extraction_receipt.json"
TRANSCODE_RECEIPT_NAME = "kpp_iss_v2_transcode_receipt.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
OUTPUT_FPS = 600

SOURCE_CONTRACT = {
    "underbody": {
        "output_name": "iss_v2_underbody.mp4",
        "source_name": "iss_v2_underbody.avi",
        "codec_name": "mjpeg",
        "width": 1700,
        "height": 236,
        "r_frame_rate": "200/1",
        "avg_frame_rate": "200/1",
        "frame_count": 11882,
        "duration_ns": 59_410_000_000,
    },
    "front_gate": {
        "output_name": "iss_v2_front_gate.mp4",
        "source_name": "iss_v2_front_gate.avi",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "r_frame_rate": "25/1",
        "avg_frame_rate": "25/1",
        "frame_count": 1380,
        "duration_ns": 55_200_000_000,
    },
}

TRANSCODE_RECIPES = {
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

BITSTREAM_FILTER_CONTRACT = {
    "h264": "h264_metadata=video_full_range_flag=0",
    "h265": "hevc_metadata=video_full_range_flag=0",
}


class TranscodeFreezeError(RuntimeError):
    """Raised when the transcode candidate cannot be frozen safely."""


Runner = Callable[[tuple[str, ...]], None]
Prober = Callable[[Path], dict[str, object]]
VersionReader = Callable[[Path], bytes]


class _TestAdapters(NamedTuple):
    runner: Runner
    prober: Prober
    version_reader: VersionReader


def _require_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise TranscodeFreezeError(f"{label} must be an exact lowercase SHA-256")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise TranscodeFreezeError(f"{label} must be a positive integer")
    return value


def _is_reparse_or_symlink(path: Path) -> bool:
    observed = path.lstat()
    if stat.S_ISLNK(observed.st_mode):
        return True
    attributes = getattr(observed, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _require_regular_file(path: Path, *, label: str) -> os.stat_result:
    if not path.is_absolute():
        raise TranscodeFreezeError(f"{label} must be absolute")
    try:
        if _is_reparse_or_symlink(path):
            raise TranscodeFreezeError(
                f"{label} must not be a symlink or reparse point"
            )
        observed = path.stat()
    except FileNotFoundError as exc:
        raise TranscodeFreezeError(f"{label} does not exist") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise TranscodeFreezeError(f"{label} must be a regular file")
    if observed.st_size <= 0:
        raise TranscodeFreezeError(f"{label} must be non-empty")
    return observed


def _file_identity(observed: os.stat_result) -> tuple[int, int]:
    return int(observed.st_dev), int(observed.st_ino)


def _require_unchanged(
    before: os.stat_result,
    handle_state: os.stat_result,
    after: os.stat_result,
    *,
    label: str,
) -> None:
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(handle_state, field) for field in fields):
        raise TranscodeFreezeError(f"{label} changed while it was read")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise TranscodeFreezeError(f"{label} changed after it was read")


def _stable_sha256(path: Path, *, label: str) -> tuple[str, os.stat_result]:
    before = _require_regular_file(path, label=label)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
        handle_state = os.fstat(source.fileno())
    after = path.stat()
    _require_unchanged(before, handle_state, after, label=label)
    return digest.hexdigest(), after


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _extraction_receipt_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        b"VAST:kpp-legacy-iss-extraction-receipt:v1\0"
        + _canonical_bytes(value)
    ).hexdigest()


def _transcode_receipt_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        b"VAST:kpp-legacy-iss-v2-transcode-receipt:v1\0"
        + _canonical_bytes(value)
    ).hexdigest()


def _strict_json(payload: bytes, *, label: str) -> dict[str, object]:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TranscodeFreezeError(f"{label} must be canonical ASCII JSON") from exc

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise TranscodeFreezeError(
                    f"{label} contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise TranscodeFreezeError(f"{label} contains invalid constant {value}")

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except TranscodeFreezeError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise TranscodeFreezeError(f"{label} is invalid JSON") from exc
    if type(value) is not dict:
        raise TranscodeFreezeError(f"{label} must contain one JSON object")
    if _canonical_bytes(value) != payload:
        raise TranscodeFreezeError(f"{label} is not canonical JSON")
    return value


def _read_stable_receipt(
    path: Path,
) -> tuple[bytes, str, os.stat_result]:
    before = _require_regular_file(path, label="extraction receipt")
    if before.st_size > MAX_RECEIPT_BYTES:
        raise TranscodeFreezeError("extraction receipt exceeds its size bound")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        payload = stream.read(MAX_RECEIPT_BYTES + 1)
        digest.update(payload)
        handle_state = os.fstat(stream.fileno())
    after = path.stat()
    _require_unchanged(before, handle_state, after, label="extraction receipt")
    if len(payload) != before.st_size:
        raise TranscodeFreezeError("extraction receipt changed while it was read")
    return payload, digest.hexdigest(), after


def _validated_project_root(value: Path) -> Path:
    root = value.absolute()
    if not root.is_dir() or _is_reparse_or_symlink(root):
        raise TranscodeFreezeError("project_root must be a plain existing directory")
    return root


def _validated_output_dir(project_root: Path, value: Path) -> Path:
    candidate = value.absolute()
    try:
        relative = candidate.relative_to(project_root)
    except ValueError as exc:
        raise TranscodeFreezeError(
            "output_dir must stay inside project_root/staging"
        ) from exc
    if len(relative.parts) != 2:
        raise TranscodeFreezeError(
            "output_dir must be a direct child directory of staging"
        )
    first = relative.parts[0]
    matches = first.casefold() == "staging" if os.name == "nt" else first == "staging"
    if not matches:
        raise TranscodeFreezeError(
            "output_dir must stay inside project_root/staging"
        )
    current = project_root
    for component in relative.parts:
        current = current / component
        if current.exists() and _is_reparse_or_symlink(current):
            raise TranscodeFreezeError(
                "output_dir path must not contain links or reparse points"
            )
    return candidate


def _validated_receipt_path(project_root: Path, value: Path) -> Path:
    path = value.absolute()
    if path.name != EXTRACTION_RECEIPT_NAME:
        raise TranscodeFreezeError(
            f"extraction receipt must be named {EXTRACTION_RECEIPT_NAME}"
        )
    try:
        relative = path.relative_to(project_root)
    except ValueError as exc:
        raise TranscodeFreezeError(
            "extraction receipt must stay inside project_root/staging"
        ) from exc
    if len(relative.parts) < 3:
        raise TranscodeFreezeError(
            "extraction receipt must be inside a child directory of staging"
        )
    first = relative.parts[0]
    matches = first.casefold() == "staging" if os.name == "nt" else first == "staging"
    if not matches:
        raise TranscodeFreezeError(
            "extraction receipt must stay inside project_root/staging"
        )
    current = project_root
    for component in relative.parts:
        current = current / component
        if current.exists() and _is_reparse_or_symlink(current):
            raise TranscodeFreezeError(
                "extraction receipt path must not contain links or reparse points"
            )
    _require_regular_file(path, label="extraction receipt")
    return path


def _path_from_receipt(project_root: Path, value: object, *, label: str) -> Path:
    if type(value) is not str or not value:
        raise TranscodeFreezeError(f"{label} must be a non-empty POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(
        component in ("", ".", "..") for component in pure.parts
    ):
        raise TranscodeFreezeError(f"{label} must be a canonical relative POSIX path")
    if "\\" in value or pure.as_posix() != value:
        raise TranscodeFreezeError(f"{label} must be a canonical relative POSIX path")
    candidate = project_root.joinpath(*pure.parts).absolute()
    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise TranscodeFreezeError(f"{label} escapes project_root") from exc
    return candidate


def _same_path(left: Path, right: Path) -> bool:
    left_text = os.path.normcase(os.path.abspath(str(left)))
    right_text = os.path.normcase(os.path.abspath(str(right)))
    return left_text == right_text


def _validate_source_media(role: str, value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise TranscodeFreezeError(f"{role} extraction media must be an object")
    contract = SOURCE_CONTRACT[role]
    expected = {
        "codec_name": contract["codec_name"],
        "width": contract["width"],
        "height": contract["height"],
        "r_frame_rate": contract["r_frame_rate"],
        "avg_frame_rate": contract["avg_frame_rate"],
        "frame_count": contract["frame_count"],
        "duration_ns": contract["duration_ns"],
    }
    if set(value) != set(expected):
        raise TranscodeFreezeError(f"{role} extraction media schema mismatch")
    for key, expected_value in expected.items():
        observed = value.get(key)
        if type(expected_value) is int and type(observed) is not int:
            raise TranscodeFreezeError(f"{role} extraction media {key} type mismatch")
        if observed != expected_value:
            raise TranscodeFreezeError(
                f"{role} extraction media {key} mismatch: "
                f"expected {expected_value!r}, got {observed!r}"
            )
    return dict(expected)


def _validate_extraction_provenance(value: dict[str, object]) -> None:
    source_archives = value["source_archives"]
    recipes = value["recipes"]
    tools = value["tools"]
    source_expectations = {
        "underbody": {"logical_id": "13._03", "demuxer": "mjpeg", "fps": 200},
        "front_gate": {
            "logical_id": "13._03_2",
            "demuxer": "h264",
            "fps": 25,
        },
    }
    for index, role in enumerate(("underbody", "front_gate")):
        source = source_archives[index]
        recipe = recipes[index]
        if type(source) is not dict or set(source) != {
            "archive_logical_id",
            "size_bytes",
            "sha256",
            "role",
            "payload_offset",
        }:
            raise TranscodeFreezeError(
                f"{role} extraction source archive schema mismatch"
            )
        if source.get("role") != role:
            raise TranscodeFreezeError("extraction source role order mismatch")
        if source.get("archive_logical_id") != source_expectations[role]["logical_id"]:
            raise TranscodeFreezeError(f"{role} extraction source logical ID mismatch")
        _require_positive_int(
            source.get("size_bytes"), label=f"{role} extraction source size_bytes"
        )
        _require_sha256(
            source.get("sha256"), label=f"{role} extraction source SHA-256"
        )
        payload_offset = _require_positive_int(
            source.get("payload_offset"),
            label=f"{role} extraction payload_offset",
        )
        if type(recipe) is not dict or set(recipe) != {
            "role",
            "demuxer",
            "source_fps",
            "payload_offset",
            "codec_mode",
            "container",
        }:
            raise TranscodeFreezeError(f"{role} extraction recipe schema mismatch")
        expected_recipe = {
            "role": role,
            "demuxer": source_expectations[role]["demuxer"],
            "source_fps": source_expectations[role]["fps"],
            "payload_offset": payload_offset,
            "codec_mode": "stream_copy",
            "container": "avi",
        }
        if recipe != expected_recipe:
            raise TranscodeFreezeError(f"{role} extraction recipe mismatch")

    for index, role in enumerate(("ffmpeg", "ffprobe")):
        tool = tools[index]
        if type(tool) is not dict or set(tool) != {
            "role",
            "executable_sha256",
            "version_output_sha256",
        }:
            raise TranscodeFreezeError(f"extraction {role} descriptor schema mismatch")
        if tool.get("role") != role:
            raise TranscodeFreezeError("extraction tool role order mismatch")
        _require_sha256(
            tool.get("executable_sha256"),
            label=f"extraction {role} executable SHA-256",
        )
        _require_sha256(
            tool.get("version_output_sha256"),
            label=f"extraction {role} version output SHA-256",
        )


def _validate_extraction_receipt(
    *,
    project_root: Path,
    receipt_path: Path,
    expected_extraction_receipt_file_sha256: str,
    underbody_avi: Path,
    front_avi: Path,
) -> tuple[
    dict[str, object],
    bytes,
    dict[str, dict[str, object]],
    str,
    os.stat_result,
]:
    expected_file_sha256 = _require_sha256(
        expected_extraction_receipt_file_sha256,
        label="extraction receipt file SHA-256",
    )
    encoded, file_sha256, receipt_state = _read_stable_receipt(receipt_path)
    if file_sha256 != expected_file_sha256:
        raise TranscodeFreezeError(
            "extraction receipt file SHA-256 does not match its external pin"
        )
    value = _strict_json(encoded, label="extraction receipt")
    expected_keys = {
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
    }
    if set(value) != expected_keys:
        raise TranscodeFreezeError("extraction receipt top-level schema mismatch")
    if value.get("schema_version") != 1:
        raise TranscodeFreezeError("extraction receipt schema_version mismatch")
    if value.get("artifact_kind") != "vast_kpp_legacy_iss_extraction_receipt":
        raise TranscodeFreezeError("extraction receipt artifact_kind mismatch")
    if value.get("generation_id") != GENERATION_ID:
        raise TranscodeFreezeError("extraction receipt generation_id mismatch")
    if value.get("status") != "headless_stream_copy_candidate":
        raise TranscodeFreezeError("extraction receipt is not authoritative")
    if not all(
        type(value.get(key)) is list and len(value[key]) == 2
        for key in ("source_archives", "tools", "recipes", "outputs")
    ):
        raise TranscodeFreezeError("extraction receipt collection cardinality mismatch")
    claims = value.get("claims")
    if type(claims) is not dict:
        raise TranscodeFreezeError("extraction receipt claims must be an object")
    authoritative_true_claims = (
        "source_bytes_externally_pinned",
        "source_private_snapshots_verified",
        "tool_bytes_and_version_outputs_externally_pinned",
        "payload_offsets_detected",
        "video_payloads_stream_copied",
        "output_set_directory_published_atomically",
    )
    if any(claims.get(name) is not True for name in authoritative_true_claims):
        raise TranscodeFreezeError("extraction receipt is not authoritative")
    expected_claims = {
        "source_bytes_externally_pinned": True,
        "source_private_snapshots_verified": True,
        "tool_bytes_and_version_outputs_externally_pinned": True,
        "payload_offsets_detected": True,
        "video_payloads_stream_copied": True,
        "output_set_directory_published_atomically": True,
        "windows_project_root_staging_and_working_directory_handle_custody_validated": True,
        "source_timestamps_preserved": False,
        "archiveplayer_export_reproduced": False,
        "v1_dataset_identity_equivalent": False,
        "accuracy_ground_truth_validated": False,
        "publication_authorized": False,
    }
    if claims != expected_claims:
        raise TranscodeFreezeError("extraction receipt claims schema mismatch")
    _validate_extraction_provenance(value)
    claimed_hash = _require_sha256(
        value.get("extraction_receipt_sha256"),
        label="extraction receipt self hash",
    )
    unsigned = dict(value)
    unsigned.pop("extraction_receipt_sha256")
    if _extraction_receipt_sha256(unsigned) != claimed_hash:
        raise TranscodeFreezeError("extraction receipt self hash mismatch")

    supplied = {
        "underbody": underbody_avi.absolute(),
        "front_gate": front_avi.absolute(),
    }
    descriptors: dict[str, dict[str, object]] = {}
    outputs = value["outputs"]
    for index, role in enumerate(("underbody", "front_gate")):
        item = outputs[index]
        if type(item) is not dict:
            raise TranscodeFreezeError(f"{role} extraction output must be an object")
        if set(item) != {"role", "path", "size_bytes", "sha256", "media"}:
            raise TranscodeFreezeError(f"{role} extraction output schema mismatch")
        if item.get("role") != role:
            raise TranscodeFreezeError("extraction output role order mismatch")
        expected_path = _path_from_receipt(
            project_root,
            item.get("path"),
            label=f"{role} extraction output path",
        )
        if not _same_path(expected_path, supplied[role]):
            raise TranscodeFreezeError(
                f"{role} AVI path does not match the extraction receipt"
            )
        if expected_path.parent != receipt_path.parent:
            raise TranscodeFreezeError(
                f"{role} AVI and extraction receipt must share one directory"
            )
        if expected_path.name != SOURCE_CONTRACT[role]["source_name"]:
            raise TranscodeFreezeError(f"{role} AVI logical name mismatch")
        size_bytes = _require_positive_int(
            item.get("size_bytes"), label=f"{role} AVI size_bytes"
        )
        sha256 = _require_sha256(
            item.get("sha256"), label=f"{role} AVI SHA-256"
        )
        media = _validate_source_media(role, item.get("media"))
        descriptors[role] = {
            "role": role,
            "artifact_logical_id": expected_path.name,
            "path": str(item["path"]),
            "size_bytes": size_bytes,
            "sha256": sha256,
            "media": media,
        }
    identities = {
        _file_identity(_require_regular_file(supplied[role], label=f"{role} AVI"))
        for role in ("underbody", "front_gate")
    }
    if len(identities) != 2:
        raise TranscodeFreezeError("underbody and front AVIs must be physically distinct")
    return value, encoded, descriptors, file_sha256, receipt_state


def _ffmpeg_filter_for_role(role: str) -> str:
    if role not in SOURCE_CONTRACT:
        raise TranscodeFreezeError(f"unknown source role: {role}")
    source_contract = SOURCE_CONTRACT[role]
    return (
        f"scale=w={source_contract['width']}:h={source_contract['height']}:"
        "in_range=auto:out_range=tv,format=pix_fmts=yuv420p,"
        "fps=fps=600:start_time=0:round=near:eof_action=round"
    )


def _require_bitstream_filter_contract(
    codec_variant: str, recipe: dict[str, object]
) -> str:
    expected = BITSTREAM_FILTER_CONTRACT.get(codec_variant)
    observed = recipe.get("bitstream_filter")
    if expected is None or observed != expected:
        raise TranscodeFreezeError(
            f"{codec_variant} bitstream filter contract mismatch"
        )
    return expected


def _transcode_recipe_descriptor(
    codec_variant: str, role: str
) -> dict[str, object]:
    recipe = TRANSCODE_RECIPES.get(codec_variant)
    if recipe is None:
        raise TranscodeFreezeError(f"unknown codec variant: {codec_variant}")
    return {
        "codec_variant": codec_variant,
        "role": role,
        "ffmpeg_filter": _ffmpeg_filter_for_role(role),
        "reinit_filter": 0,
        "encoder": recipe["encoder"],
        "preset": recipe["preset"],
        "crf": recipe["crf"],
        "pix_fmt": recipe["pix_fmt"],
        "color_range": "tv",
        "output_frame_rate": f"{OUTPUT_FPS}/1",
        "fps_mode": "cfr",
        "encoder_time_base": f"1/{OUTPUT_FPS}",
        "expected_frame_count": _expected_derived_frame_count(role),
        "video_track_timescale": OUTPUT_FPS,
        "bitstream_filter": _require_bitstream_filter_contract(
            codec_variant, recipe
        ),
        "container": "mp4",
    }


def build_ffmpeg_command(
    *,
    source: Path,
    target: Path,
    codec_variant: str,
    role: str,
    ffmpeg: str,
) -> tuple[str, ...]:
    descriptor = _transcode_recipe_descriptor(codec_variant, role)
    return (
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-reinit_filter:v",
        "0",
        "-i",
        str(source),
        "-vf",
        str(descriptor["ffmpeg_filter"]),
        "-an",
        "-c:v",
        str(descriptor["encoder"]),
        "-preset",
        str(descriptor["preset"]),
        "-crf",
        str(descriptor["crf"]),
        "-pix_fmt",
        str(descriptor["pix_fmt"]),
        "-color_range",
        "tv",
        "-r",
        str(OUTPUT_FPS),
        "-fps_mode",
        "cfr",
        "-enc_time_base:v",
        f"1:{OUTPUT_FPS}",
        "-frames:v",
        str(descriptor["expected_frame_count"]),
        "-video_track_timescale",
        str(OUTPUT_FPS),
        "-bsf:v",
        str(descriptor["bitstream_filter"]),
        str(target),
    )


def _run(command: tuple[str, ...]) -> None:
    completed = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise TranscodeFreezeError(
            f"ffmpeg transcode failed with exit code {completed.returncode}: "
            + diagnostic
        )


def _probe(path: Path, *, ffprobe: Path) -> dict[str, object]:
    command = (
        str(ffprobe),
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v",
        "-show_frames",
        "-show_entries",
        (
            "stream=codec_name,pix_fmt,width,height,r_frame_rate,"
            "avg_frame_rate,nb_frames,nb_read_frames,duration,time_base,"
            "duration_ts:frame=pts,width,height,pix_fmt,color_range"
        ),
        "-of",
        "json",
        str(path),
    )
    completed = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise TranscodeFreezeError("ffprobe validation failed: " + diagnostic)
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
        streams = value["streams"]
        if type(streams) is not list or len(streams) != 1:
            raise ValueError("expected exactly one video stream")
        stream = streams[0]
        if type(stream) is not dict:
            raise ValueError("stream must be an object")
        frame_count = int(stream["nb_read_frames"])
        frames = value["frames"]
        if type(frames) is not list or len(frames) != frame_count:
            raise ValueError("decoded frames do not match nb_read_frames")
        frame_signatures: set[tuple[int, int, str, str]] = set()
        frame_pts: list[int] = []
        complete_frame_pts = True
        for frame in frames:
            if type(frame) is not dict:
                raise ValueError("decoded frame must be an object")
            raw_color_range = frame.get("color_range")
            color_range = (
                raw_color_range
                if type(raw_color_range) is str and raw_color_range
                else "unknown"
            )
            frame_signatures.add(
                (
                    int(frame["width"]),
                    int(frame["height"]),
                    str(frame["pix_fmt"]),
                    color_range,
                )
            )
            raw_pts = frame.get("pts")
            if raw_pts is None:
                complete_frame_pts = False
            else:
                frame_pts.append(int(raw_pts))
        if not complete_frame_pts:
            frame_pts = []
        duration = Decimal(str(stream["duration"]))
        duration_ns_decimal = duration * Decimal(1_000_000_000)
        if duration_ns_decimal != duration_ns_decimal.to_integral_value():
            raise ValueError("duration is not exact to one nanosecond")
        duration_ns = int(duration_ns_decimal)
        result = {
            "codec_name": str(stream["codec_name"]),
            "pix_fmt": str(stream["pix_fmt"]),
            "width": int(stream["width"]),
            "height": int(stream["height"]),
            "r_frame_rate": str(stream["r_frame_rate"]),
            "avg_frame_rate": str(stream["avg_frame_rate"]),
            "frame_count": frame_count,
            "duration_ns": duration_ns,
            "decoded_frame_count": len(frames),
            "decoded_frame_signatures": [
                {
                    "width": width,
                    "height": height,
                    "pix_fmt": pix_fmt,
                    "color_range": color_range,
                }
                for width, height, pix_fmt, color_range in sorted(
                    frame_signatures
                )
            ],
            "stream_time_base": str(stream.get("time_base", "")),
            "stream_duration_ts": (
                int(stream["duration_ts"])
                if stream.get("duration_ts") is not None
                else None
            ),
            "decoded_first_pts": frame_pts[0] if frame_pts else None,
            "decoded_last_pts": frame_pts[-1] if frame_pts else None,
            "decoded_pts_steps": (
                sorted(
                    {
                        current - previous
                        for previous, current in zip(frame_pts, frame_pts[1:])
                    }
                )
                if frame_pts
                else None
            ),
        }
    except (
        KeyError,
        TypeError,
        ValueError,
        InvalidOperation,
        json.JSONDecodeError,
    ) as exc:
        raise TranscodeFreezeError(
            "ffprobe returned an invalid stream description"
        ) from exc
    if frame_count <= 0 or duration_ns <= 0:
        raise TranscodeFreezeError(
            "ffprobe returned non-positive duration or frame count"
        )
    return result


def _validate_source_probe(
    role: str, value: dict[str, object]
) -> dict[str, object]:
    contract = SOURCE_CONTRACT[role]
    for key in (
        "codec_name",
        "width",
        "height",
        "r_frame_rate",
        "avg_frame_rate",
        "frame_count",
        "duration_ns",
    ):
        expected = contract[key]
        observed = value.get(key)
        if type(expected) is int and type(observed) is not int:
            raise TranscodeFreezeError(f"{role} source {key} type mismatch")
        if observed != expected:
            raise TranscodeFreezeError(
                f"{role} source {key} mismatch: expected {expected!r}, "
                f"got {observed!r}"
            )
    pix_fmt = value.get("pix_fmt")
    if type(pix_fmt) is not str or not pix_fmt:
        raise TranscodeFreezeError(f"{role} source pix_fmt is missing")
    return {
        "codec_name": str(value["codec_name"]),
        "pix_fmt": pix_fmt,
        "width": int(value["width"]),
        "height": int(value["height"]),
        "r_frame_rate": str(value["r_frame_rate"]),
        "avg_frame_rate": str(value["avg_frame_rate"]),
        "frame_count": int(value["frame_count"]),
        "duration_ns": int(value["duration_ns"]),
    }


def _expected_derived_frame_count(role: str) -> int:
    duration_ns = int(SOURCE_CONTRACT[role]["duration_ns"])
    numerator = duration_ns * OUTPUT_FPS
    quotient, remainder = divmod(numerator, 1_000_000_000)
    if remainder:
        raise TranscodeFreezeError(
            f"{role} source duration cannot map exactly to the 600/1 timeline"
        )
    return quotient


def _validate_output_probe(
    role: str,
    codec_variant: str,
    value: dict[str, object],
) -> dict[str, object]:
    source = SOURCE_CONTRACT[role]
    recipe = TRANSCODE_RECIPES[codec_variant]
    expected = {
        "codec_name": recipe["codec_name"],
        "pix_fmt": recipe["pix_fmt"],
        "width": source["width"],
        "height": source["height"],
        "r_frame_rate": "600/1",
        "avg_frame_rate": "600/1",
        "frame_count": _expected_derived_frame_count(role),
        "duration_ns": source["duration_ns"],
    }
    for key, expected_value in expected.items():
        observed = value.get(key)
        if type(expected_value) is int and type(observed) is not int:
            raise TranscodeFreezeError(
                f"{codec_variant}/{role} output {key} type mismatch"
            )
        if observed != expected_value:
            raise TranscodeFreezeError(
                f"{codec_variant}/{role} output {key} mismatch: "
                f"expected {expected_value!r}, got {observed!r}"
            )
    expected_decoded_signature = [
        {
            "width": int(source["width"]),
            "height": int(source["height"]),
            "pix_fmt": str(recipe["pix_fmt"]),
            "color_range": "tv",
        }
    ]
    if (
        type(value.get("decoded_frame_count")) is not int
        or value["decoded_frame_count"] != expected["frame_count"]
        or value.get("decoded_frame_signatures") != expected_decoded_signature
    ):
        raise TranscodeFreezeError(
            f"{codec_variant}/{role} output decoded frame contract mismatch"
        )
    expected_pts_contract = {
        "stream_time_base": f"1/{OUTPUT_FPS}",
        "stream_duration_ts": expected["frame_count"],
        "decoded_first_pts": 0,
        "decoded_last_pts": int(expected["frame_count"]) - 1,
        "decoded_pts_steps": [1],
    }
    if any(
        value.get(key) != expected_value
        for key, expected_value in expected_pts_contract.items()
    ):
        raise TranscodeFreezeError(
            f"{codec_variant}/{role} output decoded frame PTS contract mismatch"
        )
    validated = dict(expected)
    validated.update(
        {
            "color_range": "tv",
            "stream_time_base": expected_pts_contract["stream_time_base"],
            "stream_duration_ts": expected_pts_contract["stream_duration_ts"],
            "decoded_frame_count": expected["frame_count"],
            "decoded_first_pts": expected_pts_contract["decoded_first_pts"],
            "decoded_last_pts": expected_pts_contract["decoded_last_pts"],
            "decoded_pts_steps": [1],
            "decoded_frame_signatures": expected_decoded_signature,
        }
    )
    return validated


def _read_tool_version(path: Path) -> bytes:
    completed = subprocess.run(
        [str(path), "-version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise TranscodeFreezeError(
            f"{path.name} -version failed with exit code "
            f"{completed.returncode}: {diagnostic}"
        )
    if not completed.stdout:
        raise TranscodeFreezeError(f"{path.name} -version returned no stdout bytes")
    return bytes(completed.stdout)


def _copy_pinned_snapshot(
    *,
    source: Path,
    target: Path,
    expected_sha256: str,
    label: str,
    expected_size_bytes: int | None = None,
    preserve_executable_mode: bool = False,
) -> tuple[dict[str, object], Path]:
    expected_hash = _require_sha256(expected_sha256, label=f"{label} SHA-256")
    before = _require_regular_file(source, label=label)
    if expected_size_bytes is not None:
        expected_size = _require_positive_int(
            expected_size_bytes, label=f"{label} size_bytes"
        )
        if int(before.st_size) != expected_size:
            raise TranscodeFreezeError(f"{label} size does not match its receipt")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, target.open("xb") as output_stream:
            while True:
                chunk = input_stream.read(8 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
            source_handle = os.fstat(input_stream.fileno())
        after = source.stat()
        _require_unchanged(before, source_handle, after, label=label)
        if preserve_executable_mode and os.name != "nt":
            target.chmod(stat.S_IMODE(before.st_mode))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    observed_hash = digest.hexdigest()
    if observed_hash != expected_hash:
        target.unlink(missing_ok=True)
        raise TranscodeFreezeError(f"{label} SHA-256 does not match its external pin")
    snapshot_hash, snapshot_state = _stable_sha256(
        target, label=f"{label} private snapshot"
    )
    if (
        snapshot_hash != observed_hash
        or int(snapshot_state.st_size) != int(before.st_size)
    ):
        target.unlink(missing_ok=True)
        raise TranscodeFreezeError(f"{label} private snapshot does not match its source")
    return (
        {
            "artifact_logical_id": source.name,
            "size_bytes": int(before.st_size),
            "sha256": observed_hash,
        },
        target,
    )


def _validate_tool(
    *,
    role: str,
    path: Path,
    expected_sha256: str,
    expected_version_sha256: str,
    version_reader: VersionReader,
) -> dict[str, object]:
    observed_hash, _ = _stable_sha256(path, label=f"{role} executable snapshot")
    if observed_hash != expected_sha256:
        raise TranscodeFreezeError(
            f"{role} executable SHA-256 does not match its external pin"
        )
    try:
        version_bytes = version_reader(path)
    except TranscodeFreezeError:
        raise
    except Exception as exc:
        raise TranscodeFreezeError(f"{role} version query failed") from exc
    if type(version_bytes) is not bytes or not version_bytes:
        raise TranscodeFreezeError(f"{role} version query must return non-empty bytes")
    version_hash = hashlib.sha256(version_bytes).hexdigest()
    if version_hash != expected_version_sha256:
        raise TranscodeFreezeError(
            f"{role} version output SHA-256 does not match its external pin"
        )
    return {
        "role": role,
        "executable_sha256": observed_hash,
        "version_output_sha256": version_hash,
    }


def _atomic_publish_directory(source: Path, target: Path) -> None:
    if target.exists():
        raise TranscodeFreezeError(f"output already exists: {target.name}")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
        ]
        move_file_ex.restype = ctypes.c_int
        if not move_file_ex(str(source), str(target), 0):
            code = ctypes.get_last_error()
            if code in (80, 183):
                raise TranscodeFreezeError(f"output already exists: {target.name}")
            raise TranscodeFreezeError(
                f"atomic directory publication failed with Win32 error {code}"
            )
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise TranscodeFreezeError("atomic no-replace publication is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(target),
            1,
        ) != 0:
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise TranscodeFreezeError(f"output already exists: {target.name}")
            raise TranscodeFreezeError(
                f"atomic directory publication failed with errno {code}"
            )
        return
    raise TranscodeFreezeError("atomic no-replace publication is unsupported")


def _unlink_owned(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except PermissionError:
        path.chmod(0o600)
        path.unlink(missing_ok=True)


def _cleanup_private_tree(
    *,
    working: Path,
    source_snapshots: Sequence[Path],
    tool_snapshots: Sequence[Path],
    outputs: Sequence[Path],
    receipt: Path,
) -> None:
    _unlink_owned(receipt)
    for path in outputs:
        _unlink_owned(path)
    for path in source_snapshots:
        _unlink_owned(path)
    for path in tool_snapshots:
        _unlink_owned(path)
    for directory in (
        working / ".sources",
        working / ".tools",
        working / "h264",
        working / "h265",
    ):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
    try:
        working.rmdir()
    except FileNotFoundError:
        pass


def _freeze_transcodes_impl(
    *,
    project_root: Path,
    extraction_receipt: Path,
    expected_extraction_receipt_file_sha256: str,
    underbody_avi: Path,
    front_avi: Path,
    output_dir: Path,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    test_adapters: _TestAdapters | None,
) -> dict[str, object]:
    if test_adapters is None:
        runner = _run
        prober: Prober | None = None
        version_reader = _read_tool_version
        authoritative = True
    else:
        runner = test_adapters.runner
        prober = test_adapters.prober
        version_reader = test_adapters.version_reader
        authoritative = False
    if authoritative and os.name != "nt":
        raise TranscodeFreezeError(
            "authoritative transcode freeze requires Windows"
        )
    root = _validated_project_root(project_root)
    destination = _validated_output_dir(root, output_dir)
    if destination.exists():
        raise TranscodeFreezeError(f"output already exists: {destination.name}")
    root_custody: _WindowsDirectoryCustody | None = None
    parent_custody: _WindowsDirectoryCustody | None = None
    working_custody: _WindowsDirectoryCustody | None = None
    try:
        if authoritative:
            root_custody = _open_windows_directory_custody(
                root,
                label="transcode project root",
                require_delete_access=False,
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _validated_output_dir(root, destination)
        if destination.exists():
            raise TranscodeFreezeError(
                f"output already exists: {destination.name}"
            )
        if authoritative:
            if root_custody is None:
                raise TranscodeFreezeError(
                    "transcode project root custody was not acquired"
                )
            parent_custody = _open_windows_directory_custody(
                destination.parent,
                label="transcode staging parent",
                require_delete_access=False,
            )
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=destination.parent.name,
            )
    except Exception as exc:
        if parent_custody is not None:
            parent_custody.close()
            parent_custody = None
        if root_custody is not None:
            root_custody.close()
            root_custody = None
        if isinstance(exc, _ExtractionSecurityError):
            raise TranscodeFreezeError(
                f"could not acquire transcode project/staging custody: {exc}"
            ) from exc
        raise

    try:
        receipt_path = _validated_receipt_path(root, extraction_receipt)
        source_paths = {
            "underbody": underbody_avi.absolute(),
            "front_gate": front_avi.absolute(),
        }
        (
            extraction_value,
            extraction_bytes,
            source_descriptors,
            extraction_file_sha256,
            extraction_state,
        ) = _validate_extraction_receipt(
            project_root=root,
            receipt_path=receipt_path,
            expected_extraction_receipt_file_sha256=(
                expected_extraction_receipt_file_sha256
            ),
            underbody_avi=source_paths["underbody"],
            front_avi=source_paths["front_gate"],
        )

        tool_paths = {"ffmpeg": ffmpeg.absolute(), "ffprobe": ffprobe.absolute()}
        expected_tool_hashes = {
            "ffmpeg": _require_sha256(
                expected_ffmpeg_sha256, label="ffmpeg executable SHA-256"
            ),
            "ffprobe": _require_sha256(
                expected_ffprobe_sha256, label="ffprobe executable SHA-256"
            ),
        }
        expected_tool_versions = {
            "ffmpeg": _require_sha256(
                expected_ffmpeg_version_sha256,
                label="ffmpeg version output SHA-256",
            ),
            "ffprobe": _require_sha256(
                expected_ffprobe_version_sha256,
                label="ffprobe version output SHA-256",
            ),
        }
        tool_identities = {
            role: _file_identity(
                _require_regular_file(path, label=f"{role} executable")
            )
            for role, path in tool_paths.items()
        }
        if tool_identities["ffmpeg"] == tool_identities["ffprobe"]:
            raise TranscodeFreezeError(
                "ffmpeg and ffprobe must be physically distinct executables"
            )
    except Exception:
        if parent_custody is not None:
            parent_custody.close()
            parent_custody = None
        if root_custody is not None:
            root_custody.close()
            root_custody = None
        raise

    try:
        try:
            if authoritative:
                if root_custody is None or parent_custody is None:
                    raise TranscodeFreezeError(
                        "transcode project root/staging custody was not acquired"
                    )
                working, working_custody = _create_windows_private_working_directory_with_custody(
                    parent=parent_custody,
                    prefix=f".{destination.name}.",
                    suffix=".candidate",
                    label="transcode working directory",
                )
            else:
                working = _create_private_working_directory(
                    parent=destination.parent,
                    prefix=f".{destination.name}.",
                    suffix=".candidate",
                )
        except _ExtractionSecurityError as exc:
            raise TranscodeFreezeError(
                f"could not create private transcode directory: {exc}"
            ) from exc
        if _is_reparse_or_symlink(working):
            raise TranscodeFreezeError(
                "private transcode directory must not be a reparse point"
            )
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise TranscodeFreezeError(
                    "private Windows transcode custody was not acquired"
                )
            try:
                _validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=destination.parent.name,
                )
                _validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=working.name,
                )
                if not _windows_private_directory_acl_is_exact(working):
                    raise _ExtractionSecurityError(
                        "private transcode directory ACL changed before snapshots"
                    )
            except _ExtractionSecurityError as exc:
                raise TranscodeFreezeError(
                    f"transcode working custody validation failed: {exc}"
                ) from exc
        source_snapshot_dir = working / ".sources"
        source_snapshot_dir.mkdir()
        tool_snapshot_dir = working / ".tools"
        tool_snapshot_dir.mkdir()
        output_dirs = {variant: working / variant for variant in ("h264", "h265")}
        for directory in output_dirs.values():
            directory.mkdir()
    except Exception:
        # Authoritative failures retain the protected candidate.  Adapters own
        # their path-only fixtures and may clean them before custody is closed.
        if not authoritative and "working" in locals():
            try:
                _cleanup_private_tree(
                    working=working,
                    source_snapshots=[],
                    tool_snapshots=[],
                    outputs=[],
                    receipt=working / TRANSCODE_RECEIPT_NAME,
                )
            except OSError:
                pass
        if working_custody is not None:
            working_custody.close()
            working_custody = None
        if parent_custody is not None:
            parent_custody.close()
            parent_custody = None
        if root_custody is not None:
            root_custody.close()
            root_custody = None
        raise
    source_snapshots = {
        "receipt": source_snapshot_dir / EXTRACTION_RECEIPT_NAME,
        "underbody": source_snapshot_dir / "iss_v2_underbody.avi",
        "front_gate": source_snapshot_dir / "iss_v2_front_gate.avi",
    }
    tool_snapshots = {
        role: tool_snapshot_dir / f"{role}{tool_paths[role].suffix}"
        for role in ("ffmpeg", "ffprobe")
    }
    working_outputs = {
        (variant, role): output_dirs[variant]
        / str(SOURCE_CONTRACT[role]["output_name"])
        for variant in ("h264", "h265")
        for role in ("underbody", "front_gate")
    }
    working_receipt = working / TRANSCODE_RECEIPT_NAME
    published = False
    output_descriptors: list[dict[str, object]] = []
    tool_descriptors: dict[str, dict[str, object]] = {}
    try:
        _copy_pinned_snapshot(
            source=receipt_path,
            target=source_snapshots["receipt"],
            expected_sha256=extraction_file_sha256,
            expected_size_bytes=int(extraction_state.st_size),
            label="extraction receipt",
        )
        if source_snapshots["receipt"].read_bytes() != extraction_bytes:
            raise TranscodeFreezeError(
                "extraction receipt private snapshot changed after validation"
            )
        if _strict_json(
            extraction_bytes, label="extraction receipt private snapshot"
        ) != extraction_value:
            raise TranscodeFreezeError("extraction receipt private snapshot mismatch")

        for role in ("underbody", "front_gate"):
            descriptor = source_descriptors[role]
            _copy_pinned_snapshot(
                source=source_paths[role],
                target=source_snapshots[role],
                expected_sha256=str(descriptor["sha256"]),
                expected_size_bytes=int(descriptor["size_bytes"]),
                label=f"{role} AVI",
            )

        for role in ("ffmpeg", "ffprobe"):
            _copy_pinned_snapshot(
                source=tool_paths[role],
                target=tool_snapshots[role],
                expected_sha256=expected_tool_hashes[role],
                label=f"{role} executable",
                preserve_executable_mode=True,
            )
            tool_descriptors[role] = _validate_tool(
                role=role,
                path=tool_snapshots[role],
                expected_sha256=expected_tool_hashes[role],
                expected_version_sha256=expected_tool_versions[role],
                version_reader=version_reader,
            )

        active_prober: Prober
        if prober is None:
            active_prober = lambda path: _probe(
                path, ffprobe=tool_snapshots["ffprobe"]
            )
        else:
            active_prober = prober

        for role in ("underbody", "front_gate"):
            source_media = _validate_source_probe(
                role, active_prober(source_snapshots[role])
            )
            if {
                key: source_media[key]
                for key in source_descriptors[role]["media"]
            } != source_descriptors[role]["media"]:
                raise TranscodeFreezeError(
                    f"{role} source probe does not match the extraction receipt"
                )

        for variant in ("h264", "h265"):
            for role in ("underbody", "front_gate"):
                target = working_outputs[(variant, role)]
                command = build_ffmpeg_command(
                    source=source_snapshots[role],
                    target=target,
                    codec_variant=variant,
                    role=role,
                    ffmpeg=str(tool_snapshots["ffmpeg"]),
                )
                runner(command)
                before_hash, before_state = _stable_sha256(
                    target, label=f"{variant}/{role} transcode candidate"
                )
                media = _validate_output_probe(
                    role, variant, active_prober(target)
                )
                after_hash, after_state = _stable_sha256(
                    target,
                    label=f"{variant}/{role} transcode candidate after probe",
                )
                if (
                    after_hash != before_hash
                    or int(after_state.st_size) != int(before_state.st_size)
                ):
                    raise TranscodeFreezeError(
                        f"{variant}/{role} transcode changed during validation"
                    )
                final_path = (
                    destination / variant / str(SOURCE_CONTRACT[role]["output_name"])
                ).relative_to(root).as_posix()
                output_descriptors.append(
                    {
                        "codec_variant": variant,
                        "role": role,
                        "path": final_path,
                        "size_bytes": int(after_state.st_size),
                        "sha256": after_hash,
                        "media": media,
                    }
                )

        for role, snapshot in source_snapshots.items():
            expected_hash = (
                extraction_file_sha256
                if role == "receipt"
                else str(source_descriptors[role]["sha256"])
            )
            observed_hash, _ = _stable_sha256(
                snapshot, label=f"{role} private source snapshot post-transcode"
            )
            if observed_hash != expected_hash:
                raise TranscodeFreezeError(
                    f"{role} private source snapshot changed during transcode"
                )
        for role, snapshot in tool_snapshots.items():
            observed_hash, _ = _stable_sha256(
                snapshot, label=f"{role} private tool snapshot post-transcode"
            )
            if observed_hash != expected_tool_hashes[role]:
                raise TranscodeFreezeError(
                    f"{role} private executable snapshot changed during transcode"
                )

        receipt: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_v2_transcode_receipt",
            "generation_id": GENERATION_ID,
            "status": (
                "pinned_codec_transcode_candidate"
                if authoritative
                else "test_adapter_candidate"
            ),
            "source_extraction": {
                "artifact_logical_id": receipt_path.name,
                "path": receipt_path.relative_to(root).as_posix(),
                "size_bytes": int(extraction_state.st_size),
                "file_sha256": extraction_file_sha256,
                "extraction_receipt_sha256": extraction_value[
                    "extraction_receipt_sha256"
                ],
                "status": extraction_value["status"],
            },
            "sources": [
                source_descriptors["underbody"],
                source_descriptors["front_gate"],
            ],
            "tools": [tool_descriptors["ffmpeg"], tool_descriptors["ffprobe"]],
            "recipes": [
                _transcode_recipe_descriptor(variant, role)
                for variant in ("h264", "h265")
                for role in ("underbody", "front_gate")
            ],
            "outputs": output_descriptors,
            "claims": {
                "authoritative_extraction_receipt_consumed": True,
                "source_avi_bytes_verified_against_extraction_receipt": True,
                "source_avi_private_snapshots_verified": True,
                "tool_bytes_and_version_outputs_externally_pinned": authoritative,
                "transcodes_executed_by_pinned_ffmpeg": authoritative,
                "outputs_validated_by_pinned_ffprobe": authoritative,
                "output_bytes_post_hashed": True,
                "output_set_directory_published_atomically": authoritative,
                "windows_project_root_staging_and_working_directory_handle_custody_validated": (
                    authoritative
                ),
                "source_timestamps_preserved": False,
                "accuracy_ground_truth_validated": False,
                "v1_dataset_identity_equivalent": False,
                "publication_authorized": False,
            },
        }
        receipt["transcode_receipt_sha256"] = _transcode_receipt_sha256(receipt)
        encoded = _canonical_bytes(receipt)
        with working_receipt.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

        for snapshot in source_snapshots.values():
            _unlink_owned(snapshot)
        source_snapshot_dir.rmdir()
        for snapshot in tool_snapshots.values():
            _unlink_owned(snapshot)
        tool_snapshot_dir.rmdir()

        expected_root_names = {"h264", "h265", TRANSCODE_RECEIPT_NAME}
        if {entry.name for entry in working.iterdir()} != expected_root_names:
            raise TranscodeFreezeError("private output set has unexpected entries")
        for variant in ("h264", "h265"):
            expected_names = {
                str(SOURCE_CONTRACT[role]["output_name"])
                for role in ("underbody", "front_gate")
            }
            if {entry.name for entry in output_dirs[variant].iterdir()} != expected_names:
                raise TranscodeFreezeError(
                    f"private {variant} output set has unexpected entries"
                )
        publication_set = [
            output_dirs["h264"],
            output_dirs["h265"],
            *working_outputs.values(),
            working_receipt,
        ]
        try:
            _validate_private_publication_set(working, publication_set)
        except _ExtractionSecurityError as exc:
            raise TranscodeFreezeError(
                f"private transcode publication policy failed: {exc}"
            ) from exc
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise TranscodeFreezeError(
                    "Windows transcode publication custody is incomplete"
                )
            try:
                _validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=destination.parent.name,
                )
                _validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=working.name,
                )
                _windows_publish_directory_by_handle(
                    source=working_custody,
                    parent=parent_custody,
                    target_name=destination.name,
                )
                published = True
                _validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=destination.name,
                )
                _validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=destination.parent.name,
                )
            except _ExtractionSecurityError as exc:
                raise TranscodeFreezeError(
                    f"custodied transcode publication failed: {exc}"
                ) from exc
        else:
            _atomic_publish_directory(working, destination)
            published = True

        for output in output_descriptors:
            final_path = root / str(output["path"])
            final_hash, final_state = _stable_sha256(
                final_path,
                label=f"{output['codec_variant']}/{output['role']} published transcode",
            )
            if (
                final_hash != output["sha256"]
                or int(final_state.st_size) != output["size_bytes"]
            ):
                raise TranscodeFreezeError(
                    f"{output['codec_variant']}/{output['role']} published transcode "
                    "does not match its receipt"
                )
        if (destination / TRANSCODE_RECEIPT_NAME).read_bytes() != encoded:
            raise TranscodeFreezeError("published transcode receipt bytes changed")
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise TranscodeFreezeError(
                    "Windows transcode post-publication custody is incomplete"
                )
            try:
                _validate_windows_direct_child_custody(
                    parent=root_custody,
                    child=parent_custody,
                    expected_name=destination.parent.name,
                )
                _validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=working_custody,
                    expected_name=destination.name,
                )
            except _ExtractionSecurityError as exc:
                raise TranscodeFreezeError(
                    f"post-publication transcode custody failed: {exc}"
                ) from exc
        return receipt
    except Exception:
        # Never close then path-delete an authoritative failed candidate.
        if not authoritative:
            cleanup_root = destination if published else working
            try:
                _cleanup_private_tree(
                    working=cleanup_root,
                    source_snapshots=[
                        cleanup_root / ".sources" / EXTRACTION_RECEIPT_NAME,
                        cleanup_root / ".sources" / "iss_v2_underbody.avi",
                        cleanup_root / ".sources" / "iss_v2_front_gate.avi",
                    ],
                    tool_snapshots=[
                        cleanup_root / ".tools" / tool_snapshots[role].name
                        for role in ("ffmpeg", "ffprobe")
                    ],
                    outputs=[
                        cleanup_root
                        / variant
                        / str(SOURCE_CONTRACT[role]["output_name"])
                        for variant in ("h264", "h265")
                        for role in ("underbody", "front_gate")
                    ],
                    receipt=cleanup_root / TRANSCODE_RECEIPT_NAME,
                )
            except OSError:
                pass
        raise
    finally:
        if working_custody is not None:
            working_custody.close()
        if parent_custody is not None:
            parent_custody.close()
        if root_custody is not None:
            root_custody.close()


def freeze_transcodes(
    *,
    project_root: Path,
    extraction_receipt: Path,
    expected_extraction_receipt_file_sha256: str,
    underbody_avi: Path,
    front_avi: Path,
    output_dir: Path,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
) -> dict[str, object]:
    return _freeze_transcodes_impl(
        project_root=project_root,
        extraction_receipt=extraction_receipt,
        expected_extraction_receipt_file_sha256=(
            expected_extraction_receipt_file_sha256
        ),
        underbody_avi=underbody_avi,
        front_avi=front_avi,
        output_dir=output_dir,
        ffmpeg=ffmpeg,
        expected_ffmpeg_sha256=expected_ffmpeg_sha256,
        expected_ffmpeg_version_sha256=expected_ffmpeg_version_sha256,
        ffprobe=ffprobe,
        expected_ffprobe_sha256=expected_ffprobe_sha256,
        expected_ffprobe_version_sha256=expected_ffprobe_version_sha256,
        test_adapters=None,
    )


def _freeze_transcodes_with_test_adapters(
    *,
    project_root: Path,
    extraction_receipt: Path,
    expected_extraction_receipt_file_sha256: str,
    underbody_avi: Path,
    front_avi: Path,
    output_dir: Path,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    runner: Runner,
    prober: Prober,
    version_reader: VersionReader,
) -> dict[str, object]:
    return _freeze_transcodes_impl(
        project_root=project_root,
        extraction_receipt=extraction_receipt,
        expected_extraction_receipt_file_sha256=(
            expected_extraction_receipt_file_sha256
        ),
        underbody_avi=underbody_avi,
        front_avi=front_avi,
        output_dir=output_dir,
        ffmpeg=ffmpeg,
        expected_ffmpeg_sha256=expected_ffmpeg_sha256,
        expected_ffmpeg_version_sha256=expected_ffmpeg_version_sha256,
        ffprobe=ffprobe,
        expected_ffprobe_sha256=expected_ffprobe_sha256,
        expected_ffprobe_version_sha256=expected_ffprobe_version_sha256,
        test_adapters=_TestAdapters(runner, prober, version_reader),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze four H.264/H.265 KPP legacy ISS v2 transcodes from one "
            "authoritative extraction receipt into a new staging directory."
        )
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--extraction-receipt", required=True, type=Path)
    parser.add_argument(
        "--expected-extraction-receipt-file-sha256",
        required=True,
    )
    parser.add_argument("--underbody-avi", required=True, type=Path)
    parser.add_argument("--front-avi", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--expected-ffmpeg-sha256", required=True)
    parser.add_argument("--expected-ffmpeg-version-sha256", required=True)
    parser.add_argument("--ffprobe", required=True, type=Path)
    parser.add_argument("--expected-ffprobe-sha256", required=True)
    parser.add_argument("--expected-ffprobe-version-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        receipt = freeze_transcodes(
            project_root=arguments.project_root,
            extraction_receipt=arguments.extraction_receipt,
            expected_extraction_receipt_file_sha256=(
                arguments.expected_extraction_receipt_file_sha256
            ),
            underbody_avi=arguments.underbody_avi,
            front_avi=arguments.front_avi,
            output_dir=arguments.output_dir,
            ffmpeg=arguments.ffmpeg,
            expected_ffmpeg_sha256=arguments.expected_ffmpeg_sha256,
            expected_ffmpeg_version_sha256=(
                arguments.expected_ffmpeg_version_sha256
            ),
            ffprobe=arguments.ffprobe,
            expected_ffprobe_sha256=arguments.expected_ffprobe_sha256,
            expected_ffprobe_version_sha256=(
                arguments.expected_ffprobe_version_sha256
            ),
        )
    except TranscodeFreezeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(_canonical_bytes(receipt).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
