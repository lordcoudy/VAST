#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import stat
import tarfile
from pathlib import Path
from typing import Any

import zstandard


class PairArchiveError(RuntimeError):
    pass


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_descendant(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PairArchiveError(f"{label} must be inside run_root") from exc
    if not relative.parts:
        raise PairArchiveError(f"{label} must not equal run_root")
    return resolved


def _archive_members(pair_dir: Path) -> list[Path]:
    members = sorted(
        pair_dir.rglob("*"),
        key=lambda path: path.relative_to(pair_dir).as_posix(),
    )
    for member in members:
        if member.is_symlink():
            raise PairArchiveError(f"pair evidence must not contain symlinks: {member}")
        if not member.is_dir() and not member.is_file():
            raise PairArchiveError(f"unsupported pair evidence entry: {member}")
    return members


def build_pair_archive(
    *,
    pair_dir: Path,
    archive_path: Path,
    compression_level: int = 10,
) -> dict[str, Any]:
    resolved_pair = pair_dir.resolve()
    if not resolved_pair.is_dir():
        raise PairArchiveError(f"pair directory does not exist: {resolved_pair}")
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
    resolved_pair = _assert_descendant(pair_dir, run_root, label="pair_dir")
    if not resolved_pair.is_dir():
        raise PairArchiveError(f"pair directory does not exist: {resolved_pair}")

    resolved_spool = _assert_descendant(spool_root, run_root, label="spool_root")
    try:
        resolved_spool.relative_to(resolved_pair)
    except ValueError:
        pass
    else:
        raise PairArchiveError("spool_root must not be inside pair_dir")

    if Path(remote_name).name != remote_name:
        raise PairArchiveError("remote_name must be a single file name")
    if not remote_name.endswith(".tar.zst"):
        raise PairArchiveError("remote_name must end with .tar.zst")

    resolved_spool.mkdir(parents=True, exist_ok=True)
    archive_path = resolved_spool / remote_name
    archive = build_pair_archive(pair_dir=resolved_pair, archive_path=archive_path)

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

    shutil.rmtree(resolved_pair)
    archive_path.unlink()
    return {
        "status": "uploaded_verified_local_deleted",
        "remote_name": remote_name,
        "size_bytes": archive["size_bytes"],
        "sha256": archive["sha256"],
        "member_count": archive["member_count"],
        "pair_directory_deleted": not resolved_pair.exists(),
        "local_archive_deleted": not archive_path.exists(),
    }
