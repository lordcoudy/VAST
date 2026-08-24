#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tarfile
import uuid
from pathlib import Path
from typing import Any

import zstandard


class PairArchiveError(RuntimeError):
    pass


_PAIR_NAMESPACE = "pairs"
_SPOOL_NAMESPACE = "spool"
_ACCEPTANCE_MARKER = "manifest.json"


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if is_junction(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except (FileNotFoundError, OSError):
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _path_identity(path: Path) -> tuple[int, int, int, int, int, int]:
    metadata = path.lstat()
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(stat.S_IFMT(metadata.st_mode)),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
    )


def _directory_identity(path: Path) -> tuple[int, int, int]:
    identity = _path_identity(path)
    return identity[0], identity[1], identity[2]


def _assert_canonical_directory(path: Path, *, label: str) -> Path:
    lexical = _absolute_lexical(path)
    if lexical == Path(lexical.anchor):
        raise PairArchiveError(f"{label} must not be a filesystem root")
    if _is_reparse_point(lexical):
        raise PairArchiveError(f"{label} must not be a symlink, junction, or reparse point")
    if not lexical.is_dir():
        raise PairArchiveError(f"{label} directory does not exist: {lexical}")
    if lexical.resolve() != lexical:
        raise PairArchiveError(f"{label} must not be an alias")
    return lexical


def _assert_not_cwd_or_parent(path: Path, *, label: str) -> None:
    cwd = Path.cwd().resolve()
    if path == cwd or path in cwd.parents:
        raise PairArchiveError(f"{label} must not be the current directory or its parent")


def _acceptance_marker_sha256(pair_dir: Path) -> str:
    marker = pair_dir / _ACCEPTANCE_MARKER
    if marker.parent != pair_dir:
        raise PairArchiveError("pair acceptance marker escaped pair_dir")
    if _is_reparse_point(marker) or not marker.is_file() or marker.resolve() != marker:
        raise PairArchiveError("pair acceptance marker is missing or unsafe")
    try:
        payload = marker.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairArchiveError("pair acceptance marker is unreadable") from exc
    if not isinstance(value, dict) or value.get("accepted") is not True:
        raise PairArchiveError("pair acceptance marker does not record accepted=true")
    return hashlib.sha256(payload).hexdigest()


def _pair_snapshot(pair_dir: Path) -> str:
    records: list[dict[str, Any]] = []
    for member in _archive_members(pair_dir):
        relative = member.relative_to(pair_dir).as_posix()
        identity = _path_identity(member)
        record: dict[str, Any] = {
            "path": relative,
            "identity": list(identity),
            "kind": "directory" if member.is_dir() else "file",
        }
        if member.is_file():
            record["sha256"] = _sha256_file(member)
            if _path_identity(member) != identity:
                raise PairArchiveError(f"pair evidence changed while hashing: {member}")
        records.append(record)
    payload = json.dumps(
        {
            "root_identity": list(_directory_identity(pair_dir)),
            "acceptance_marker_sha256": _acceptance_marker_sha256(pair_dir),
            "members": records,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _guard_cleanup_directory(
    path: Path,
    *,
    expected_parent: Path,
    expected_prefix: str,
    expected_identity: tuple[int, int, int],
) -> Path:
    parent = _assert_canonical_directory(expected_parent, label="pair cleanup parent")
    lexical = _absolute_lexical(path)
    if lexical.parent != parent:
        raise PairArchiveError("pair cleanup target escaped its expected parent")
    if not lexical.name.startswith(expected_prefix) or lexical.name == expected_prefix:
        raise PairArchiveError("pair cleanup target has an unexpected name")
    _assert_not_cwd_or_parent(lexical, label="pair cleanup target")
    if _is_reparse_point(lexical):
        raise PairArchiveError(
            "pair cleanup target must not be a symlink, junction, or reparse point"
        )
    if not lexical.is_dir() or lexical.resolve() != lexical:
        raise PairArchiveError("pair cleanup target is missing, non-directory, or an alias")
    if _directory_identity(lexical) != expected_identity:
        raise PairArchiveError("pair cleanup target identity changed")
    return lexical


def _guard_archive_cleanup(
    path: Path,
    *,
    expected_parent: Path,
    expected_name: str,
    expected_identity: tuple[int, int, int, int, int, int],
    expected_sha256: str,
) -> Path:
    parent = _assert_canonical_directory(expected_parent, label="archive cleanup parent")
    lexical = _absolute_lexical(path)
    if lexical.parent != parent or lexical.name != expected_name:
        raise PairArchiveError("archive cleanup target is not the expected spool child")
    _assert_not_cwd_or_parent(lexical, label="archive cleanup target")
    if _is_reparse_point(lexical):
        raise PairArchiveError(
            "archive cleanup target must not be a symlink, junction, or reparse point"
        )
    if not lexical.is_file() or lexical.resolve() != lexical:
        raise PairArchiveError("archive cleanup target is missing, non-file, or an alias")
    if _path_identity(lexical) != expected_identity:
        raise PairArchiveError("archive cleanup target identity changed")
    if _sha256_file(lexical) != expected_sha256:
        raise PairArchiveError("archive cleanup target SHA-256 changed")
    return lexical


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_members(pair_dir: Path) -> list[Path]:
    members = sorted(
        pair_dir.rglob("*"),
        key=lambda path: path.relative_to(pair_dir).as_posix(),
    )
    for member in members:
        if _is_reparse_point(member):
            raise PairArchiveError(
                f"pair evidence must not contain symlinks, junctions, or reparse points: {member}"
            )
        if not member.is_dir() and not member.is_file():
            raise PairArchiveError(f"unsupported pair evidence entry: {member}")
    return members


def build_pair_archive(
    *,
    pair_dir: Path,
    archive_path: Path,
    compression_level: int = 10,
) -> dict[str, Any]:
    resolved_pair = _assert_canonical_directory(
        pair_dir,
        label="pair archive source",
    )
    if archive_path.suffixes[-2:] != [".tar", ".zst"]:
        raise PairArchiveError("pair archive must use .tar.zst")
    if archive_path.exists():
        raise PairArchiveError(f"pair archive already exists: {archive_path}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    members = _archive_members(resolved_pair)

    try:
        with archive_path.open("xb") as raw:
            compressor = zstandard.ZstdCompressor(
                level=int(compression_level),
                threads=0,
                write_checksum=True,
                write_content_size=False,
            )
            with compressor.stream_writer(raw, closefd=False) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w|",
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    root_info = tarfile.TarInfo(resolved_pair.name)
                    root_info.type = tarfile.DIRTYPE
                    root_info.mode = 0o755
                    root_info.uid = 0
                    root_info.gid = 0
                    root_info.uname = ""
                    root_info.gname = ""
                    root_info.mtime = 0
                    archive.addfile(root_info)
                    for member in members:
                        relative = member.relative_to(resolved_pair)
                        archive_name = (Path(resolved_pair.name) / relative).as_posix()
                        info = archive.gettarinfo(str(member), arcname=archive_name)
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        info.mtime = 0
                        if member.is_dir():
                            info.mode = 0o755
                            archive.addfile(info)
                            continue
                        info.mode = stat.S_IMODE(member.stat().st_mode) & 0o755
                        with member.open("rb") as source:
                            archive.addfile(info, fileobj=source)
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    return {
        "archive_path": str(archive_path.resolve()),
        "size_bytes": archive_path.stat().st_size,
        "sha256": _sha256_file(archive_path),
        "member_count": len(members) + 1,
        "format": "tar.zst",
        "deterministic_metadata": True,
    }


def drain_pair_to_store(
    *,
    pair_dir: Path,
    run_root: Path,
    spool_root: Path,
    remote_name: str,
    store: Any,
) -> dict[str, Any]:
    lexical_run = _absolute_lexical(run_root)
    lexical_pair = _absolute_lexical(pair_dir)
    try:
        lexical_pair.relative_to(lexical_run)
    except ValueError as exc:
        raise PairArchiveError("pair_dir must be inside run_root") from exc
    resolved_run = _assert_canonical_directory(lexical_run, label="run_root")
    pairs_root = resolved_run / _PAIR_NAMESPACE
    if lexical_pair.parent != pairs_root:
        raise PairArchiveError("pair_dir must be an immediate child of the pairs namespace")
    resolved_pairs = _assert_canonical_directory(pairs_root, label="pairs namespace")
    resolved_pair = _assert_canonical_directory(lexical_pair, label="pair_dir")
    _assert_not_cwd_or_parent(resolved_pair, label="pair cleanup target")

    if Path(remote_name).name != remote_name:
        raise PairArchiveError("remote_name must be a single file name")
    if not remote_name.endswith(".tar.zst"):
        raise PairArchiveError("remote_name must end with .tar.zst")
    if remote_name != f"{resolved_pair.name}.tar.zst":
        raise PairArchiveError("remote_name must be bound to the exact pair directory")

    lexical_spool = _absolute_lexical(spool_root)
    expected_spool = resolved_run / _SPOOL_NAMESPACE
    if lexical_spool != expected_spool:
        raise PairArchiveError("spool_root must be the dedicated run spool namespace")
    lexical_spool.mkdir(parents=False, exist_ok=True)
    resolved_spool = _assert_canonical_directory(lexical_spool, label="spool_root")

    initial_snapshot = _pair_snapshot(resolved_pair)
    pair_identity = _directory_identity(resolved_pair)

    archive_path = resolved_spool / remote_name
    archive = build_pair_archive(pair_dir=resolved_pair, archive_path=archive_path)
    archive_identity = _path_identity(archive_path)

    try:
        remote = store.upload_and_verify(archive_path, remote_name=remote_name)
    except Exception as exc:
        raise PairArchiveError("remote upload/readback verification failed") from exc

    if not isinstance(remote, dict):
        raise PairArchiveError("remote verification returned an invalid result")
    if str(remote.get("remote_name", "")) != remote_name:
        raise PairArchiveError("remote verification returned a different file name")
    if int(remote.get("size_bytes", -1)) != int(archive["size_bytes"]):
        raise PairArchiveError("remote verification size does not match the local archive")
    if str(remote.get("sha256", "")) != str(archive["sha256"]):
        raise PairArchiveError("remote verification SHA-256 does not match the local archive")
    if "verified" not in str(remote.get("status", "")):
        raise PairArchiveError("remote verification status is not verified")

    try:
        current_snapshot = _pair_snapshot(resolved_pair)
    except PairArchiveError as exc:
        raise PairArchiveError(
            "pair evidence changed after archiving; refusing cleanup"
        ) from exc
    if current_snapshot != initial_snapshot:
        raise PairArchiveError("pair evidence changed after archiving; refusing cleanup")
    if _directory_identity(resolved_pair) != pair_identity:
        raise PairArchiveError("pair evidence changed after archiving; refusing cleanup")
    guarded_archive = _guard_archive_cleanup(
        archive_path,
        expected_parent=resolved_spool,
        expected_name=remote_name,
        expected_identity=archive_identity,
        expected_sha256=str(archive["sha256"]),
    )
    quarantine_prefix = f".{resolved_pair.name}.verified-delete."
    quarantine = resolved_pairs / f"{quarantine_prefix}{uuid.uuid4().hex}"
    if quarantine.exists() or quarantine.is_symlink():
        raise PairArchiveError("pair cleanup quarantine collision")
    os.replace(resolved_pair, quarantine)
    guarded_quarantine = _guard_cleanup_directory(
        quarantine,
        expected_parent=resolved_pairs,
        expected_prefix=quarantine_prefix,
        expected_identity=pair_identity,
    )
    if _pair_snapshot(guarded_quarantine) != initial_snapshot:
        raise PairArchiveError("pair evidence changed after quarantine; refusing cleanup")
    shutil.rmtree(guarded_quarantine)
    guarded_archive = _guard_archive_cleanup(
        guarded_archive,
        expected_parent=resolved_spool,
        expected_name=remote_name,
        expected_identity=archive_identity,
        expected_sha256=str(archive["sha256"]),
    )
    guarded_archive.unlink()
    return {
        "status": "uploaded_verified_local_deleted",
        "remote_name": remote_name,
        "size_bytes": archive["size_bytes"],
        "sha256": archive["sha256"],
        "member_count": archive["member_count"],
        "pair_directory_deleted": not resolved_pair.exists() and not quarantine.exists(),
        "local_archive_deleted": not archive_path.exists(),
    }
