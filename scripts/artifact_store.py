"""Shared held-file upload and durable remote materialization primitives."""
from __future__ import annotations
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any
try:
    import fcntl
except ImportError:
    fcntl = None
from publication_physical_io_v1 import PhysicalRootCustodyV1, PublicationPhysicalIoV1Error

class ArtifactStoreError(RuntimeError):
    pass


class ArtifactIntegrityError(ArtifactStoreError):
    pass


class ArtifactPermanentError(ArtifactIntegrityError):
    """Permanent transport/configuration rejection, distinct from transient IO."""


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


_MATERIALIZATION_JOURNAL_ROOT = ".seafile-materialization-v1"
_MATERIALIZATION_INTENT = "intent.json"
_MATERIALIZATION_LOCK = ".lock"
_MATERIALIZATION_STAGE = "payload.stage"
_RENAME_NOREPLACE = 1
_RENAMEAT2: Any | None = None


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _file_inode(metadata: os.stat_result) -> tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _regular_file_snapshot(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(metadata.st_nlink),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
        int(getattr(metadata, "st_uid", 0)),
        int(getattr(metadata, "st_gid", 0)),
        int(getattr(metadata, "st_file_attributes", 0)),
        int(getattr(metadata, "st_reparse_tag", 0)),
    )


def _directory_inode(metadata: os.stat_result) -> tuple[int, int]:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or int(getattr(metadata, "st_file_attributes", 0)) & 0x400
    ):
        raise ArtifactIntegrityError("materialize directory custody is unsafe")
    return _file_inode(metadata)


def _open_directory_at(parent_fd: int, name: str, *, label: str) -> int:
    descriptor = -1
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _directory_inode(named)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if _directory_inode(named) != _directory_inode(opened):
            raise ArtifactIntegrityError(f"{label} changed while opening")
        return descriptor
    except ArtifactStoreError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        raise ArtifactIntegrityError(f"{label} could not be opened safely") from None


def _verify_directory_at(
    parent_fd: int,
    name: str,
    descriptor: int,
    *,
    label: str,
) -> None:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError:
        raise ArtifactIntegrityError(f"{label} changed during custody") from None
    if _directory_inode(named) != _directory_inode(opened):
        raise ArtifactIntegrityError(f"{label} changed during custody")


def _rename_noreplace_at(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> bool:
    """Try Linux renameat2(RENAME_NOREPLACE); False selects hard-link fallback."""

    global _RENAMEAT2
    if _RENAMEAT2 is False:
        return False
    if _RENAMEAT2 is None:
        library = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = library.renameat2
        except AttributeError:
            _RENAMEAT2 = False
            return False
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        _RENAMEAT2 = renameat2
    ctypes.set_errno(0)
    result = int(
        _RENAMEAT2(
            source_fd,
            os.fsencode(source_name),
            destination_fd,
            os.fsencode(destination_name),
            _RENAME_NOREPLACE,
        )
    )
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number))
    if error_number in {
        errno.EINVAL,
        errno.ENOSYS,
        errno.EXDEV,
        errno.EOPNOTSUPP,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
    }:
        return False
    raise OSError(error_number, os.strerror(error_number))


def _hash_open_file(
    descriptor: int,
    *,
    chunk_size: int,
    check=None,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        if check is not None:
            check()
        chunk = os.read(descriptor, chunk_size)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return total, digest.hexdigest()


def _open_verified_file_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
    expected_size: int,
    expected_sha256: str,
    expected_inode: tuple[int, int] | None = None,
    allowed_links: frozenset[int] = frozenset({1}),
    chunk_size: int,
) -> tuple[int, tuple[int, int]]:
    descriptor = -1
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(named.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or int(named.st_nlink) not in allowed_links
            or int(named.st_size) != expected_size
        ):
            raise ArtifactIntegrityError(f"{label} physical identity is invalid")
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_NONBLOCK", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        inode = _file_inode(opened)
        if _file_inode(named) != inode or (
            expected_inode is not None and inode != expected_inode
        ):
            raise ArtifactIntegrityError(f"{label} inode changed while opening")
        size, digest = _hash_open_file(descriptor, chunk_size=chunk_size)
        after_fd = os.fstat(descriptor)
        after_name = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_inode(after_fd) != inode
            or _file_inode(after_name) != inode
            or int(after_fd.st_nlink) not in allowed_links
            or int(after_name.st_nlink) not in allowed_links
            or int(after_fd.st_size) != expected_size
            or int(after_name.st_size) != expected_size
            or size != expected_size
            or digest != expected_sha256
        ):
            raise ArtifactIntegrityError(f"{label} bytes or inode changed")
        os.fsync(descriptor)
        return descriptor, inode
    except ArtifactStoreError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        raise ArtifactIntegrityError(f"{label} could not be read safely") from None


def _materialization_key(
    *, remote_name: str, target_name: str, expected_sha256: str, expected_size: int
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "expected_sha256": expected_sha256,
                "expected_size": expected_size,
                "remote_name": remote_name,
                "target_name": target_name,
            }
        )
    ).hexdigest()


def upload_and_verify(
    self,
    local_path: Path,
    *,
    remote_name: str | None = None,
    check_existing: bool = True,
) -> dict[str, Any]:
    lexical = Path(os.path.abspath(os.fspath(local_path)))
    parent = lexical.parent
    try:
        resolved_parent = parent.resolve(strict=True)
        parent_before = parent.lstat()
    except OSError:
        raise ArtifactStoreError("local upload source is unavailable") from None
    if resolved_parent != parent or lexical != resolved_parent / lexical.name:
        raise ArtifactStoreError("local upload source parent is redirected")
    _directory_inode(parent_before)
    name = remote_name or lexical.name
    self._validate_remote_name(name)
    parent_fd = source_fd = -1
    try:
        parent_fd = os.open(
            resolved_parent,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        if _directory_inode(os.fstat(parent_fd)) != _directory_inode(parent_before):
            raise ArtifactStoreError(
                "local upload source parent changed while opening"
            )
        named = os.stat(
            lexical.name, dir_fd=parent_fd, follow_symlinks=False
        )
        if (
            not stat.S_ISREG(named.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or int(named.st_nlink) != 1
        ):
            raise ArtifactStoreError(
                "local upload source is not one physical file"
            )
        source_fd = os.open(
            lexical.name,
            os.O_RDONLY
            | int(getattr(os, "O_NONBLOCK", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(source_fd)
        source_snapshot = _regular_file_snapshot(opened)
        if _regular_file_snapshot(named) != source_snapshot:
            raise ArtifactStoreError(
                "local upload source changed while opening"
            )
        if hasattr(self, "_validate_source_size"):
            self._validate_source_size(int(opened.st_size))
        size, digest = _hash_open_file(
            source_fd, chunk_size=self.chunk_size, check=getattr(self, "_check_deadline", None)
        )
        if size != int(opened.st_size) or (
            _regular_file_snapshot(os.fstat(source_fd)) != source_snapshot
        ):
            raise ArtifactStoreError(
                "local upload source changed while hashing"
            )
        if self.upload_physical_fault is not None:
            self.upload_physical_fault("post_digest_pre_upload", lexical)
        named_before_upload = os.stat(
            lexical.name, dir_fd=parent_fd, follow_symlinks=False
        )
        held_size, held_digest = _hash_open_file(
            source_fd, chunk_size=self.chunk_size, check=getattr(self, "_check_deadline", None)
        )
        if (
            _regular_file_snapshot(named_before_upload) != source_snapshot
            or _regular_file_snapshot(os.fstat(source_fd)) != source_snapshot
            or held_size != size
            or held_digest != digest
        ):
            raise ArtifactStoreError(
                "local upload source was rebound or mutated before upload"
            )

        if check_existing and name in self.list_remote_files():
            verified = self.verify_remote(
                name,
                expected_sha256=digest,
                expected_size=size,
            )
            return {**verified, "status": "already_present_and_verified"}

        self._upload_held_file(lexical, name, source_fd=source_fd, source_size=size)
        if (_regular_file_snapshot(os.fstat(source_fd)) != source_snapshot
                or _regular_file_snapshot(os.stat(lexical.name, dir_fd=parent_fd,
                                                  follow_symlinks=False)) != source_snapshot):
            raise ArtifactIntegrityError("held upload source changed during streaming")
        after_size, after_digest = _hash_open_file(source_fd, chunk_size=self.chunk_size, check=getattr(self, "_check_deadline", None))
        if after_size != size or after_digest != digest:
            raise ArtifactIntegrityError("held upload bytes changed during streaming")
        verified = self.verify_remote(
            name,
            expected_sha256=digest,
            expected_size=size,
        )
        return {**verified, "status": "uploaded_and_verified"}
    except ArtifactStoreError:
        raise
    except OSError:
        raise ArtifactStoreError(
            "local upload source physical custody failed"
        ) from None
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if parent_fd >= 0:
            os.close(parent_fd)

def materialize_remote(
    self,
    remote_name: str,
    *,
    destination: Path,
    expected_sha256: str,
    expected_size: int,
    journal_root: str,
    intent_kind: str,
    rename_noreplace: Any,
) -> dict[str, Any]:
    """Download and durably publish one ledger-pinned remote object.

    The download inode stays open from the first byte through digest,
    durability, and no-replace publication.  A deterministic immutable
    intent binds the staging inode, so a retry can resume a hard-crash
    window but cannot adopt a same-UID path replacement.
    """

    self._validate_remote_name(remote_name)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ArtifactIntegrityError("expected SHA-256 must be 64 lowercase hex characters")
    if type(expected_size) is not int or expected_size < 0:
        raise ArtifactIntegrityError("expected materialize size is invalid")
    if os.name != "posix" or fcntl is None:
        raise ArtifactIntegrityError(
            "canonical remote materialization requires WSL POSIX custody"
        )

    lexical_target = Path(os.path.abspath(os.fspath(destination)))
    lexical_parent = lexical_target.parent
    lexical_parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved_parent = lexical_parent.resolve(strict=True)
        parent_before = lexical_parent.lstat()
    except OSError:
        raise ArtifactIntegrityError(
            "materialize destination parent is unavailable"
        ) from None
    if (
        resolved_parent != lexical_parent
        or lexical_target != resolved_parent / lexical_target.name
    ):
        raise ArtifactIntegrityError(
            "materialize destination parent is redirected"
        )
    parent_inode = _directory_inode(parent_before)
    target = resolved_parent / lexical_target.name

    remote = self.list_remote_files().get(remote_name)
    if remote is None:
        raise ArtifactIntegrityError("remote artifact is missing")
    try:
        listed_size = int(remote.get("size"))
    except (TypeError, ValueError):
        raise ArtifactIntegrityError("remote artifact size is invalid") from None
    if listed_size != int(expected_size):
        raise ArtifactIntegrityError("remote artifact size does not match receipt")

    storage_binding = self.materialization_binding(remote_name)
    transaction_key = _materialization_key(
        remote_name=remote_name,
        target_name=target.name,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
    )
    if storage_binding:
        transaction_key = hashlib.sha256(_canonical_json({"legacy_key": transaction_key, "storage": storage_binding})).hexdigest()
    transaction_relative = f"{journal_root}/{transaction_key}"
    intent_relative = f"{transaction_relative}/{_MATERIALIZATION_INTENT}"
    stage = resolved_parent / transaction_relative / _MATERIALIZATION_STAGE
    root_fd = journal_fd = transaction_fd = lock_fd = stage_fd = final_fd = -1
    try:
        with PhysicalRootCustodyV1.open(
            resolved_parent,
            label="Seafile materialize destination parent",
        ) as custody:
            custody.ensure_directory_owned(
                journal_root,
                label="Seafile materialization journal root",
            )
            custody.ensure_directory_owned(
                transaction_relative,
                label="Seafile materialization transaction",
            )
            for relative, label in (
                (
                    journal_root,
                    "Seafile materialization journal root",
                ),
                (transaction_relative, "Seafile materialization transaction"),
            ):
                mode, _identity = custody.stat_directory_identity(
                    relative, label=label
                )
                if custody.permission_modes_enforced and mode != 0o700:
                    raise ArtifactIntegrityError(f"{label} mode drifted")

            root_fd = os.open(
                resolved_parent,
                os.O_RDONLY
                | int(getattr(os, "O_DIRECTORY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            if _directory_inode(os.fstat(root_fd)) != parent_inode:
                raise ArtifactIntegrityError(
                    "materialize destination parent changed while opening"
                )
            journal_fd = _open_directory_at(
                root_fd,
                journal_root,
                label="Seafile materialization journal root",
            )
            transaction_fd = _open_directory_at(
                journal_fd,
                transaction_key,
                label="Seafile materialization transaction",
            )
            lock_fd = os.open(
                _MATERIALIZATION_LOCK,
                os.O_RDWR
                | os.O_CREAT
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                0o600,
                dir_fd=transaction_fd,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            os.fchmod(lock_fd, 0o600)
            os.ftruncate(lock_fd, 0)
            os.fsync(lock_fd)
            lock_named = os.stat(
                _MATERIALIZATION_LOCK,
                dir_fd=transaction_fd,
                follow_symlinks=False,
            )
            lock_opened = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_opened.st_mode)
                or int(lock_opened.st_nlink) != 1
                or int(lock_opened.st_size) != 0
                or _file_inode(lock_named) != _file_inode(lock_opened)
            ):
                raise ArtifactIntegrityError(
                    "Seafile materialization lock identity drifted"
                )
            _verify_directory_at(
                root_fd,
                journal_root,
                journal_fd,
                label="Seafile materialization journal root",
            )
            _verify_directory_at(
                journal_fd,
                transaction_key,
                transaction_fd,
                label="Seafile materialization transaction",
            )
            custody.verify()

            entries = set(os.listdir(transaction_fd))
            allowed_entries = {
                _MATERIALIZATION_LOCK,
                _MATERIALIZATION_INTENT,
                _MATERIALIZATION_STAGE,
            }
            if not entries <= allowed_entries:
                raise ArtifactIntegrityError(
                    "Seafile materialization transaction contains foreign entries"
                )

            intent: dict[str, Any] | None = None
            intent_names = custody.list_directory_names(
                transaction_relative,
                label="Seafile materialization transaction",
            )
            if _MATERIALIZATION_INTENT in intent_names:
                descriptor, payload, _intent_inode = custody.read_descriptor_identity(
                    intent_relative,
                    label="Seafile materialization intent",
                    maximum=64 * 1024,
                    capture=True,
                )
                if payload is None:
                    raise ArtifactIntegrityError(
                        "Seafile materialization intent is unreadable"
                    )
                try:
                    decoded = json.loads(payload)
                except (TypeError, ValueError, UnicodeDecodeError):
                    raise ArtifactIntegrityError(
                        "Seafile materialization intent is invalid"
                    ) from None
                expected_fields = {
                    "schema_version",
                    "remote_name",
                    "target_name",
                    "expected_sha256",
                    "expected_size",
                    "stage_name",
                    "stage_inode",
                }
                if storage_binding:
                    expected_fields.add("storage_binding")
                if (
                    type(decoded) is not dict
                    or set(decoded) != expected_fields
                    or (storage_binding and decoded.get("storage_binding") != storage_binding)
                    or decoded.get("schema_version")
                    != intent_kind
                    or decoded.get("remote_name") != remote_name
                    or decoded.get("target_name") != target.name
                    or decoded.get("expected_sha256") != expected_sha256
                    or decoded.get("expected_size") != expected_size
                    or decoded.get("stage_name") != _MATERIALIZATION_STAGE
                    or type(decoded.get("stage_inode")) is not list
                    or len(decoded["stage_inode"]) != 2
                    or any(
                        type(value) is not int or value < 0
                        for value in decoded["stage_inode"]
                    )
                    or descriptor["sha256"] != hashlib.sha256(payload).hexdigest()
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization intent binding drifted"
                    )
                intent = dict(decoded)

            def optional_stat(parent: int, name: str) -> os.stat_result | None:
                try:
                    return os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    return None

            stage_named = optional_stat(transaction_fd, _MATERIALIZATION_STAGE)
            final_named = optional_stat(root_fd, target.name)

            if intent is None and stage_named is not None:
                raise ArtifactIntegrityError(
                    "Seafile materialization stage has no immutable intent"
                )

            if intent is None and final_named is not None:
                final_fd, _final_inode = _open_verified_file_at(
                    root_fd,
                    target.name,
                    label="existing materialize destination",
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    chunk_size=self.chunk_size,
                )
                os.fsync(root_fd)
                return {
                    "status": "already_materialized_and_verified",
                    "remote_name": remote_name,
                    "size_bytes": expected_size,
                    "sha256": expected_sha256,
                    "destination": str(target),
                }

            if intent is None:
                stage_fd = os.open(
                    _MATERIALIZATION_STAGE,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    0o600,
                    dir_fd=transaction_fd,
                )
                created = os.fstat(stage_fd)
                if not stat.S_ISREG(created.st_mode) or int(created.st_nlink) != 1:
                    raise ArtifactIntegrityError(
                        "Seafile materialization stage is not one physical file"
                    )
                stage_inode = _file_inode(created)
                intent = {
                    "schema_version": intent_kind,
                    "remote_name": remote_name,
                    "target_name": target.name,
                    "expected_sha256": expected_sha256,
                    "expected_size": expected_size,
                    "stage_name": _MATERIALIZATION_STAGE,
                    "stage_inode": list(stage_inode),
                }
                if storage_binding:
                    intent["storage_binding"] = storage_binding
                custody.commit_or_adopt_exact_identity(
                    intent_relative,
                    _canonical_json(intent),
                    label="Seafile materialization intent",
                    mode=0o444,
                    create_parents=False,
                )
                os.fsync(transaction_fd)
            else:
                stage_inode = tuple(int(value) for value in intent["stage_inode"])

            stage_named = optional_stat(transaction_fd, _MATERIALIZATION_STAGE)
            final_named = optional_stat(root_fd, target.name)
            if final_named is not None:
                if not stat.S_ISREG(final_named.st_mode):
                    raise ArtifactIntegrityError(
                        "resumed materialize destination is not one physical file"
                    )
                final_inode_before = _file_inode(final_named)
                same_link_recovery = False
                if stage_named is None:
                    if int(final_named.st_nlink) != 1:
                        raise ArtifactIntegrityError(
                            "resumed materialize destination has foreign links"
                        )
                    allowed_final_links = frozenset({1})
                else:
                    if (
                        not stat.S_ISREG(stage_named.st_mode)
                        or _file_inode(stage_named) != stage_inode
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization stage was rebound"
                        )
                    same_link_recovery = final_inode_before == stage_inode
                    if same_link_recovery:
                        if (
                            int(final_named.st_nlink) != 2
                            or int(stage_named.st_nlink) != 2
                        ):
                            raise ArtifactIntegrityError(
                                "Seafile materialization linked recovery topology drifted"
                            )
                        allowed_final_links = frozenset({2})
                    else:
                        if (
                            int(final_named.st_nlink) != 1
                            or int(stage_named.st_nlink) != 1
                        ):
                            raise ArtifactIntegrityError(
                                "Seafile materialization distinct final/stage topology has foreign links"
                            )
                        allowed_final_links = frozenset({1})
                final_fd, final_inode = _open_verified_file_at(
                    root_fd,
                    target.name,
                    label="resumed materialize destination",
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    allowed_links=allowed_final_links,
                    chunk_size=self.chunk_size,
                )
                if stage_named is not None:
                    current = os.stat(
                        _MATERIALIZATION_STAGE,
                        dir_fd=transaction_fd,
                        follow_symlinks=False,
                    )
                    current_final = os.stat(
                        target.name,
                        dir_fd=root_fd,
                        follow_symlinks=False,
                    )
                    expected_links = 2 if same_link_recovery else 1
                    if (
                        _file_inode(current) != stage_inode
                        or _file_inode(current_final) != final_inode
                        or int(current.st_nlink) != expected_links
                        or int(current_final.st_nlink) != expected_links
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization final/stage topology changed before cleanup"
                        )
                    os.unlink(_MATERIALIZATION_STAGE, dir_fd=transaction_fd)
                    os.fsync(transaction_fd)
                os.fsync(root_fd)
                os.close(final_fd)
                final_fd = -1
                final_fd, _final_inode = _open_verified_file_at(
                    root_fd,
                    target.name,
                    label="durable resumed materialize destination",
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    chunk_size=self.chunk_size,
                )
                return {
                    "status": "already_materialized_and_verified",
                    "remote_name": remote_name,
                    "size_bytes": expected_size,
                    "sha256": expected_sha256,
                    "destination": str(target),
                }

            if stage_named is None or _file_inode(stage_named) != stage_inode:
                raise ArtifactIntegrityError(
                    "Seafile materialization stage is missing or rebound"
                )
            if stage_fd < 0:
                stage_fd = os.open(
                    _MATERIALIZATION_STAGE,
                    os.O_RDONLY
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=transaction_fd,
                )
            opened_stage = os.fstat(stage_fd)
            if (
                not stat.S_ISREG(opened_stage.st_mode)
                or int(opened_stage.st_nlink) != 1
                or _file_inode(opened_stage) != stage_inode
            ):
                raise ArtifactIntegrityError(
                    "Seafile materialization staged inode drifted"
                )
            os.fchmod(stage_fd, 0o600)
            # A durable pre-publish crash leaves the owned stage 0444.
            # Pin/chmod it through the current descriptor before reopening
            # the exact inode for a deterministic restart.
            os.close(stage_fd)
            stage_fd = os.open(
                _MATERIALIZATION_STAGE,
                os.O_RDWR
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=transaction_fd,
            )
            if _file_inode(os.fstat(stage_fd)) != stage_inode:
                raise ArtifactIntegrityError(
                    "Seafile materialization stage rebound while reopening"
                )
            os.ftruncate(stage_fd, 0)
            os.lseek(stage_fd, 0, os.SEEK_SET)

            digest = hashlib.sha256()
            downloaded = 0
            mid_write_invoked = False

            def write_all(payload: bytes) -> None:
                offset = 0
                while offset < len(payload):
                    written = os.write(stage_fd, payload[offset:])
                    if written <= 0:
                        raise ArtifactIntegrityError(
                            "Seafile materialization write stalled"
                        )
                    offset += written

            with self._read_remote(remote_name) as response:
                for chunk in iter(lambda: response.read(self.chunk_size), b""):
                    if downloaded + len(chunk) > expected_size:
                        raise ArtifactIntegrityError("materialized artifact exceeds receipt size")
                    if not mid_write_invoked:
                        split = max(1, len(chunk) // 2)
                        first, remainder = chunk[:split], chunk[split:]
                        write_all(first)
                        digest.update(first)
                        downloaded += len(first)
                        mid_write_invoked = True
                        if self.materialize_physical_fault is not None:
                            self.materialize_physical_fault("mid_write", stage)
                        rebound = os.stat(
                            _MATERIALIZATION_STAGE,
                            dir_fd=transaction_fd,
                            follow_symlinks=False,
                        )
                        if _file_inode(rebound) != stage_inode:
                            raise ArtifactIntegrityError(
                                "Seafile materialization stage was rebound mid-write"
                            )
                        write_all(remainder)
                        digest.update(remainder)
                        downloaded += len(remainder)
                    else:
                        write_all(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
            if not mid_write_invoked and self.materialize_physical_fault is not None:
                self.materialize_physical_fault("mid_write", stage)
            if downloaded != expected_size or digest.hexdigest() != expected_sha256:
                raise ArtifactIntegrityError(
                    "materialized artifact does not match receipt"
                )
            os.fchmod(stage_fd, 0o444)
            os.fsync(stage_fd)
            os.fsync(transaction_fd)
            held_size, held_sha256 = _hash_open_file(
                stage_fd, chunk_size=self.chunk_size, check=getattr(self, "_check_deadline", None)
            )
            staged_after = os.stat(
                _MATERIALIZATION_STAGE,
                dir_fd=transaction_fd,
                follow_symlinks=False,
            )
            if (
                _file_inode(staged_after) != stage_inode
                or _file_inode(os.fstat(stage_fd)) != stage_inode
                or int(staged_after.st_nlink) != 1
                or held_size != expected_size
                or held_sha256 != expected_sha256
            ):
                raise ArtifactIntegrityError(
                    "Seafile materialization stage changed before publication"
                )
            if self.materialize_physical_fault is not None:
                self.materialize_physical_fault("post_fsync_pre_publish", stage)
            staged_after_hook = os.stat(
                _MATERIALIZATION_STAGE,
                dir_fd=transaction_fd,
                follow_symlinks=False,
            )
            hook_size, hook_sha256 = _hash_open_file(
                stage_fd, chunk_size=self.chunk_size, check=getattr(self, "_check_deadline", None)
            )
            if (
                _file_inode(staged_after_hook) != stage_inode
                or int(staged_after_hook.st_nlink) != 1
                or hook_size != expected_size
                or hook_sha256 != expected_sha256
            ):
                raise ArtifactIntegrityError(
                    "Seafile materialization stage was rebound or mutated before publication"
                )
            _verify_directory_at(
                root_fd,
                journal_root,
                journal_fd,
                label="Seafile materialization journal root",
            )
            _verify_directory_at(
                journal_fd,
                transaction_key,
                transaction_fd,
                label="Seafile materialization transaction",
            )
            custody.verify()

            try:
                renamed = rename_noreplace(
                    transaction_fd,
                    _MATERIALIZATION_STAGE,
                    root_fd,
                    target.name,
                )
                if not renamed:
                    os.link(
                        _MATERIALIZATION_STAGE,
                        target.name,
                        src_dir_fd=transaction_fd,
                        dst_dir_fd=root_fd,
                        follow_symlinks=False,
                    )
            except FileExistsError:
                final_fd, _final_inode = _open_verified_file_at(
                    root_fd,
                    target.name,
                    label="raced materialize destination",
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    chunk_size=self.chunk_size,
                )
                current_stage = os.stat(
                    _MATERIALIZATION_STAGE,
                    dir_fd=transaction_fd,
                    follow_symlinks=False,
                )
                raced_final = os.stat(
                    target.name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(current_stage.st_mode)
                    or _file_inode(current_stage) != stage_inode
                    or int(current_stage.st_nlink) != 1
                    or not stat.S_ISREG(raced_final.st_mode)
                    or int(raced_final.st_nlink) != 1
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization raced final/stage topology drifted"
                    )
                os.unlink(_MATERIALIZATION_STAGE, dir_fd=transaction_fd)
                os.fsync(transaction_fd)
                os.fsync(root_fd)
                status = "already_materialized_and_verified"
            else:
                published = os.stat(
                    target.name, dir_fd=root_fd, follow_symlinks=False
                )
                if (
                    _file_inode(published) != stage_inode
                    or not stat.S_ISREG(published.st_mode)
                    or int(published.st_size) != expected_size
                    or int(published.st_nlink) not in {1, 2}
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization published inode drifted"
                    )
                if self.materialize_physical_fault is not None:
                    self.materialize_physical_fault(
                        "post_publish_pre_parent_fsync", target
                    )
                published_after_hook = os.stat(
                    target.name, dir_fd=root_fd, follow_symlinks=False
                )
                if (
                    _file_inode(published_after_hook) != stage_inode
                    or int(published_after_hook.st_size) != expected_size
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization destination was rebound after publish"
                    )
                if not renamed:
                    linked_stage = os.stat(
                        _MATERIALIZATION_STAGE,
                        dir_fd=transaction_fd,
                        follow_symlinks=False,
                    )
                    if (
                        _file_inode(linked_stage) != stage_inode
                        or int(linked_stage.st_nlink) != 2
                        or int(published_after_hook.st_nlink) != 2
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization hard-link recovery drifted"
                        )
                    os.unlink(_MATERIALIZATION_STAGE, dir_fd=transaction_fd)
                os.fsync(transaction_fd)
                os.fsync(root_fd)
                status = "materialized_and_verified"

            if final_fd >= 0:
                os.close(final_fd)
                final_fd = -1
            final_fd, final_inode = _open_verified_file_at(
                root_fd,
                target.name,
                label="cold materialize destination",
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                expected_inode=(stage_inode if status == "materialized_and_verified" else None),
                chunk_size=self.chunk_size,
            )
            if status == "materialized_and_verified" and final_inode != stage_inode:
                raise ArtifactIntegrityError(
                    "Seafile materialization final inode changed across commit"
                )
            os.fsync(root_fd)
            custody.verify()
    except ArtifactStoreError:
        raise
    except PublicationPhysicalIoV1Error:
        raise ArtifactIntegrityError(
            "remote materialization physical custody failed"
        ) from None
    except Exception:
        raise ArtifactIntegrityError("remote materialization failed") from None
    finally:
        for descriptor in (
            final_fd,
            stage_fd,
            lock_fd,
            transaction_fd,
            journal_fd,
            root_fd,
        ):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    return {
        "status": status,
        "remote_name": remote_name,
        "size_bytes": expected_size,
        "sha256": expected_sha256,
        "destination": str(target),
    }
