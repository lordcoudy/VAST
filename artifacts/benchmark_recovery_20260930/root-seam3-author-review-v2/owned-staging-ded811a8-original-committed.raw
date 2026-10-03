#!/usr/bin/env python3
"""Descriptor-anchored cleanup for caller-owned publication staging leaves."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import struct
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal


_MUTATION_MASK = (
    0x00000002  # IN_MODIFY
    | 0x00000004  # IN_ATTRIB
    | 0x00000008  # IN_CLOSE_WRITE
    | 0x00000040  # IN_MOVED_FROM
    | 0x00000080  # IN_MOVED_TO
    | 0x00000100  # IN_CREATE
    | 0x00000200  # IN_DELETE
    | 0x00000400  # IN_DELETE_SELF
    | 0x00000800  # IN_MOVE_SELF
    | 0x00002000  # IN_UNMOUNT
)


class OwnedStagingCleanupV1Error(RuntimeError):
    """A caller-owned staging inode or its held parent changed before cleanup."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OwnedStagingCleanupV1Error(message)


def _flags(*, directory: bool) -> int:
    value = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
    if directory:
        value |= int(getattr(os, "O_DIRECTORY", 0))
    else:
        value |= int(getattr(os, "O_NONBLOCK", 0))
    value |= int(getattr(os, "O_NOFOLLOW", 0))
    return value


def _begin_mutation_watch(descriptors: list[int], *, label: str) -> int:
    _require(
        hasattr(os, "uname") and os.uname().sysname == "Linux" and descriptors,
        f"{label} mutation watch is unavailable",
    )
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        initialize = libc.inotify_init1
        add_watch = libc.inotify_add_watch
    except AttributeError as error:
        raise OwnedStagingCleanupV1Error(
            f"{label} mutation watch is unavailable"
        ) from error
    initialize.argtypes = [ctypes.c_int]
    initialize.restype = ctypes.c_int
    add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    add_watch.restype = ctypes.c_int
    watch_fd = int(
        initialize(
            int(getattr(os, "O_NONBLOCK", 0))
            | int(getattr(os, "O_CLOEXEC", 0))
        )
    )
    if watch_fd < 0:
        error_number = ctypes.get_errno()
        raise OwnedStagingCleanupV1Error(
            f"{label} mutation watch could not start: {os.strerror(error_number)}"
        )
    try:
        identities: set[tuple[int, int, int]] = set()
        for descriptor in descriptors:
            identity = _inode_identity(os.fstat(descriptor))
            if identity in identities:
                continue
            identities.add(identity)
            if int(
                add_watch(
                    watch_fd,
                    os.fsencode(f"/proc/self/fd/{descriptor}"),
                    _MUTATION_MASK,
                )
            ) < 0:
                error_number = ctypes.get_errno()
                raise OwnedStagingCleanupV1Error(
                    f"{label} mutation watch failed: {os.strerror(error_number)}"
                )
        return watch_fd
    except BaseException:
        os.close(watch_fd)
        raise


def _drain_mutation_watch(watch_fd: int) -> list[int]:
    masks: list[int] = []
    while True:
        try:
            payload = os.read(watch_fd, 1024 * 1024)
        except BlockingIOError:
            break
        except InterruptedError:
            continue
        if not payload:
            break
        offset = 0
        while offset < len(payload):
            _require(
                len(payload) - offset >= 16,
                "owned staging mutation watch returned a truncated event",
            )
            _watch, mask, _cookie, name_size = struct.unpack_from(
                "iIII", payload, offset
            )
            offset += 16 + int(name_size)
            _require(
                offset <= len(payload),
                "owned staging mutation watch returned an invalid event",
            )
            masks.append(int(mask))
    return masks


def _consume_mutation_watch(watch_fd: int) -> list[int]:
    try:
        return _drain_mutation_watch(watch_fd)
    finally:
        os.close(watch_fd)


def _assert_mutation_watch_clean(watch_fd: int, *, label: str) -> None:
    _require(
        not _consume_mutation_watch(watch_fd),
        f"{label} mutated after its physical anchor was sealed",
    )


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _parent_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
    )


def _same_held_parent(
    observed: tuple[int, ...], anchored: tuple[int, ...]
) -> bool:
    """Sibling create/rename may change nlink; the held parent inode may not."""

    return observed[:3] == anchored[:3]


def _same_directory_after_rename(
    observed: tuple[int, ...], anchored: tuple[int, ...]
) -> bool:
    """A root-directory rename may advance ctime without changing its content."""

    return observed[:6] == anchored[:6] and observed[7:] == anchored[7:]


def _inode_identity(info: os.stat_result) -> tuple[int, int, int]:
    return int(info.st_dev), int(info.st_ino), int(stat.S_IFMT(info.st_mode))


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0))
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


@dataclass(frozen=True)
class _TreeNodeV1:
    relative: str
    kind: Literal["directory", "file"]
    snapshot: tuple[int, ...]
    sha256: str | None


def _child_relative(parent: str, name: str) -> str:
    return name if not parent else f"{parent}/{name}"


def _scan_tree_fd(
    directory_fd: int,
    *,
    parent: str = "",
    rows: dict[str, _TreeNodeV1] | None = None,
) -> dict[str, _TreeNodeV1]:
    result = {} if rows is None else rows
    for name in sorted(os.listdir(directory_fd)):
        _require(
            type(name) is str
            and PurePosixPath(name).parts == (name,)
            and name not in {"", ".", ".."},
            "owned staging contains an invalid child name",
        )
        relative = _child_relative(parent, name)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        _require(not _is_reparse(named), f"owned staging contains a link/reparse point: {relative}")
        if stat.S_ISDIR(named.st_mode):
            child_fd = os.open(name, _flags(directory=True), dir_fd=directory_fd)
            try:
                opened = os.fstat(child_fd)
                _require(
                    _snapshot(opened) == _snapshot(named),
                    f"owned staging directory identity drifted: {relative}",
                )
                result[relative] = _TreeNodeV1(
                    relative, "directory", _snapshot(opened), None
                )
                _scan_tree_fd(child_fd, parent=relative, rows=result)
            finally:
                os.close(child_fd)
        else:
            _require(
                stat.S_ISREG(named.st_mode) and int(named.st_nlink) == 1,
                f"owned staging contains a non-regular or linked file: {relative}",
            )
            child_fd = os.open(name, _flags(directory=False), dir_fd=directory_fd)
            try:
                opened = os.fstat(child_fd)
                _require(
                    _snapshot(opened) == _snapshot(named)
                    and stat.S_ISREG(opened.st_mode)
                    and int(opened.st_nlink) == 1,
                    f"owned staging file identity drifted: {relative}",
                )
                digest = _sha256_fd(child_fd)
                after = os.fstat(child_fd)
                named_after = os.stat(
                    name, dir_fd=directory_fd, follow_symlinks=False
                )
                _require(
                    _snapshot(after) == _snapshot(opened) == _snapshot(named_after),
                    f"owned staging file changed while hashing: {relative}",
                )
                result[relative] = _TreeNodeV1(
                    relative, "file", _snapshot(after), digest
                )
            finally:
                os.close(child_fd)
    return result


def _validate_node(
    directory_fd: int,
    name: str,
    node: _TreeNodeV1,
) -> int:
    named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    _require(
        not _is_reparse(named) and _snapshot(named) == node.snapshot,
        f"owned staging child was rebound or ABA-restored: {node.relative}",
    )
    child_fd = os.open(
        name,
        _flags(directory=node.kind == "directory"),
        dir_fd=directory_fd,
    )
    opened = os.fstat(child_fd)
    _require(
        _snapshot(opened) == node.snapshot,
        f"owned staging child changed while opening: {node.relative}",
    )
    if node.kind == "file":
        _require(
            stat.S_ISREG(opened.st_mode)
            and int(opened.st_nlink) == 1
            and _sha256_fd(child_fd) == node.sha256
            and _snapshot(os.fstat(child_fd)) == node.snapshot,
            f"owned staging file content drifted: {node.relative}",
        )
    else:
        _require(
            stat.S_ISDIR(opened.st_mode),
            f"owned staging directory type drifted: {node.relative}",
        )
    return child_fd


def _open_anchored_directory_fds(
    directory_fd: int,
    *,
    parent: str,
    anchors: dict[str, _TreeNodeV1],
    opened: list[int],
) -> None:
    for relative, node in sorted(anchors.items()):
        if (
            node.kind != "directory"
            or PurePosixPath(relative).parent.as_posix() != (parent or ".")
        ):
            continue
        name = relative.rsplit("/", 1)[-1]
        child_fd = _validate_node(directory_fd, name, node)
        opened.append(child_fd)
        _open_anchored_directory_fds(
            child_fd, parent=relative, anchors=anchors, opened=opened
        )


def _remove_tree_fd(
    directory_fd: int,
    *,
    parent: str,
    anchors: dict[str, _TreeNodeV1],
) -> None:
    expected_names = sorted(
        relative.rsplit("/", 1)[-1]
        for relative in anchors
        if PurePosixPath(relative).parent.as_posix() == (parent or ".")
    )
    observed_names = sorted(os.listdir(directory_fd))
    _require(
        observed_names == expected_names,
        f"owned staging contents allowlist drifted below {parent or '.'}",
    )
    for name in observed_names:
        relative = _child_relative(parent, name)
        node = anchors[relative]
        child_fd = _validate_node(directory_fd, name, node)
        try:
            if node.kind == "directory":
                _remove_tree_fd(child_fd, parent=relative, anchors=anchors)
                os.fsync(child_fd)
            else:
                named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                _require(
                    _snapshot(named) == node.snapshot
                    and _snapshot(os.fstat(child_fd)) == node.snapshot,
                    f"owned staging file changed before unlink: {relative}",
                )
        finally:
            os.close(child_fd)
        if node.kind == "directory":
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            _require(
                _inode_identity(named)
                == (node.snapshot[0], node.snapshot[1], stat.S_IFDIR),
                f"owned staging directory changed before rmdir: {relative}",
            )
            os.rmdir(name, dir_fd=directory_fd)
        else:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            _require(
                _snapshot(named) == node.snapshot,
                f"owned staging file changed before unlink: {relative}",
            )
            os.unlink(name, dir_fd=directory_fd)
        os.fsync(directory_fd)


class OwnedStagingDirectoryV1:
    """Hold a staging directory and its parent from pre-publish through cleanup."""

    def __init__(
        self,
        *,
        path: Path,
        parent_fd: int,
        directory_fd: int,
        parent_identity: tuple[int, ...],
        root_snapshot: tuple[int, ...],
        anchors: dict[str, _TreeNodeV1],
        label: str,
    ) -> None:
        self.path = path
        self._parent_fd = parent_fd
        self._directory_fd = directory_fd
        self.parent_identity = parent_identity
        self.root_snapshot = root_snapshot
        self.anchors = anchors
        self.label = label
        self.closed = False
        self.sealed = False
        self._mutation_watch_fd = -1
        self._published_target: Path | None = None

    @classmethod
    def capture(
        cls,
        path: Path | str,
        *,
        expected_parent: Path | str,
        expected_prefix: str,
        label: str,
    ) -> "OwnedStagingDirectoryV1":
        _require(os.name == "posix", f"{label} cleanup requires canonical POSIX custody")
        lexical = Path(os.path.abspath(os.fspath(path)))
        parent = Path(os.path.abspath(os.fspath(expected_parent)))
        _require(
            lexical.parent == parent
            and lexical.name.startswith(expected_prefix)
            and lexical.name != expected_prefix,
            f"{label} staging path escaped its expected parent/prefix",
        )
        _require(
            parent.resolve(strict=True) == parent
            and lexical.resolve(strict=True) == lexical,
            f"{label} staging path is an alias",
        )
        parent_fd = -1
        directory_fd = -1
        try:
            parent_fd = os.open(parent, _flags(directory=True))
            parent_info = os.fstat(parent_fd)
            named = os.stat(lexical.name, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISDIR(named.st_mode) and not _is_reparse(named),
                f"{label} staging is not one physical directory",
            )
            directory_fd = os.open(
                lexical.name, _flags(directory=True), dir_fd=parent_fd
            )
            opened = os.fstat(directory_fd)
            _require(
                _snapshot(opened) == _snapshot(named),
                f"{label} staging identity changed while anchoring",
            )
            anchors = _scan_tree_fd(directory_fd)
            _require(
                _snapshot(os.fstat(directory_fd)) == _snapshot(opened),
                f"{label} staging root changed while anchoring",
            )
            return cls(
                path=lexical,
                parent_fd=parent_fd,
                directory_fd=directory_fd,
                parent_identity=_parent_identity(parent_info),
                root_snapshot=_snapshot(opened),
                anchors=anchors,
                label=label,
            )
        except BaseException:
            if directory_fd >= 0:
                os.close(directory_fd)
            if parent_fd >= 0:
                os.close(parent_fd)
            raise

    def seal_tree(self) -> None:
        """Freeze the completed staging tree while retaining its creation inode."""

        _require(not self.closed, f"{self.label} cleanup anchor is closed")
        _require(not self.sealed, f"{self.label} staging tree is already sealed")
        _require(
            _same_held_parent(
                _parent_identity(os.fstat(self._parent_fd)), self.parent_identity
            ),
            f"{self.label} held parent identity changed before sealing",
        )
        named = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        opened = os.fstat(self._directory_fd)
        creation_identity = (
            self.root_snapshot[0],
            self.root_snapshot[1],
            stat.S_IFDIR,
        )
        _require(
            not _is_reparse(named)
            and _inode_identity(named) == creation_identity
            and _inode_identity(opened) == creation_identity,
            f"{self.label} creation inode was rebound before sealing",
        )
        anchors = _scan_tree_fd(self._directory_fd)
        after = os.fstat(self._directory_fd)
        named_after = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        _require(
            _snapshot(after) == _snapshot(named_after),
            f"{self.label} staging root changed while sealing",
        )
        watched_fds = [os.dup(self._directory_fd)]
        try:
            _open_anchored_directory_fds(
                watched_fds[0], parent="", anchors=anchors, opened=watched_fds
            )
            watch_fd = _begin_mutation_watch(watched_fds, label=self.label)
        finally:
            for descriptor in reversed(watched_fds):
                os.close(descriptor)
        try:
            _require(
                _scan_tree_fd(self._directory_fd) == anchors
                and _snapshot(os.fstat(self._directory_fd)) == _snapshot(after),
                f"{self.label} staging changed while mutation watches started",
            )
        except BaseException:
            os.close(watch_fd)
            raise
        self.root_snapshot = _snapshot(after)
        self.anchors = anchors
        self._mutation_watch_fd = watch_fd
        self.sealed = True

    def assert_staging_unchanged(self) -> None:
        """Prove the still-named staging tree is the held sealed inode/tree."""

        _require(not self.closed, f"{self.label} cleanup anchor is closed")
        _require(self.sealed, f"{self.label} staging tree is not sealed")
        _require(
            self._published_target is None,
            f"{self.label} staging was already published",
        )
        _require(
            _same_held_parent(
                _parent_identity(os.fstat(self._parent_fd)), self.parent_identity
            ),
            f"{self.label} held parent identity changed",
        )
        _require(
            not _drain_mutation_watch(self._mutation_watch_fd),
            f"{self.label} mutated after its physical anchor was sealed",
        )
        named = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        opened = os.fstat(self._directory_fd)
        _require(
            _snapshot(named) == self.root_snapshot == _snapshot(opened)
            and _scan_tree_fd(self._directory_fd) == self.anchors,
            f"{self.label} staging was rebound, mutated, or ABA-restored",
        )

    def assert_published_to(self, final_target: Path | str) -> None:
        """Prove a final name still maps to this held sealed inode and tree."""

        _require(not self.closed, f"{self.label} cleanup anchor is closed")
        _require(self.sealed, f"{self.label} staging tree is not sealed")
        target = Path(os.path.abspath(os.fspath(final_target)))
        _require(target != self.path, f"{self.label} final target aliases staging")
        if self._published_target is None:
            masks = _drain_mutation_watch(self._mutation_watch_fd)
            _require(
                all((mask & ~(0x00000004 | 0x00000800)) == 0 for mask in masks),
                f"{self.label} changed before becoming the final inode: {masks}",
            )
            self._published_target = target
        else:
            _require(
                target == self._published_target
                and not _drain_mutation_watch(self._mutation_watch_fd),
                f"{self.label} final target or tree mutated after publication",
            )
        parent_fd = -1
        final_fd = -1
        try:
            parent_named = target.parent.lstat()
            parent_fd = os.open(target.parent, _flags(directory=True))
            parent_opened = os.fstat(parent_fd)
            _require(
                not _is_reparse(parent_named)
                and _snapshot(parent_named) == _snapshot(parent_opened),
                f"{self.label} final parent changed before publication validation",
            )
            absolute_fallback = False
            visibility_deadline = time.monotonic() + 2.0
            while True:
                try:
                    named = os.stat(
                        target.name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    final_fd = os.open(
                        target.name,
                        _flags(directory=True),
                        dir_fd=parent_fd,
                    )
                    break
                except FileNotFoundError:
                    # Some DrvFS builds cannot resolve a freshly cross-parent
                    # renamed child through *at(2), even though the canonical
                    # absolute path already names it.  O_NOFOLLOW plus the
                    # held, stable parent/final identities preserves the same
                    # proof.  DrvFS may also expose that absolute name after a
                    # short delay, so retry ENOENT within a strict bound.
                    try:
                        named = target.lstat()
                        final_fd = os.open(target, _flags(directory=True))
                    except FileNotFoundError:
                        if time.monotonic() >= visibility_deadline:
                            raise
                        time.sleep(0.01)
                        continue
                    absolute_fallback = True
                    break
            opened = os.fstat(final_fd)
            try:
                held = os.fstat(self._directory_fd)
                held_anchors = _scan_tree_fd(self._directory_fd)
            except FileNotFoundError:
                # WSL DrvFS may invalidate an open directory descriptor after
                # a successful cross-parent rename.  Accept that platform
                # behavior only when the old staging name is gone and the
                # independently opened final inode/tree still matches every
                # pre-rename physical anchor.
                try:
                    os.stat(
                        self.path.name,
                        dir_fd=self._parent_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    held = None
                    held_anchors = None
                else:
                    raise OwnedStagingCleanupV1Error(
                        f"{self.label} held directory vanished while staging remained"
                    )
            creation_identity = (
                self.root_snapshot[0],
                self.root_snapshot[1],
                stat.S_IFDIR,
            )
            _require(
                not _is_reparse(named)
                and _inode_identity(named) == creation_identity
                and _inode_identity(opened) == creation_identity
                and (
                    held is None
                    or _inode_identity(held) == creation_identity
                )
                and _same_directory_after_rename(
                    _snapshot(opened), self.root_snapshot
                )
                and (
                    held is None
                    or _same_directory_after_rename(
                        _snapshot(held), self.root_snapshot
                    )
                )
                and (held_anchors is None or held_anchors == self.anchors)
                and _scan_tree_fd(final_fd) == self.anchors,
                f"{self.label} final inode/tree differs from held staging",
            )
            named_after = (
                target.lstat()
                if absolute_fallback
                else os.stat(
                    target.name, dir_fd=parent_fd, follow_symlinks=False
                )
            )
            parent_named_after = target.parent.lstat()
            _require(
                _snapshot(named_after) == _snapshot(os.fstat(final_fd))
                and _snapshot(parent_named_after) == _snapshot(parent_opened),
                f"{self.label} final name changed while validating publication",
            )
        finally:
            if final_fd >= 0:
                os.close(final_fd)
            if parent_fd >= 0:
                os.close(parent_fd)

    def cleanup_after_publication(self, *, final_target: Path | str) -> str:
        _require(not self.closed, f"{self.label} cleanup anchor is closed")
        _require(self.sealed, f"{self.label} staging tree is not sealed")
        target = Path(os.path.abspath(os.fspath(final_target)))
        _require(
            target.parent == self.path.parent and target != self.path,
            f"{self.label} final target is not a distinct sibling",
        )
        _require(
            _same_held_parent(
                _parent_identity(os.fstat(self._parent_fd)), self.parent_identity
            ),
            f"{self.label} held parent identity changed",
        )
        try:
            named = os.stat(
                self.path.name,
                dir_fd=self._parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            final_named = os.stat(
                target.name, dir_fd=self._parent_fd, follow_symlinks=False
            )
            _require(
                stat.S_ISDIR(final_named.st_mode)
                and _inode_identity(final_named)
                == (
                    self.root_snapshot[0],
                    self.root_snapshot[1],
                    stat.S_IFDIR,
                ),
                f"{self.label} staging disappeared without becoming the final inode",
            )
            final_fd = os.open(
                target.name, _flags(directory=True), dir_fd=self._parent_fd
            )
            try:
                opened_final = os.fstat(final_fd)
                _require(
                    _inode_identity(opened_final)
                    == (
                        self.root_snapshot[0],
                        self.root_snapshot[1],
                        stat.S_IFDIR,
                    )
                    and _same_directory_after_rename(
                        _snapshot(opened_final), self.root_snapshot
                    )
                    and _scan_tree_fd(final_fd) == self.anchors,
                    f"{self.label} final inode changed after its staging rename",
                )
                final_after = os.stat(
                    target.name, dir_fd=self._parent_fd, follow_symlinks=False
                )
                _require(
                    _snapshot(os.fstat(final_fd)) == _snapshot(final_after),
                    f"{self.label} final inode changed while validating its rename",
                )
            finally:
                os.close(final_fd)
            if self._mutation_watch_fd >= 0:
                masks = _consume_mutation_watch(self._mutation_watch_fd)
                self._mutation_watch_fd = -1
                _require(
                    all(
                        (mask & ~(0x00000004 | 0x00000800 | 0x00008000)) == 0
                        for mask in masks
                    ),
                    f"{self.label} changed before becoming the final inode: {masks}",
                )
            return "published"
        if self._mutation_watch_fd >= 0:
            watch_fd = self._mutation_watch_fd
            self._mutation_watch_fd = -1
            _assert_mutation_watch_clean(watch_fd, label=self.label)
        _require(
            _snapshot(named) == self.root_snapshot
            and _snapshot(os.fstat(self._directory_fd)) == self.root_snapshot,
            f"{self.label} staging was rebound, mutated, or ABA-restored",
        )
        try:
            final_named = os.stat(
                target.name, dir_fd=self._parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            final_named = None
        _require(
            final_named is None
            or _inode_identity(final_named)
            != (
                self.root_snapshot[0],
                self.root_snapshot[1],
                stat.S_IFDIR,
            ),
            f"{self.label} staging aliases the final inode",
        )
        observed = _scan_tree_fd(self._directory_fd)
        _require(
            observed == self.anchors,
            f"{self.label} staging tree changed before cleanup",
        )
        _remove_tree_fd(self._directory_fd, parent="", anchors=self.anchors)
        _require(
            os.listdir(self._directory_fd) == [],
            f"{self.label} staging is not empty after owned cleanup",
        )
        named = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        _require(
            _inode_identity(named)
            == (self.root_snapshot[0], self.root_snapshot[1], stat.S_IFDIR)
            and _inode_identity(os.fstat(self._directory_fd))
            == (self.root_snapshot[0], self.root_snapshot[1], stat.S_IFDIR),
            f"{self.label} staging changed before final rmdir",
        )
        os.rmdir(self.path.name, dir_fd=self._parent_fd)
        os.fsync(self._parent_fd)
        return "adopted_staging_removed"

    def retire_owned_tree(self) -> str:
        """Remove only this still-named, sealed, physically anchored tree."""

        _require(not self.closed, f"{self.label} cleanup anchor is closed")
        _require(self.sealed, f"{self.label} staging tree is not sealed")
        _require(
            self._published_target is None,
            f"{self.label} tree was already published",
        )
        _require(
            _same_held_parent(
                _parent_identity(os.fstat(self._parent_fd)), self.parent_identity
            ),
            f"{self.label} held parent identity changed",
        )
        if self._mutation_watch_fd >= 0:
            watch_fd = self._mutation_watch_fd
            self._mutation_watch_fd = -1
            _assert_mutation_watch_clean(watch_fd, label=self.label)
        named = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        _require(
            _snapshot(named) == self.root_snapshot
            and _snapshot(os.fstat(self._directory_fd)) == self.root_snapshot,
            f"{self.label} tree was rebound, mutated, or ABA-restored",
        )
        observed = _scan_tree_fd(self._directory_fd)
        _require(
            observed == self.anchors,
            f"{self.label} tree changed before retirement",
        )
        _remove_tree_fd(self._directory_fd, parent="", anchors=self.anchors)
        _require(
            os.listdir(self._directory_fd) == [],
            f"{self.label} tree is not empty after owned cleanup",
        )
        named = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        creation_identity = (
            self.root_snapshot[0],
            self.root_snapshot[1],
            stat.S_IFDIR,
        )
        _require(
            _inode_identity(named) == creation_identity
            and _inode_identity(os.fstat(self._directory_fd)) == creation_identity,
            f"{self.label} tree changed before final rmdir",
        )
        os.rmdir(self.path.name, dir_fd=self._parent_fd)
        os.fsync(self._parent_fd)
        try:
            os.stat(self.path.name, dir_fd=self._parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "owned_tree_retired"
        raise OwnedStagingCleanupV1Error(
            f"{self.label} name still exists after owned retirement"
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._mutation_watch_fd >= 0:
            os.close(self._mutation_watch_fd)
            self._mutation_watch_fd = -1
        os.close(self._directory_fd)
        os.close(self._parent_fd)

    def __enter__(self) -> "OwnedStagingDirectoryV1":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class OwnedStagingFileV1:
    """Hold one candidate file and its parent until exact owned unlink."""

    def __init__(
        self,
        *,
        path: Path,
        parent_fd: int,
        file_fd: int,
        parent_identity: tuple[int, ...],
        snapshot: tuple[int, ...],
        sha256: str,
        mutation_watch_fd: int,
        label: str,
    ) -> None:
        self.path = path
        self._parent_fd = parent_fd
        self._file_fd = file_fd
        self.parent_identity = parent_identity
        self.snapshot = snapshot
        self.sha256 = sha256
        self._mutation_watch_fd = mutation_watch_fd
        self.label = label
        self.closed = False

    @classmethod
    def capture(cls, path: Path | str, *, label: str) -> "OwnedStagingFileV1":
        _require(os.name == "posix", f"{label} cleanup requires canonical POSIX custody")
        lexical = Path(os.path.abspath(os.fspath(path)))
        _require(
            lexical.parent.resolve(strict=True) == lexical.parent
            and lexical.resolve(strict=True) == lexical,
            f"{label} candidate path is an alias",
        )
        parent_fd = -1
        file_fd = -1
        try:
            parent_fd = os.open(lexical.parent, _flags(directory=True))
            parent_info = os.fstat(parent_fd)
            named = os.stat(lexical.name, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISREG(named.st_mode)
                and not _is_reparse(named)
                and int(named.st_nlink) == 1,
                f"{label} candidate is not one physical single-link file",
            )
            file_fd = os.open(lexical.name, _flags(directory=False), dir_fd=parent_fd)
            opened = os.fstat(file_fd)
            _require(
                _snapshot(opened) == _snapshot(named),
                f"{label} candidate identity changed while anchoring",
            )
            digest = _sha256_fd(file_fd)
            _require(
                _snapshot(os.fstat(file_fd)) == _snapshot(opened),
                f"{label} candidate changed while anchoring",
            )
            mutation_watch_fd = _begin_mutation_watch([file_fd], label=label)
            return cls(
                path=lexical,
                parent_fd=parent_fd,
                file_fd=file_fd,
                parent_identity=_parent_identity(parent_info),
                snapshot=_snapshot(opened),
                sha256=digest,
                mutation_watch_fd=mutation_watch_fd,
                label=label,
            )
        except BaseException:
            if file_fd >= 0:
                os.close(file_fd)
            if parent_fd >= 0:
                os.close(parent_fd)
            raise

    def unlink_owned(self, *, final_target: Path | str) -> None:
        _require(not self.closed, f"{self.label} cleanup anchor is closed")
        target = Path(os.path.abspath(os.fspath(final_target)))
        _require(
            target.parent == self.path.parent and target != self.path,
            f"{self.label} final target is not a distinct sibling",
        )
        _require(
            _same_held_parent(
                _parent_identity(os.fstat(self._parent_fd)), self.parent_identity
            ),
            f"{self.label} held parent identity changed",
        )
        watch_fd = self._mutation_watch_fd
        self._mutation_watch_fd = -1
        _assert_mutation_watch_clean(watch_fd, label=self.label)
        named = os.stat(
            self.path.name, dir_fd=self._parent_fd, follow_symlinks=False
        )
        opened = os.fstat(self._file_fd)
        _require(
            _snapshot(named) == self.snapshot == _snapshot(opened)
            and _sha256_fd(self._file_fd) == self.sha256
            and _snapshot(os.fstat(self._file_fd)) == self.snapshot,
            f"{self.label} candidate was rebound, mutated, or ABA-restored",
        )
        try:
            final_named = os.stat(
                target.name, dir_fd=self._parent_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            final_named = None
        _require(
            final_named is None
            or _inode_identity(final_named) != _inode_identity(opened),
            f"{self.label} candidate aliases the final inode",
        )
        os.unlink(self.path.name, dir_fd=self._parent_fd)
        os.fsync(self._parent_fd)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._mutation_watch_fd >= 0:
            os.close(self._mutation_watch_fd)
            self._mutation_watch_fd = -1
        os.close(self._file_fd)
        os.close(self._parent_fd)

    def __enter__(self) -> "OwnedStagingFileV1":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def retire_owned_runtime_output_v1(
    path: Path | str,
    *,
    output_root: Path | str,
    leaf_name: str = "native_runtime",
    label: str = "publication native runtime output",
) -> str:
    """Retire one exact runtime scratch leaf without following aliases."""

    lexical = Path(os.path.abspath(os.fspath(path)))
    parent = Path(os.path.abspath(os.fspath(output_root)))
    _require(
        leaf_name not in {"", ".", ".."}
        and "/" not in leaf_name
        and os.sep not in leaf_name
        and lexical.parent == parent
        and lexical.name == leaf_name,
        f"{label} path escaped its exact output-root leaf",
    )
    prefix = leaf_name[:-1]
    _require(prefix, f"{label} leaf name is too short to anchor")
    with OwnedStagingDirectoryV1.capture(
        lexical,
        expected_parent=parent,
        expected_prefix=prefix,
        label=label,
    ) as anchor:
        anchor.seal_tree()
        return anchor.retire_owned_tree()


__all__ = [
    "OwnedStagingCleanupV1Error",
    "OwnedStagingDirectoryV1",
    "OwnedStagingFileV1",
    "retire_owned_runtime_output_v1",
]
