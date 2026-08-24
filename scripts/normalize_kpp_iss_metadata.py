#!/usr/bin/env python3
"""Normalize the verified metadata grammar of the legacy ``13._03`` ISS file.

The normalizer deliberately keeps the record-header calendar clock and the
optional tag-4 integer clock in separate domains.  It never fills missing
tag-4 timestamps and it makes no claim about timezone, epoch, or event
semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Sequence

from extract_kpp_legacy_iss import (
    ExtractionError,
    _atomic_publish_directory,
    _cleanup_private_tree,
    _copy_pinned_snapshot,
    _create_private_working_directory,
    _create_windows_private_working_directory_with_custody,
    _open_windows_directory_custody,
    _validate_private_publication_set,
    _validate_windows_direct_child_custody,
    _windows_private_directory_acl_is_exact,
    _windows_publish_directory_by_handle,
)


GENERATION_ID = "kpp_legacy_iss_v2"
ARTIFACT_KIND = "vast_kpp_legacy_iss_metadata"
METADATA_NAME = "kpp_iss_v2_metadata.json"
HEADER_SIZE = 65
HEADER_PREFIX = b"\x0f\x00\xff\xff\x01\x00"
HEADER_DEADCODE_OFFSET = 44
HEADER_DEADCODE = b"\xde\xc0\xad\xde"
RECORD_SENTINEL = 0xFFFFFFFC
TLV_TERMINATOR = 0xFFFFFFFF
RECORD_PREFIX = struct.Struct("<I8H10I")
U32 = struct.Struct("<I")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_AUX_BYTES = 16 * 1024 * 1024
MAX_PRIMARY_BYTES = 16 * 1024 * 1024
MAX_TAG_BYTES = 16 * 1024 * 1024
MAX_MEDIA_BYTES = 512 * 1024 * 1024
MAX_RECORD_COUNT = 1_000_000
READ_BLOCK_BYTES = 8 * 1024 * 1024
MEDIA_PREFIX = b"\xff\xd8\xff"
MEDIA_SUFFIX = b"\xff\xd9I+v}"
RIFF_U32 = struct.Struct("<I")
PACKET_SEQUENCE_FRAME = struct.Struct("<QQ")
PACKETIZATION_CONTRACT = (
    "iss_record_media_start_to_next_record_media_start_or_eof_v1"
)
EVENT_RE = re.compile(
    r"#@@#(?:(?P<dated_kind>MD_TRUE|MD_FALSE) "
    r"(?P<dated_time>\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}\.\d{3})|"
    r"(?P<time_kind>STITCHING_STARTED|IMAGE) "
    r"(?P<time_only>\d{2}:\d{2}:\d{2}\.\d{3}))<br>"
)


class MetadataNormalizationError(RuntimeError):
    """Raised when an input does not satisfy the pinned ISS contract."""


@dataclass(frozen=True)
class _TestAdapters:
    after_snapshots: (
        Callable[[dict[str, Path], dict[str, Path]], None] | None
    ) = None


def _require_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise MetadataNormalizationError(
            f"{label} must be an exact lowercase SHA-256"
        )
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise MetadataNormalizationError(f"{label} must be a positive integer")
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
        raise MetadataNormalizationError(f"{label} must be absolute")
    try:
        if _is_reparse_or_symlink(path):
            raise MetadataNormalizationError(
                f"{label} must not be a symlink or reparse point"
            )
        observed = path.stat()
    except FileNotFoundError as exc:
        raise MetadataNormalizationError(f"{label} does not exist") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise MetadataNormalizationError(f"{label} must be a regular file")
    if observed.st_size <= 0:
        raise MetadataNormalizationError(f"{label} must be non-empty")
    return observed


def _identity(observed: os.stat_result) -> tuple[int, int]:
    return int(observed.st_dev), int(observed.st_ino)


def _stable_file_hash(
    path: Path,
    *,
    label: str,
    expected_sha256: str,
    expected_size_bytes: int,
) -> tuple[str, os.stat_result]:
    expected_hash = _require_sha256(expected_sha256, label=f"{label} SHA-256")
    expected_size = _require_positive_int(
        expected_size_bytes, label=f"{label} size_bytes"
    )
    before = _require_regular_file(path, label=label)
    if int(before.st_size) != expected_size:
        raise MetadataNormalizationError(
            f"{label} size does not match its external pin"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
        handle_state = os.fstat(stream.fileno())
    after = path.stat()
    _require_unchanged(before, handle_state, after, label=label)
    observed_hash = digest.hexdigest()
    if observed_hash != expected_hash:
        raise MetadataNormalizationError(
            f"{label} SHA-256 does not match its external pin"
        )
    return observed_hash, after


def _require_unchanged(
    before: os.stat_result,
    handle_state: os.stat_result,
    after: os.stat_result,
    *,
    label: str,
) -> None:
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(handle_state, field) for field in fields):
        raise MetadataNormalizationError(f"{label} changed while it was read")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise MetadataNormalizationError(f"{label} changed after it was read")


class _HashingReader:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()
        self.offset = 0

    def read_exact(self, size: int, *, label: str) -> bytes:
        if type(size) is not int or size < 0:
            raise MetadataNormalizationError(f"invalid byte count for {label}")
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.stream.read(min(READ_BLOCK_BYTES, remaining))
            if not chunk:
                raise MetadataNormalizationError(
                    f"unexpected EOF while reading {label}"
                )
            chunks.append(chunk)
            self.digest.update(chunk)
            self.offset += len(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def discard_exact(self, size: int, *, label: str) -> None:
        if type(size) is not int or size < 0:
            raise MetadataNormalizationError(f"invalid byte count for {label}")
        remaining = size
        while remaining:
            chunk = self.stream.read(min(READ_BLOCK_BYTES, remaining))
            if not chunk:
                raise MetadataNormalizationError(
                    f"unexpected EOF while reading {label}"
                )
            self.digest.update(chunk)
            self.offset += len(chunk)
            remaining -= len(chunk)

    def read_some(self, size: int) -> bytes:
        chunk = self.stream.read(size)
        if chunk:
            self.digest.update(chunk)
            self.offset += len(chunk)
        return chunk


def _read_u32(reader: _HashingReader, *, label: str) -> int:
    return U32.unpack(reader.read_exact(U32.size, label=label))[0]


def _validate_count(value: int, *, label: str, maximum: int) -> int:
    if value < 0 or value > maximum:
        raise MetadataNormalizationError(
            f"{label} exceeds the supported grammar bound"
        )
    return value


def _parse_header_timestamp(
    values: tuple[int, ...], *, frame_index: int
) -> dict[str, object]:
    year, month, day, hour, minute, second, millisecond, reserved = values
    if reserved != 0:
        raise MetadataNormalizationError(
            f"frame {frame_index} header timestamp reserved field is not zero"
        )
    if not 0 <= millisecond <= 999:
        raise MetadataNormalizationError(
            f"frame {frame_index} header timestamp millisecond is invalid"
        )
    try:
        datetime(year, month, day, hour, minute, second, millisecond * 1000)
    except ValueError as exc:
        raise MetadataNormalizationError(
            f"frame {frame_index} header timestamp is invalid"
        ) from exc
    return {
        "calendar_text": (
            f"{year:04d}-{month:02d}-{day:02d} "
            f"{hour:02d}:{minute:02d}:{second:02d}.{millisecond:03d}"
        ),
        "fields": {
            "year": year,
            "month": month,
            "day": day,
            "hour": hour,
            "minute": minute,
            "second": second,
            "millisecond": millisecond,
        },
    }


def _strict_json_object(payload: bytes, *, frame_index: int) -> dict[str, object]:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 is not ASCII JSON"
        ) from exc

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise MetadataNormalizationError(
                    f"frame {frame_index} tag 4 contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 contains invalid constant {value}"
        )

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except MetadataNormalizationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 is invalid JSON"
        ) from exc
    if type(value) is not dict:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 must contain one JSON object"
        )
    canonical = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    if canonical != payload:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 is not in the exact compact grammar"
        )
    return value


def _parse_tag4(
    payload: bytes, *, frame_index: int
) -> tuple[int | None, list[list[int]] | None, dict[str, int] | None]:
    value = _strict_json_object(payload, frame_index=frame_index)
    if list(value) == ["status"]:
        status = value["status"]
        if type(status) is not int or status != 1:
            raise MetadataNormalizationError(
                f"frame {frame_index} tag 4 status must be integer 1"
            )
        return 1, None, None
    if list(value) != ["data", "magnet_time", "frame_time"]:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 has an unsupported key grammar"
        )
    matrix = value["data"]
    if type(matrix) is not list or len(matrix) != 8:
        raise MetadataNormalizationError(
            f"frame {frame_index} tag 4 data must be an 8x3 integer matrix"
        )
    normalized_matrix: list[list[int]] = []
    for row in matrix:
        if type(row) is not list or len(row) != 3:
            raise MetadataNormalizationError(
                f"frame {frame_index} tag 4 data must be an 8x3 integer matrix"
            )
        normalized_row: list[int] = []
        for item in row:
            if type(item) is not int or not -(2**31) <= item < 2**31:
                raise MetadataNormalizationError(
                    f"frame {frame_index} tag 4 matrix values must be int32"
                )
            normalized_row.append(item)
        normalized_matrix.append(normalized_row)
    clock: dict[str, int] = {}
    for key in ("frame_time", "magnet_time"):
        observed = value[key]
        if (
            type(observed) is not int
            or observed < 1_000_000_000_000_000
            or observed > 9_999_999_999_999_999
        ):
            raise MetadataNormalizationError(
                f"frame {frame_index} tag 4 {key} must be a 16-digit integer"
            )
        clock[key] = observed
    return None, normalized_matrix, clock


def _validate_event_time(kind: str, value: str, *, frame_index: int) -> None:
    pattern = "%d-%m-%Y %H:%M:%S.%f" if kind.startswith("MD_") else "%H:%M:%S.%f"
    try:
        datetime.strptime(value, pattern)
    except ValueError as exc:
        raise MetadataNormalizationError(
            f"frame {frame_index} event timestamp is invalid"
        ) from exc


def _append_events(
    *,
    primary: bytes,
    previous: bytes,
    frame_index: int,
    events: list[dict[str, object]],
) -> bytes:
    if not primary.startswith(previous):
        raise MetadataNormalizationError(
            f"frame {frame_index} primary event snapshot is not append-only"
        )
    try:
        text = primary.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MetadataNormalizationError(
            f"frame {frame_index} primary event snapshot is not ASCII"
        ) from exc
    position = 0
    parsed: list[tuple[str, str]] = []
    while position < len(text):
        match = EVENT_RE.match(text, position)
        if match is None:
            raise MetadataNormalizationError(
                f"frame {frame_index} primary event snapshot violates the exact regex"
            )
        kind = match.group("dated_kind") or match.group("time_kind")
        timestamp_text = match.group("dated_time") or match.group("time_only")
        assert kind is not None and timestamp_text is not None
        _validate_event_time(kind, timestamp_text, frame_index=frame_index)
        parsed.append((kind, timestamp_text))
        position = match.end()
    previous_text = previous.decode("ascii")
    previous_count = 0
    position = 0
    while position < len(previous_text):
        match = EVENT_RE.match(previous_text, position)
        if match is None:
            raise MetadataNormalizationError("internal event snapshot state is invalid")
        previous_count += 1
        position = match.end()
    for kind, timestamp_text in parsed[previous_count:]:
        events.append(
            {
                "event_index": len(events),
                "kind": kind,
                "timestamp_text": timestamp_text,
                "timestamp_has_date": kind.startswith("MD_"),
                "first_observed_frame_index": frame_index,
            }
        )
    return primary


def _read_media(
    reader: _HashingReader, *, size: int, frame_index: int
) -> tuple[int, str, int, str]:
    _validate_count(size, label=f"frame {frame_index} media_len", maximum=MAX_MEDIA_BYTES)
    if size < len(MEDIA_PREFIX) + len(MEDIA_SUFFIX):
        raise MetadataNormalizationError(f"frame {frame_index} media is too short")
    start_offset = reader.offset
    digest = hashlib.sha256()
    jpeg_digest = hashlib.sha256()
    prefix = reader.read_exact(len(MEDIA_PREFIX), label=f"frame {frame_index} media SOI")
    digest.update(prefix)
    jpeg_digest.update(prefix)
    if prefix != MEDIA_PREFIX:
        raise MetadataNormalizationError(
            f"frame {frame_index} media does not start with MJPEG SOI"
        )
    remaining = size - len(MEDIA_PREFIX) - len(MEDIA_SUFFIX)
    while remaining:
        chunk_size = min(8 * 1024 * 1024, remaining)
        chunk = reader.read_exact(chunk_size, label=f"frame {frame_index} media")
        digest.update(chunk)
        jpeg_digest.update(chunk)
        remaining -= len(chunk)
    suffix = reader.read_exact(
        len(MEDIA_SUFFIX), label=f"frame {frame_index} media suffix"
    )
    digest.update(suffix)
    if suffix != MEDIA_SUFFIX:
        raise MetadataNormalizationError(
            f"frame {frame_index} media does not end with EOI+492b767d"
        )
    jpeg_digest.update(suffix[:2])
    return (
        start_offset,
        digest.hexdigest(),
        size - 4,
        jpeg_digest.hexdigest(),
    )


def _parse_source_archive(
    *,
    path: Path,
    expected_sha256: str,
    expected_size_bytes: int,
    external_frame_count: int,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], os.stat_result]:
    expected_hash = _require_sha256(
        expected_sha256, label="source archive SHA-256"
    )
    expected_size = _require_positive_int(
        expected_size_bytes, label="source archive size_bytes"
    )
    before = _require_regular_file(path, label="source archive")
    if int(before.st_size) != expected_size:
        raise MetadataNormalizationError(
            "source archive size does not match its external pin"
        )
    frames: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    previous_primary = b""
    previous_header_clock: tuple[int, ...] | None = None
    previous_frame_time: int | None = None
    previous_magnet_time: int | None = None
    with path.open("rb") as stream:
        reader = _HashingReader(stream)
        header = reader.read_exact(HEADER_SIZE, label="ISS header")
        if header[: len(HEADER_PREFIX)] != HEADER_PREFIX:
            raise MetadataNormalizationError("ISS header prefix is invalid")
        if (
            header[HEADER_DEADCODE_OFFSET : HEADER_DEADCODE_OFFSET + 4]
            != HEADER_DEADCODE
        ):
            raise MetadataNormalizationError("ISS header deadcode marker is invalid")
        record_count = U32.unpack_from(header, 6)[0]
        if record_count <= 0:
            raise MetadataNormalizationError("ISS header record_count must be positive")
        if record_count > MAX_RECORD_COUNT:
            raise MetadataNormalizationError("ISS header record_count exceeds its bound")
        if record_count != external_frame_count:
            raise MetadataNormalizationError(
                "ISS record_count does not match exported AVI external frame_count"
            )

        for frame_index in range(record_count):
            record_offset = reader.offset
            prefix = reader.read_exact(
                RECORD_PREFIX.size, label=f"frame {frame_index} record prefix"
            )
            unpacked = RECORD_PREFIX.unpack(prefix)
            if unpacked[0] != RECORD_SENTINEL:
                raise MetadataNormalizationError(
                    f"frame {frame_index} record sentinel is invalid"
                )
            header_clock = _parse_header_timestamp(
                tuple(unpacked[1:9]), frame_index=frame_index
            )
            header_clock_key = tuple(unpacked[1:8])
            if (
                previous_header_clock is not None
                and header_clock_key <= previous_header_clock
            ):
                raise MetadataNormalizationError(
                    "ISS record header clocks must be strictly monotonic"
                )
            previous_header_clock = header_clock_key
            source_fields = list(unpacked[9:16])
            media_len, aux_len, primary_len = unpacked[16:19]
            if aux_len != 0:
                raise MetadataNormalizationError(
                    f"frame {frame_index} aux_len must be exactly zero"
                )
            _validate_count(
                primary_len,
                label=f"frame {frame_index} primary_len",
                maximum=MAX_PRIMARY_BYTES,
            )
            if primary_len == 0:
                raise MetadataNormalizationError(
                    f"frame {frame_index} primary event snapshot must be non-empty"
                )
            aux = reader.read_exact(aux_len, label=f"frame {frame_index} aux")
            primary = reader.read_exact(
                primary_len, label=f"frame {frame_index} primary event snapshot"
            )
            previous_primary = _append_events(
                primary=primary,
                previous=previous_primary,
                frame_index=frame_index,
                events=events,
            )

            tag4_id = _read_u32(reader, label=f"frame {frame_index} tag 4 id")
            if tag4_id != 4:
                raise MetadataNormalizationError(
                    f"frame {frame_index} TLVs must be exactly 4,5,7"
                )
            tag4_len = _read_u32(reader, label=f"frame {frame_index} tag 4 length")
            _validate_count(
                tag4_len,
                label=f"frame {frame_index} tag 4 length",
                maximum=MAX_TAG_BYTES,
            )
            tag4 = reader.read_exact(tag4_len, label=f"frame {frame_index} tag 4")
            status, sensor_data, frame_clock = _parse_tag4(
                tag4, frame_index=frame_index
            )
            if frame_clock is not None:
                frame_time = frame_clock["frame_time"]
                magnet_time = frame_clock["magnet_time"]
                if (
                    previous_frame_time is not None
                    and frame_time <= previous_frame_time
                ) or (
                    previous_magnet_time is not None
                    and magnet_time <= previous_magnet_time
                ):
                    raise MetadataNormalizationError(
                        "ISS tag-4 clocks must be strictly monotonic"
                    )
                previous_frame_time = frame_time
                previous_magnet_time = magnet_time

            tag5_id = _read_u32(reader, label=f"frame {frame_index} tag 5 id")
            if tag5_id != 5:
                raise MetadataNormalizationError(
                    f"frame {frame_index} TLVs must be exactly 4,5,7"
                )
            tag5_len = _read_u32(reader, label=f"frame {frame_index} tag 5 length")
            if tag5_len != primary_len:
                raise MetadataNormalizationError(
                    f"frame {frame_index} tag 5 length does not match primary"
                )
            tag5 = reader.read_exact(tag5_len, label=f"frame {frame_index} tag 5")
            if tag5 != primary:
                raise MetadataNormalizationError(
                    f"frame {frame_index} tag 5 does not equal primary"
                )

            tag7_id = _read_u32(reader, label=f"frame {frame_index} tag 7 id")
            if tag7_id != 7:
                raise MetadataNormalizationError(
                    f"frame {frame_index} TLVs must be exactly 4,5,7"
                )
            tag7_len = _read_u32(reader, label=f"frame {frame_index} tag 7 length")
            if tag7_len != 4:
                raise MetadataNormalizationError(
                    f"frame {frame_index} tag 7 length must be 4"
                )
            tag7 = reader.read_exact(tag7_len, label=f"frame {frame_index} tag 7")
            if tag7 != U32.pack(31):
                raise MetadataNormalizationError(
                    f"frame {frame_index} tag 7 value must be 31"
                )
            terminator = _read_u32(reader, label=f"frame {frame_index} TLV terminator")
            if terminator != TLV_TERMINATOR:
                raise MetadataNormalizationError(
                    f"frame {frame_index} TLVs are not followed by the exact terminator"
                )

            (
                media_offset,
                media_sha256,
                jpeg_payload_size,
                jpeg_payload_sha256,
            ) = _read_media(
                reader, size=media_len, frame_index=frame_index
            )
            frames.append(
                {
                    "frame_index": frame_index,
                    "record_offset_bytes": record_offset,
                    "header_clock": header_clock,
                    "frame_clock": frame_clock,
                    "tag4_status": status,
                    "sensor_data_8x3": sensor_data,
                    "source_fields_u32": source_fields,
                    "aux": {
                        "size_bytes": aux_len,
                        "sha256": hashlib.sha256(aux).hexdigest(),
                    },
                    "primary_event_snapshot": {
                        "size_bytes": primary_len,
                        "sha256": hashlib.sha256(primary).hexdigest(),
                    },
                    "media": {
                        "offset_bytes": media_offset,
                        "size_bytes": media_len,
                        "sha256": media_sha256,
                        "jpeg_payload_size_bytes": jpeg_payload_size,
                        "jpeg_payload_sha256": jpeg_payload_sha256,
                    },
                }
            )

        trailing = reader.read_some(1)
        if trailing:
            raise MetadataNormalizationError(
                "source archive contains bytes after the declared record_count"
            )
        handle_state = os.fstat(stream.fileno())
        source_hash = reader.digest.hexdigest()
        consumed_size = reader.offset
    after = path.stat()
    _require_unchanged(before, handle_state, after, label="source archive")
    if consumed_size != expected_size:
        raise MetadataNormalizationError(
            "source archive parsed size does not match its external pin"
        )
    if source_hash != expected_hash:
        raise MetadataNormalizationError(
            "source archive SHA-256 does not match its external pin"
        )
    descriptor = {
        "archive_logical_id": path.name,
        "sha256": source_hash,
        "size_bytes": consumed_size,
        "header_size_bytes": HEADER_SIZE,
        "header_sha256": hashlib.sha256(header).hexdigest(),
        "record_count": record_count,
    }
    return descriptor, frames, events, after


def _bind_source_packet_intervals(
    *,
    path: Path,
    expected_sha256: str,
    expected_size_bytes: int,
    parsed_source_state: os.stat_result,
    frames: list[dict[str, object]],
) -> tuple[os.stat_result, str]:
    """Bind each demuxed AVI packet to its exact source-archive byte interval."""

    expected_hash = _require_sha256(
        expected_sha256, label="source archive SHA-256"
    )
    expected_size = _require_positive_int(
        expected_size_bytes, label="source archive size_bytes"
    )
    before = _require_regular_file(path, label="source archive interval binding")
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(
        getattr(parsed_source_state, field) != getattr(before, field)
        for field in stable_fields
    ):
        raise MetadataNormalizationError(
            "source archive changed before AVI packet interval binding"
        )

    media_descriptors: list[dict[str, object]] = []
    offsets: list[int] = []
    for frame_index, frame in enumerate(frames):
        media = frame.get("media")
        if type(media) is not dict:
            raise MetadataNormalizationError(
                "internal source media descriptor is invalid"
            )
        offset = media.get("offset_bytes")
        if type(offset) is not int or offset < 0 or offset >= expected_size:
            raise MetadataNormalizationError(
                f"frame {frame_index} source media offset is invalid"
            )
        if offsets and offset <= offsets[-1]:
            raise MetadataNormalizationError(
                "source media offsets must be strictly increasing"
            )
        media_descriptors.append(media)
        offsets.append(offset)
    if not offsets:
        raise MetadataNormalizationError("source archive contains no media records")

    sequence_digest = hashlib.sha256(
        b"VAST:kpp-iss-raw-mjpeg-demux-packets:v1\0"
    )
    with path.open("rb") as stream:
        reader = _HashingReader(stream)
        reader.discard_exact(offsets[0], label="source bytes before first media")
        for frame_index, start_offset in enumerate(offsets):
            end_offset = (
                offsets[frame_index + 1]
                if frame_index + 1 < len(offsets)
                else expected_size
            )
            interval_size = end_offset - start_offset
            if interval_size <= 0:
                raise MetadataNormalizationError(
                    f"frame {frame_index} source packet interval is empty"
                )
            interval_digest = hashlib.sha256()
            sequence_digest.update(
                PACKET_SEQUENCE_FRAME.pack(frame_index, interval_size)
            )
            remaining = interval_size
            while remaining:
                chunk = reader.read_exact(
                    min(8 * 1024 * 1024, remaining),
                    label=f"frame {frame_index} source packet interval",
                )
                interval_digest.update(chunk)
                sequence_digest.update(chunk)
                remaining -= len(chunk)
            media_descriptors[frame_index]["avi_packet_source_interval"] = {
                "contract": PACKETIZATION_CONTRACT,
                "offset_bytes": start_offset,
                "size_bytes": interval_size,
                "sha256": interval_digest.hexdigest(),
            }
        if reader.offset != expected_size or reader.read_some(1):
            raise MetadataNormalizationError(
                "source packet intervals do not end at the pinned archive EOF"
            )
        handle_state = os.fstat(stream.fileno())
        observed_hash = reader.digest.hexdigest()
    after = path.stat()
    _require_unchanged(before, handle_state, after, label="source archive interval binding")
    if observed_hash != expected_hash:
        raise MetadataNormalizationError(
            "source archive SHA-256 changed during AVI packet interval binding"
        )
    return after, sequence_digest.hexdigest()


def _consume_avi_packet(
    reader: _HashingReader,
    *,
    size: int,
    frame: dict[str, object],
    packet_index: int,
) -> None:
    media = frame.get("media")
    if type(media) is not dict:
        raise MetadataNormalizationError("internal source media descriptor is invalid")
    interval = media.get("avi_packet_source_interval")
    if type(interval) is not dict:
        raise MetadataNormalizationError(
            "internal AVI packet source interval is invalid"
        )
    if interval.get("contract") != PACKETIZATION_CONTRACT:
        raise MetadataNormalizationError(
            "internal AVI packet source interval contract is invalid"
        )
    expected_size = interval.get("size_bytes")
    expected_sha256 = interval.get("sha256")
    if type(expected_size) is not int or expected_size <= 0:
        raise MetadataNormalizationError("internal source interval size is invalid")
    if type(expected_sha256) is not str or SHA256_RE.fullmatch(expected_sha256) is None:
        raise MetadataNormalizationError("internal source interval hash is invalid")
    if size != expected_size:
        raise MetadataNormalizationError(
            f"AVI packet {packet_index} size does not match its ISS source interval"
        )
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = reader.read_exact(
            min(8 * 1024 * 1024, remaining),
            label=f"AVI packet {packet_index}",
        )
        digest.update(chunk)
        remaining -= len(chunk)
    if digest.hexdigest() != expected_sha256:
        raise MetadataNormalizationError(
            f"AVI packet {packet_index} bytes do not match its ISS source interval"
        )


def _parse_avi_chunks(
    reader: _HashingReader,
    *,
    end_offset: int,
    in_movi: bool,
    frames: list[dict[str, object]],
    packet_index: int,
    depth: int,
) -> int:
    if depth > 8:
        raise MetadataNormalizationError("AVI LIST nesting exceeds its bound")
    while reader.offset < end_offset:
        if end_offset - reader.offset < 8:
            raise MetadataNormalizationError("AVI chunk header is truncated")
        chunk_id = reader.read_exact(4, label="AVI chunk id")
        chunk_size = RIFF_U32.unpack(
            reader.read_exact(4, label="AVI chunk size")
        )[0]
        data_end = reader.offset + chunk_size
        if data_end > end_offset:
            raise MetadataNormalizationError("AVI chunk exceeds its parent bounds")
        if chunk_id == b"LIST":
            if chunk_size < 4:
                raise MetadataNormalizationError("AVI LIST chunk is too short")
            list_type = reader.read_exact(4, label="AVI LIST type")
            packet_index = _parse_avi_chunks(
                reader,
                end_offset=data_end,
                in_movi=in_movi or list_type == b"movi",
                frames=frames,
                packet_index=packet_index,
                depth=depth + 1,
            )
        elif len(chunk_id) == 4 and chunk_id[2:] in (b"dc", b"db"):
            if not in_movi:
                raise MetadataNormalizationError(
                    "AVI contains a video packet outside movi"
                )
            if not chunk_id[:2].isdigit() or chunk_id[:2] != b"00":
                raise MetadataNormalizationError(
                    "AVI contains a video packet outside stream 00"
                )
            if packet_index >= len(frames):
                raise MetadataNormalizationError("AVI contains extra video packets")
            _consume_avi_packet(
                reader,
                size=chunk_size,
                frame=frames[packet_index],
                packet_index=packet_index,
            )
            packet_index += 1
        else:
            reader.discard_exact(
                data_end - reader.offset,
                label="AVI chunk payload",
            )
        if reader.offset != data_end:
            raise MetadataNormalizationError("AVI chunk parser lost byte alignment")
        if chunk_size & 1:
            if reader.offset >= end_offset:
                raise MetadataNormalizationError("AVI chunk padding is truncated")
            reader.read_exact(1, label="AVI chunk padding")
    if reader.offset != end_offset:
        raise MetadataNormalizationError("AVI LIST does not end on its declared bound")
    return packet_index


def _validate_avi_packet_sequence(
    *,
    path: Path,
    expected_sha256: str,
    expected_size_bytes: int,
    frames: list[dict[str, object]],
) -> tuple[str, os.stat_result, int]:
    expected_hash = _require_sha256(
        expected_sha256, label="exported AVI SHA-256"
    )
    expected_size = _require_positive_int(
        expected_size_bytes, label="exported AVI size_bytes"
    )
    before = _require_regular_file(path, label="exported AVI")
    if int(before.st_size) != expected_size:
        raise MetadataNormalizationError(
            "exported AVI size does not match its external pin"
        )
    packet_index = 0
    riff_index = 0
    with path.open("rb") as stream:
        reader = _HashingReader(stream)
        while reader.offset < expected_size:
            if expected_size - reader.offset < 12:
                raise MetadataNormalizationError("AVI RIFF header is truncated")
            riff_start = reader.offset
            if reader.read_exact(4, label="AVI RIFF id") != b"RIFF":
                raise MetadataNormalizationError("AVI must contain only RIFF segments")
            riff_size = RIFF_U32.unpack(
                reader.read_exact(4, label="AVI RIFF size")
            )[0]
            if riff_size < 4:
                raise MetadataNormalizationError("AVI RIFF segment is too short")
            riff_end = riff_start + 8 + riff_size
            if riff_end > expected_size:
                raise MetadataNormalizationError("AVI RIFF segment exceeds file bounds")
            form_type = reader.read_exact(4, label="AVI RIFF form type")
            expected_form = b"AVI " if riff_index == 0 else b"AVIX"
            if form_type != expected_form:
                raise MetadataNormalizationError(
                    "AVI RIFF segment has an unexpected form type"
                )
            packet_index = _parse_avi_chunks(
                reader,
                end_offset=riff_end,
                in_movi=False,
                frames=frames,
                packet_index=packet_index,
                depth=0,
            )
            if riff_size & 1:
                if reader.offset >= expected_size:
                    raise MetadataNormalizationError("AVI RIFF padding is truncated")
                reader.read_exact(1, label="AVI RIFF padding")
            riff_index += 1
        handle_state = os.fstat(stream.fileno())
        observed_hash = reader.digest.hexdigest()
    after = path.stat()
    _require_unchanged(before, handle_state, after, label="exported AVI")
    if observed_hash != expected_hash:
        raise MetadataNormalizationError(
            "exported AVI SHA-256 does not match its external pin"
        )
    if packet_index != len(frames):
        raise MetadataNormalizationError(
            "AVI packet count does not match the ISS record sequence"
        )
    return observed_hash, after, packet_index


def _validated_project_root(value: Path) -> Path:
    if not value.is_absolute():
        raise MetadataNormalizationError("project_root must be absolute")
    root = value.absolute()
    if not root.is_dir() or _is_reparse_or_symlink(root):
        raise MetadataNormalizationError(
            "project_root must be a plain existing directory"
        )
    return root


def _validated_output_path(project_root: Path, value: Path) -> Path:
    if not value.is_absolute():
        raise MetadataNormalizationError("output_path must be absolute")
    output = value.absolute()
    try:
        relative = output.relative_to(project_root)
    except ValueError as exc:
        raise MetadataNormalizationError(
            "output_path must stay inside project_root/staging"
        ) from exc
    if not relative.parts or relative.parts[0].casefold() != "staging":
        raise MetadataNormalizationError(
            "output_path must stay inside project_root/staging"
        )
    if len(relative.parts) != 3:
        raise MetadataNormalizationError(
            "output parent must be one absent direct child directory of staging"
        )
    if output.name != METADATA_NAME:
        raise MetadataNormalizationError(
            f"output_path must use the fixed filename {METADATA_NAME}"
        )
    destination = output.parent
    if destination.exists() or destination.is_symlink():
        raise MetadataNormalizationError(
            f"output parent already exists: {destination.name}"
        )
    return output


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _receipt_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        b"VAST:kpp-legacy-iss-metadata:v1\0" + _canonical_bytes(value)
    ).hexdigest()


def _write_verified_candidate(path: Path, payload: bytes) -> None:
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    observed_sha256, observed = _stable_file_hash(
        path,
        label="normalized metadata candidate",
        expected_sha256=expected_sha256,
        expected_size_bytes=len(payload),
    )
    if observed_sha256 != expected_sha256 or int(observed.st_size) != len(payload):
        raise MetadataNormalizationError(
            "normalized metadata candidate does not match its canonical bytes"
        )


def _normalize_metadata_impl(
    *,
    project_root: Path,
    source_archive: Path,
    expected_source_sha256: str,
    expected_source_size_bytes: int,
    exported_avi: Path,
    expected_exported_avi_sha256: str,
    expected_exported_avi_size_bytes: int,
    exported_avi_frame_count: int,
    output_path: Path,
    test_adapters: _TestAdapters | None,
) -> dict[str, object]:
    """Normalize private snapshots and publish one no-replace directory."""

    root = _validated_project_root(project_root)
    output = _validated_output_path(root, output_path)
    source = source_archive.absolute()
    avi = exported_avi.absolute()
    expected_source_hash = _require_sha256(
        expected_source_sha256, label="source archive SHA-256"
    )
    expected_source_size = _require_positive_int(
        expected_source_size_bytes, label="source archive size_bytes"
    )
    expected_avi_hash = _require_sha256(
        expected_exported_avi_sha256, label="exported AVI SHA-256"
    )
    expected_avi_size = _require_positive_int(
        expected_exported_avi_size_bytes, label="exported AVI size_bytes"
    )
    external_frame_count = _require_positive_int(
        exported_avi_frame_count, label="exported AVI frame_count"
    )
    source_state = _require_regular_file(source, label="source archive")
    avi_state = _require_regular_file(avi, label="exported AVI")
    if int(source_state.st_size) != expected_source_size:
        raise MetadataNormalizationError(
            "source archive size does not match its external pin"
        )
    if int(avi_state.st_size) != expected_avi_size:
        raise MetadataNormalizationError(
            "exported AVI size does not match its external pin"
        )
    if _identity(source_state) == _identity(avi_state):
        raise MetadataNormalizationError(
            "source archive and exported AVI must be physically distinct"
        )

    authoritative = test_adapters is None and os.name == "nt"
    staging_parent = output.parent.parent
    root_custody = None
    parent_custody = None
    working_custody = None
    working: Path | None = None
    published = False
    source_snapshot: Path | None = None
    avi_snapshot: Path | None = None
    try:
        if authoritative:
            root_custody = _open_windows_directory_custody(
                root,
                label="metadata project root",
                require_delete_access=False,
            )
        try:
            staging_parent.mkdir(exist_ok=True)
        except OSError as exc:
            raise MetadataNormalizationError(
                f"could not create staging directory: {exc}"
            ) from exc
        if not staging_parent.is_dir() or _is_reparse_or_symlink(staging_parent):
            raise MetadataNormalizationError(
                "staging parent must be a plain existing directory"
            )
        output = _validated_output_path(root, output)
        destination = output.parent
        if authoritative:
            if root_custody is None:
                raise MetadataNormalizationError(
                    "metadata project root custody was not acquired"
                )
            parent_custody = _open_windows_directory_custody(
                staging_parent,
                label="metadata staging parent",
                require_delete_access=False,
            )
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=staging_parent.name,
            )
        if authoritative:
            if root_custody is None or parent_custody is None:
                raise MetadataNormalizationError(
                    "metadata project root/staging custody was not acquired"
                )
            working, working_custody = (
                _create_windows_private_working_directory_with_custody(
                    parent=parent_custody,
                    prefix=f".{destination.name}.",
                    suffix=".candidate",
                    label="metadata working directory",
                )
            )
        else:
            working = _create_private_working_directory(
                parent=staging_parent,
                prefix=f".{destination.name}.",
                suffix=".candidate",
            )
        if _is_reparse_or_symlink(working):
            raise MetadataNormalizationError(
                "private metadata directory must not be a reparse point"
            )
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise MetadataNormalizationError(
                    "private Windows metadata custody was not acquired"
                )
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=staging_parent.name,
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=working.name,
            )
            if not _windows_private_directory_acl_is_exact(working):
                raise MetadataNormalizationError(
                    "private metadata directory ACL changed before snapshots"
                )

        snapshot_dir = working / ".sources"
        snapshot_dir.mkdir()
        source_snapshot = snapshot_dir / "source_archive.iss"
        avi_snapshot = snapshot_dir / "exported_avi.avi"
        source_snapshot_descriptor, _ = _copy_pinned_snapshot(
            source=source,
            target=source_snapshot,
            expected_sha256=expected_source_hash,
            label="source archive",
        )
        avi_snapshot_descriptor, _ = _copy_pinned_snapshot(
            source=avi,
            target=avi_snapshot,
            expected_sha256=expected_avi_hash,
            label="exported AVI",
        )
        if source_snapshot_descriptor.get("size_bytes") != expected_source_size:
            raise MetadataNormalizationError(
                "source archive snapshot size does not match its external pin"
            )
        if avi_snapshot_descriptor.get("size_bytes") != expected_avi_size:
            raise MetadataNormalizationError(
                "exported AVI snapshot size does not match its external pin"
            )

        origins = {"source_archive": source, "exported_avi": avi}
        snapshots = {
            "source_archive": source_snapshot,
            "exported_avi": avi_snapshot,
        }
        if test_adapters is not None and test_adapters.after_snapshots is not None:
            test_adapters.after_snapshots(origins, snapshots)

        source_descriptor, frames, events, parsed_source_state = (
            _parse_source_archive(
                path=source_snapshot,
                expected_sha256=expected_source_hash,
                expected_size_bytes=expected_source_size,
                external_frame_count=external_frame_count,
            )
        )
        source_descriptor["archive_logical_id"] = source.name
        _, packet_sequence_sha256 = _bind_source_packet_intervals(
            path=source_snapshot,
            expected_sha256=expected_source_hash,
            expected_size_bytes=expected_source_size,
            parsed_source_state=parsed_source_state,
            frames=frames,
        )
        source_descriptor["avi_packet_source_interval_sequence_sha256"] = (
            packet_sequence_sha256
        )
        avi_hash, avi_after, avi_packet_count = _validate_avi_packet_sequence(
            path=avi_snapshot,
            expected_sha256=expected_avi_hash,
            expected_size_bytes=expected_avi_size,
            frames=frames,
        )
        if avi_packet_count != external_frame_count:
            raise MetadataNormalizationError(
                "AVI packet count does not match exported AVI external frame_count"
            )

        _stable_file_hash(
            source_snapshot,
            label="source archive private snapshot before publication",
            expected_sha256=expected_source_hash,
            expected_size_bytes=expected_source_size,
        )
        _stable_file_hash(
            avi_snapshot,
            label="exported AVI private snapshot before publication",
            expected_sha256=expected_avi_hash,
            expected_size_bytes=expected_avi_size,
        )

        receipt: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": ARTIFACT_KIND,
            "generation_id": GENERATION_ID,
            "status": (
                "authoritative_windows_candidate"
                if authoritative
                else "non_authoritative_path_fallback_candidate"
            ),
            "source_archive": source_descriptor,
            "exported_avi": {
                "artifact_logical_id": avi.name,
                "sha256": avi_hash,
                "size_bytes": int(avi_after.st_size),
                "frame_count": avi_packet_count,
                "frame_count_authority": (
                    "physical_movi_packet_sequence_validation"
                ),
                "packetization_contract": PACKETIZATION_CONTRACT,
            },
            "clock_domains": {
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
            },
            "frames": frames,
            "events": events,
            "claims": {
                "timestamps_interpolated": False,
                "clock_domains_equated": False,
                "timezone_validated": False,
                "frame_clock_unit_validated": False,
                "frame_clock_epoch_validated": False,
                "event_semantics_validated": False,
                "avi_packet_source_interval_binding_validated": True,
                "avi_physical_movi_packet_index_alignment_validated": True,
                "avi_demuxed_or_decoded_frame_index_alignment_validated": False,
                "avi_packet_jpeg_prefix_binding_validated": True,
                "avi_packet_equals_declared_media_without_trailer": False,
                "avi_packet_payload_is_clean_jpeg": False,
                "source_and_avi_private_snapshots_verified": True,
                "output_set_directory_published_atomically": authoritative,
                "windows_project_root_staging_and_working_directory_"
                "handle_custody_validated": authoritative,
                "accuracy_ground_truth_validated": False,
                "v1_dataset_identity_equivalent": False,
                "publication_authorized": False,
            },
        }
        receipt["normalization_receipt_sha256"] = _receipt_sha256(receipt)
        encoded = _canonical_bytes(receipt)
        working_output = working / METADATA_NAME
        _write_verified_candidate(working_output, encoded)

        source_snapshot.unlink()
        source_snapshot = None
        avi_snapshot.unlink()
        avi_snapshot = None
        snapshot_dir.rmdir()
        if {entry.name for entry in working.iterdir()} != {METADATA_NAME}:
            raise MetadataNormalizationError(
                "private metadata output set has unexpected entries"
            )
        _validate_private_publication_set(working, [working_output])

        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise MetadataNormalizationError(
                    "Windows metadata publication custody is incomplete"
                )
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=staging_parent.name,
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
                parent=root_custody,
                child=parent_custody,
                expected_name=staging_parent.name,
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=destination.name,
            )
        else:
            _atomic_publish_directory(working, destination)
            published = True
        _stable_file_hash(
            destination / METADATA_NAME,
            label="published metadata output",
            expected_sha256=hashlib.sha256(encoded).hexdigest(),
            expected_size_bytes=len(encoded),
        )
        return receipt
    except Exception as exc:
        cleanup_error: Exception | None = None
        if working is not None and not published and not authoritative:
            try:
                _cleanup_private_tree(
                    working=working,
                    source_snapshots=[
                        working / ".sources" / "source_archive.iss",
                        working / ".sources" / "exported_avi.avi",
                    ],
                    tool_snapshots=[],
                    outputs=[],
                    receipt=working / METADATA_NAME,
                )
            except Exception as cleanup_exc:
                cleanup_error = cleanup_exc
        if cleanup_error is not None:
            exc.add_note(f"owned metadata candidate cleanup failed: {cleanup_error}")
        if isinstance(exc, ExtractionError):
            raise MetadataNormalizationError(str(exc)) from exc
        raise
    finally:
        if working_custody is not None:
            working_custody.close()
        if parent_custody is not None:
            parent_custody.close()
        if root_custody is not None:
            root_custody.close()


def normalize_metadata(
    *,
    project_root: Path,
    source_archive: Path,
    expected_source_sha256: str,
    expected_source_size_bytes: int,
    exported_avi: Path,
    expected_exported_avi_sha256: str,
    expected_exported_avi_size_bytes: int,
    exported_avi_frame_count: int,
    output_path: Path,
) -> dict[str, object]:
    """Run normalization without test adapters."""

    return _normalize_metadata_impl(
        project_root=project_root,
        source_archive=source_archive,
        expected_source_sha256=expected_source_sha256,
        expected_source_size_bytes=expected_source_size_bytes,
        exported_avi=exported_avi,
        expected_exported_avi_sha256=expected_exported_avi_sha256,
        expected_exported_avi_size_bytes=expected_exported_avi_size_bytes,
        exported_avi_frame_count=exported_avi_frame_count,
        output_path=output_path,
        test_adapters=None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize an externally pinned 13._03 ISS archive and bind it to "
            "an externally pinned exported AVI without inventing timestamps."
        )
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--source-archive", required=True, type=Path)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-source-size-bytes", required=True, type=int)
    parser.add_argument("--exported-avi", required=True, type=Path)
    parser.add_argument("--expected-exported-avi-sha256", required=True)
    parser.add_argument(
        "--expected-exported-avi-size-bytes", required=True, type=int
    )
    parser.add_argument("--exported-avi-frame-count", required=True, type=int)
    parser.add_argument("--output-path", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        receipt = normalize_metadata(
            project_root=arguments.project_root,
            source_archive=arguments.source_archive,
            expected_source_sha256=arguments.expected_source_sha256,
            expected_source_size_bytes=arguments.expected_source_size_bytes,
            exported_avi=arguments.exported_avi,
            expected_exported_avi_sha256=arguments.expected_exported_avi_sha256,
            expected_exported_avi_size_bytes=(
                arguments.expected_exported_avi_size_bytes
            ),
            exported_avi_frame_count=arguments.exported_avi_frame_count,
            output_path=arguments.output_path,
        )
    except MetadataNormalizationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(_canonical_bytes(receipt).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
