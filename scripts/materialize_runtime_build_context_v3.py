#!/usr/bin/env python3
"""Materialize an exact, immutable-input Docker build context from manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from itertools import islice
from pathlib import Path, PurePosixPath
from typing import Sequence


_COPY_CHUNK_BYTES = 1024 * 1024
_MANIFEST_COUNT = 3
_MANIFEST_BYTES = 8192
_CONTEXT_FILES = 128
_PATH_BYTES = 256
_PATH_DEPTH = 8
_MEMBER_BYTES = 32 * 1024 * 1024
_CONTEXT_BYTES = 40 * 1024 * 1024
_CONTEXT_DIRECTORIES = 896
_METADATA_BYTES = 65536


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_relative(value: str) -> str:
    _require(bool(value) and value == value.strip(), "manifest path is empty or padded")
    _require(
        len(value) <= _PATH_BYTES
        and value.isascii()
        and all(32 <= ord(character) <= 126 for character in value)
        and len(value.split("/")) <= _PATH_DEPTH,
        "manifest path bound exceeded",
    )
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"manifest path is not canonical and relative: {value}",
    )
    return value


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    ctime_ns = 0 if os.name == "nt" else int(info.st_ctime_ns)
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        ctime_ns,
    )


def _physical_member(root: Path, relative: str) -> tuple[Path, os.stat_result]:
    parts = PurePosixPath(relative).parts
    cursor = root
    for part in parts[:-1]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as error:
            raise ValueError(f"manifest parent is absent: {relative}") from error
        _require(
            stat.S_ISDIR(info.st_mode) and not cursor.is_symlink(),
            f"manifest parent is unsafe: {relative}",
        )
    source = root.joinpath(*parts)
    try:
        info = source.lstat()
    except OSError as error:
        raise ValueError(f"manifest member is absent: {relative}") from error
    _require(
        stat.S_ISREG(info.st_mode)
        and not source.is_symlink()
        and int(info.st_nlink) == 1,
        f"manifest member must be a physical single-link regular file: {relative}",
    )
    try:
        source.resolve(strict=True).relative_to(root)
    except ValueError as error:
        raise ValueError(f"manifest member escapes project root: {relative}") from error
    return source, info


def _manifest_members(root: Path, manifest_path: Path) -> tuple[str, ...]:
    manifest_input = Path(os.path.abspath(os.fspath(manifest_path)))
    try:
        input_info = manifest_input.lstat()
    except OSError as error:
        raise ValueError("path manifest is absent") from error
    _require(
        stat.S_ISREG(input_info.st_mode)
        and not manifest_input.is_symlink()
        and int(input_info.st_nlink) == 1,
        "path manifest must be a physical single-link regular file",
    )
    try:
        manifest = manifest_input.resolve(strict=True)
    except OSError as error:
        raise ValueError("path manifest is absent") from error
    try:
        relative = manifest.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("path manifest escapes project root") from error
    manifest, expected = _physical_member(root, _canonical_relative(relative))
    _require(
        _snapshot(input_info) == _snapshot(expected),
        "path manifest identity is aliased",
    )
    sealed_size = int(expected.st_size)
    _require(0 < sealed_size <= _MANIFEST_BYTES, "manifest byte bound exceeded")
    raw = bytearray()
    try:
        descriptor = os.open(
            manifest,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        primary = None
        try:
            opened = os.fstat(descriptor)
            _require(
                stat.S_ISREG(opened.st_mode)
                and int(opened.st_nlink) == 1
                and _snapshot(opened) == _snapshot(expected),
                "path manifest changed before read",
            )
            while True:
                remaining = sealed_size - len(raw)
                chunk = os.read(descriptor, min(_MANIFEST_BYTES, remaining + 1))
                if not chunk:
                    break
                _require(len(chunk) <= remaining, "path manifest size drifted")
                raw.extend(chunk)
            _require(len(raw) == sealed_size, "path manifest size drifted")
            _require(
                _snapshot(os.fstat(descriptor)) == _snapshot(expected),
                "path manifest changed while reading",
            )
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                os.close(descriptor)
            except BaseException as close_error:
                if primary is not None and close_error is not primary:
                    raise primary from close_error
                raise
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"path manifest is not canonical UTF-8: {relative}") from error
    try:
        after = manifest.lstat()
    except OSError as error:
        raise ValueError(f"path manifest disappeared while reading: {relative}") from error
    _require(
        _snapshot(after) == _snapshot(expected),
        f"path manifest changed while reading: {relative}",
    )
    _require(
        bool(raw) and raw.endswith(b"\n") and b"\r" not in raw,
        f"path manifest must be non-empty and LF-terminated: {relative}",
    )
    _require(raw.count(b"\n") <= _CONTEXT_FILES, "manifest entry bound exceeded")
    members = tuple(text.split("\n")[:-1])
    _require(
        members == tuple(sorted(set(members))) and all(members),
        f"path manifest must be sorted and unique: {relative}",
    )
    return tuple(_canonical_relative(value) for value in members)


def _copy_held_source(
    source: Path,
    destination: Path,
    *,
    expected: os.stat_result,
    source_date_epoch: int,
) -> str:
    source_fd = -1
    destination_fd = -1
    digest = hashlib.sha256()
    try:
        source_fd = os.open(
            source,
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(source_fd)
        _require(
            _snapshot(opened) == _snapshot(expected),
            f"manifest member changed before copy: {source}",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_fd = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o444,
        )
        sealed_size = int(expected.st_size)
        copied = 0
        while True:
            remaining = sealed_size - copied
            chunk = os.read(source_fd, min(_COPY_CHUNK_BYTES, remaining + 1))
            if not chunk:
                break
            _require(len(chunk) <= remaining, f"manifest member size drifted: {source}")
            digest.update(chunk)
            copied += len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                _require(written > 0, f"build-context write stalled: {destination}")
                view = view[written:]
        _require(copied == sealed_size, f"manifest member size drifted: {source}")
        os.fsync(destination_fd)
    except OSError as error:
        raise ValueError(f"cannot materialize build-context member: {source}") from error
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        if source_fd >= 0:
            os.close(source_fd)
    try:
        after = source.lstat()
    except OSError as error:
        raise ValueError(f"manifest member disappeared after copy: {source}") from error
    _require(
        _snapshot(after) == _snapshot(expected),
        f"manifest member changed during copy: {source}",
    )
    os.chmod(destination, 0o444, follow_symlinks=False)
    try:
        os.utime(
            destination,
            (source_date_epoch, source_date_epoch),
            follow_symlinks=False,
        )
    except NotImplementedError:
        _require(not destination.is_symlink(), "build-context destination became a link")
        os.utime(destination, (source_date_epoch, source_date_epoch))
    return digest.hexdigest()


def materialize_runtime_build_context(
    *,
    project_root: Path,
    output_dir: Path,
    manifest_paths: Sequence[Path],
    source_date_epoch: int,
) -> dict[str, object]:
    """Copy exactly the union of canonical path manifests into an empty directory."""

    root_input = Path(project_root)
    _require(root_input.is_dir() and not root_input.is_symlink(), "project root is unsafe")
    root = root_input.resolve(strict=True)
    output_input = Path(output_dir)
    _require(output_input.is_dir() and not output_input.is_symlink(), "output directory is unsafe")
    output = output_input.resolve(strict=True)
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("output directory must be outside project root")
    with os.scandir(output) as entries:
        _require(next(entries, None) is None, "output directory must be empty")
    _require(
        type(source_date_epoch) is int and 0 <= source_date_epoch <= 2_147_483_647,
        "SOURCE_DATE_EPOCH is invalid",
    )
    candidates = tuple(islice(manifest_paths, _MANIFEST_COUNT + 1))
    _require(len(candidates) <= _MANIFEST_COUNT, "manifest count bound exceeded")
    manifests = tuple(Path(value) for value in candidates)
    _require(bool(manifests), "at least one path manifest is required")
    normalized_manifests = tuple(
        Path(os.path.abspath(os.fspath(path))) for path in manifests
    )
    _require(
        len(normalized_manifests) == len(set(normalized_manifests)),
        "duplicate path manifest",
    )

    selected: set[str] = set()
    for manifest in normalized_manifests:
        for relative in _manifest_members(root, manifest):
            if relative not in selected:
                _require(len(selected) < _CONTEXT_FILES, "build-context path union bound exceeded")
                selected.add(relative)
    relative_paths = tuple(sorted(selected))
    _require(bool(relative_paths), "build-context path union is empty")
    held = {
        relative: _physical_member(root, relative)
        for relative in relative_paths
    }

    total_bytes = 0
    for _, expected in held.values():
        size = int(expected.st_size)
        _require(0 <= size <= _MEMBER_BYTES, "build-context member byte bound exceeded")
        total_bytes += size
        _require(total_bytes <= _CONTEXT_BYTES, "build-context byte bound exceeded")

    # Admit every parent and metadata form before the first destination write.
    expected_children: dict[str, dict[str, bool]] = {"": {}}
    row_bytes = 0
    for relative in relative_paths:
        row_bytes += 64 + 2 + len(relative.encode("ascii")) + 1
        _require(row_bytes <= _METADATA_BYTES, "build-context hash rows bound exceeded")
        parts = PurePosixPath(relative).parts
        for index, name in enumerate(parts):
            parent = "/".join(parts[:index])
            directory = index + 1 < len(parts)
            children = expected_children.setdefault(parent, {})
            _require(name not in children or children[name] == directory, "build-context path collision")
            children[name] = directory
        _require(len(expected_children) - 1 <= _CONTEXT_DIRECTORIES, "build-context parent bound exceeded")
    result = {
        "schema_version": 3,
        "artifact_kind": "vast_exact_runtime_build_context_v3",
        "relative_paths": relative_paths,
        "aggregate_sha256": "0" * 64,
        "source_date_epoch": source_date_epoch,
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    _require(len(encoded) + 1 <= _METADATA_BYTES, "build-context result bound exceeded")

    rows = bytearray()
    for relative in relative_paths:
        source, expected = held[relative]
        digest = _copy_held_source(
            source,
            output.joinpath(*PurePosixPath(relative).parts),
            expected=expected,
            source_date_epoch=source_date_epoch,
        )
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))

    for parent, children in expected_children.items():
        seen: set[str] = set()
        with os.scandir(output.joinpath(*PurePosixPath(parent).parts)) as entries:
            for entry in entries:
                _require(
                    entry.name in children and entry.name not in seen,
                    "materialized build-context inventory drifted",
                )
                info = entry.stat(follow_symlinks=False)
                _require(not entry.is_symlink(), "materialized build-context inventory drifted")
                _require(
                    stat.S_ISDIR(info.st_mode) if children[entry.name]
                    else stat.S_ISREG(info.st_mode) and int(info.st_nlink) == 1,
                    "materialized build-context inventory drifted",
                )
                seen.add(entry.name)
        _require(seen == children.keys(), "materialized build-context inventory drifted")
    result["aggregate_sha256"] = hashlib.sha256(rows).hexdigest()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", action="append", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    args = parser.parse_args(argv)
    result = materialize_runtime_build_context(
        project_root=args.project_root,
        output_dir=args.output_dir,
        manifest_paths=tuple(args.manifest),
        source_date_epoch=args.source_date_epoch,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
