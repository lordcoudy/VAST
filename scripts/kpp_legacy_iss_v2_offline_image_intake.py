#!/usr/bin/env python3
"""Explicit, offline-only intake for the frozen KPP v2 TensorRT image.

This command is intentionally separate from the pilot executor.  It accepts
only a caller-pinned Docker 29 save hybrid, normalizes that archive without
extracting it, and performs one daemon mutation: ``docker image load``.  Its
authoritative fence, attempt marker, and receipt live in a per-user global
nonpublication ledger so changing or copying the project root cannot retry an
unresolved load.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

DOCKER_CLI = "/usr/bin/docker"
DOCKER_HOST_FLAG = "--host"
DOCKER_HOST_VALUE = "unix:///var/run/docker.sock"
TENSORRT_IMAGE = "vast/analytics-tensorrt-worker:v2"
TENSORRT_IMAGE_ID = (
    "sha256:29ad51f4057f5aa77eb18e572c5055ed465fac39d49365d8eb5ffafe4fe8001f"
)
TENSORRT_BASE_IMAGE_ID = (
    "sha256:277bb99b1b23b5b763332041703905242a1238c3faeb72533aa6045c9d2d7489"
)
TENSORRT_ENTRYPOINT = "/opt/vast/bin/vast_tensorrt_worker"
IMAGE_LABELS = {
    "org.vast.analytics_worker.base_image_id": TENSORRT_BASE_IMAGE_ID,
    "org.vast.analytics_worker.engine": "tensorrt_cuda",
}
_CANONICAL_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GLOBAL_STATE_COMPONENTS = (
    ".local",
    "state",
    "vast",
    "nonpublication",
    "offline_image_intake",
)
FENCE_NAME = "offline_image_intake_fence.json"
ATTEMPT_NAME = "offline_image_intake_load_attempt.json"
RECEIPT_NAME = "offline_image_intake_receipt.json"
FALSE_CLAIM_FIELDS = (
    "publication_ready",
    "publication_capable",
    "publishable",
    "accepted_evidence",
    "evidence_accepted",
    "benchmark",
    "benchmark_accepted",
    "promotable",
    "publication_authorized",
    "canonical_publication_outputs_written",
    "publication_receipt_written",
    "result_accepted",
    "runtime_acceptance",
    "image_runtime_acceptance",
    "daemon_content_store_unchanged_attested",
    "load_atomicity_attested",
    "accuracy_accepted",
    "executed_engine_attested",
    "dynamic_library_closure_attested",
    "power_loss_recovery_attested",
    "preexisting_image_provenance_attested",
    "daemon_wide_exclusivity_attested",
    "cross_user_unresolved_attempt_exclusion_attested",
    "docker_image_remove_performed",
    "docker_image_tag_performed",
    "daemon_cleanup_performed",
    "rollback_performed",
)
_FALSE_CLAIMS = {field: False for field in FALSE_CLAIM_FIELDS}
LOAD_FACT_FIELDS = (
    "load_command_start_possible_historically",
    "load_command_start_observed_during_this_invocation",
    "load_command_return_observed_during_this_invocation",
    "exact_expected_image_effect_observed",
    "historical_load_command_outcome_known",
    "bounded_command_and_exact_effect_correlation_observed",
    "effect_causally_attributed_to_this_intake",
)
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{64}\Z")
_INTAKE_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
_BLOB_PATH_RE = re.compile(r"blobs/sha256/([0-9a-f]{64})\Z")
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_MEMBERS = 16_384
_MAX_UNCOMPRESSED_LAYER_BYTES = 32 * 1024 * 1024 * 1024
_MAX_DAEMON_IMAGES = 256
_MAX_DAEMON_CONTAINERS = 4096
_MAX_IMAGE_REFERENCES = 8
_MAX_IMAGE_REFERENCE_BYTES = 512
_MAX_CATALOG_JSON_BYTES = 4 * 1024 * 1024
_MAX_SANITIZED_CAPTURE_BYTES = 4 * 1024
_OCI_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
_OCI_MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
_CONFIG_MEDIA_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
_LAYER_MEDIA_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
}
_FENCE_DOMAIN = b"VAST:kpp-v2-offline-image-intake-fence:v1\0"
_ATTEMPT_DOMAIN = b"VAST:kpp-v2-offline-image-intake-load-attempt:v1\0"
_RECEIPT_DOMAIN = b"VAST:kpp-v2-offline-image-intake-receipt:v1\0"
_ASSESSMENT_DOMAIN = b"VAST:kpp-v2-offline-image-intake-assessment:v1\0"
_OPERATION_DOMAIN = b"VAST:kpp-v2-offline-image-intake-operation:v1\0"
_INVENTORY_DOMAIN = b"VAST:kpp-v2-offline-image-archive-inventory:v1\0"
_CATALOG_DOMAIN = b"VAST:kpp-v2-offline-image-daemon-catalog:v1\0"
_DURABLE_NAMESPACE_DOMAIN = b"VAST:kpp-v2-offline-image-daemon-target-namespace:v1\0"


class IntakeContractError(RuntimeError):
    """The archive, local daemon, or durable intake state is not exact."""


@dataclass(frozen=True)
class FileIdentity:
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class CommandCapture:
    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    stdout_overflow: bool = False
    stderr_overflow: bool = False


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
        pass_fds: tuple[int, ...] = (),
        executable_override: str | None = None,
    ) -> CommandCapture: ...


class ArchiveSession(Protocol):
    identity: FileIdentity
    normalized_identity: FileIdentity
    inventory: Mapping[str, object]
    load_input: str
    pass_fds: tuple[int, ...]

    def __enter__(self) -> "ArchiveSession": ...

    def __exit__(self, *args: object) -> None: ...

    def revalidate(self) -> None: ...


class DockerCliSession(Protocol):
    identity: FileIdentity
    executable: str
    pass_fds: tuple[int, ...]

    def __enter__(self) -> "DockerCliSession": ...

    def __exit__(self, *args: object) -> None: ...

    def revalidate(self) -> None: ...


@dataclass(frozen=True)
class _IntakeDependencies:
    platform_name: str
    environment: Mapping[str, str]
    observe_docker_cli: Callable[[], FileIdentity | DockerCliSession]
    command_runner: CommandRunner
    archive_opener: Callable[..., ArchiveSession]
    canonical_project_root: Path
    local_runtime_guard: Callable[[], None] | None = None
    daemon_lock_factory: Callable[[str], Any] | None = None
    output_namespace_factory: Callable[[Path, str], Any] | None = None
    lifecycle_hook: Callable[[str], None] | None = None


@dataclass(frozen=True)
class _NormalizedGraph:
    root_payloads: Mapping[str, bytes]
    blob_names: tuple[str, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IntakeContractError(message)


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as error:
        raise IntakeContractError("offline image intake value is not canonical JSON") from error


def canonical_line(value: object) -> bytes:
    return _canonical_json(value) + b"\n"


def _identity(domain: bytes, core: Mapping[str, object]) -> str:
    return hashlib.sha256(domain + canonical_line(core)).hexdigest()


def _durable_operation_namespace_id(daemon_id: str) -> str:
    _require(type(daemon_id) is str and daemon_id, "Docker daemon ID is invalid")
    return "target-" + _identity(
        _DURABLE_NAMESPACE_DOMAIN,
        {"daemon_id": daemon_id, "image_id": TENSORRT_IMAGE_ID},
    )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IntakeContractError(f"{label} must be an object")
    return value


def _sha(value: object, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None, f"{label} is not a lowercase SHA-256")
    return value


def _image_id(value: object, label: str) -> str:
    _require(type(value) is str and _IMAGE_ID_RE.fullmatch(value) is not None, f"{label} is not an immutable image ID")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntakeContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(payload: bytes, label: str, *, maximum: int = _MAX_JSON_BYTES) -> Any:
    _require(0 < len(payload) <= maximum, f"{label} byte length is invalid")
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                IntakeContractError(f"invalid JSON constant: {item}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise IntakeContractError(f"{label} is invalid JSON") from error


def _safe_tar_name(name: str) -> str:
    _require(type(name) is str and 0 < len(name) <= 100, "archive member name is invalid")
    _require(not name.endswith("/"), "archive member name has a trailing slash")
    _require("\\" not in name and all(0x20 <= ord(character) < 0x7F for character in name), "archive member name contains unsafe characters")
    parsed = PurePosixPath(name)
    _require(
        not parsed.is_absolute()
        and bool(parsed.parts)
        and all(part not in {"", ".", ".."} for part in parsed.parts)
        and parsed.as_posix() == name,
        "archive member path is unsafe or noncanonical",
    )
    return parsed.as_posix()


def _read_member(archive: tarfile.TarFile, member: tarfile.TarInfo, label: str) -> bytes:
    _require(member.size <= _MAX_JSON_BYTES, f"{label} is too large")
    source = archive.extractfile(member)
    _require(source is not None, f"{label} payload is missing")
    payload = source.read(_MAX_JSON_BYTES + 1)
    _require(len(payload) == member.size and len(payload) <= _MAX_JSON_BYTES, f"{label} payload size drifted")
    return payload


def _hash_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    source = archive.extractfile(member)
    _require(source is not None, "archive blob payload is missing")
    digest = hashlib.sha256()
    observed = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            break
        observed += len(chunk)
        digest.update(chunk)
    _require(observed == member.size, "archive blob payload is partial")
    return digest.hexdigest()


def _descriptor(value: Any, label: str, *, media_types: set[str]) -> dict[str, object]:
    raw = dict(_mapping(value, label))
    _require(set(raw) == {"mediaType", "digest", "size"}, f"{label} fields drifted")
    _require(type(raw.get("mediaType")) is str and raw.get("mediaType") in media_types, f"{label} media type is unsupported")
    digest = raw.get("digest")
    size = raw.get("size")
    _image_id(digest, f"{label} digest")
    _require(type(size) is int and size >= 0, f"{label} size is invalid")
    return {"mediaType": raw["mediaType"], "digest": digest, "size": size}


def _layer_descriptor(value: Any, label: str) -> dict[str, object]:
    raw = dict(_mapping(value, label))
    allowed_fields = {"mediaType", "digest", "size"}
    if "annotations" in raw:
        allowed_fields.add("annotations")
        _require(
            type(raw["annotations"]) is dict
            and raw["annotations"]
            == {"buildkit/rewritten-timestamp": "0"},
            f"{label} annotations drifted",
        )
    _require(set(raw) == allowed_fields, f"{label} fields drifted")
    return _descriptor(
        {key: raw[key] for key in ("mediaType", "digest", "size")},
        label,
        media_types=_LAYER_MEDIA_TYPES,
    )


def _blob_path(digest: object) -> str:
    value = _image_id(digest, "OCI descriptor digest")
    return f"blobs/sha256/{value[7:]}"


def _layer_diff_id(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    media_type: str,
    *,
    remaining_uncompressed_budget: int = _MAX_UNCOMPRESSED_LAYER_BYTES,
) -> tuple[str, int]:
    _require(
        type(remaining_uncompressed_budget) is int
        and 0 <= remaining_uncompressed_budget <= _MAX_UNCOMPRESSED_LAYER_BYTES,
        "remaining uncompressed layer budget is invalid",
    )
    source = archive.extractfile(member)
    _require(source is not None, "OCI layer payload is missing")
    digest = hashlib.sha256()
    total = 0
    if media_type == "application/vnd.oci.image.layer.v1.tar":
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= remaining_uncompressed_budget, "uncompressed layer exceeds the remaining aggregate bound")
            digest.update(chunk)
    else:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            pending = chunk
            while pending:
                remaining = remaining_uncompressed_budget - total
                _require(remaining >= 0, "gzip layer expansion exceeds the bound")
                decoded = decoder.decompress(pending, min(1024 * 1024, remaining + 1))
                total += len(decoded)
                _require(total <= remaining_uncompressed_budget, "gzip layer expansion exceeds the remaining aggregate bound")
                digest.update(decoded)
                _require(not decoder.unused_data, "gzip layer contains trailing or concatenated data")
                pending = decoder.unconsumed_tail
                if not decoded and pending:
                    raise IntakeContractError("gzip layer expansion cannot make bounded progress")
        tail = decoder.flush(min(1024 * 1024, remaining_uncompressed_budget - total + 1))
        total += len(tail)
        _require(total <= remaining_uncompressed_budget, "gzip layer expansion exceeds the remaining aggregate bound")
        digest.update(tail)
        _require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, "gzip layer stream is incomplete")
    return "sha256:" + digest.hexdigest(), total


def _tar_octal(field: bytes, label: str) -> int:
    _require(
        len(field) >= 2
        and field[-1:] == b"\0"
        and all(0x30 <= value <= 0x37 for value in field[:-1]),
        f"{label} is not canonical zero-padded USTAR octal",
    )
    return int(field[:-1], 8)


def _tar_checksum(field: bytes) -> int:
    _require(
        len(field) == 8
        and field[6:8] == b"\0 "
        and all(0x30 <= value <= 0x37 for value in field[:6]),
        "raw USTAR checksum field is not canonical",
    )
    return int(field[:6], 8)


def _tar_text(field: bytes, label: str, *, allow_empty: bool = False) -> str:
    if b"\0" in field:
        value, padding = field.split(b"\0", 1)
        _require(not padding.strip(b"\0"), f"{label} has nonzero bytes after its terminator")
    else:
        value = field
    _require(allow_empty or bool(value), f"{label} is empty")
    _require(
        all(0x20 <= character < 0x7F for character in value),
        f"{label} is not printable ASCII",
    )
    return value.decode("ascii")


def _preflight_raw_ustar(descriptor: int) -> None:
    before = _fd_snapshot(descriptor)
    _require(
        stat.S_ISREG(before.mode)
        and 0 < before.size <= _MAX_ARCHIVE_BYTES
        and before.size % tarfile.BLOCKSIZE == 0,
        "offline archive raw USTAR file identity or alignment is invalid",
    )
    duplicate = os.dup(descriptor)
    source = os.fdopen(duplicate, "rb", closefd=True)
    try:
        offset = 0
        members = 0
        logical_names: set[str] = set()
        while offset + tarfile.BLOCKSIZE <= before.size:
            source.seek(offset)
            header = source.read(tarfile.BLOCKSIZE)
            _require(len(header) == tarfile.BLOCKSIZE, "raw USTAR header is truncated")
            if header == b"\0" * tarfile.BLOCKSIZE:
                trailing_size = before.size - offset
                _require(
                    2 * tarfile.BLOCKSIZE <= trailing_size <= tarfile.RECORDSIZE,
                    "raw USTAR end-of-stream padding is noncanonical",
                )
                trailing = header + source.read(trailing_size - tarfile.BLOCKSIZE)
                _require(
                    len(trailing) == trailing_size
                    and trailing == b"\0" * trailing_size,
                    "raw USTAR contains concatenated or nonzero trailing payload",
                )
                _require(members > 0, "raw USTAR contains no members")
                break

            members += 1
            _require(members <= _MAX_MEMBERS, "raw USTAR member count exceeds the bound")
            _require(
                header[257:263] == b"ustar\0"
                and header[263:265] == b"00"
                and header[345:500] == b"\0" * 155
                and header[500:512] == b"\0" * 12,
                "raw archive is not the closed USTAR header profile",
            )
            stored_checksum = _tar_checksum(header[148:156])
            checksum_header = bytearray(header)
            checksum_header[148:156] = b" " * 8
            _require(
                stored_checksum == sum(checksum_header),
                "raw USTAR header checksum drifted",
            )
            type_flag = header[156:157]
            _require(
                type_flag in {b"\0", b"0", b"5"},
                "raw USTAR contains an extended, sparse, linked, or unsupported member type",
            )
            _require(
                header[157:257] == b"\0" * 100,
                "raw USTAR member contains a link target",
            )
            raw_name = _tar_text(header[0:100], "raw USTAR member name")
            name = raw_name[:-1] if type_flag == b"5" and raw_name.endswith("/") else raw_name
            logical_name = _safe_tar_name(name)
            _require(
                logical_name not in logical_names,
                "raw USTAR contains duplicate logical member names",
            )
            logical_names.add(logical_name)
            for field, label in (
                (header[100:108], "raw USTAR mode"),
                (header[108:116], "raw USTAR uid"),
                (header[116:124], "raw USTAR gid"),
                (header[136:148], "raw USTAR mtime"),
            ):
                _tar_octal(field, label)
            _tar_text(header[265:297], "raw USTAR uname", allow_empty=True)
            _tar_text(header[297:329], "raw USTAR gname", allow_empty=True)
            _require(
                header[329:337] == b"\0" * 8
                and header[337:345] == b"\0" * 8,
                "raw USTAR regular/directory member has nonzero device fields",
            )
            size = _tar_octal(header[124:136], "raw USTAR member size")
            _require(size <= _MAX_ARCHIVE_BYTES, "raw USTAR member size exceeds the bound")
            if type_flag == b"5":
                _require(size == 0, "raw USTAR directory has a payload")
            padded_size = ((size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE
            next_offset = offset + tarfile.BLOCKSIZE + padded_size
            _require(
                next_offset > offset and next_offset <= before.size,
                "raw USTAR member payload exceeds the held archive",
            )
            padding_size = padded_size - size
            if padding_size:
                source.seek(offset + tarfile.BLOCKSIZE + size)
                padding = source.read(padding_size)
                _require(
                    len(padding) == padding_size and padding == b"\0" * padding_size,
                    "raw USTAR member payload padding is noncanonical",
                )
            offset = next_offset
        else:
            raise IntakeContractError("raw USTAR end-of-stream blocks are missing")
    finally:
        source.close()
    _require(
        _fd_snapshot(descriptor) == before,
        "held archive metadata drifted during raw USTAR preflight",
    )


def _parse_docker_save_hybrid(
    descriptor: int,
    *,
    expected_image_id: str,
    expected_entrypoint: str,
    expected_labels: Mapping[str, str],
) -> tuple[dict[str, object], _NormalizedGraph]:
    _image_id(expected_image_id, "expected image ID")
    _preflight_raw_ustar(descriptor)
    duplicate = os.dup(descriptor)
    source_file = os.fdopen(duplicate, "rb", closefd=True)
    try:
        source_file.seek(0)
        with tarfile.open(fileobj=source_file, mode="r:") as archive:
            _require(not archive.pax_headers, "archive contains global PAX metadata")
            members: dict[str, tarfile.TarInfo] = {}
            directories: set[str] = set()
            blob_hashes: dict[str, str] = {}
            for member in archive:
                _require(len(members) + len(directories) < _MAX_MEMBERS, "archive member count exceeds the bound")
                _require(
                    member.offset_data == member.offset + tarfile.BLOCKSIZE,
                    "archive contains a GNU long-name, PAX, or other extended header",
                )
                raw_name = member.name
                if member.isdir():
                    _require(raw_name in {"blobs", "blobs/", "blobs/sha256", "blobs/sha256/"}, "archive directory name is noncanonical")
                    raw_name = raw_name[:-1] if raw_name.endswith("/") else raw_name
                name = _safe_tar_name(raw_name)
                _require(name not in members and name not in directories, "archive contains duplicate members")
                _require(not member.pax_headers and not member.sparse, "archive contains extended or sparse metadata")
                if member.isdir():
                    _require(name in {"blobs", "blobs/sha256"}, "archive contains an unexpected directory")
                    _require(member.size == 0, "archive directory has a payload")
                    directories.add(name)
                    continue
                _require(member.isreg(), "archive contains a link, device, FIFO, or unsupported member")
                members[name] = member
                match = _BLOB_PATH_RE.fullmatch(name)
                if match is not None:
                    actual = _hash_member(archive, member)
                    _require(actual == match.group(1), "content-addressed archive blob SHA-256 drifted")
                    blob_hashes[name] = actual
            logical_end = archive.offset
            source_file.seek(0, os.SEEK_END)
            archive_size = source_file.tell()
            trailing_size = archive_size - logical_end
            _require(
                logical_end >= 0
                and logical_end % tarfile.BLOCKSIZE == 0
                and 2 * tarfile.BLOCKSIZE <= trailing_size <= tarfile.RECORDSIZE
                and archive_size % tarfile.BLOCKSIZE == 0,
                "archive end-of-stream framing is noncanonical",
            )
            source_file.seek(logical_end)
            trailing = source_file.read(trailing_size)
            _require(
                len(trailing) == trailing_size and trailing == b"\0" * trailing_size,
                "archive contains concatenated or nonzero trailing payload",
            )
            root_names = {"oci-layout", "index.json", "manifest.json", "repositories"}
            _require(root_names <= set(members), "Docker-save hybrid metadata is incomplete")
            _require(
                all(name in root_names or _BLOB_PATH_RE.fullmatch(name) is not None for name in members),
                "archive contains an unexpected file",
            )
            layout = _parse_json(_read_member(archive, members["oci-layout"], "oci-layout"), "oci-layout")
            _require(layout == {"imageLayoutVersion": "1.0.0"}, "oci-layout contract drifted")
            repositories = _parse_json(_read_member(archive, members["repositories"], "repositories"), "repositories")
            _require(repositories == {}, "Docker-save repositories must be empty and tagless")
            index = _mapping(_parse_json(_read_member(archive, members["index.json"], "index.json"), "index.json"), "OCI index")
            allowed_index_fields = {"schemaVersion", "manifests"}
            if "mediaType" in index:
                allowed_index_fields.add("mediaType")
                _require(index.get("mediaType") == _OCI_INDEX_MEDIA_TYPE, "OCI index media type drifted")
            _require(
                set(index) == allowed_index_fields
                and type(index.get("schemaVersion")) is int
                and index.get("schemaVersion") == 2,
                "OCI index fields drifted",
            )
            descriptors = index.get("manifests")
            _require(type(descriptors) is list and len(descriptors) == 1, "OCI index must contain exactly one manifest")
            index_descriptor = dict(_mapping(descriptors[0], "OCI index manifest descriptor"))
            allowed_descriptor_fields = {"mediaType", "digest", "size", "platform"}
            if "annotations" in index_descriptor:
                allowed_descriptor_fields.add("annotations")
                annotations = dict(_mapping(index_descriptor["annotations"], "OCI index annotations"))
                _require(
                    set(annotations) <= {"io.containerd.image.name", "org.opencontainers.image.ref.name"}
                    and all(
                        type(key) is str
                        and type(value) is str
                        and value in {expected_image_id, expected_image_id[7:]}
                        for key, value in annotations.items()
                    ),
                    "OCI index contains tag or unknown annotations",
                )
            _require(set(index_descriptor) == allowed_descriptor_fields, "OCI index descriptor fields drifted")
            _require(index_descriptor.get("platform") == {"architecture": "amd64", "os": "linux"}, "OCI index platform drifted")
            normalized_index_descriptor = _descriptor(
                {key: index_descriptor[key] for key in ("mediaType", "digest", "size")},
                "OCI index manifest descriptor",
                media_types=_OCI_MANIFEST_MEDIA_TYPES,
            )
            _require(
                normalized_index_descriptor["digest"] == expected_image_id,
                "OCI manifest digest differs from the frozen image ID",
            )
            manifest_path = _blob_path(normalized_index_descriptor["digest"])
            _require(manifest_path in members, "OCI manifest blob is missing")
            manifest_member = members[manifest_path]
            _require(manifest_member.size == normalized_index_descriptor["size"], "OCI manifest blob size drifted")
            manifest_payload = _read_member(archive, manifest_member, "OCI manifest blob")
            manifest = dict(_mapping(_parse_json(manifest_payload, "OCI manifest blob"), "OCI manifest"))
            _require(
                set(manifest) == {"schemaVersion", "mediaType", "config", "layers"}
                and type(manifest.get("schemaVersion")) is int
                and manifest.get("schemaVersion") == 2
                and type(manifest.get("mediaType")) is str
                and manifest.get("mediaType") in _OCI_MANIFEST_MEDIA_TYPES,
                "OCI manifest fields drifted",
            )
            _require(
                manifest.get("mediaType") == normalized_index_descriptor["mediaType"],
                "OCI index and manifest media types differ",
            )
            config_descriptor = _descriptor(
                manifest.get("config"),
                "OCI config descriptor",
                media_types=_CONFIG_MEDIA_TYPES,
            )
            config_path = _blob_path(config_descriptor["digest"])
            _require(config_path in members, "OCI config blob is missing")
            config_member = members[config_path]
            _require(config_member.size == config_descriptor["size"], "OCI config blob size drifted")
            config_payload = _read_member(archive, config_member, "OCI config blob")
            _require(
                hashlib.sha256(config_payload).hexdigest()
                == str(config_descriptor["digest"])[7:],
                "raw OCI config SHA-256 differs from its descriptor digest",
            )
            config = dict(_mapping(_parse_json(config_payload, "OCI config blob"), "OCI image config"))
            image_config = _mapping(config.get("config"), "OCI image runtime config")
            labels = _mapping(image_config.get("Labels"), "OCI image labels")
            _require(
                config.get("architecture") == "amd64"
                and config.get("os") == "linux"
                and image_config.get("Entrypoint") == [expected_entrypoint]
                and all(labels.get(key) == value for key, value in expected_labels.items()),
                "OCI image config platform, entrypoint, or labels drifted",
            )
            layers_raw = manifest.get("layers")
            _require(type(layers_raw) is list and bool(layers_raw), "OCI manifest layers are missing")
            layers = [
                _layer_descriptor(value, f"OCI layer descriptor {index}")
                for index, value in enumerate(layers_raw)
            ]
            layer_paths = [_blob_path(layer["digest"]) for layer in layers]
            _require(len(set(layer_paths)) == len(layer_paths), "OCI manifest repeats a layer blob")
            rootfs = _mapping(config.get("rootfs"), "OCI config rootfs")
            diff_ids = rootfs.get("diff_ids")
            _require(
                set(rootfs) == {"type", "diff_ids"}
                and rootfs.get("type") == "layers"
                and type(diff_ids) is list
                and len(diff_ids) == len(layers),
                "OCI config rootfs diff-id coverage drifted",
            )
            total_uncompressed_layer_bytes = 0
            for index, (layer, path, diff_id) in enumerate(zip(layers, layer_paths, diff_ids, strict=True)):
                _image_id(diff_id, f"OCI layer {index} diff-id")
                _require(path in members, f"OCI layer {index} blob is missing")
                member = members[path]
                _require(member.size == layer["size"], f"OCI layer {index} blob size drifted")
                observed_diff_id, uncompressed_size = _layer_diff_id(
                    archive,
                    member,
                    str(layer["mediaType"]),
                    remaining_uncompressed_budget=(
                        _MAX_UNCOMPRESSED_LAYER_BYTES
                        - total_uncompressed_layer_bytes
                    ),
                )
                total_uncompressed_layer_bytes += uncompressed_size
                _require(
                    total_uncompressed_layer_bytes <= _MAX_UNCOMPRESSED_LAYER_BYTES,
                    "aggregate uncompressed layer bytes exceed the bound",
                )
                _require(observed_diff_id == diff_id, f"OCI layer {index} uncompressed diff-id drifted")
            legacy = _parse_json(_read_member(archive, members["manifest.json"], "Docker manifest.json"), "Docker manifest.json")
            _require(type(legacy) is list and len(legacy) == 1, "Docker manifest.json image count drifted")
            record = dict(_mapping(legacy[0], "Docker manifest.json record"))
            _require(set(record) == {"Config", "RepoTags", "Layers"}, "Docker manifest.json fields drifted")
            _require(record.get("RepoTags") in (None, []), "Docker-save archive contains a tag")
            _require(
                record.get("Config") == config_path
                and record.get("Layers") == layer_paths,
                "Docker legacy metadata does not cross-bind the OCI graph",
            )
            referenced = root_names | {manifest_path, config_path, *layer_paths}
            _require(set(members) == referenced, "archive contains an unreferenced or missing blob")
            normalized_index = {
                "schemaVersion": 2,
                "mediaType": _OCI_INDEX_MEDIA_TYPE,
                "manifests": [
                    {
                        **normalized_index_descriptor,
                        "platform": {"architecture": "amd64", "os": "linux"},
                    }
                ],
            }
            normalized_legacy = [{"Config": config_path, "RepoTags": None, "Layers": layer_paths}]
            root_payloads = {
                "oci-layout": _canonical_json({"imageLayoutVersion": "1.0.0"}),
                "index.json": _canonical_json(normalized_index),
                "manifest.json": _canonical_json(normalized_legacy),
                "repositories": b"{}",
            }
            inventory_core: dict[str, object] = {
                "format": "docker_save_oci_hybrid_v1",
                "outer_tar_profile": "closed_ustar_regular_directory_only_v1",
                "image_id": expected_image_id,
                "platform": {"os": "linux", "architecture": "amd64"},
                "repo_tags": [],
                "repo_digests": [],
                "manifest_digest": normalized_index_descriptor["digest"],
                "config_digest": config_descriptor["digest"],
                "layer_digests": [layer["digest"] for layer in layers],
                "layer_diff_ids": list(diff_ids),
                "layer_media_types": [layer["mediaType"] for layer in layers],
                "layer_count": len(layers),
                "uncompressed_layer_bytes": total_uncompressed_layer_bytes,
                "file_count": len(members),
                "normalized_members": [
                    {
                        "name": name,
                        "type": "directory",
                        "size_bytes": 0,
                        "mode": "0555",
                    }
                    for name in ("blobs", "blobs/sha256")
                ]
                + [
                    {
                        "name": name,
                        "type": "regular",
                        "size_bytes": len(root_payloads[name]),
                        "sha256": hashlib.sha256(root_payloads[name]).hexdigest(),
                        "mode": "0444",
                    }
                    for name in ("oci-layout", "index.json", "manifest.json", "repositories")
                ]
                + [
                    {
                        "name": name,
                        "type": "regular",
                        "size_bytes": members[name].size,
                        "sha256": name.rsplit("/", 1)[-1],
                        "mode": "0444",
                    }
                    for name in sorted({manifest_path, config_path, *layer_paths})
                ],
            }
            inventory = {
                **inventory_core,
                "inventory_sha256": _identity(_INVENTORY_DOMAIN, inventory_core),
            }
            return inventory, _NormalizedGraph(
                root_payloads=root_payloads,
                blob_names=tuple(sorted({manifest_path, config_path, *layer_paths})),
            )
    except (tarfile.TarError, OSError, EOFError, zlib.error, gzip.BadGzipFile, TypeError, KeyError, OverflowError) as error:
        raise IntakeContractError("Docker-save hybrid archive is corrupt or unreadable") from error
    finally:
        source_file.close()


def _validate_docker_save_hybrid(
    descriptor: int,
    *,
    expected_image_id: str = TENSORRT_IMAGE_ID,
    expected_entrypoint: str = TENSORRT_ENTRYPOINT,
    expected_labels: Mapping[str, str] = IMAGE_LABELS,
) -> dict[str, object]:
    inventory, _graph = _parse_docker_save_hybrid(
        descriptor,
        expected_image_id=expected_image_id,
        expected_entrypoint=expected_entrypoint,
        expected_labels=expected_labels,
    )
    return inventory


@dataclass(frozen=True)
class _FdSnapshot:
    device: int
    inode: int
    mode: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int


def _fd_snapshot(descriptor: int) -> _FdSnapshot:
    observed = os.fstat(descriptor)
    return _FdSnapshot(
        device=observed.st_dev,
        inode=observed.st_ino,
        mode=observed.st_mode,
        links=observed.st_nlink,
        size=observed.st_size,
        mtime_ns=observed.st_mtime_ns,
        ctime_ns=observed.st_ctime_ns,
    )


def _hash_fd(descriptor: int) -> FileIdentity:
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        return FileIdentity(total, digest.hexdigest())
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)


def _open_absolute_nofollow(path: Path) -> int:
    _require(os.name == "posix", "offline archive custody is supported only on POSIX")
    _require(path.is_absolute(), "offline archive path must be absolute")
    parts = PurePosixPath(str(path)).parts
    _require(parts and parts[0] == "/" and all(part not in {"", ".", ".."} for part in parts[1:]), "offline archive path is noncanonical")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in parts[1:-1]:
            next_directory = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            os.close(directory)
            directory = next_directory
        return os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
    except OSError as error:
        raise IntakeContractError("offline archive no-follow open failed") from error
    finally:
        os.close(directory)


def _copy_pinned_source(
    archive_path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
) -> tuple[Any, FileIdentity]:
    _require(type(expected_size_bytes) is int and 0 < expected_size_bytes <= _MAX_ARCHIVE_BYTES, "offline archive size pin is invalid")
    _sha(expected_sha256, "offline archive SHA-256 pin")
    source = _open_absolute_nofollow(archive_path)
    destination: Any | None = None
    try:
        before = _fd_snapshot(source)
        _require(stat.S_ISREG(before.mode) and before.links == 1, "offline archive must be one regular non-hardlinked file")
        _require(before.size == expected_size_bytes, "offline archive size differs from the caller pin")
        destination = tempfile.TemporaryFile(prefix="vast-offline-image-source-", mode="w+b")
        os.lseek(source, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= expected_size_bytes, "offline archive grew while copied")
            digest.update(chunk)
            destination.write(chunk)
        destination.flush()
        os.fsync(destination.fileno())
        after = _fd_snapshot(source)
        identity = FileIdentity(total, digest.hexdigest())
        _require(before == after and identity.size_bytes == expected_size_bytes and identity.sha256 == expected_sha256, "offline archive identity drifted during held copy")
        destination.seek(0)
        return destination, identity
    except BaseException:
        if destination is not None:
            destination.close()
        raise
    finally:
        os.close(source)


def _tar_info(name: str, size: int, *, directory: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name + ("/" if directory else ""))
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.size = 0 if directory else size
    info.mode = 0o555 if directory else 0o444
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def _normalize_archive(source_descriptor: int, graph: _NormalizedGraph) -> tuple[Any, FileIdentity]:
    _preflight_raw_ustar(source_descriptor)
    source_duplicate = os.dup(source_descriptor)
    source_file = os.fdopen(source_duplicate, "rb", closefd=True)
    destination: Any | None = None
    readonly: Any | None = None
    try:
        source_file.seek(0)
        with tarfile.open(fileobj=source_file, mode="r:") as source_archive:
            members = {member.name.rstrip("/"): member for member in source_archive.getmembers() if member.isreg()}
            destination = tempfile.TemporaryFile(prefix="vast-offline-image-normalized-", mode="w+b")
            with tarfile.open(fileobj=destination, mode="w", format=tarfile.USTAR_FORMAT) as normalized:
                for directory in ("blobs", "blobs/sha256"):
                    normalized.addfile(_tar_info(directory, 0, directory=True))
                for name in ("oci-layout", "index.json", "manifest.json", "repositories"):
                    payload = graph.root_payloads[name]
                    normalized.addfile(_tar_info(name, len(payload)), io.BytesIO(payload))
                for name in graph.blob_names:
                    member = members.get(name)
                    _require(member is not None, "verified archive blob disappeared during normalization")
                    payload = source_archive.extractfile(member)
                    _require(payload is not None, "verified archive blob cannot be reopened")
                    normalized.addfile(_tar_info(name, member.size), payload)
            destination.flush()
            os.fsync(destination.fileno())
            destination.seek(0)
            _preflight_raw_ustar(destination.fileno())
            identity = _hash_fd(destination.fileno())
            destination.seek(0)
            if os.name == "posix":
                writable_snapshot = _fd_snapshot(destination.fileno())
                readonly_descriptor = os.open(
                    f"/proc/self/fd/{destination.fileno()}",
                    os.O_RDONLY | os.O_CLOEXEC,
                )
                try:
                    readonly_snapshot = _fd_snapshot(readonly_descriptor)
                    _require(
                        (
                            readonly_snapshot.device,
                            readonly_snapshot.inode,
                            readonly_snapshot.mode,
                            readonly_snapshot.size,
                        )
                        == (
                            writable_snapshot.device,
                            writable_snapshot.inode,
                            writable_snapshot.mode,
                            writable_snapshot.size,
                        ),
                        "normalized read-only archive reopen changed file identity",
                    )
                    readonly = os.fdopen(readonly_descriptor, "rb", closefd=True)
                    readonly_descriptor = -1
                finally:
                    if readonly_descriptor >= 0:
                        os.close(readonly_descriptor)
                destination.close()
                destination = None
                _require(_hash_fd(readonly.fileno()) == identity, "normalized read-only archive identity drifted")
                result = readonly
                readonly = None
                return result, identity
            return destination, identity
    except BaseException:
        if destination is not None:
            destination.close()
        if readonly is not None:
            readonly.close()
        raise
    finally:
        source_file.close()


class _HeldArchiveSession:
    def __init__(
        self,
        source: Any,
        normalized: Any,
        *,
        identity: FileIdentity,
        normalized_identity: FileIdentity,
        inventory: Mapping[str, object],
    ) -> None:
        self._source = source
        self._normalized = normalized
        self.identity = identity
        self.normalized_identity = normalized_identity
        self.inventory = dict(inventory)
        descriptor = normalized.fileno()
        self.load_input = f"/proc/self/fd/{descriptor}"
        self.pass_fds = (descriptor,)

    def __enter__(self) -> "_HeldArchiveSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self._normalized.close()
        self._source.close()

    def revalidate(self) -> None:
        _require(_hash_fd(self._source.fileno()) == self.identity, "held caller archive copy drifted")
        _require(_hash_fd(self._normalized.fileno()) == self.normalized_identity, "held normalized archive drifted")


def _default_archive_opener(
    *,
    archive_path: Path,
    expected_size_bytes: int,
    expected_sha256: str,
    expected_image_id: str = TENSORRT_IMAGE_ID,
    expected_entrypoint: str = TENSORRT_ENTRYPOINT,
    expected_labels: Mapping[str, str] = IMAGE_LABELS,
) -> ArchiveSession:
    source, identity = _copy_pinned_source(
        archive_path,
        expected_size_bytes=expected_size_bytes,
        expected_sha256=expected_sha256,
    )
    try:
        inventory, graph = _parse_docker_save_hybrid(
            source.fileno(),
            expected_image_id=expected_image_id,
            expected_entrypoint=expected_entrypoint,
            expected_labels=expected_labels,
        )
        normalized, normalized_identity = _normalize_archive(source.fileno(), graph)
        return _HeldArchiveSession(
            source,
            normalized,
            identity=identity,
            normalized_identity=normalized_identity,
            inventory=inventory,
        )
    except BaseException:
        source.close()
        raise


class _BoundedCommandRunner:
    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
        pass_fds: tuple[int, ...] = (),
        executable_override: str | None = None,
    ) -> CommandCapture:
        _require(type(argv) is list and bool(argv) and all(type(token) is str and token and "\0" not in token for token in argv), "Docker argv is invalid")
        _require(
            executable_override is None
            or (
                type(executable_override) is str
                and bool(executable_override)
                and "\0" not in executable_override
            ),
            "Docker executable override is invalid",
        )
        _require(0 < timeout_seconds <= 600 and 0 <= stdout_limit <= 16 * 1024 * 1024 and 0 <= stderr_limit <= 16 * 1024 * 1024, "Docker capture bounds are invalid")
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        stdout = bytearray()
        stderr = bytearray()
        timed_out = False
        stdout_overflow = False
        stderr_overflow = False
        deadline = time.monotonic() + timeout_seconds
        try:
            process = subprocess.Popen(
                argv,
                executable=executable_override,
                shell=False,
                env={},
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=pass_fds,
                start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, (stdout, stdout_limit, "stdout"))
            selector.register(process.stderr, selectors.EVENT_READ, (stderr, stderr_limit, "stderr"))
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _mask in selector.select(min(remaining, 0.1)):
                    target, limit, label = key.data
                    chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    available = max(0, limit - len(target))
                    target.extend(chunk[:available])
                    if len(chunk) > available:
                        if label == "stdout":
                            stdout_overflow = True
                        else:
                            stderr_overflow = True
                if timed_out or stdout_overflow or stderr_overflow:
                    break
                if process.poll() is not None and not selector.get_map():
                    break
            if timed_out or stdout_overflow or stderr_overflow:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            returncode = process.wait(timeout=5)
            return CommandCapture(
                returncode,
                bytes(stdout),
                bytes(stderr),
                timed_out,
                stdout_overflow,
                stderr_overflow,
            )
        except BaseException:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    process.wait(timeout=5)
                except (subprocess.SubprocessError, OSError):
                    pass
            raise
        finally:
            selector.close()
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()


def _observe_file_identity(path: str) -> FileIdentity:
    descriptor = _open_absolute_nofollow(Path(path))
    try:
        before = _fd_snapshot(descriptor)
        _require(stat.S_ISREG(before.mode), "Docker CLI is not a regular file")
        identity = _hash_fd(descriptor)
        _require(_fd_snapshot(descriptor) == before, "Docker CLI drifted during observation")
        return identity
    finally:
        os.close(descriptor)


class _InjectedDockerCliSession:
    def __init__(self, identity: FileIdentity) -> None:
        self.identity = identity
        self.executable = DOCKER_CLI
        self.pass_fds: tuple[int, ...] = ()

    def __enter__(self) -> "_InjectedDockerCliSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def revalidate(self) -> None:
        return None


class _HeldDockerCliSession:
    def __init__(self, descriptor: int, snapshot: _FdSnapshot, identity: FileIdentity) -> None:
        self._descriptor = descriptor
        self._snapshot = snapshot
        self.identity = identity
        self.executable = f"/proc/self/fd/{descriptor}"
        self.pass_fds = (descriptor,)

    def __enter__(self) -> "_HeldDockerCliSession":
        return self

    def __exit__(self, *_args: object) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1

    def revalidate(self) -> None:
        _require(self._descriptor >= 0, "held Docker CLI descriptor is closed")
        _require(_fd_snapshot(self._descriptor) == self._snapshot, "held Docker CLI file metadata drifted")
        _require(_hash_fd(self._descriptor) == self.identity, "held Docker CLI bytes drifted")


def _open_held_docker_cli() -> DockerCliSession:
    descriptor = _open_absolute_nofollow(Path(DOCKER_CLI))
    try:
        snapshot = _fd_snapshot(descriptor)
        _require(
            stat.S_ISREG(snapshot.mode)
            and snapshot.links == 1
            and os.fstat(descriptor).st_uid == 0
            and stat.S_IMODE(snapshot.mode) & 0o111 != 0
            and stat.S_IMODE(snapshot.mode) & 0o022 == 0,
            "Docker CLI ownership, mode, link, or executable custody failed",
        )
        identity = _hash_fd(descriptor)
        _require(_fd_snapshot(descriptor) == snapshot, "Docker CLI drifted during held observation")
        return _HeldDockerCliSession(descriptor, snapshot, identity)
    except BaseException:
        os.close(descriptor)
        raise


def _coerce_docker_cli_session(value: FileIdentity | DockerCliSession) -> DockerCliSession:
    if isinstance(value, FileIdentity):
        return _InjectedDockerCliSession(value)
    _require(
        isinstance(getattr(value, "identity", None), FileIdentity)
        and type(getattr(value, "executable", None)) is str
        and bool(getattr(value, "executable", ""))
        and "\0" not in getattr(value, "executable", "")
        and type(getattr(value, "pass_fds", None)) is tuple
        and all(type(descriptor) is int and descriptor >= 0 for descriptor in getattr(value, "pass_fds", ())),
        "held Docker CLI session contract is invalid",
    )
    return value


def _merge_pass_fds(*groups: tuple[int, ...]) -> tuple[int, ...]:
    result: list[int] = []
    for group in groups:
        for descriptor in group:
            if descriptor not in result:
                result.append(descriptor)
    return tuple(result)


class _DaemonLock:
    def __init__(self, daemon_id: str) -> None:
        self._address = b"\0vast-offline-image-intake-" + hashlib.sha256(
            daemon_id.encode("utf-8")
        ).hexdigest().encode("ascii")
        self._socket: socket.socket | None = None

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return () if self._socket is None else (self._socket.fileno(),)

    def __enter__(self) -> "_DaemonLock":
        _require(sys.platform.startswith("linux"), "global Docker daemon lease requires Linux abstract Unix sockets")
        lease = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            try:
                lease.bind(self._address)
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    raise IntakeContractError("another offline intake holds the exact daemon lease") from error
                raise
            lease.set_inheritable(False)
            self._socket = lease
            return self
        except BaseException:
            lease.close()
            raise

    def __exit__(self, *_args: object) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def _default_local_runtime_guard(environment: Mapping[str, str]) -> None:
    _require(os.name == "posix" and sys.platform.startswith("linux"), "offline image intake is WSL/POSIX-only")
    for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        _require(name not in environment, f"Docker environment override is forbidden: {name}")
    socket_path = Path("/var/run/docker.sock")
    try:
        observed = socket_path.lstat()
    except OSError as error:
        raise IntakeContractError("local Docker Unix socket is unavailable") from error
    _require(stat.S_ISSOCK(observed.st_mode), "Docker endpoint is not the exact local Unix socket")


def _docker_prefix(docker_cli: DockerCliSession) -> list[str]:
    return [DOCKER_CLI, DOCKER_HOST_FLAG, DOCKER_HOST_VALUE]


def _run_exact_read(
    runner: CommandRunner,
    docker_cli: DockerCliSession,
    tail: Sequence[str],
    *,
    timeout_seconds: float = 15,
    stdout_limit: int = 4 * 1024 * 1024,
) -> bytes:
    capture = runner.run(
        _docker_prefix(docker_cli) + list(tail),
        timeout_seconds=timeout_seconds,
        stdout_limit=stdout_limit,
        stderr_limit=64 * 1024,
        pass_fds=docker_cli.pass_fds,
        executable_override=docker_cli.executable,
    )
    _require(
        capture.returncode == 0
        and not capture.timed_out
        and not capture.stdout_overflow
        and not capture.stderr_overflow
        and capture.stderr == b"",
        "read-only Docker observation failed",
    )
    return capture.stdout


def _observe_daemon(
    runner: CommandRunner,
    docker_cli: DockerCliSession,
    *,
    expected_daemon_id: str,
    expected_server_version: str,
    expected_api_version: str,
) -> dict[str, str]:
    info = dict(_mapping(_parse_json(_run_exact_read(runner, docker_cli, ["info", "--format", "{{json .}}"]), "Docker daemon info"), "Docker daemon info"))
    version = dict(_mapping(_parse_json(_run_exact_read(runner, docker_cli, ["version", "--format", "{{json .Server}}"]), "Docker server version"), "Docker server version"))
    _require(
        type(info.get("ID")) is str
        and info.get("ID") == expected_daemon_id
        and info.get("ServerVersion") == expected_server_version
        and info.get("OSType") == "linux"
        and info.get("Architecture") in {"x86_64", "amd64"},
        "Docker daemon identity or platform pin drifted",
    )
    _require(
        info.get("Driver") == "overlayfs"
        and info.get("DriverStatus")
        == [["driver-type", "io.containerd.snapshotter.v1"]],
        "Docker daemon is not using the exact containerd snapshotter image store",
    )
    _require(
        version.get("Version") == expected_server_version
        and version.get("ApiVersion") == expected_api_version
        and version.get("Os") == "linux"
        and version.get("Arch") == "amd64",
        "Docker server version/API pin drifted",
    )
    return {
        "daemon_id": expected_daemon_id,
        "server_version": expected_server_version,
        "api_version": expected_api_version,
        "os": "linux",
        "architecture": "amd64",
        "storage_driver": "overlayfs",
        "image_store_driver_type": "io.containerd.snapshotter.v1",
    }


def _ascii_lines(payload: bytes, label: str) -> list[str]:
    try:
        text = payload.decode("ascii")
    except UnicodeError as error:
        raise IntakeContractError(f"{label} is not ASCII") from error
    if not text:
        return []
    _require(text.endswith("\n") and "\r" not in text, f"{label} framing drifted")
    lines = text[:-1].split("\n")
    _require(all(lines), f"{label} contains an empty record")
    return lines


def _string_list_or_null(value: object, label: str) -> list[str]:
    if value is None:
        return []
    _require(
        type(value) is list
        and len(value) <= _MAX_IMAGE_REFERENCES
        and all(
            type(item) is str
            and item
            and len(item.encode("utf-8")) <= _MAX_IMAGE_REFERENCE_BYTES
            for item in value
        ),
        f"{label} is invalid or exceeds its bound",
    )
    result = sorted(value)
    _require(len(result) == len(set(result)), f"{label} contains duplicates")
    return result


def _inspect_image(runner: CommandRunner, docker_cli: DockerCliSession, image_id: str) -> dict[str, object]:
    _image_id(image_id, "daemon image ID")
    document = dict(_mapping(
        _parse_json(
            _run_exact_read(runner, docker_cli, ["image", "inspect", "--format", "{{json .}}", image_id]),
            f"Docker inspect {image_id}",
        ),
        "Docker image inspect",
    ))
    _require(document.get("Id") == image_id, "Docker inspect returned a different immutable image ID")
    return document


def _image_projection(document: Mapping[str, object]) -> dict[str, object]:
    image_id = _image_id(document.get("Id"), "Docker inspect image ID")
    return {
        "image_id": image_id,
        "repo_tags": _string_list_or_null(document.get("RepoTags"), "Docker RepoTags"),
        "repo_digests": _string_list_or_null(document.get("RepoDigests"), "Docker RepoDigests"),
    }


def _validate_target_document(document: Mapping[str, object]) -> dict[str, object]:
    projection = _image_projection(document)
    _require(projection["image_id"] == TENSORRT_IMAGE_ID, "loaded image ID differs from the frozen TensorRT image")
    _require(projection["repo_tags"] == [] and projection["repo_digests"] == [], "offline image must remain tagless")
    config = _mapping(document.get("Config"), "loaded image Config")
    labels = _mapping(config.get("Labels"), "loaded image labels")
    _require(
        document.get("Os") == "linux"
        and document.get("Architecture") == "amd64"
        and config.get("Entrypoint") == [TENSORRT_ENTRYPOINT]
        and all(labels.get(key) == value for key, value in IMAGE_LABELS.items()),
        "loaded image inspect contract drifted",
    )
    return projection


def _catalog(runner: CommandRunner, docker_cli: DockerCliSession) -> dict[str, object]:
    raw_ids = _ascii_lines(
        _run_exact_read(runner, docker_cli, ["image", "ls", "--all", "--no-trunc", "--quiet"]),
        "Docker image ID inventory",
    )
    for image_id in raw_ids:
        _image_id(image_id, "Docker image inventory ID")
    image_ids = sorted(set(raw_ids))
    _require(
        len(raw_ids) <= _MAX_DAEMON_IMAGES * _MAX_IMAGE_REFERENCES
        and len(image_ids) <= _MAX_DAEMON_IMAGES,
        "Docker image inventory exceeds the exact bound",
    )
    projections = [_image_projection(_inspect_image(runner, docker_cli, image_id)) for image_id in image_ids]
    container_ids = _ascii_lines(
        _run_exact_read(runner, docker_cli, ["container", "ls", "--all", "--no-trunc", "--quiet"]),
        "Docker container ID inventory",
    )
    _require(all(_CONTAINER_ID_RE.fullmatch(item) is not None for item in container_ids), "Docker container inventory contains an invalid ID")
    _require(
        len(container_ids) <= _MAX_DAEMON_CONTAINERS
        and len(container_ids) == len(set(container_ids)),
        "Docker container inventory is duplicate or exceeds the exact bound",
    )
    core: dict[str, object] = {
        "images": projections,
        "container_ids": sorted(container_ids),
    }
    _require(len(canonical_line(core)) <= _MAX_CATALOG_JSON_BYTES, "Docker daemon catalog exceeds its canonical byte bound")
    return {**core, "catalog_sha256": _identity(_CATALOG_DOMAIN, core)}


def _stable_catalog(runner: CommandRunner, docker_cli: DockerCliSession) -> dict[str, object]:
    first = _catalog(runner, docker_cli)
    second = _catalog(runner, docker_cli)
    _require(first == second, "Docker daemon catalog changed during the bounded observation")
    return second


def _catalog_images(catalog: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    images = catalog.get("images")
    _require(type(images) is list, "daemon catalog image projection is invalid")
    result: dict[str, Mapping[str, object]] = {}
    for value in images:
        projection = _mapping(value, "daemon catalog image")
        image_id = _image_id(projection.get("image_id"), "daemon catalog image ID")
        _require(set(projection) == {"image_id", "repo_tags", "repo_digests"} and image_id not in result, "daemon catalog image projection drifted")
        _require(
            projection.get("repo_tags") == _string_list_or_null(projection.get("repo_tags"), "daemon catalog RepoTags")
            and projection.get("repo_digests") == _string_list_or_null(projection.get("repo_digests"), "daemon catalog RepoDigests"),
            "daemon catalog image tag/digest projection is not canonical",
        )
        result[image_id] = projection
    return result


def _validate_catalog(catalog: Mapping[str, object]) -> None:
    _require(set(catalog) == {"images", "container_ids", "catalog_sha256"}, "daemon catalog fields drifted")
    images = _catalog_images(catalog)
    container_ids = catalog.get("container_ids")
    _require(type(container_ids) is list and container_ids == sorted(container_ids) and len(container_ids) == len(set(container_ids)), "daemon catalog container IDs drifted")
    _require(all(type(item) is str and _CONTAINER_ID_RE.fullmatch(item) is not None for item in container_ids), "daemon catalog container ID is invalid")
    core = {"images": list(catalog["images"]), "container_ids": list(container_ids)}
    _require(catalog.get("catalog_sha256") == _identity(_CATALOG_DOMAIN, core), "daemon catalog self-hash drifted")
    _require(list(images) == sorted(images), "daemon catalog images are not sorted")


def _catalog_is_exact_post_delta(baseline: Mapping[str, object], current: Mapping[str, object]) -> bool:
    _validate_catalog(baseline)
    _validate_catalog(current)
    if baseline.get("container_ids") != current.get("container_ids"):
        return False
    before = _catalog_images(baseline)
    after = _catalog_images(current)
    if TENSORRT_IMAGE_ID in before or set(after) != set(before) | {TENSORRT_IMAGE_ID}:
        return False
    if any(after[image_id] != projection for image_id, projection in before.items()):
        return False
    target = after[TENSORRT_IMAGE_ID]
    return target.get("repo_tags") == [] and target.get("repo_digests") == []


def _project_exact_post_catalog(baseline: Mapping[str, object]) -> dict[str, object]:
    _validate_catalog(baseline)
    images = [dict(_mapping(item, "baseline image projection")) for item in baseline["images"]]
    _require(TENSORRT_IMAGE_ID not in {item["image_id"] for item in images}, "baseline already contains the target image")
    images.append(
        {
            "image_id": TENSORRT_IMAGE_ID,
            "repo_tags": [],
            "repo_digests": [],
        }
    )
    images.sort(key=lambda item: str(item["image_id"]))
    core: dict[str, object] = {
        "images": images,
        "container_ids": list(baseline["container_ids"]),
    }
    _require(len(canonical_line(core)) <= _MAX_CATALOG_JSON_BYTES, "projected post-load catalog exceeds its bound")
    return {**core, "catalog_sha256": _identity(_CATALOG_DOMAIN, core)}


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(path: Path) -> None:
    if path.exists():
        observed = path.lstat()
        _require(stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode), "offline intake output directory custody failed")
        return
    parent = path.parent
    _require(parent != path, "offline intake output root is invalid")
    _ensure_directory(parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    observed = path.lstat()
    _require(stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode), "offline intake output directory was replaced")
    _fsync_directory(parent)


def _validate_existing_output_chain(project_root: Path, output: Path) -> None:
    current = project_root
    _require(output.is_relative_to(project_root), "offline intake output escapes the project root")
    for component in output.relative_to(project_root).parts:
        current = current / component
        try:
            observed = current.lstat()
        except FileNotFoundError:
            return
        _require(
            stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode),
            "offline intake output namespace contains a non-directory or link",
        )


def _atomic_publish_no_replace(source: Path, target: Path) -> None:
    _require(source.parent == target.parent or os.name == "posix", "cross-directory atomic publication is unsupported on this platform")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file_ex.restype = ctypes.c_int
        if not move_file_ex(str(source), str(target), 0):
            code = ctypes.get_last_error()
            if code in (80, 183):
                raise IntakeContractError("offline intake durable target already exists")
            raise IntakeContractError(f"atomic no-replace publication failed with Win32 error {code}")
        return
    _require(sys.platform.startswith("linux"), "atomic no-replace publication is unsupported")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    _require(renameat2 is not None, "renameat2 no-replace publication is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise IntakeContractError("offline intake durable target already exists")
        raise IntakeContractError(f"atomic no-replace publication failed with errno {code}")


def _write_create_new(path: Path, value: Mapping[str, object]) -> None:
    payload = canonical_line(value)
    _require(len(payload) <= _MAX_JSON_BYTES, "offline intake durable artifact exceeds the read bound")
    parent = path.parent
    temporary = parent / f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    published = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "durable intake artifact write stalled")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        _atomic_publish_no_replace(temporary, path)
        published = True
        _fsync_directory(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
            _fsync_directory(parent)
        except FileNotFoundError:
            pass
        if published:
            observed = path.lstat()
            _require(
                stat.S_ISREG(observed.st_mode)
                and not stat.S_ISLNK(observed.st_mode)
                and observed.st_nlink == 1
                and observed.st_size == len(payload),
                "durable intake artifact identity drifted after create-new",
            )


def _create_fenced_output(output: Path, fence: Mapping[str, object]) -> None:
    parent = output.parent
    _ensure_directory(parent)
    temporary = parent / f".{output.name}.{secrets.token_hex(16)}.pending"
    temporary.mkdir(mode=0o700)
    published = False
    try:
        _write_create_new(temporary / FENCE_NAME, fence)
        _fsync_directory(temporary)
        _atomic_publish_no_replace(temporary, output)
        published = True
        _fsync_directory(parent)
    finally:
        if not published:
            try:
                (temporary / FENCE_NAME).unlink()
            except FileNotFoundError:
                pass
            try:
                temporary.rmdir()
            except FileNotFoundError:
                pass
        if published:
            observed = output.lstat()
            _require(
                stat.S_ISDIR(observed.st_mode) and not stat.S_ISLNK(observed.st_mode),
                "durable fenced output directory identity drifted",
            )


def _read_artifact(path: Path, *, domain: bytes, hash_field: str) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise IntakeContractError("offline intake artifact cannot be opened no-follow") from error
    try:
        before = _fd_snapshot(descriptor)
        _require(stat.S_ISREG(before.mode) and before.links == 1 and 0 < before.size <= _MAX_JSON_BYTES, "offline intake artifact file identity is invalid")
        payload = b""
        while len(payload) <= _MAX_JSON_BYTES:
            chunk = os.read(descriptor, min(1024 * 1024, _MAX_JSON_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload += chunk
        after = _fd_snapshot(descriptor)
        _require(
            (
                after.device,
                after.inode,
                after.mode,
                after.links,
                after.size,
            )
            == (
                before.device,
                before.inode,
                before.mode,
                before.links,
                before.size,
            )
            and len(payload) == before.size,
            "offline intake artifact drifted while read",
        )
    finally:
        os.close(descriptor)
    parsed = dict(_mapping(_parse_json(payload, path.name), path.name))
    _require(payload == canonical_line(parsed), "offline intake artifact is not canonical")
    sealed = parsed.pop(hash_field, None)
    _require(type(sealed) is str and sealed == _identity(domain, parsed), "offline intake artifact self-hash drifted")
    parsed[hash_field] = sealed
    return parsed


def _snapshot_from_stat(observed: os.stat_result) -> _FdSnapshot:
    return _FdSnapshot(
        device=observed.st_dev,
        inode=observed.st_ino,
        mode=observed.st_mode,
        links=observed.st_nlink,
        size=observed.st_size,
        mtime_ns=observed.st_mtime_ns,
        ctime_ns=observed.st_ctime_ns,
    )


def _open_absolute_directory_nofollow(path: Path) -> int:
    _require(os.name == "posix" and path.is_absolute(), "held output directory custody requires an absolute POSIX path")
    parts = PurePosixPath(str(path)).parts
    _require(parts and parts[0] == "/" and all(part not in {"", ".", ".."} for part in parts[1:]), "held output directory path is noncanonical")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in parts[1:]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _renameat2_noreplace(
    source_directory_fd: int,
    source_name: str,
    target_directory_fd: int,
    target_name: str,
) -> None:
    _require(sys.platform.startswith("linux"), "relative renameat2 no-replace is unavailable")
    _require(
        all(
            type(name) is str
            and name
            and "/" not in name
            and "\\" not in name
            and "\0" not in name
            for name in (source_name, target_name)
        ),
        "relative durable artifact name is invalid",
    )
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    _require(renameat2 is not None, "relative renameat2 no-replace is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    if renameat2(
        source_directory_fd,
        os.fsencode(source_name),
        target_directory_fd,
        os.fsencode(target_name),
        1,
    ) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise IntakeContractError("durable relative target already exists")
        raise IntakeContractError(f"relative renameat2 no-replace failed with errno {code}")


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        _require(written > 0, "durable intake artifact write stalled")
        view = view[written:]


def _write_private_file_at(directory_fd: int, name: str, payload: bytes) -> None:
    _require(len(payload) <= _MAX_JSON_BYTES, "offline intake durable artifact exceeds the read bound")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        observed = os.fstat(descriptor)
        _require(
            stat.S_ISREG(observed.st_mode)
            and observed.st_nlink == 1
            and observed.st_uid == os.getuid()
            and observed.st_size == len(payload),
            "private durable artifact identity drifted",
        )
    finally:
        os.close(descriptor)


def _read_artifact_at(
    directory_fd: int,
    name: str,
    *,
    domain: bytes,
    hash_field: str,
) -> dict[str, object]:
    entry_before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        before = os.fstat(descriptor)
        _require(
            _snapshot_from_stat(entry_before) == _snapshot_from_stat(before)
            and stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_uid == os.getuid()
            and 0 < before.st_size <= _MAX_JSON_BYTES,
            "held durable artifact file custody failed",
        )
        chunks: list[bytes] = []
        total = 0
        while total <= _MAX_JSON_BYTES:
            chunk = os.read(descriptor, min(1024 * 1024, _MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            chunks.append(chunk)
        after = os.fstat(descriptor)
        entry_after = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require(
            _snapshot_from_stat(before) == _snapshot_from_stat(after)
            and _snapshot_from_stat(after) == _snapshot_from_stat(entry_after)
            and total == before.st_size,
            "held durable artifact changed during same-handle read",
        )
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    parsed = dict(_mapping(_parse_json(payload, name), name))
    _require(payload == canonical_line(parsed), "held durable artifact is not canonical")
    sealed = parsed.pop(hash_field, None)
    _require(type(sealed) is str and sealed == _identity(domain, parsed), "held durable artifact self-hash drifted")
    parsed[hash_field] = sealed
    return parsed


@dataclass
class _HeldDirectoryNode:
    descriptor: int
    parent_descriptor: int | None
    name: str | None
    snapshot: _FdSnapshot
    uid: int
    gid: int


class _PathOutputNamespace:
    def __init__(self, project_root: Path, intake_id: str) -> None:
        self.output = project_root / "runs" / "nonpublication" / "offline_image_intake" / intake_id

    def __enter__(self) -> "_PathOutputNamespace":
        _validate_existing_output_chain(self.output.parents[3], self.output)
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @property
    def output_exists(self) -> bool:
        return self.output.exists()

    def fence_exists(self) -> bool:
        return _artifact_exists(self.output / FENCE_NAME) if self.output_exists else False

    def receipt_exists(self) -> bool:
        return _artifact_exists(self.output / RECEIPT_NAME) if self.output_exists else False

    def attempt_exists(self) -> bool:
        return _artifact_exists(self.output / ATTEMPT_NAME) if self.output_exists else False

    def read_fence(self) -> dict[str, object]:
        return _read_artifact(self.output / FENCE_NAME, domain=_FENCE_DOMAIN, hash_field="fence_sha256")

    def read_receipt(self) -> dict[str, object]:
        return _read_artifact(self.output / RECEIPT_NAME, domain=_RECEIPT_DOMAIN, hash_field="receipt_sha256")

    def read_attempt(self) -> dict[str, object]:
        return _read_artifact(self.output / ATTEMPT_NAME, domain=_ATTEMPT_DOMAIN, hash_field="attempt_sha256")

    def create_fence(self, fence: Mapping[str, object]) -> None:
        _create_fenced_output(self.output, fence)

    def create_receipt(self, receipt: Mapping[str, object]) -> None:
        _write_create_new(self.output / RECEIPT_NAME, receipt)

    def create_attempt(self, attempt: Mapping[str, object]) -> None:
        _write_create_new(self.output / ATTEMPT_NAME, attempt)

    def revalidate(self) -> None:
        _validate_existing_output_chain(self.output.parents[3], self.output)
        if self.output_exists:
            _require(
                {item.name for item in self.output.iterdir()}
                <= {FENCE_NAME, ATTEMPT_NAME, RECEIPT_NAME},
                "offline intake output contains an unexpected entry",
            )


class _PosixNamespaceOps:
    def open_project(self, path: Path) -> int:
        return _open_absolute_directory_nofollow(path)

    def fstat(self, descriptor: int) -> os.stat_result:
        return os.fstat(descriptor)

    def stat_at(self, directory_fd: int, name: str) -> os.stat_result:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)

    def open_directory_at(self, directory_fd: int, name: str) -> int:
        return os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )

    def close(self, descriptor: int) -> None:
        os.close(descriptor)

    def listdir(self, descriptor: int) -> list[str]:
        return os.listdir(descriptor)

    def mkdir_at(self, directory_fd: int, name: str, mode: int) -> None:
        os.mkdir(name, mode=mode, dir_fd=directory_fd)

    def fsync(self, descriptor: int) -> None:
        os.fsync(descriptor)

    def unlink_at(self, directory_fd: int, name: str) -> None:
        os.unlink(name, dir_fd=directory_fd)

    def rmdir_at(self, directory_fd: int, name: str) -> None:
        os.rmdir(name, dir_fd=directory_fd)

    def rename_noreplace(
        self,
        source_directory_fd: int,
        source_name: str,
        target_directory_fd: int,
        target_name: str,
    ) -> None:
        _renameat2_noreplace(
            source_directory_fd,
            source_name,
            target_directory_fd,
            target_name,
        )

    def write_private_file(self, directory_fd: int, name: str, payload: bytes) -> None:
        _write_private_file_at(directory_fd, name, payload)

    def read_artifact(
        self,
        directory_fd: int,
        name: str,
        *,
        domain: bytes,
        hash_field: str,
    ) -> dict[str, object]:
        return _read_artifact_at(
            directory_fd,
            name,
            domain=domain,
            hash_field=hash_field,
        )

    def current_uid(self) -> int:
        return os.getuid()


class _PosixOutputNamespace:
    _COMPONENTS = ("runs", "nonpublication", "offline_image_intake")

    def __init__(
        self,
        project_root: Path,
        intake_id: str,
        *,
        _ops: _PosixNamespaceOps | None = None,
        _components: tuple[str, ...] | None = None,
        _require_non_owner_writable: bool = False,
    ) -> None:
        self._project_root = project_root
        self._intake_id = intake_id
        self._ops = _ops or _PosixNamespaceOps()
        self._components = self._COMPONENTS if _components is None else _components
        _require(
            type(self._components) is tuple
            and bool(self._components)
            and len(self._components) <= 8
            and all(
                type(component) is str
                and component not in {".", ".."}
                and re.fullmatch(r"[a-z0-9._-]{1,96}", component) is not None
                for component in self._components
            ),
            "held output namespace components are invalid",
        )
        self._require_non_owner_writable = _require_non_owner_writable
        self._nodes: list[_HeldDirectoryNode] = []
        self._output_node: _HeldDirectoryNode | None = None
        self._missing_component_index: int | None = None

    def _node(self, descriptor: int, parent: int | None, name: str | None) -> _HeldDirectoryNode:
        observed = self._ops.fstat(descriptor)
        _require(
            stat.S_ISDIR(observed.st_mode)
            and observed.st_uid == self._ops.current_uid()
            and (
                not self._require_non_owner_writable
                or stat.S_IMODE(observed.st_mode) & 0o022 == 0
            ),
            "held output directory type, owner, or mode drifted",
        )
        return _HeldDirectoryNode(
            descriptor=descriptor,
            parent_descriptor=parent,
            name=name,
            snapshot=_snapshot_from_stat(observed),
            uid=observed.st_uid,
            gid=observed.st_gid,
        )

    def __enter__(self) -> "_PosixOutputNamespace":
        try:
            project_descriptor = self._ops.open_project(self._project_root)
            try:
                project_node = self._node(project_descriptor, None, None)
            except BaseException:
                try:
                    self._ops.close(project_descriptor)
                except OSError:
                    pass
                raise
            self._nodes.append(project_node)
            parent = project_descriptor
            for index, component in enumerate((*self._components, self._intake_id)):
                try:
                    entry = self._ops.stat_at(parent, component)
                except FileNotFoundError:
                    self._missing_component_index = index
                    break
                _require(stat.S_ISDIR(entry.st_mode), "held output namespace contains a link or non-directory")
                child = self._ops.open_directory_at(parent, component)
                try:
                    node = self._node(child, parent, component)
                    _require(node.snapshot == _snapshot_from_stat(entry), "held output directory entry identity drifted during open")
                except BaseException:
                    try:
                        self._ops.close(child)
                    except OSError:
                        pass
                    raise
                self._nodes.append(node)
                parent = child
            if len(self._nodes) == len(self._components) + 2:
                self._output_node = self._nodes[-1]
            self.revalidate()
            return self
        except BaseException:
            self._close_all()
            raise

    def __exit__(self, *_args: object) -> None:
        self._close_all()

    def _close_all(self) -> None:
        for node in reversed(self._nodes):
            try:
                self._ops.close(node.descriptor)
            except OSError:
                pass
        self._nodes.clear()
        self._output_node = None

    def _reopen_project_matches(self) -> None:
        reopened = self._ops.open_project(self._project_root)
        try:
            current = self._ops.fstat(reopened)
            project = self._nodes[0]
            _require(
                _snapshot_from_stat(current) == project.snapshot
                and current.st_uid == project.uid
                and current.st_gid == project.gid,
                "project root namespace identity drifted",
            )
        finally:
            self._ops.close(reopened)

    def revalidate(self) -> None:
        _require(bool(self._nodes), "held output namespace is closed")
        self._reopen_project_matches()
        for node in self._nodes:
            observed = self._ops.fstat(node.descriptor)
            _require(
                _snapshot_from_stat(observed) == node.snapshot
                and observed.st_uid == node.uid
                and observed.st_gid == node.gid,
                "held output directory metadata drifted",
            )
            if node.parent_descriptor is not None and node.name is not None:
                entry = self._ops.stat_at(node.parent_descriptor, node.name)
                _require(
                    _snapshot_from_stat(entry) == node.snapshot
                    and entry.st_uid == node.uid
                    and entry.st_gid == node.gid,
                    "held output parent/name binding drifted",
                )
        if self._output_node is not None:
            _require(
                set(self._ops.listdir(self._output_node.descriptor))
                <= {FENCE_NAME, ATTEMPT_NAME, RECEIPT_NAME},
                "held output directory contains an unexpected entry",
            )

    def _refresh_after_owned_mutation(self) -> None:
        for node in self._nodes:
            observed = self._ops.fstat(node.descriptor)
            _require(
                stat.S_ISDIR(observed.st_mode)
                and observed.st_dev == node.snapshot.device
                and observed.st_ino == node.snapshot.inode
                and observed.st_mode == node.snapshot.mode
                and observed.st_uid == node.uid
                and observed.st_gid == node.gid,
                "owned output mutation changed directory identity",
            )
            node.snapshot = _snapshot_from_stat(observed)
        self.revalidate()

    @property
    def output_exists(self) -> bool:
        return self._output_node is not None

    def _artifact_exists(self, name: str) -> bool:
        if self._output_node is None:
            return False
        try:
            observed = self._ops.stat_at(self._output_node.descriptor, name)
        except FileNotFoundError:
            return False
        _require(stat.S_ISREG(observed.st_mode), "durable output artifact entry is not a regular file")
        return True

    def fence_exists(self) -> bool:
        return self._artifact_exists(FENCE_NAME)

    def receipt_exists(self) -> bool:
        return self._artifact_exists(RECEIPT_NAME)

    def attempt_exists(self) -> bool:
        return self._artifact_exists(ATTEMPT_NAME)

    def read_fence(self) -> dict[str, object]:
        _require(self._output_node is not None, "held output directory is absent")
        self.revalidate()
        return self._ops.read_artifact(self._output_node.descriptor, FENCE_NAME, domain=_FENCE_DOMAIN, hash_field="fence_sha256")

    def read_receipt(self) -> dict[str, object]:
        _require(self._output_node is not None, "held output directory is absent")
        self.revalidate()
        return self._ops.read_artifact(self._output_node.descriptor, RECEIPT_NAME, domain=_RECEIPT_DOMAIN, hash_field="receipt_sha256")

    def read_attempt(self) -> dict[str, object]:
        _require(self._output_node is not None, "held output directory is absent")
        self.revalidate()
        return self._ops.read_artifact(self._output_node.descriptor, ATTEMPT_NAME, domain=_ATTEMPT_DOMAIN, hash_field="attempt_sha256")

    def _ensure_intake_parent(self) -> _HeldDirectoryNode:
        _require(self._output_node is None, "held output already exists")
        existing_components = len(self._nodes) - 1
        for component in self._components[existing_components:]:
            parent = self._nodes[-1]
            try:
                self._ops.mkdir_at(parent.descriptor, component, 0o700)
            except FileExistsError as error:
                raise IntakeContractError("output namespace appeared during held create") from error
            self._ops.fsync(parent.descriptor)
            child = self._ops.open_directory_at(parent.descriptor, component)
            try:
                node = self._node(child, parent.descriptor, component)
            except BaseException:
                try:
                    self._ops.close(child)
                except OSError:
                    pass
                raise
            self._nodes.append(node)
            self._refresh_after_owned_mutation()
        return self._nodes[-1]

    def create_fence(self, fence: Mapping[str, object]) -> None:
        parent = self._ensure_intake_parent()
        temporary_name = f".{self._intake_id}.{secrets.token_hex(16)}.pending"
        self._ops.mkdir_at(parent.descriptor, temporary_name, 0o700)
        temporary_fd = self._ops.open_directory_at(parent.descriptor, temporary_name)
        published = False
        try:
            self._ops.write_private_file(temporary_fd, FENCE_NAME, canonical_line(fence))
            self._ops.fsync(temporary_fd)
            self._refresh_after_owned_mutation()
            self._ops.rename_noreplace(
                parent.descriptor,
                temporary_name,
                parent.descriptor,
                self._intake_id,
            )
            published = True
            self._ops.fsync(parent.descriptor)
            output = self._node(temporary_fd, parent.descriptor, self._intake_id)
            temporary_fd = -1
            self._nodes.append(output)
            self._output_node = output
            self._refresh_after_owned_mutation()
            _require(
                self._ops.read_artifact(output.descriptor, FENCE_NAME, domain=_FENCE_DOMAIN, hash_field="fence_sha256")
                == fence,
                "published fence bytes differ from the sealed input",
            )
        finally:
            if not published:
                try:
                    self._ops.unlink_at(temporary_fd, FENCE_NAME)
                except FileNotFoundError:
                    pass
                finally:
                    if temporary_fd >= 0:
                        self._ops.close(temporary_fd)
                        temporary_fd = -1
            elif temporary_fd >= 0:
                self._ops.close(temporary_fd)
                temporary_fd = -1
            if not published:
                try:
                    self._ops.rmdir_at(parent.descriptor, temporary_name)
                except FileNotFoundError:
                    pass

    def _create_output_artifact(
        self,
        *,
        name: str,
        value: Mapping[str, object],
        domain: bytes,
        hash_field: str,
    ) -> None:
        _require(self._output_node is not None, "held output directory is absent")
        parent = self._nodes[-2]
        temporary_name = f".{self._intake_id}.{name}.{secrets.token_hex(16)}.tmp"
        payload = canonical_line(value)
        self._ops.write_private_file(parent.descriptor, temporary_name, payload)
        renamed = False
        try:
            self._refresh_after_owned_mutation()
            self._ops.rename_noreplace(
                parent.descriptor,
                temporary_name,
                self._output_node.descriptor,
                name,
            )
            renamed = True
            self._ops.fsync(self._output_node.descriptor)
            self._ops.fsync(parent.descriptor)
            self._refresh_after_owned_mutation()
            _require(
                self._ops.read_artifact(self._output_node.descriptor, name, domain=domain, hash_field=hash_field)
                == value,
                "published durable output artifact differs from the sealed input",
            )
        finally:
            if not renamed:
                try:
                    self._ops.unlink_at(parent.descriptor, temporary_name)
                    self._ops.fsync(parent.descriptor)
                except FileNotFoundError:
                    pass

    def create_receipt(self, receipt: Mapping[str, object]) -> None:
        self._create_output_artifact(
            name=RECEIPT_NAME,
            value=receipt,
            domain=_RECEIPT_DOMAIN,
            hash_field="receipt_sha256",
        )

    def create_attempt(self, attempt: Mapping[str, object]) -> None:
        self._create_output_artifact(
            name=ATTEMPT_NAME,
            value=attempt,
            domain=_ATTEMPT_DOMAIN,
            hash_field="attempt_sha256",
        )


def _open_output_namespace(project_root: Path, intake_id: str) -> _PathOutputNamespace | _PosixOutputNamespace:
    if os.name == "posix":
        return _PosixOutputNamespace(project_root, intake_id)
    return _PathOutputNamespace(project_root, intake_id)


def _default_user_state_root() -> Path:
    _require(
        os.name == "posix" and sys.platform.startswith("linux"),
        "per-user global offline intake state requires Linux",
    )
    try:
        import pwd

        account = pwd.getpwuid(os.getuid())
    except (ImportError, KeyError, OSError) as error:
        raise IntakeContractError("current POSIX account state root cannot be resolved") from error
    _require(
        type(account.pw_dir) is str
        and bool(account.pw_dir)
        and account.pw_uid == os.getuid(),
        "current POSIX account identity drifted",
    )
    state_root = Path(account.pw_dir)
    _require(
        state_root.is_absolute() and PurePosixPath(str(state_root)).as_posix() == str(state_root),
        "current POSIX account state root is noncanonical",
    )
    return state_root


def _open_global_output_namespace(
    _project_root: Path,
    intake_id: str,
) -> _PosixOutputNamespace:
    return _PosixOutputNamespace(
        _default_user_state_root(),
        intake_id,
        _components=_GLOBAL_STATE_COMPONENTS,
        _require_non_owner_writable=True,
    )


def _seal(core: Mapping[str, object], *, domain: bytes, hash_field: str) -> dict[str, object]:
    return {**core, hash_field: _identity(domain, core)}


def _artifact_exists(path: Path) -> bool:
    try:
        observed = path.lstat()
    except FileNotFoundError:
        return False
    _require(stat.S_ISREG(observed.st_mode) and not stat.S_ISLNK(observed.st_mode), "offline intake artifact namespace is not a regular file")
    return True


def _assessment(status: str, message: str, **fields: object) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "kpp_legacy_iss_v2_offline_image_intake_assessment",
        "status": status,
        "message": message,
        "image_id": TENSORRT_IMAGE_ID,
        "durable_operation_scope": "per_user_global_nonpublication_state_v1",
        "network_performed": False,
        "docker_pull_performed": False,
        "docker_build_performed": False,
        "docker_import_performed": False,
        "load_command_start_possible_historically": True,
        "load_command_start_observed_during_this_invocation": False,
        "load_command_return_observed_during_this_invocation": False,
        "exact_expected_image_effect_observed": False,
        "historical_load_command_outcome_known": False,
        "bounded_command_and_exact_effect_correlation_observed": False,
        "effect_causally_attributed_to_this_intake": False,
        **_FALSE_CLAIMS,
        **fields,
    }
    return _seal(core, domain=_ASSESSMENT_DOMAIN, hash_field="assessment_sha256")


def _sanitized_capture_ascii(payload: bytes) -> str | None:
    if len(payload) > _MAX_SANITIZED_CAPTURE_BYTES:
        return None
    try:
        text = payload.decode("ascii")
    except UnicodeError:
        return None
    if any(
        character not in "\t\r\n" and not (" " <= character <= "~")
        for character in text
    ):
        return None
    return (
        text.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _load_capture_facts(
    capture: CommandCapture | None,
    error: BaseException | None,
) -> dict[str, object]:
    _require(not (capture is not None and error is not None), "Docker load outcome is internally inconsistent")
    if capture is None:
        return {
            "capture_observed": False,
            "runner_error_type": type(error).__name__ if error is not None else None,
            "returncode": None,
            "timed_out": None,
            "stdout_overflow": None,
            "stderr_overflow": None,
            "stdout_size_bytes": None,
            "stdout_sha256": None,
            "stdout_sanitized_ascii": None,
            "stdout_sanitized_ascii_omitted": True,
            "stderr_size_bytes": None,
            "stderr_sha256": None,
            "stderr_sanitized_ascii": None,
            "stderr_sanitized_ascii_omitted": True,
        }
    _require(
        type(capture.returncode) is int
        and type(capture.timed_out) is bool
        and type(capture.stdout_overflow) is bool
        and type(capture.stderr_overflow) is bool
        and type(capture.stdout) is bytes
        and type(capture.stderr) is bytes,
        "Docker load capture types drifted",
    )
    stdout_text = (
        None
        if capture.stdout_overflow
        else _sanitized_capture_ascii(capture.stdout)
    )
    stderr_text = (
        None
        if capture.stderr_overflow
        else _sanitized_capture_ascii(capture.stderr)
    )
    return {
        "capture_observed": True,
        "runner_error_type": None,
        "returncode": capture.returncode,
        "timed_out": capture.timed_out,
        "stdout_overflow": capture.stdout_overflow,
        "stderr_overflow": capture.stderr_overflow,
        "stdout_size_bytes": len(capture.stdout),
        "stdout_sha256": hashlib.sha256(capture.stdout).hexdigest(),
        "stdout_sanitized_ascii": stdout_text,
        "stdout_sanitized_ascii_omitted": stdout_text is None,
        "stderr_size_bytes": len(capture.stderr),
        "stderr_sha256": hashlib.sha256(capture.stderr).hexdigest(),
        "stderr_sanitized_ascii": stderr_text,
        "stderr_sanitized_ascii_omitted": stderr_text is None,
    }


def _load_capture_is_exact_success(
    capture: CommandCapture | None,
    error: BaseException | None,
) -> bool:
    expected_tagless_confirmation = (
        f"Loaded image ID: {TENSORRT_IMAGE_ID}\n".encode("ascii")
    )
    return (
        error is None
        and capture is not None
        and type(capture.returncode) is int
        and type(capture.timed_out) is bool
        and type(capture.stdout_overflow) is bool
        and type(capture.stderr_overflow) is bool
        and type(capture.stdout) is bytes
        and type(capture.stderr) is bytes
        and capture.returncode == 0
        and not capture.timed_out
        and not capture.stdout_overflow
        and not capture.stderr_overflow
        and capture.stdout in {b"", expected_tagless_confirmation}
        and capture.stderr == b""
    )


def _attempt_marker(
    *,
    request: Mapping[str, object],
    request_sha256: str,
    operation_sha256: str,
    fence_sha256: str,
) -> dict[str, object]:
    archive = _mapping(request.get("archive"), "attempt archive request")
    docker_cli = _mapping(request.get("docker_cli"), "attempt Docker CLI request")
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "kpp_legacy_iss_v2_offline_image_load_attempt",
        "state": "load_may_have_started",
        "request_sha256": request_sha256,
        "operation_sha256": operation_sha256,
        "fence_sha256": fence_sha256,
        "image_id": TENSORRT_IMAGE_ID,
        "normalized_load_tar_sha256": archive["normalized_sha256"],
        "docker_cli_sha256": docker_cli["sha256"],
        "logical_load_argv": [
            DOCKER_CLI,
            DOCKER_HOST_FLAG,
            DOCKER_HOST_VALUE,
            "image",
            "load",
            "--quiet",
            "--platform=linux/amd64",
            "--input",
            "<held-normalized-archive-fd>",
        ],
        "executable_binding": "held_verified_inode_via_proc_self_fd",
        "marker_committed_before_load_command_invocation": True,
        "absence_of_matching_receipt_requires_load_outcome_unknown": True,
        "network_performed": False,
        "docker_pull_performed": False,
        "docker_build_performed": False,
        "docker_import_performed": False,
        **_FALSE_CLAIMS,
    }
    return _seal(core, domain=_ATTEMPT_DOMAIN, hash_field="attempt_sha256")


def _validate_attempt_marker(
    attempt: Mapping[str, object],
    *,
    request: Mapping[str, object],
    request_sha256: str,
    fence: Mapping[str, object],
) -> None:
    _require(
        type(attempt.get("schema_version")) is int,
        "offline image load attempt marker schema version is not an exact integer",
    )
    expected = _attempt_marker(
        request=request,
        request_sha256=request_sha256,
        operation_sha256=str(fence["operation_sha256"]),
        fence_sha256=str(fence["fence_sha256"]),
    )
    _require(attempt == expected, "offline image load attempt marker drifted")


def _receipt(
    *,
    status: str,
    request: Mapping[str, object],
    request_sha256: str,
    operation_sha256: str,
    fence_sha256: str,
    baseline: Mapping[str, object],
    post_catalog: Mapping[str, object],
    attempt_sha256: str | None,
) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "kpp_legacy_iss_v2_offline_image_intake_receipt",
        "status": status,
        "request": dict(request),
        "request_sha256": request_sha256,
        "operation_sha256": operation_sha256,
        "fence_sha256": fence_sha256,
        "load_attempt_sha256": attempt_sha256,
        "baseline_catalog": dict(baseline),
        "post_catalog": dict(post_catalog),
        "image_id": TENSORRT_IMAGE_ID,
        "archive_inventory_sha256": _mapping(request["archive"], "receipt archive request")["inventory_sha256"],
        "normalized_load_tar_sha256": _mapping(request["archive"], "receipt archive request")["normalized_sha256"],
        "load_command_start_possible_historically": True,
        "load_command_start_observed_during_this_invocation": True,
        "load_command_return_observed_during_this_invocation": True,
        "exact_expected_image_effect_observed": True,
        "historical_load_command_outcome_known": True,
        "bounded_command_and_exact_effect_correlation_observed": True,
        "effect_causally_attributed_to_this_intake": False,
        "network_performed": False,
        "docker_pull_performed": False,
        "docker_build_performed": False,
        "docker_import_performed": False,
        **_FALSE_CLAIMS,
    }
    return _seal(core, domain=_RECEIPT_DOMAIN, hash_field="receipt_sha256")


def _require_operation_artifact_bounds(
    *,
    request: Mapping[str, object],
    request_sha256: str,
    operation_sha256: str,
    fence: Mapping[str, object],
    baseline: Mapping[str, object],
) -> None:
    projected_post = _project_exact_post_catalog(baseline)
    projected_attempt = _attempt_marker(
        request=request,
        request_sha256=request_sha256,
        operation_sha256=operation_sha256,
        fence_sha256=str(fence["fence_sha256"]),
    )
    projected_receipts = (
        _receipt(
            status="loaded_exact_offline_image",
            request=request,
            request_sha256=request_sha256,
            operation_sha256=operation_sha256,
            fence_sha256=str(fence["fence_sha256"]),
            baseline=baseline,
            post_catalog=projected_post,
            attempt_sha256=str(projected_attempt["attempt_sha256"]),
        ),
        _receipt(
            status="loaded_exact_offline_image_after_matching_fence_retry",
            request=request,
            request_sha256=request_sha256,
            operation_sha256=operation_sha256,
            fence_sha256=str(fence["fence_sha256"]),
            baseline=baseline,
            post_catalog=projected_post,
            attempt_sha256=str(projected_attempt["attempt_sha256"]),
        ),
    )
    _require(
        all(
            len(canonical_line(value)) <= _MAX_JSON_BYTES
            for value in (fence, projected_attempt, *projected_receipts)
        ),
        "offline intake fence, attempt, or worst-case receipt exceeds its replay bound",
    )


def _validate_session(session: ArchiveSession, *, size_bytes: int, sha256: str) -> None:
    _require(session.identity == FileIdentity(size_bytes, sha256), "archive session caller identity differs from the pins")
    _require(type(session.normalized_identity.size_bytes) is int and session.normalized_identity.size_bytes > 0, "normalized load tar size is invalid")
    _sha(session.normalized_identity.sha256, "normalized load tar SHA-256")
    _require(session.load_input.startswith("/proc/self/fd/") and session.load_input[14:].isdigit(), "normalized load fd path is invalid")
    _require(len(session.pass_fds) == 1 and session.load_input == f"/proc/self/fd/{session.pass_fds[0]}", "normalized load fd custody drifted")
    inventory = _mapping(session.inventory, "verified archive inventory")
    _require(
        inventory.get("format") == "docker_save_oci_hybrid_v1"
        and inventory.get("outer_tar_profile")
        == "closed_ustar_regular_directory_only_v1"
        and inventory.get("image_id") == TENSORRT_IMAGE_ID
        and inventory.get("platform") == {"os": "linux", "architecture": "amd64"}
        and inventory.get("repo_tags") == []
        and inventory.get("repo_digests") == []
        and type(inventory.get("layer_count")) is int
        and inventory.get("layer_count", 0) > 0,
        "verified archive inventory differs from the frozen image contract",
    )
    _sha(inventory.get("inventory_sha256"), "archive inventory SHA-256")


def _request_core(
    *,
    intake_id: str,
    durable_namespace_id: str,
    archive_path: Path,
    session: ArchiveSession,
    docker_cli: FileIdentity,
    daemon: Mapping[str, str],
) -> dict[str, object]:
    inventory = _mapping(session.inventory, "archive inventory")
    return {
        "intake_id": intake_id,
        "durable_namespace_id": durable_namespace_id,
        "durable_operation_scope": "per_user_global_nonpublication_state_v1",
        "archive": {
            "caller_path": str(archive_path),
            "caller_size_bytes": session.identity.size_bytes,
            "caller_sha256": session.identity.sha256,
            "inventory_sha256": inventory["inventory_sha256"],
            "normalized_size_bytes": session.normalized_identity.size_bytes,
            "normalized_sha256": session.normalized_identity.sha256,
        },
        "image": {
            "reference": TENSORRT_IMAGE,
            "image_id": TENSORRT_IMAGE_ID,
            "platform": "linux/amd64",
            "entrypoint": TENSORRT_ENTRYPOINT,
            "required_labels": dict(IMAGE_LABELS),
        },
        "docker_cli": {
            "path": DOCKER_CLI,
            "size_bytes": docker_cli.size_bytes,
            "sha256": docker_cli.sha256,
        },
        "daemon": dict(daemon),
        "load_argv_prefix": [
            DOCKER_CLI,
            DOCKER_HOST_FLAG,
            DOCKER_HOST_VALUE,
            "image",
            "load",
            "--quiet",
            "--platform=linux/amd64",
            "--input",
        ],
    }


def _validate_fence(fence: Mapping[str, object], request: Mapping[str, object], request_sha256: str) -> Mapping[str, object]:
    _require(
        set(fence)
        == {
            "schema_version",
            "artifact_kind",
            "state",
            "request",
            "request_sha256",
            "operation_sha256",
            "baseline_catalog",
            "fence_sha256",
        }
        and type(fence.get("schema_version")) is int
        and fence.get("schema_version") == 1
        and fence.get("artifact_kind") == "kpp_legacy_iss_v2_offline_image_intake_fence"
        and fence.get("state") == "prepared"
        and fence.get("request") == request
        and fence.get("request_sha256") == request_sha256,
        "offline intake fence request identity drifted",
    )
    baseline = _mapping(fence.get("baseline_catalog"), "offline intake fence baseline")
    _validate_catalog(baseline)
    operation_core = {
        "request_sha256": request_sha256,
        "baseline_catalog_sha256": baseline["catalog_sha256"],
    }
    _require(fence.get("operation_sha256") == _identity(_OPERATION_DOMAIN, operation_core), "offline intake operation identity drifted")
    return baseline


def _validate_receipt(
    receipt: Mapping[str, object],
    *,
    request: Mapping[str, object],
    request_sha256: str,
    fence: Mapping[str, object],
    attempt: Mapping[str, object] | None,
    current_catalog: Mapping[str, object],
) -> None:
    expected_fields = {
        "schema_version",
        "artifact_kind",
        "status",
        "request",
        "request_sha256",
        "operation_sha256",
        "fence_sha256",
        "load_attempt_sha256",
        "baseline_catalog",
        "post_catalog",
        "image_id",
        "archive_inventory_sha256",
        "normalized_load_tar_sha256",
        *LOAD_FACT_FIELDS,
        "network_performed",
        "docker_pull_performed",
        "docker_build_performed",
        "docker_import_performed",
        *FALSE_CLAIM_FIELDS,
        "receipt_sha256",
    }
    _require(
        set(receipt) == expected_fields
        and type(receipt.get("schema_version")) is int
        and receipt.get("schema_version") == 1
        and receipt.get("artifact_kind") == "kpp_legacy_iss_v2_offline_image_intake_receipt"
        and receipt.get("status")
        in {
            "loaded_exact_offline_image",
            "loaded_exact_offline_image_after_matching_fence_retry",
        }
        and receipt.get("request") == request
        and receipt.get("request_sha256") == request_sha256
        and receipt.get("operation_sha256") == fence.get("operation_sha256")
        and receipt.get("fence_sha256") == fence.get("fence_sha256")
        and receipt.get("baseline_catalog") == fence.get("baseline_catalog")
        and receipt.get("post_catalog") == current_catalog,
        "offline intake receipt no longer matches the request or daemon catalog",
    )
    _validate_catalog(_mapping(receipt.get("baseline_catalog"), "offline intake receipt baseline"))
    _validate_catalog(_mapping(receipt.get("post_catalog"), "offline intake receipt post catalog"))
    receipt_baseline = _mapping(receipt.get("baseline_catalog"), "offline intake receipt baseline")
    receipt_post = _mapping(receipt.get("post_catalog"), "offline intake receipt post catalog")
    request_archive = _mapping(request.get("archive"), "offline intake request archive")
    _require(
        receipt.get("image_id") == TENSORRT_IMAGE_ID
        and receipt.get("archive_inventory_sha256") == request_archive.get("inventory_sha256")
        and receipt.get("normalized_load_tar_sha256") == request_archive.get("normalized_sha256")
        and _catalog_is_exact_post_delta(receipt_baseline, receipt_post)
        and all(type(receipt.get(field)) is bool for field in LOAD_FACT_FIELDS)
        and receipt.get("network_performed") is False
        and receipt.get("docker_pull_performed") is False
        and receipt.get("docker_build_performed") is False
        and receipt.get("docker_import_performed") is False,
        "offline intake receipt operational claims drifted",
    )
    loaded = receipt.get("status") in {
        "loaded_exact_offline_image",
        "loaded_exact_offline_image_after_matching_fence_retry",
    }
    _require(
            loaded
            and attempt is not None
            and receipt.get("load_attempt_sha256") == attempt.get("attempt_sha256")
            and receipt.get("load_command_start_possible_historically") is True
            and receipt.get("load_command_start_observed_during_this_invocation") is True
            and receipt.get("load_command_return_observed_during_this_invocation") is True
            and receipt.get("exact_expected_image_effect_observed") is True
            and receipt.get("historical_load_command_outcome_known") is True
            and receipt.get("bounded_command_and_exact_effect_correlation_observed") is True
            and receipt.get("effect_causally_attributed_to_this_intake") is False,
        "offline intake receipt status/load-causality flags are inconsistent",
    )
    for field in FALSE_CLAIM_FIELDS:
        _require(receipt.get(field) is False, "offline intake receipt contains a forbidden positive claim")


def _default_dependencies() -> _IntakeDependencies:
    environment = dict(os.environ)
    return _IntakeDependencies(
        platform_name=os.name,
        environment=environment,
        observe_docker_cli=_open_held_docker_cli,
        command_runner=_BoundedCommandRunner(),
        archive_opener=_default_archive_opener,
        canonical_project_root=_CANONICAL_PROJECT_ROOT,
        local_runtime_guard=lambda: _default_local_runtime_guard(environment),
        daemon_lock_factory=lambda daemon_id: _DaemonLock(daemon_id),
        output_namespace_factory=_open_global_output_namespace,
    )


def intake_offline_image(
    *,
    project_root: Path,
    archive_path: Path,
    expected_archive_size_bytes: int,
    expected_archive_sha256: str,
    intake_id: str,
    expected_docker_cli_size_bytes: int,
    expected_docker_cli_sha256: str,
    expected_daemon_id: str,
    expected_daemon_server_version: str,
    expected_daemon_api_version: str,
    _dependencies: _IntakeDependencies | None = None,
) -> tuple[dict[str, object], int]:
    dependencies = _dependencies or _default_dependencies()
    # Until the held global target namespace proves otherwise, a prior durable
    # attempt may exist even when this invocation fails during early custody or
    # archive validation.  Narrow these conservative facts only after that
    # namespace has been opened and its state has been validated.
    load_start_possible_historically = True
    load_started_during_this_invocation = False
    load_return_observed_during_this_invocation = False
    exact_expected_image_effect_observed = False
    historical_load_command_outcome_known = False
    bounded_command_and_exact_effect_correlation_observed = False
    effect_causally_attributed_to_this_intake = False
    try:
        _require(dependencies.platform_name == "posix", "offline image intake is WSL/POSIX-only")
        _require(type(intake_id) is str and _INTAKE_ID_RE.fullmatch(intake_id) is not None, "offline image intake ID is invalid")
        _require(project_root.is_absolute() and archive_path.is_absolute(), "project root and archive path must be absolute")
        _require(
            project_root == dependencies.canonical_project_root,
            "project root differs from the self-bound canonical intake root",
        )
        _require(project_root.exists() and project_root.is_dir() and not project_root.is_symlink(), "project root custody failed")
        _sha(expected_archive_sha256, "caller archive SHA-256")
        _sha(expected_docker_cli_sha256, "Docker CLI SHA-256")
        _require(type(expected_archive_size_bytes) is int and expected_archive_size_bytes > 0, "caller archive size is invalid")
        _require(type(expected_docker_cli_size_bytes) is int and expected_docker_cli_size_bytes > 0, "Docker CLI size pin is invalid")
        _require(all(type(value) is str and value for value in (expected_daemon_id, expected_daemon_server_version, expected_daemon_api_version)), "Docker daemon pins are invalid")
        durable_namespace_id = _durable_operation_namespace_id(expected_daemon_id)
        if dependencies.local_runtime_guard is not None:
            dependencies.local_runtime_guard()
        with dependencies.archive_opener(
            archive_path=archive_path,
            expected_size_bytes=expected_archive_size_bytes,
            expected_sha256=expected_archive_sha256,
            expected_image_id=TENSORRT_IMAGE_ID,
            expected_entrypoint=TENSORRT_ENTRYPOINT,
            expected_labels=IMAGE_LABELS,
        ) as session:
            _validate_session(session, size_bytes=expected_archive_size_bytes, sha256=expected_archive_sha256)
            session.revalidate()
            lock_factory = dependencies.daemon_lock_factory or (lambda daemon_id: _DaemonLock(daemon_id))
            namespace_factory = dependencies.output_namespace_factory or _open_output_namespace
            load_start_possible_historically = True
            historical_load_command_outcome_known = False
            with lock_factory(expected_daemon_id) as daemon_lock, _coerce_docker_cli_session(
                dependencies.observe_docker_cli()
            ) as docker_cli, namespace_factory(project_root, durable_namespace_id) as output_namespace:
                if not output_namespace.output_exists:
                    load_start_possible_historically = False
                    historical_load_command_outcome_known = True
                _require(docker_cli.identity == FileIdentity(expected_docker_cli_size_bytes, expected_docker_cli_sha256), "Docker CLI identity differs from external pins")
                docker_cli.revalidate()
                daemon = _observe_daemon(
                    dependencies.command_runner,
                    docker_cli,
                    expected_daemon_id=expected_daemon_id,
                    expected_server_version=expected_daemon_server_version,
                    expected_api_version=expected_daemon_api_version,
                )
                request = _request_core(
                    intake_id=intake_id,
                    durable_namespace_id=durable_namespace_id,
                    archive_path=archive_path,
                    session=session,
                    docker_cli=docker_cli.identity,
                    daemon=daemon,
                )
                request_sha256 = _identity(_OPERATION_DOMAIN, request)
                fence_exists = output_namespace.fence_exists()
                attempt_exists = output_namespace.attempt_exists()
                receipt_exists = output_namespace.receipt_exists()
                _require(not receipt_exists or fence_exists, "offline intake receipt exists without its fence")
                _require(not attempt_exists or fence_exists, "offline image load attempt exists without its fence")
                current_catalog = _stable_catalog(dependencies.command_runner, docker_cli)
                _validate_catalog(current_catalog)
                current_images = _catalog_images(current_catalog)
                if fence_exists:
                    fence = output_namespace.read_fence()
                    baseline = _validate_fence(fence, request, request_sha256)
                    if not attempt_exists and not receipt_exists:
                        load_start_possible_historically = False
                        historical_load_command_outcome_known = True
                    _require_operation_artifact_bounds(
                        request=request,
                        request_sha256=request_sha256,
                        operation_sha256=str(fence["operation_sha256"]),
                        fence=fence,
                        baseline=baseline,
                    )
                    attempt: Mapping[str, object] | None = None
                    if attempt_exists:
                        attempt = output_namespace.read_attempt()
                        _validate_attempt_marker(
                            attempt,
                            request=request,
                            request_sha256=request_sha256,
                            fence=fence,
                        )
                        load_start_possible_historically = True
                        historical_load_command_outcome_known = False
                    if receipt_exists:
                        receipt = output_namespace.read_receipt()
                        _validate_receipt(
                            receipt,
                            request=request,
                            request_sha256=request_sha256,
                            fence=fence,
                            attempt=attempt,
                            current_catalog=current_catalog,
                        )
                        target = _inspect_image(dependencies.command_runner, docker_cli, TENSORRT_IMAGE_ID)
                        _validate_target_document(target)
                        session.revalidate()
                        _require(
                            _stable_catalog(dependencies.command_runner, docker_cli) == current_catalog,
                            "Docker daemon catalog drifted during receipt replay validation",
                        )
                        _require(
                            output_namespace.read_fence() == fence
                            and output_namespace.read_receipt() == receipt,
                            "durable replay artifacts drifted during validation",
                        )
                        _require(
                            attempt is None or output_namespace.read_attempt() == attempt,
                            "durable replay load-attempt marker drifted",
                        )
                        return _assessment(
                            "already_loaded_by_matching_offline_intake_receipt",
                            "matching durable receipt and exact daemon image were revalidated; no load was invoked",
                            request_sha256=request_sha256,
                            operation_sha256=fence["operation_sha256"],
                            matching_receipt_sha256=receipt["receipt_sha256"],
                            load_command_start_possible_historically=receipt[
                                "load_command_start_possible_historically"
                            ],
                            exact_expected_image_effect_observed=True,
                            historical_load_command_outcome_known=receipt[
                                "historical_load_command_outcome_known"
                            ],
                            matching_receipt_historical_bounded_command_effect_correlation_attested=receipt[
                                "bounded_command_and_exact_effect_correlation_observed"
                            ],
                        ), 0
                    if current_catalog == baseline:
                        _require(TENSORRT_IMAGE_ID not in current_images, "fence baseline unexpectedly contains the target image")
                        if attempt is not None:
                            return _assessment(
                                "blocked_prior_load_attempt_outcome_unknown",
                                "durable load-attempt marker exists with no exact image; automatic retry is forbidden",
                                request_sha256=request_sha256,
                                operation_sha256=fence["operation_sha256"],
                                prior_load_attempt_sha256=attempt["attempt_sha256"],
                                load_command_start_possible_historically=True,
                                historical_load_command_outcome_known=False,
                            ), 78
                        retry = True
                    elif _catalog_is_exact_post_delta(baseline, current_catalog):
                        target = _inspect_image(dependencies.command_runner, docker_cli, TENSORRT_IMAGE_ID)
                        _validate_target_document(target)
                        session.revalidate()
                        _require(
                            _stable_catalog(dependencies.command_runner, docker_cli) == current_catalog,
                            "Docker daemon catalog drifted before fail-closed exact-image classification",
                        )
                        _require(
                            output_namespace.read_fence() == fence
                            and (
                                attempt is None
                                or output_namespace.read_attempt() == attempt
                            ),
                            "durable fence or load-attempt marker drifted before fail-closed exact-image classification",
                        )
                        return _assessment(
                            (
                                "blocked_exact_image_observed_after_prior_load_attempt_without_receipted_success"
                                if attempt is not None
                                else "blocked_exact_image_observed_after_prepared_fence_without_load_causality"
                            ),
                            "exact target image is present, but this intake cannot attest archive origin or load causality; no success receipt was written",
                            request_sha256=request_sha256,
                            operation_sha256=fence["operation_sha256"],
                            load_attempt_sha256=(
                                None
                                if attempt is None
                                else attempt["attempt_sha256"]
                            ),
                            load_command_start_possible_historically=attempt is not None,
                            exact_expected_image_effect_observed=True,
                            historical_load_command_outcome_known=False,
                            bounded_command_and_exact_effect_correlation_observed=False,
                            effect_causally_attributed_to_this_intake=False,
                        ), 78
                    else:
                        return _assessment(
                            "blocked_resume_daemon_catalog_drift",
                            "matching fence exists but daemon images, tags, digests, or containers drifted",
                            request_sha256=request_sha256,
                            operation_sha256=fence.get("operation_sha256"),
                            load_command_start_possible_historically=attempt is not None,
                            historical_load_command_outcome_known=attempt is None,
                        ), 78
                else:
                    attempt = None
                    if output_namespace.output_exists:
                        raise IntakeContractError("offline intake output namespace preexists without matching durable state")
                    if TENSORRT_IMAGE_ID in current_images:
                        _validate_target_document(_inspect_image(dependencies.command_runner, docker_cli, TENSORRT_IMAGE_ID))
                        return _assessment(
                            "blocked_preexisting_exact_image",
                            "exact image preexists without a matching offline intake fence",
                            request_sha256=request_sha256,
                            load_command_start_possible_historically=False,
                            exact_expected_image_effect_observed=True,
                            historical_load_command_outcome_known=True,
                        ), 78
                    baseline = current_catalog
                    operation_core = {
                        "request_sha256": request_sha256,
                        "baseline_catalog_sha256": baseline["catalog_sha256"],
                    }
                    operation_sha256 = _identity(_OPERATION_DOMAIN, operation_core)
                    fence_core: dict[str, object] = {
                        "schema_version": 1,
                        "artifact_kind": "kpp_legacy_iss_v2_offline_image_intake_fence",
                        "state": "prepared",
                        "request": request,
                        "request_sha256": request_sha256,
                        "operation_sha256": operation_sha256,
                        "baseline_catalog": baseline,
                    }
                    fence = _seal(fence_core, domain=_FENCE_DOMAIN, hash_field="fence_sha256")
                    _require_operation_artifact_bounds(
                        request=request,
                        request_sha256=request_sha256,
                        operation_sha256=operation_sha256,
                        fence=fence,
                        baseline=baseline,
                    )
                    output_namespace.create_fence(fence)
                    retry = False
                if dependencies.lifecycle_hook is not None:
                    dependencies.lifecycle_hook("after_fence_before_load")
                if attempt is None:
                    attempt = _attempt_marker(
                        request=request,
                        request_sha256=request_sha256,
                        operation_sha256=str(fence["operation_sha256"]),
                        fence_sha256=str(fence["fence_sha256"]),
                    )
                    load_start_possible_historically = True
                    historical_load_command_outcome_known = False
                    output_namespace.create_attempt(attempt)
                    output_namespace.revalidate()
                load_start_possible_historically = True
                historical_load_command_outcome_known = False
                if dependencies.lifecycle_hook is not None:
                    dependencies.lifecycle_hook("after_attempt_before_load")
                session.revalidate()
                docker_cli.revalidate()
                output_namespace.revalidate()
                _require(
                    output_namespace.read_fence() == fence
                    and output_namespace.read_attempt() == attempt,
                    "durable fence or load-attempt marker drifted before Docker invocation",
                )
                load_argv = _docker_prefix(docker_cli) + [
                    "image",
                    "load",
                    "--quiet",
                    "--platform=linux/amd64",
                    "--input",
                    session.load_input,
                ]
                load_error: BaseException | None = None
                load_capture: CommandCapture | None = None
                try:
                    load_capture = dependencies.command_runner.run(
                        load_argv,
                        timeout_seconds=600,
                        stdout_limit=64 * 1024,
                        stderr_limit=1024 * 1024,
                        pass_fds=_merge_pass_fds(
                            docker_cli.pass_fds,
                            session.pass_fds,
                            getattr(daemon_lock, "pass_fds", ()),
                        ),
                        executable_override=docker_cli.executable,
                    )
                    load_started_during_this_invocation = True
                    load_return_observed_during_this_invocation = True
                except BaseException as error:
                    load_error = error
                if dependencies.lifecycle_hook is not None:
                    dependencies.lifecycle_hook("after_load_before_postflight")
                post_observation_error: BaseException | None = None
                post_catalog: Mapping[str, object] | None = None
                try:
                    session.revalidate()
                    docker_cli.revalidate()
                    output_namespace.revalidate()
                    _require(
                        output_namespace.read_fence() == fence
                        and output_namespace.read_attempt() == attempt,
                        "durable fence or load-attempt marker drifted after Docker invocation",
                    )
                    _observe_daemon(
                        dependencies.command_runner,
                        docker_cli,
                        expected_daemon_id=expected_daemon_id,
                        expected_server_version=expected_daemon_server_version,
                        expected_api_version=expected_daemon_api_version,
                    )
                    post_catalog = _stable_catalog(dependencies.command_runner, docker_cli)
                    _validate_catalog(post_catalog)
                    post_images = _catalog_images(post_catalog)
                    target_projection = post_images.get(TENSORRT_IMAGE_ID)
                    if (
                        TENSORRT_IMAGE_ID not in _catalog_images(baseline)
                        and target_projection is not None
                        and target_projection.get("repo_tags") == []
                        and target_projection.get("repo_digests") == []
                    ):
                        _validate_target_document(
                            _inspect_image(
                                dependencies.command_runner,
                                docker_cli,
                                TENSORRT_IMAGE_ID,
                            )
                        )
                        exact_expected_image_effect_observed = True
                except BaseException as error:
                    post_observation_error = error
                if post_observation_error is not None:
                    return _assessment(
                        "blocked_post_load_observation_failed",
                        "post-load daemon or held-archive revalidation failed; fence remains for explicit investigation",
                        request_sha256=request_sha256,
                        operation_sha256=fence["operation_sha256"],
                        load_command_start_possible_historically=load_start_possible_historically,
                        load_command_start_observed_during_this_invocation=load_started_during_this_invocation,
                        load_command_return_observed_during_this_invocation=load_return_observed_during_this_invocation,
                        exact_expected_image_effect_observed=exact_expected_image_effect_observed,
                        historical_load_command_outcome_known=False,
                        effect_causally_attributed_to_this_intake=False,
                    ), 78
                assert post_catalog is not None
                exact_delta = _catalog_is_exact_post_delta(baseline, post_catalog)
                load_success = _load_capture_is_exact_success(
                    load_capture,
                    load_error,
                )
                if not load_success:
                    status = (
                        "blocked_load_failed_with_daemon_mutation"
                        if post_catalog != baseline
                        else "blocked_docker_image_load_failed_without_visible_image"
                    )
                    return _assessment(
                        status,
                        "docker image load did not meet the exact bounded success contract; durable fence remains",
                        request_sha256=request_sha256,
                        operation_sha256=fence["operation_sha256"],
                        fence_sha256=fence["fence_sha256"],
                        attempt_sha256=attempt["attempt_sha256"],
                        load_capture=_load_capture_facts(load_capture, load_error),
                        load_command_start_possible_historically=load_start_possible_historically,
                        load_command_start_observed_during_this_invocation=load_started_during_this_invocation,
                        load_command_return_observed_during_this_invocation=load_return_observed_during_this_invocation,
                        exact_expected_image_effect_observed=exact_expected_image_effect_observed,
                        historical_load_command_outcome_known=False,
                        effect_causally_attributed_to_this_intake=False,
                    ), 78
                if not exact_delta:
                    return _assessment(
                        "blocked_unexpected_daemon_image_delta",
                        "successful docker load changed unexpected images, tags, digests, or containers",
                        request_sha256=request_sha256,
                        operation_sha256=fence["operation_sha256"],
                        load_command_start_possible_historically=load_start_possible_historically,
                        load_command_start_observed_during_this_invocation=load_started_during_this_invocation,
                        load_command_return_observed_during_this_invocation=load_return_observed_during_this_invocation,
                        exact_expected_image_effect_observed=exact_expected_image_effect_observed,
                        historical_load_command_outcome_known=True,
                        effect_causally_attributed_to_this_intake=False,
                    ), 78
                historical_load_command_outcome_known = True
                bounded_command_and_exact_effect_correlation_observed = True
                status = (
                    "loaded_exact_offline_image_after_matching_fence_retry"
                    if retry
                    else "loaded_exact_offline_image"
                )
                session.revalidate()
                _require(
                    _stable_catalog(dependencies.command_runner, docker_cli) == post_catalog,
                    "Docker daemon catalog drifted before durable receipt creation",
                )
                _require(
                    output_namespace.read_fence() == fence
                    and output_namespace.read_attempt() == attempt,
                    "durable fence or load-attempt marker drifted before receipt creation",
                )
                if dependencies.lifecycle_hook is not None:
                    dependencies.lifecycle_hook("after_postflight_before_receipt")
                receipt = _receipt(
                    status=status,
                    request=request,
                    request_sha256=request_sha256,
                    operation_sha256=str(fence["operation_sha256"]),
                    fence_sha256=str(fence["fence_sha256"]),
                    baseline=baseline,
                    post_catalog=post_catalog,
                    attempt_sha256=str(attempt["attempt_sha256"]),
                )
                output_namespace.create_receipt(receipt)
                output_namespace.revalidate()
                return receipt, 0
    except IntakeContractError as error:
        return _assessment(
            "blocked_contract_violation",
            str(error),
            load_command_start_possible_historically=load_start_possible_historically,
            load_command_start_observed_during_this_invocation=load_started_during_this_invocation,
            load_command_return_observed_during_this_invocation=load_return_observed_during_this_invocation,
            exact_expected_image_effect_observed=exact_expected_image_effect_observed,
            historical_load_command_outcome_known=historical_load_command_outcome_known,
            bounded_command_and_exact_effect_correlation_observed=bounded_command_and_exact_effect_correlation_observed,
            effect_causally_attributed_to_this_intake=effect_causally_attributed_to_this_intake,
        ), 78
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError, RecursionError, TypeError, KeyError, OverflowError) as error:
        return _assessment(
            "blocked_deterministic_runtime_error",
            type(error).__name__,
            load_command_start_possible_historically=load_start_possible_historically,
            load_command_start_observed_during_this_invocation=load_started_during_this_invocation,
            load_command_return_observed_during_this_invocation=load_return_observed_during_this_invocation,
            exact_expected_image_effect_observed=exact_expected_image_effect_observed,
            historical_load_command_outcome_known=historical_load_command_outcome_known,
            bounded_command_and_exact_effect_correlation_observed=bounded_command_and_exact_effect_correlation_observed,
            effect_causally_attributed_to_this_intake=effect_causally_attributed_to_this_intake,
        ), 78


class _FailClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise IntakeContractError(f"invalid offline intake arguments: {message}")


def _argument_parser() -> argparse.ArgumentParser:
    parser = _FailClosedArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-archive-size-bytes", type=int, required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--intake-id", required=True)
    parser.add_argument("--expected-docker-cli-size-bytes", type=int, required=True)
    parser.add_argument("--expected-docker-cli-sha256", required=True)
    parser.add_argument("--expected-daemon-id", required=True)
    parser.add_argument("--expected-daemon-server-version", required=True)
    parser.add_argument("--expected-daemon-api-version", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _argument_parser().parse_args(argv)
        result, code = intake_offline_image(
            project_root=arguments.project_root,
            archive_path=arguments.archive,
            expected_archive_size_bytes=arguments.expected_archive_size_bytes,
            expected_archive_sha256=arguments.expected_archive_sha256,
            intake_id=arguments.intake_id,
            expected_docker_cli_size_bytes=arguments.expected_docker_cli_size_bytes,
            expected_docker_cli_sha256=arguments.expected_docker_cli_sha256,
            expected_daemon_id=arguments.expected_daemon_id,
            expected_daemon_server_version=arguments.expected_daemon_server_version,
            expected_daemon_api_version=arguments.expected_daemon_api_version,
        )
    except IntakeContractError as error:
        result, code = _assessment(
            "blocked_contract_violation",
            str(error),
            load_command_start_possible_historically=True,
            historical_load_command_outcome_known=False,
        ), 78
    sys.stdout.buffer.write(canonical_line(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
