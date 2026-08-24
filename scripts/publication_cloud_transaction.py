#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

import zstandard

from publication_archive import (
    PairArchiveError,
    build_pair_archive,
)


TRANSACTION_STATES = (
    "accepted",
    "archive_ready",
    "remote_archive_verified",
    "remote_receipt_verified",
    "local_ledger_committed",
    "local_pruned",
)
_STATE_INDEX = {state: index for index, state in enumerate(TRANSACTION_STATES)}
_GENESIS_HASH = "0" * 64
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_QUALIFICATION_AUTHORITY_FIELDS = frozenset({
    "identity_artifact_binding_sha256",
    "resource_capability_grant_sha256",
    "backend_runtime_grant_sha256",
    "model_parity_grant_sha256",
    "model_parity_acceptance_binding_sha256",
})


class CloudTransactionError(RuntimeError):
    pass


class LedgerIntegrityError(CloudTransactionError):
    pass


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
        os.fsync(handle.fileno())
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise CloudTransactionError(
                "cloud transaction run_root is locked by another controller"
            ) from None
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Windows and some network filesystems do not support directory fsync.
        pass
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise CloudTransactionError(f"immutable local receipt collision: {path.name}")
        return
    _atomic_write_bytes(path, payload)


def _is_link_junction_or_reparse(path: Path) -> bool:
    """Return True for every link-like Windows or POSIX filesystem object."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if int(getattr(metadata, "st_file_attributes", 0)) & reparse_flag:
        return True
    path_junction = getattr(path, "is_junction", None)
    if callable(path_junction):
        try:
            if bool(path_junction()):
                return True
        except OSError:
            return True
    os_junction = getattr(os.path, "isjunction", None)
    if callable(os_junction):
        try:
            if bool(os_junction(path)):
                return True
        except OSError:
            return True
    return False


def _lstat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(getattr(metadata, "st_ctime_ns", 0)),
        int(getattr(metadata, "st_file_attributes", 0)),
        int(getattr(metadata, "st_reparse_tag", 0)),
    )


def _plain_directory_identity(path: Path, *, label: str) -> tuple[int, ...]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise CloudTransactionError(f"{label} does not exist") from None
    if _is_link_junction_or_reparse(path):
        raise CloudTransactionError(f"{label} must not be a link, junction, or reparse point")
    if not stat.S_ISDIR(metadata.st_mode):
        raise CloudTransactionError(f"{label} is not a directory")
    return _lstat_identity(metadata)


def _plain_pair_members(pair_dir: Path) -> list[Path]:
    members: list[Path] = []
    pending = [pair_dir]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name)
        except OSError:
            raise PairArchiveError(f"pair evidence directory is unreadable: {current}") from None
        for entry in entries:
            member = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                raise PairArchiveError(f"pair evidence entry is unreadable: {member}") from None
            if _is_link_junction_or_reparse(member):
                raise PairArchiveError(
                    f"pair evidence must not contain links, junctions, or reparse points: {member}"
                )
            members.append(member)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(member)
            elif not stat.S_ISREG(metadata.st_mode):
                raise PairArchiveError(f"unsupported pair evidence entry: {member}")
    return sorted(members, key=lambda item: item.relative_to(pair_dir).as_posix())


def _expected_pair_members(pair_dir: Path) -> dict[str, tuple[str, int, str | None]]:
    expected: dict[str, tuple[str, int, str | None]] = {
        pair_dir.name: ("dir", 0, None)
    }
    for member in _plain_pair_members(pair_dir):
        name = (Path(pair_dir.name) / member.relative_to(pair_dir)).as_posix()
        if member.is_dir():
            expected[name] = ("dir", 0, None)
        elif member.is_file():
            expected[name] = ("file", member.stat().st_size, _sha256_file(member))
        else:
            raise PairArchiveError(f"unsupported pair evidence entry: {member}")
    return expected


def _safe_archive_name(name: str) -> PurePosixPath:
    parsed = PurePosixPath(name)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise PairArchiveError("pair archive contains an unsafe member path")
    if parsed.as_posix() != name.rstrip("/"):
        raise PairArchiveError("pair archive contains a non-canonical member path")
    return parsed


def _validate_pair_archive(*, archive_path: Path, pair_dir: Path) -> dict[str, Any]:
    if not archive_path.is_file():
        raise PairArchiveError("pair archive does not exist")
    if not pair_dir.is_dir():
        raise PairArchiveError("pair directory does not exist")
    expected = _expected_pair_members(pair_dir)
    observed: set[str] = set()
    try:
        with archive_path.open("rb") as raw:
            with zstandard.ZstdDecompressor().stream_reader(raw) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r|") as archive:
                    for member in archive:
                        canonical = _safe_archive_name(member.name).as_posix()
                        if canonical in observed or canonical not in expected:
                            raise PairArchiveError(
                                "pair archive member set does not match local evidence"
                            )
                        observed.add(canonical)
                        expected_type, expected_size, expected_sha256 = expected[canonical]
                        if member.isdir():
                            if expected_type != "dir":
                                raise PairArchiveError("pair archive member type does not match")
                            continue
                        if not member.isfile() or expected_type != "file":
                            raise PairArchiveError(
                                "pair archive contains an unsupported member type"
                            )
                        if int(member.size) != expected_size:
                            raise PairArchiveError("pair archive member size does not match")
                        source = archive.extractfile(member)
                        if source is None:
                            raise PairArchiveError("pair archive file payload is missing")
                        digest = hashlib.sha256()
                        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                            digest.update(chunk)
                        if digest.hexdigest() != expected_sha256:
                            raise PairArchiveError("pair archive member SHA-256 does not match")
    except PairArchiveError:
        raise
    except Exception:
        raise PairArchiveError("existing spool archive is corrupt or unreadable") from None
    if observed != set(expected):
        raise PairArchiveError("pair archive member set does not match local evidence")
    return {
        "archive_path": str(archive_path.resolve()),
        "size_bytes": archive_path.stat().st_size,
        "sha256": _sha256_file(archive_path),
        "member_count": len(observed),
        "format": "tar.zst",
        "deterministic_metadata": True,
        "status": "reused_and_verified",
    }


def _build_or_reuse_pair_archive(
    *, pair_dir: Path, archive_path: Path, compression_level: int
) -> dict[str, Any]:
    # Reject link-like evidence before either the builder or archive reuse can
    # traverse the pair tree.
    _plain_pair_members(pair_dir)
    if archive_path.exists():
        return _validate_pair_archive(archive_path=archive_path, pair_dir=pair_dir)
    result = build_pair_archive(
        pair_dir=pair_dir,
        archive_path=archive_path,
        compression_level=compression_level,
    )
    return {**result, "status": "built"}


def _restore_pair_archive(
    *, archive_path: Path, destination_root: Path, pair_dir_name: str
) -> dict[str, Any]:
    if not _IDENTIFIER_RE.fullmatch(pair_dir_name):
        raise PairArchiveError("pair_dir_name contains unsupported characters")
    resolved_destination = destination_root.resolve()
    resolved_destination.mkdir(parents=True, exist_ok=True)
    pair_path = resolved_destination / pair_dir_name
    if pair_path.exists():
        try:
            _validate_pair_archive(archive_path=archive_path, pair_dir=pair_path)
        except PairArchiveError:
            raise PairArchiveError("materialize destination collision") from None
        return {"status": "already_materialized_and_verified", "pair_path": str(pair_path)}

    staging = resolved_destination / f".{pair_dir_name}.{uuid.uuid4().hex}.tmp"
    staging.mkdir()
    observed: set[str] = set()
    try:
        with archive_path.open("rb") as raw:
            with zstandard.ZstdDecompressor().stream_reader(raw) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r|") as archive:
                    for member in archive:
                        parsed = _safe_archive_name(member.name)
                        if parsed.parts[0] != pair_dir_name:
                            raise PairArchiveError(
                                "pair archive root identity does not match receipt"
                            )
                        canonical = parsed.as_posix()
                        if canonical in observed:
                            raise PairArchiveError("pair archive contains duplicate members")
                        observed.add(canonical)
                        relative_parts = parsed.parts[1:]
                        if not relative_parts:
                            if not member.isdir():
                                raise PairArchiveError("pair archive root is not a directory")
                            continue
                        target = staging.joinpath(*relative_parts)
                        target.resolve().relative_to(staging.resolve())
                        if member.isdir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        if not member.isfile():
                            raise PairArchiveError(
                                "pair archive contains an unsupported member type"
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(member)
                        if source is None:
                            raise PairArchiveError("pair archive file payload is missing")
                        with target.open("xb") as output:
                            shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                            output.flush()
                            os.fsync(output.fileno())
                        if target.stat().st_size != int(member.size):
                            raise PairArchiveError(
                                "materialized file size does not match archive"
                            )
        if pair_dir_name not in observed:
            raise PairArchiveError("pair archive root member is missing")
        os.replace(staging, pair_path)
        _fsync_directory(resolved_destination)
    except PairArchiveError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise PairArchiveError("pair archive materialization failed") from None
    return {"status": "materialized_and_verified", "pair_path": str(pair_path)}


def _entry_hash(entry_without_hash: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json(entry_without_hash))


def _pair_key(entry: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(entry.get("matrix_sha256", "")),
        str(entry.get("run_id", "")),
        int(entry.get("pair_sequence", 0)),
        str(entry.get("pair_id", "")),
    )


def verify_cloud_ledger(path: Path) -> list[dict[str, Any]]:
    resolved = path.resolve()
    if not resolved.exists():
        return []
    if not resolved.is_file():
        raise LedgerIntegrityError("cloud ledger is not a regular file")
    body = resolved.read_bytes()
    if body and not body.endswith(b"\n"):
        raise LedgerIntegrityError("cloud ledger has a torn trailing entry")

    entries: list[dict[str, Any]] = []
    previous_hash = _GENESIS_HASH
    pair_states: dict[tuple[str, str, int, str], int] = {}
    immutable_fields: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    tracked = (
        "pair_dir_name",
        "pair_attempt",
        "pair_relative_path",
        "acceptance_relative_path",
        "acceptance_sha256",
        "acceptance_size_bytes",
        "archive_remote_name",
        "archive_sha256",
        "archive_size_bytes",
        "archive_member_count",
        "receipt_remote_name",
        "receipt_sha256",
        "receipt_size_bytes",
    )

    for line_number, raw_line in enumerate(body.splitlines(), start=1):
        try:
            decoded = json.loads(raw_line)
        except (TypeError, ValueError, UnicodeDecodeError):
            raise LedgerIntegrityError(
                f"cloud ledger entry {line_number} is not valid JSON"
            ) from None
        if not isinstance(decoded, dict):
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} is not an object")
        entry = dict(decoded)
        if entry.get("schema_version") != "vast-cloud-ledger/v1":
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} has invalid schema")
        if entry.get("entry_seq") != line_number:
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} has invalid sequence")
        if entry.get("previous_entry_sha256") != previous_hash:
            raise LedgerIntegrityError(
                f"cloud ledger entry {line_number} breaks the hash chain"
            )
        observed_hash = str(entry.get("entry_sha256", ""))
        unsigned = dict(entry)
        unsigned.pop("entry_sha256", None)
        if not _SHA256_RE.fullmatch(observed_hash) or _entry_hash(unsigned) != observed_hash:
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} hash is invalid")
        if not _SHA256_RE.fullmatch(str(entry.get("matrix_sha256", ""))):
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} matrix hash is invalid")
        state = str(entry.get("state", ""))
        if state not in _STATE_INDEX:
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} state is invalid")
        try:
            key = _pair_key(entry)
        except (TypeError, ValueError):
            raise LedgerIntegrityError(
                f"cloud ledger entry {line_number} pair identity is invalid"
            ) from None
        if key[2] < 0 or not _IDENTIFIER_RE.fullmatch(key[1]) or not _IDENTIFIER_RE.fullmatch(key[3]):
            raise LedgerIntegrityError(f"cloud ledger entry {line_number} pair identity is invalid")
        expected_state_index = pair_states.get(key, -1) + 1
        if _STATE_INDEX[state] != expected_state_index:
            raise LedgerIntegrityError(
                f"cloud ledger entry {line_number} does not follow the state machine"
            )
        pair_states[key] = expected_state_index

        known = immutable_fields.setdefault(key, {})
        for field in tracked:
            value = entry.get(field)
            if value is None:
                continue
            if field in known and known[field] != value:
                raise LedgerIntegrityError(
                    f"cloud ledger entry {line_number} changes immutable field {field}"
                )
            known[field] = value

        entries.append(entry)
        previous_hash = observed_hash
    return entries


class PublicationCloudTransaction:
    def __init__(
        self,
        *,
        store: Any,
        run_root: Path,
        spool_root: Path | None = None,
        ledger_path: Path | None = None,
        state_root: Path | None = None,
        receipt_root: Path | None = None,
        compression_level: int = 10,
        transition_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self.run_root = run_root.resolve()
        self.spool_root = (spool_root or self.run_root / "cloud_spool").resolve()
        self.ledger_path = (ledger_path or self.run_root / "cloud_ledger.jsonl").resolve()
        self.ledger_pending_path = self.ledger_path.with_name(
            self.ledger_path.name + ".pending"
        )
        self.state_root = (state_root or self.run_root / "cloud_state").resolve()
        self.receipt_root = (receipt_root or self.run_root / "cloud_receipts").resolve()
        self.compression_level = int(compression_level)
        self.transition_hook = transition_hook
        if self.compression_level < 1 or self.compression_level > 22:
            raise CloudTransactionError("compression_level must be between 1 and 22")
        for path, label in (
            (self.spool_root, "spool_root"),
            (self.ledger_path, "ledger_path"),
            (self.ledger_pending_path, "ledger_pending_path"),
            (self.state_root, "state_root"),
            (self.receipt_root, "receipt_root"),
        ):
            self._assert_inside_run(path, label=label, allow_root=False)
        self._entries: list[dict[str, Any]] | None = None
        self._ledger_size: int | None = None

    def _assert_inside_run(self, path: Path, *, label: str, allow_root: bool) -> Path:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.run_root)
        except ValueError:
            raise CloudTransactionError(f"{label} must be inside run_root") from None
        if not allow_root and not relative.parts:
            raise CloudTransactionError(f"{label} must not equal run_root")
        return resolved

    def _assert_canonical_inside_run(
        self,
        path: Path,
        *,
        label: str,
        require_exists: bool,
    ) -> Path:
        candidate_path = Path(path)
        if not candidate_path.is_absolute():
            raise CloudTransactionError(f"{label} must be an absolute path")
        ancestor = candidate_path
        while True:
            if _is_link_junction_or_reparse(ancestor):
                raise CloudTransactionError(
                    f"{label} must not contain a link, junction, or reparse point"
                )
            if ancestor == self.run_root:
                break
            parent = ancestor.parent
            if parent == ancestor:
                raise CloudTransactionError(f"{label} must be inside run_root")
            ancestor = parent
        try:
            resolved = candidate_path.resolve(strict=require_exists)
        except FileNotFoundError:
            raise CloudTransactionError(f"{label} does not exist") from None
        if candidate_path != resolved:
            raise CloudTransactionError(f"{label} must be lexically canonical")
        return self._assert_inside_run(resolved, label=label, allow_root=False)

    @staticmethod
    def _expected_pair_relative_path(
        *, pair_sequence: int, pair_id: str, pair_attempt: int
    ) -> Path:
        return (
            Path("pairs")
            / f"{pair_sequence:04d}_{pair_id}"
            / f"attempt-{pair_attempt:04d}"
        )

    def _assert_exact_pair_directory(
        self,
        pair_dir: Path,
        *,
        pair_sequence: int,
        pair_id: str,
        pair_attempt: int,
        require_exists: bool,
    ) -> Path:
        resolved = self._assert_canonical_inside_run(
            pair_dir,
            label="pair_dir",
            require_exists=require_exists,
        )
        expected = self.run_root / self._expected_pair_relative_path(
            pair_sequence=pair_sequence,
            pair_id=pair_id,
            pair_attempt=pair_attempt,
        )
        if Path(pair_dir) != expected:
            raise CloudTransactionError(
                "pair directory layout does not match the frozen production layout"
            )
        return resolved

    def _read_exact_acceptance_marker(
        self,
        *,
        pair_dir: Path,
        acceptance_manifest: Path,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
    ) -> tuple[bytes, str, int]:
        expected_path = pair_dir / "acceptance.json"
        marker_path = Path(acceptance_manifest)
        if marker_path != expected_path:
            if (
                marker_path.is_absolute()
                and marker_path.resolve(strict=False) == expected_path
            ):
                raise CloudTransactionError(
                    "acceptance manifest path must be lexically canonical"
                )
            raise CloudTransactionError(
                "acceptance_manifest must be the exact pair acceptance marker"
            )
        resolved = self._assert_canonical_inside_run(
            marker_path,
            label="acceptance manifest",
            require_exists=True,
        )
        if resolved != expected_path:
            raise CloudTransactionError(
                "acceptance_manifest must be the exact pair acceptance marker"
            )
        try:
            before = marker_path.lstat()
        except FileNotFoundError:
            raise CloudTransactionError("acceptance manifest does not exist") from None
        if _is_link_junction_or_reparse(marker_path) or not stat.S_ISREG(before.st_mode):
            raise CloudTransactionError("acceptance manifest must be a regular file")
        payload = marker_path.read_bytes()
        try:
            after = marker_path.lstat()
        except FileNotFoundError:
            raise CloudTransactionError("acceptance manifest changed while reading") from None
        if (
            _is_link_junction_or_reparse(marker_path)
            or not stat.S_ISREG(after.st_mode)
            or _lstat_identity(before) != _lstat_identity(after)
            or len(payload) != int(after.st_size)
        ):
            raise CloudTransactionError("acceptance manifest changed while reading")
        digest = _sha256_bytes(payload)
        if expected_sha256 is not None and digest != expected_sha256:
            raise CloudTransactionError("acceptance manifest changed before local prune")
        if expected_size is not None and len(payload) != int(expected_size):
            raise CloudTransactionError("acceptance manifest changed before local prune")
        return payload, digest, len(payload)

    def _validate_recorded_pair_layout(self, snapshot: Mapping[str, Any]) -> tuple[Path, Path]:
        pair_attempt = snapshot.get("pair_attempt")
        if type(pair_attempt) is not int or pair_attempt < 1:
            raise LedgerIntegrityError("cloud ledger pair attempt identity is invalid")
        expected_relative = self._expected_pair_relative_path(
            pair_sequence=int(snapshot["pair_sequence"]),
            pair_id=str(snapshot["pair_id"]),
            pair_attempt=pair_attempt,
        )
        expected_acceptance = expected_relative / "acceptance.json"
        if (
            snapshot.get("pair_relative_path") != expected_relative.as_posix()
            or snapshot.get("acceptance_relative_path") != expected_acceptance.as_posix()
            or snapshot.get("pair_dir_name") != expected_relative.name
        ):
            raise LedgerIntegrityError("cloud ledger pair directory layout is invalid")
        return self.run_root / expected_relative, self.run_root / expected_acceptance

    def _clear_ledger_pending(self) -> None:
        if self.ledger_pending_path.exists():
            self.ledger_pending_path.unlink()
            _fsync_directory(self.ledger_pending_path.parent)

    def _recover_pending_ledger_append(self) -> None:
        if not self.ledger_pending_path.exists():
            return
        if self.ledger_pending_path.is_symlink() or not self.ledger_pending_path.is_file():
            raise LedgerIntegrityError("cloud ledger pending journal is not a regular file")
        try:
            pending = json.loads(self.ledger_pending_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise LedgerIntegrityError("cloud ledger pending journal is invalid") from None
        if type(pending) is not dict or set(pending) != {
            "schema_version",
            "expected_ledger_size",
            "payload_size",
            "payload_sha256",
            "entry",
        }:
            raise LedgerIntegrityError("cloud ledger pending journal schema drifted")
        if pending.get("schema_version") != "vast-cloud-ledger-pending/v1":
            raise LedgerIntegrityError("cloud ledger pending journal version drifted")
        expected_size = pending.get("expected_ledger_size")
        payload_size = pending.get("payload_size")
        expected_sha = pending.get("payload_sha256")
        entry = pending.get("entry")
        if (
            type(expected_size) is not int
            or expected_size < 0
            or type(payload_size) is not int
            or payload_size < 1
            or type(expected_sha) is not str
            or not _SHA256_RE.fullmatch(expected_sha)
            or type(entry) is not dict
        ):
            raise LedgerIntegrityError("cloud ledger pending journal values are invalid")
        payload = _canonical_json(entry) + b"\n"
        if len(payload) != payload_size or _sha256_bytes(payload) != expected_sha:
            raise LedgerIntegrityError("cloud ledger pending journal payload identity drifted")
        actual_size = self.ledger_path.stat().st_size if self.ledger_path.exists() else 0
        if actual_size < expected_size or actual_size > expected_size + payload_size:
            raise LedgerIntegrityError("cloud ledger size is inconsistent with pending append")
        if actual_size == expected_size:
            self._clear_ledger_pending()
            return
        with self.ledger_path.open("rb") as source:
            source.seek(expected_size)
            suffix = source.read()
        expected_prefix = payload[: len(suffix)]
        if suffix != expected_prefix:
            raise LedgerIntegrityError("cloud ledger pending append bytes are inconsistent")
        if len(suffix) == payload_size:
            self._clear_ledger_pending()
            return
        descriptor = os.open(self.ledger_path, os.O_WRONLY)
        try:
            os.ftruncate(descriptor, expected_size)
            os.fsync(descriptor)
        except OSError:
            raise LedgerIntegrityError("cloud ledger partial append recovery failed") from None
        finally:
            os.close(descriptor)
        self._clear_ledger_pending()

    @staticmethod
    def _validate_identity(
        *, matrix_sha256: str, run_id: str, pair_sequence: int, pair_id: str
    ) -> None:
        if not _SHA256_RE.fullmatch(matrix_sha256):
            raise CloudTransactionError("matrix_sha256 must be 64 lowercase hex characters")
        if not _IDENTIFIER_RE.fullmatch(run_id):
            raise CloudTransactionError("run_id contains unsupported characters")
        if not _IDENTIFIER_RE.fullmatch(pair_id):
            raise CloudTransactionError("pair_id contains unsupported characters")
        if type(pair_sequence) is not int or pair_sequence < 0:
            raise CloudTransactionError("pair_sequence must be non-negative")

    def _load_entries(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._entries is None or force:
            self._recover_pending_ledger_append()
            self._entries = verify_cloud_ledger(self.ledger_path)
            self._ledger_size = self.ledger_path.stat().st_size if self.ledger_path.exists() else 0
        return self._entries

    def _latest_for(
        self,
        *,
        matrix_sha256: str,
        run_id: str,
        pair_sequence: int,
        pair_id: str,
    ) -> dict[str, Any] | None:
        entries = self._load_entries()
        if entries:
            identities = {(str(row["matrix_sha256"]), str(row["run_id"])) for row in entries}
            if identities != {(matrix_sha256, run_id)}:
                raise LedgerIntegrityError("run_root cloud ledger belongs to a different run identity")
        key = (matrix_sha256, run_id, int(pair_sequence), pair_id)
        matches = [entry for entry in entries if _pair_key(entry) == key]
        return dict(matches[-1]) if matches else None

    def _state_path(self, *, pair_sequence: int, pair_id: str) -> Path:
        return self.state_root / f"{int(pair_sequence):04d}_{pair_id}.json"

    def _append_transition(self, snapshot: Mapping[str, Any], *, state: str) -> dict[str, Any]:
        if state not in _STATE_INDEX:
            raise CloudTransactionError("unsupported transaction state")
        entries = self._load_entries()
        actual_size = self.ledger_path.stat().st_size if self.ledger_path.exists() else 0
        if actual_size != self._ledger_size:
            raise LedgerIntegrityError("cloud ledger changed outside this controller")
        key = _pair_key(snapshot)
        previous_for_pair = [row for row in entries if _pair_key(row) == key]
        expected_index = len(previous_for_pair)
        if _STATE_INDEX[state] != expected_index:
            raise CloudTransactionError("invalid cloud transaction state transition")

        reserved_fields = {
            "schema_version",
            "entry_seq",
            "previous_entry_sha256",
            "entry_sha256",
            "state",
        }
        snapshot_fields = {
            key_name: value
            for key_name, value in snapshot.items()
            if key_name not in reserved_fields and value is not None
        }
        unsigned: dict[str, Any] = {
            "schema_version": "vast-cloud-ledger/v1",
            "entry_seq": len(entries) + 1,
            "previous_entry_sha256": (
                str(entries[-1]["entry_sha256"]) if entries else _GENESIS_HASH
            ),
            **snapshot_fields,
            "state": state,
        }
        entry = {**unsigned, "entry_sha256": _entry_hash(unsigned)}
        payload = _canonical_json(entry) + b"\n"
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(
            self.ledger_pending_path,
            _canonical_json(
                {
                    "schema_version": "vast-cloud-ledger-pending/v1",
                    "expected_ledger_size": actual_size,
                    "payload_size": len(payload),
                    "payload_sha256": _sha256_bytes(payload),
                    "entry": entry,
                }
            )
            + b"\n",
        )
        existed = self.ledger_path.exists()
        descriptor = os.open(
            self.ledger_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("cloud ledger append made no progress")
                offset += written
            os.fsync(descriptor)
        except BaseException:
            rolled_back = False
            try:
                os.ftruncate(descriptor, actual_size)
                os.fsync(descriptor)
                rolled_back = True
            except OSError:
                pass
            if rolled_back:
                self._clear_ledger_pending()
            raise CloudTransactionError("cloud ledger append failed and was rolled back") from None
        finally:
            os.close(descriptor)
        if not existed:
            _fsync_directory(self.ledger_path.parent)
        entries.append(entry)
        self._ledger_size = actual_size + len(payload)
        state_path = self._state_path(
            pair_sequence=int(entry["pair_sequence"]),
            pair_id=str(entry["pair_id"]),
        )
        _atomic_write_bytes(state_path, _canonical_json(entry) + b"\n")
        self._clear_ledger_pending()
        if self.transition_hook is not None:
            self.transition_hook(state)
        return entry

    @staticmethod
    def _validate_remote_result(
        result: Any,
        *,
        remote_name: str,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise CloudTransactionError("remote verification returned an invalid result")
        if result.get("remote_name") != remote_name:
            raise CloudTransactionError("remote verification returned a different file name")
        if result.get("sha256") != expected_sha256:
            raise CloudTransactionError("remote verification returned a different SHA-256")
        try:
            observed_size = int(result.get("size_bytes", -1))
        except (TypeError, ValueError):
            raise CloudTransactionError("remote verification returned an invalid size") from None
        if observed_size != int(expected_size):
            raise CloudTransactionError("remote verification returned a different size")
        if str(result.get("status", "")) not in {
            "verified",
            "uploaded_and_verified",
            "already_present_and_verified",
            "materialized_and_verified",
            "already_materialized_and_verified",
        }:
            raise CloudTransactionError("remote verification did not confirm integrity")
        return dict(result)

    @staticmethod
    def _remote_base(
        *, matrix_sha256: str, run_id: str, pair_sequence: int, pair_id: str
    ) -> str:
        run_key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
        pair_key = hashlib.sha256(pair_id.encode("utf-8")).hexdigest()[:16]
        return f"{matrix_sha256}_{run_key}_{int(pair_sequence):04d}_{pair_key}"

    def _acceptance_snapshot(
        self,
        *,
        pair_dir: Path,
        acceptance_manifest: Path,
        matrix_sha256: str,
        run_id: str,
        pair_sequence: int,
        pair_id: str,
    ) -> dict[str, Any]:
        resolved_pair = self._assert_canonical_inside_run(
            pair_dir,
            label="pair_dir",
            require_exists=True,
        )
        _plain_directory_identity(resolved_pair, label="accepted pair directory")
        payload, acceptance_sha256, acceptance_size = self._read_exact_acceptance_marker(
            pair_dir=resolved_pair,
            acceptance_manifest=acceptance_manifest,
        )
        try:
            acceptance = json.loads(payload)
        except (TypeError, ValueError, UnicodeDecodeError):
            raise CloudTransactionError("acceptance manifest is not valid JSON") from None
        if not isinstance(acceptance, dict) or acceptance.get("status") != "accepted":
            raise CloudTransactionError("pair acceptance manifest is not accepted")
        required_identity = {
            "schema_version": 2,
            "artifact_kind": "vast_full_publication_pair_acceptance",
            "matrix_sha256": matrix_sha256,
            "run_id": run_id,
            "pair_sequence": pair_sequence,
            "pair_id": pair_id,
        }
        for field, expected in required_identity.items():
            actual = acceptance.get(field)
            if type(actual) is not type(expected) or actual != expected:
                raise CloudTransactionError(
                    f"acceptance manifest {field} does not match transaction identity"
                )
        qualification_authorities = acceptance.get(
            "qualification_authorities"
        )
        if (
            type(qualification_authorities) is not dict
            or set(qualification_authorities)
            != _QUALIFICATION_AUTHORITY_FIELDS
            or any(
                type(value) is not str
                or _SHA256_RE.fullmatch(value) is None
                for value in qualification_authorities.values()
            )
        ):
            raise CloudTransactionError(
                "acceptance manifest qualification authorities are invalid"
            )
        pair_gates = acceptance.get("pair_gates")
        if (
            type(pair_gates) is not dict
            or pair_gates.get(
                "common_identity_and_qualification_authorities"
            ) is not True
        ):
            raise CloudTransactionError(
                "acceptance manifest qualification authority gate is not accepted"
            )
        pair_attempt = acceptance.get("attempt")
        attempt_match = re.fullmatch(r"attempt-([0-9]+)", resolved_pair.name)
        if attempt_match is None:
            raise CloudTransactionError(
                "pair directory layout does not match the frozen production layout"
            )
        if (
            type(pair_attempt) is not int
            or pair_attempt < 1
            or int(attempt_match.group(1)) != pair_attempt
        ):
            raise CloudTransactionError(
                "acceptance manifest attempt does not match transaction identity"
            )
        resolved_pair = self._assert_exact_pair_directory(
            resolved_pair,
            pair_sequence=pair_sequence,
            pair_id=pair_id,
            pair_attempt=pair_attempt,
            require_exists=True,
        )
        resolved_acceptance = resolved_pair / "acceptance.json"
        arm_ids = acceptance.get("arm_ids")
        if (
            type(arm_ids) is not list
            or len(arm_ids) != 2
            or any(type(arm_id) is not str or not arm_id for arm_id in arm_ids)
            or len(set(arm_ids)) != 2
        ):
            raise CloudTransactionError(
                "acceptance manifest arm_ids must contain two unique arm identifiers"
            )
        return {
            "matrix_sha256": matrix_sha256,
            "run_id": run_id,
            "pair_sequence": int(pair_sequence),
            "pair_id": pair_id,
            "pair_dir_name": resolved_pair.name,
            "pair_attempt": pair_attempt,
            "pair_relative_path": resolved_pair.relative_to(self.run_root).as_posix(),
            "acceptance_relative_path": resolved_acceptance.relative_to(self.run_root).as_posix(),
            "acceptance_sha256": acceptance_sha256,
            "acceptance_size_bytes": acceptance_size,
        }

    def _verify_resume_inputs(
        self,
        snapshot: Mapping[str, Any],
        *,
        pair_dir: Path,
        acceptance_manifest: Path,
    ) -> None:
        expected_pair, expected_acceptance = self._validate_recorded_pair_layout(snapshot)
        if Path(pair_dir) != expected_pair:
            raise CloudTransactionError("pair_dir does not match the durable transaction identity")
        pair_exists = expected_pair.exists() or _is_link_junction_or_reparse(expected_pair)
        resolved_pair = self._assert_exact_pair_directory(
            pair_dir,
            pair_sequence=int(snapshot["pair_sequence"]),
            pair_id=str(snapshot["pair_id"]),
            pair_attempt=int(snapshot["pair_attempt"]),
            require_exists=pair_exists,
        )
        if str(snapshot["state"]) == "local_pruned":
            return
        if _STATE_INDEX[str(snapshot["state"])] >= _STATE_INDEX["local_ledger_committed"]:
            # A crash while pruning can leave either a partial directory or no directory.
            return
        if not pair_exists:
            raise CloudTransactionError("local pair evidence is missing before durable prune")
        _plain_directory_identity(resolved_pair, label="recorded pair directory")
        if resolved_pair.name != snapshot.get("pair_dir_name"):
            raise CloudTransactionError("pair directory identity changed during resume")
        if Path(acceptance_manifest) != expected_acceptance:
            raise CloudTransactionError(
                "acceptance_manifest does not match the durable transaction identity"
            )
        self._read_exact_acceptance_marker(
            pair_dir=resolved_pair,
            acceptance_manifest=expected_acceptance,
            expected_sha256=str(snapshot["acceptance_sha256"]),
            expected_size=int(snapshot["acceptance_size_bytes"]),
        )

    def commit_pair(
        self,
        *,
        pair_dir: Path,
        acceptance_manifest: Path,
        matrix_sha256: str,
        run_id: str,
        pair_sequence: int,
        pair_id: str,
    ) -> dict[str, Any]:
        with _exclusive_file_lock(self.run_root / ".cloud_transaction.lock"):
            self._entries = None
            self._ledger_size = None
            return self._commit_pair_unlocked(
                pair_dir=pair_dir,
                acceptance_manifest=acceptance_manifest,
                matrix_sha256=matrix_sha256,
                run_id=run_id,
                pair_sequence=pair_sequence,
                pair_id=pair_id,
            )

    def _commit_pair_unlocked(
        self,
        *,
        pair_dir: Path,
        acceptance_manifest: Path,
        matrix_sha256: str,
        run_id: str,
        pair_sequence: int,
        pair_id: str,
    ) -> dict[str, Any]:
        self._validate_identity(
            matrix_sha256=matrix_sha256,
            run_id=run_id,
            pair_sequence=pair_sequence,
            pair_id=pair_id,
        )
        current = self._latest_for(
            matrix_sha256=matrix_sha256,
            run_id=run_id,
            pair_sequence=pair_sequence,
            pair_id=pair_id,
        )
        resume_requires_remote_reverify = bool(
            current is not None
            and _STATE_INDEX[str(current["state"])]
            >= _STATE_INDEX["remote_receipt_verified"]
        )
        if current is None:
            accepted = self._acceptance_snapshot(
                pair_dir=pair_dir,
                acceptance_manifest=acceptance_manifest,
                matrix_sha256=matrix_sha256,
                run_id=run_id,
                pair_sequence=pair_sequence,
                pair_id=pair_id,
            )
            current = self._append_transition(accepted, state="accepted")
        else:
            self._verify_resume_inputs(
                current,
                pair_dir=pair_dir,
                acceptance_manifest=acceptance_manifest,
            )
        if current["state"] == "local_pruned":
            return self._result(current)

        recorded_pair, _ = self._validate_recorded_pair_layout(current)
        if Path(pair_dir) != recorded_pair:
            raise CloudTransactionError("pair_dir does not match the durable transaction identity")
        pair_present = recorded_pair.exists() or _is_link_junction_or_reparse(recorded_pair)
        resolved_pair = self._assert_exact_pair_directory(
            pair_dir,
            pair_sequence=pair_sequence,
            pair_id=pair_id,
            pair_attempt=int(current["pair_attempt"]),
            require_exists=pair_present,
        )
        remote_base = self._remote_base(
            matrix_sha256=matrix_sha256,
            run_id=run_id,
            pair_sequence=pair_sequence,
            pair_id=pair_id,
        )

        if _STATE_INDEX[str(current["state"])] < _STATE_INDEX["archive_ready"]:
            self.spool_root.mkdir(parents=True, exist_ok=True)
            archive_path = self.spool_root / f"{remote_base}.tar.zst"
            try:
                archive = _build_or_reuse_pair_archive(
                    pair_dir=resolved_pair,
                    archive_path=archive_path,
                    compression_level=self.compression_level,
                )
            except PairArchiveError:
                raise
            archive_sha256 = str(archive["sha256"])
            archive_remote_name = f"{remote_base}_{archive_sha256}.tar.zst"
            current = self._append_transition(
                {
                    **current,
                    "local_archive_path": str(archive_path),
                    "archive_remote_name": archive_remote_name,
                    "archive_sha256": archive_sha256,
                    "archive_size_bytes": int(archive["size_bytes"]),
                    "archive_member_count": int(archive["member_count"]),
                    "archive_format": str(archive["format"]),
                },
                state="archive_ready",
            )

        archive_path = Path(str(current["local_archive_path"]))
        if _STATE_INDEX[str(current["state"])] < _STATE_INDEX["remote_archive_verified"]:
            if not archive_path.is_file():
                raise CloudTransactionError("local spool archive is missing before upload")
            if (
                archive_path.stat().st_size != int(current["archive_size_bytes"])
                or _sha256_file(archive_path) != current["archive_sha256"]
            ):
                raise CloudTransactionError("local spool archive changed before upload")
            remote = self.store.upload_and_verify(
                archive_path,
                remote_name=str(current["archive_remote_name"]),
            )
            self._validate_remote_result(
                remote,
                remote_name=str(current["archive_remote_name"]),
                expected_sha256=str(current["archive_sha256"]),
                expected_size=int(current["archive_size_bytes"]),
            )
            current = self._append_transition(current, state="remote_archive_verified")

        if _STATE_INDEX[str(current["state"])] < _STATE_INDEX["remote_receipt_verified"]:
            receipt_payload = {
                "schema_version": "vast-cloud-pair-receipt/v1",
                "matrix_sha256": matrix_sha256,
                "run_id": run_id,
                "pair_sequence": int(pair_sequence),
                "pair_id": pair_id,
                "pair_dir_name": str(current["pair_dir_name"]),
                "acceptance": {
                    "sha256": str(current["acceptance_sha256"]),
                    "size_bytes": int(current["acceptance_size_bytes"]),
                },
                "archive": {
                    "remote_name": str(current["archive_remote_name"]),
                    "sha256": str(current["archive_sha256"]),
                    "size_bytes": int(current["archive_size_bytes"]),
                    "member_count": int(current["archive_member_count"]),
                    "format": str(current["archive_format"]),
                },
                "remote_archive_status": "verified",
            }
            receipt_bytes = _canonical_json(receipt_payload) + b"\n"
            receipt_sha256 = _sha256_bytes(receipt_bytes)
            receipt_remote_name = f"{remote_base}_{receipt_sha256}.receipt.json"
            receipt_path = self.receipt_root / receipt_remote_name
            _write_immutable_bytes(receipt_path, receipt_bytes)
            remote = self.store.upload_and_verify(
                receipt_path,
                remote_name=receipt_remote_name,
            )
            self._validate_remote_result(
                remote,
                remote_name=receipt_remote_name,
                expected_sha256=receipt_sha256,
                expected_size=len(receipt_bytes),
            )
            current = self._append_transition(
                {
                    **current,
                    "local_receipt_path": str(receipt_path),
                    "receipt_remote_name": receipt_remote_name,
                    "receipt_sha256": receipt_sha256,
                    "receipt_size_bytes": len(receipt_bytes),
                },
                state="remote_receipt_verified",
            )

        if _STATE_INDEX[str(current["state"])] < _STATE_INDEX["local_ledger_committed"]:
            current = self._append_transition(current, state="local_ledger_committed")

        if _STATE_INDEX[str(current["state"])] < _STATE_INDEX["local_pruned"]:
            if current["state"] != "local_ledger_committed":
                raise CloudTransactionError("local prune is not backed by a durable ledger entry")
            prune_target, recorded_acceptance = self._validate_recorded_pair_layout(current)
            if prune_target != resolved_pair or Path(pair_dir) != prune_target:
                raise CloudTransactionError("pair path changed before local prune")
            if resume_requires_remote_reverify:
                archive_remote = self.store.verify_remote(
                    str(current["archive_remote_name"]),
                    expected_sha256=str(current["archive_sha256"]),
                    expected_size=int(current["archive_size_bytes"]),
                )
                receipt_remote = self.store.verify_remote(
                    str(current["receipt_remote_name"]),
                    expected_sha256=str(current["receipt_sha256"]),
                    expected_size=int(current["receipt_size_bytes"]),
                )
                self._validate_remote_result(
                    archive_remote,
                    remote_name=str(current["archive_remote_name"]),
                    expected_sha256=str(current["archive_sha256"]),
                    expected_size=int(current["archive_size_bytes"]),
                )
                self._validate_remote_result(
                    receipt_remote,
                    remote_name=str(current["receipt_remote_name"]),
                    expected_sha256=str(current["receipt_sha256"]),
                    expected_size=int(current["receipt_size_bytes"]),
                )
            target_present = prune_target.exists() or _is_link_junction_or_reparse(
                prune_target
            )
            if target_present:
                self._assert_exact_pair_directory(
                    prune_target,
                    pair_sequence=pair_sequence,
                    pair_id=pair_id,
                    pair_attempt=int(current["pair_attempt"]),
                    require_exists=True,
                )
                identity_before_validation = _plain_directory_identity(
                    prune_target,
                    label="recorded prune target",
                )
                self._read_exact_acceptance_marker(
                    pair_dir=prune_target,
                    acceptance_manifest=recorded_acceptance,
                    expected_sha256=str(current["acceptance_sha256"]),
                    expected_size=int(current["acceptance_size_bytes"]),
                )
                if not archive_path.is_file():
                    raise CloudTransactionError("local spool archive is missing before prune")
                try:
                    _validate_pair_archive(
                        archive_path=archive_path,
                        pair_dir=prune_target,
                    )
                except PairArchiveError:
                    raise CloudTransactionError(
                        "local pair evidence changed after archive sealing"
                    ) from None
                identity_immediately_before_prune = _plain_directory_identity(
                    prune_target,
                    label="recorded prune target",
                )
                if identity_immediately_before_prune != identity_before_validation:
                    raise CloudTransactionError(
                        "pair directory lstat identity changed before local prune"
                    )
                self._read_exact_acceptance_marker(
                    pair_dir=prune_target,
                    acceptance_manifest=recorded_acceptance,
                    expected_sha256=str(current["acceptance_sha256"]),
                    expected_size=int(current["acceptance_size_bytes"]),
                )
                if (
                    _plain_directory_identity(
                        prune_target,
                        label="recorded prune target",
                    )
                    != identity_immediately_before_prune
                ):
                    raise CloudTransactionError(
                        "pair directory lstat identity changed before local prune"
                    )
                shutil.rmtree(prune_target)
            archive_path.unlink(missing_ok=True)
            current = self._append_transition(current, state="local_pruned")
        return self._result(current)

    @staticmethod
    def _result(current: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "state": str(current["state"]),
            "matrix_sha256": str(current["matrix_sha256"]),
            "run_id": str(current["run_id"]),
            "pair_sequence": int(current["pair_sequence"]),
            "pair_id": str(current["pair_id"]),
            "acceptance_sha256": str(current["acceptance_sha256"]),
            "archive_remote_name": str(current["archive_remote_name"]),
            "archive_sha256": str(current["archive_sha256"]),
            "archive_size_bytes": int(current["archive_size_bytes"]),
            "receipt_remote_name": str(current["receipt_remote_name"]),
            "receipt_sha256": str(current["receipt_sha256"]),
            "receipt_size_bytes": int(current["receipt_size_bytes"]),
            "local_archive_path": str(current["local_archive_path"]),
            "local_receipt_path": str(current["local_receipt_path"]),
            "ledger_entry_sha256": str(current["entry_sha256"]),
        }

    def _latest_by_pair(self, *, pair_sequence: int, pair_id: str) -> dict[str, Any]:
        entries = self._load_entries(force=True)
        matches = [
            row
            for row in entries
            if int(row["pair_sequence"]) == int(pair_sequence) and row["pair_id"] == pair_id
        ]
        if not matches:
            raise CloudTransactionError("pair is absent from the cloud ledger")
        identities = {(_pair_key(row)[0], _pair_key(row)[1]) for row in matches}
        if len(identities) != 1:
            raise LedgerIntegrityError("pair identity is ambiguous in the cloud ledger")
        return dict(matches[-1])

    def verify_pair_remote(self, *, pair_sequence: int, pair_id: str) -> dict[str, Any]:
        current = self._latest_by_pair(pair_sequence=pair_sequence, pair_id=pair_id)
        if _STATE_INDEX[str(current["state"])] < _STATE_INDEX["remote_receipt_verified"]:
            raise CloudTransactionError("pair has no verified remote receipt")
        archive = self.store.verify_remote(
            str(current["archive_remote_name"]),
            expected_sha256=str(current["archive_sha256"]),
            expected_size=int(current["archive_size_bytes"]),
        )
        receipt = self.store.verify_remote(
            str(current["receipt_remote_name"]),
            expected_sha256=str(current["receipt_sha256"]),
            expected_size=int(current["receipt_size_bytes"]),
        )
        self._validate_remote_result(
            archive,
            remote_name=str(current["archive_remote_name"]),
            expected_sha256=str(current["archive_sha256"]),
            expected_size=int(current["archive_size_bytes"]),
        )
        self._validate_remote_result(
            receipt,
            remote_name=str(current["receipt_remote_name"]),
            expected_sha256=str(current["receipt_sha256"]),
            expected_size=int(current["receipt_size_bytes"]),
        )
        return {**self._result(current), "remote_status": "verified"}

    def materialize_pair(
        self,
        *,
        pair_sequence: int,
        pair_id: str,
        destination_root: Path,
    ) -> dict[str, Any]:
        current = self._latest_by_pair(pair_sequence=pair_sequence, pair_id=pair_id)
        self.verify_pair_remote(pair_sequence=pair_sequence, pair_id=pair_id)
        destination = destination_root.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".vast-materialize-", dir=destination
        ) as temporary_root:
            temporary_archive = Path(temporary_root) / "pair.tar.zst"
            materialized = self.store.materialize_remote(
                str(current["archive_remote_name"]),
                destination=temporary_archive,
                expected_sha256=str(current["archive_sha256"]),
                expected_size=int(current["archive_size_bytes"]),
            )
            self._validate_remote_result(
                materialized,
                remote_name=str(current["archive_remote_name"]),
                expected_sha256=str(current["archive_sha256"]),
                expected_size=int(current["archive_size_bytes"]),
            )
            restored = _restore_pair_archive(
                archive_path=temporary_archive,
                destination_root=destination,
                pair_dir_name=str(current["pair_dir_name"]),
            )
        return {
            **self._result(current),
            "pair_path": str(restored["pair_path"]),
            "materialize_status": str(restored["status"]),
        }
