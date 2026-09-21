#!/usr/bin/env python3
"""Descriptor-held physical file I/O for WSL publication boundaries.

The POSIX implementation anchors the project root for the complete operation,
walks every relative parent through ``openat`` with ``O_NOFOLLOW``, and keeps
all directory descriptors open until the leaf read or exclusive write has
been verified.  The Windows branch exists for deterministic unit tests; the
publication boundary itself is WSL/Linux.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import stat
import time
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, Callable, Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - publication commits execute in WSL.
    fcntl = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from publication_guardian_preprocessing_contract_v1 import DirectoryFdCustodyV1


_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_INOTIFY_MUTATION_MASK = (
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
_INOTIFY_API: tuple[Any, Any] | None = None
_ATOMIC_STAGING_ROOT = ".publication-atomic-staging-v1"
_ATOMIC_STAGING_LOCK = ".lock"
_ATOMIC_STAGING_LEAF = "payload.stage"
_ATOMIC_TRANSACTION_INTENT = "transaction.intent.json"
_ATOMIC_STAGE_INTENT = "stage.intent.json"
_ATOMIC_STAGE_COMPLETE = "stage.complete.json"
_ATOMIC_TRANSACTION_RECORDS = frozenset(
    {
        _ATOMIC_TRANSACTION_INTENT,
        _ATOMIC_STAGE_INTENT,
        _ATOMIC_STAGE_COMPLETE,
    }
)
_RENAME_NOREPLACE = 1
_RENAMEAT2_API: Any | None = None
_V9FS_MAGIC = 0x01021997
_POST_RENAME_VISIBILITY_ATTEMPTS = 500
_POST_RENAME_VISIBILITY_DELAY_S = 0.01


class PublicationPhysicalIoV1Error(RuntimeError):
    """A physical namespace, file identity, or immutable commit drifted."""


class _PinnedDirectoryMutationWatchV1:
    """Owned Linux inotify descriptor for one guarded cold-load interval."""

    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.descriptor)
        except OSError:
            pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationPhysicalIoV1Error(message)


def _rename_noreplace_posix(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> bool:
    """Try Linux renameat2(RENAME_NOREPLACE); return False if unsupported."""

    global _RENAMEAT2_API
    if _RENAMEAT2_API is False:
        return False
    if _RENAMEAT2_API is None:
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = libc.renameat2
        except AttributeError:
            _RENAMEAT2_API = False
            return False
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        _RENAMEAT2_API = renameat2
    ctypes.set_errno(0)
    result = int(
        _RENAMEAT2_API(
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
    unsupported = {
        errno.EINVAL,
        errno.ENOSYS,
        errno.EXDEV,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
        errno.EOPNOTSUPP,
    }
    if error_number in unsupported:
        return False
    raise OSError(error_number, os.strerror(error_number))


def _filesystem_magic_posix(path: Path) -> int | None:
    """Return Linux statfs.f_type without depending on a platform struct ABI."""

    if not (hasattr(os, "uname") and os.uname().sysname == "Linux"):
        return None
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        statfs_call = libc.statfs
    except AttributeError:
        return None
    statfs_call.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    statfs_call.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    ctypes.set_errno(0)
    if int(statfs_call(os.fsencode(path), ctypes.byref(buffer))) != 0:
        return None
    return int(ctypes.c_long.from_buffer(buffer).value)


def canonical_relative_path_v1(value: Any, *, label: str) -> str:
    """Return one canonical, portable, project-relative POSIX path."""

    _require(type(value) is str and bool(value), f"{label} path is empty")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and not posix.is_absolute()
        and not windows.is_absolute()
        and posix.as_posix() == value
        and bool(posix.parts)
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and part.split(".", 1)[0].upper() not in _RESERVED
            and all(ord(character) >= 32 for character in part)
            for part in posix.parts
        ),
        f"{label} path is unsafe",
    )
    return value


def _is_link_or_reparse(path: Path, info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(getattr(info, "st_uid", 0)),
        int(getattr(info, "st_gid", 0)),
    )


def _directory_epoch(info: os.stat_result) -> tuple[int, ...]:
    """Identity plus mutation clocks, deliberately excluding access time."""

    return (
        *_directory_identity(info),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(getattr(info, "st_uid", 0)),
        int(getattr(info, "st_gid", 0)),
    )


def _file_rename_identity(info: os.stat_result) -> tuple[int, ...]:
    """Stable inode/content fields; rename may legitimately advance ctime."""

    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(getattr(info, "st_uid", 0)),
        int(getattr(info, "st_gid", 0)),
    )


class PhysicalRootCustodyV1:
    """Hold a physical project root and perform relative leaf operations."""

    def __init__(
        self,
        root: Path,
        *,
        label: str,
        posix_custody: DirectoryFdCustodyV1 | None,
        windows_identity: tuple[int, ...] | None,
    ) -> None:
        self._root = root
        self._label = label
        self._posix_custody = posix_custody
        self._windows_identity = windows_identity
        root_identity = (
            _directory_identity(os.fstat(posix_custody.directory_fd))
            if posix_custody is not None
            else windows_identity
        )
        _require(root_identity is not None, f"{label} root identity is unavailable")
        self._directory_pins: dict[str, tuple[int, ...]] = {"": root_identity}
        self._posix_mode_enforced = (
            posix_custody is not None
            and _filesystem_magic_posix(root) != _V9FS_MAGIC
        )
        self._closed = False

    @classmethod
    def open(
        cls, root: Path | str, *, label: str = "publication project_root"
    ) -> "PhysicalRootCustodyV1":
        supplied = Path(os.path.abspath(os.fspath(root)))
        try:
            resolved = supplied.resolve(strict=True)
            info = supplied.lstat()
        except OSError as error:
            raise PublicationPhysicalIoV1Error(f"{label} is unavailable") from error
        _require(
            resolved == supplied
            and stat.S_ISDIR(info.st_mode)
            and not _is_link_or_reparse(supplied, info),
            f"{label} is not one canonical physical directory",
        )
        if os.name == "posix":
            # The guardian imports this module for PhysicalRootCustodyV1.  Keep
            # its lower-level dirfd helper lazy so either fresh import order is
            # valid and the dependency is resolved only when custody is opened.
            from publication_guardian_preprocessing_contract_v1 import (
                DirectoryFdCustodyV1,
            )

            try:
                custody = DirectoryFdCustodyV1.open_existing(supplied, label=label)
            except Exception as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} cannot be held with dirfd custody"
                ) from error
            return cls(
                supplied,
                label=label,
                posix_custody=custody,
                windows_identity=None,
            )
        return cls(
            supplied,
            label=label,
            posix_custody=None,
            windows_identity=_directory_identity(info),
        )

    @property
    def root(self) -> Path:
        self._require_open()
        return self._root

    @property
    def permission_modes_enforced(self) -> bool:
        """Whether this filesystem reports/enforces requested POSIX modes."""

        self._require_open()
        return self._posix_mode_enforced

    def _require_open(self) -> None:
        _require(not self._closed, f"{self._label} custody is closed")

    def _mode_matches(self, observed: int, expected: int) -> bool:
        return observed == expected or not self._posix_mode_enforced

    def verify(self) -> None:
        self._require_open()
        if self._posix_custody is not None:
            try:
                self._posix_custody.verify()
            except Exception as error:
                raise PublicationPhysicalIoV1Error(
                    f"{self._label} directory chain changed"
                ) from error
            return
        try:
            info = self._root.lstat()
            resolved = self._root.resolve(strict=True)
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{self._label} changed"
            ) from error
        _require(
            resolved == self._root
            and stat.S_ISDIR(info.st_mode)
            and not _is_link_or_reparse(self._root, info)
            and _directory_identity(info) == self._windows_identity,
            f"{self._label} directory identity changed",
        )

    def _relative(self, value: Path | str, *, label: str) -> str:
        raw = Path(value)
        if raw.is_absolute():
            absolute = Path(os.path.abspath(raw))
            try:
                relative = absolute.relative_to(self._root).as_posix()
            except ValueError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} escaped project_root"
                ) from error
        else:
            relative = raw.as_posix()
        return canonical_relative_path_v1(relative, label=label)

    def _check_directory_pin(
        self, relative: str, info: os.stat_result, *, label: str
    ) -> None:
        identity = _directory_identity(info)
        pinned = self._directory_pins.get(relative)
        if pinned is None:
            self._directory_pins[relative] = identity
            return
        _require(
            pinned == identity,
            f"{label} parent directory was rebound after custody",
        )

    @staticmethod
    def _epochs(descriptors: list[int]) -> tuple[tuple[int, ...], ...]:
        return tuple(_directory_epoch(os.fstat(item)) for item in descriptors)

    @staticmethod
    def _require_epochs(
        descriptors: list[int],
        expected: tuple[tuple[int, ...], ...],
        *,
        label: str,
    ) -> None:
        _require(
            PhysicalRootCustodyV1._epochs(descriptors) == expected,
            f"{label} parent directory mutated during custody",
        )

    def _open_parent_posix(
        self,
        relative: str,
        *,
        create: bool,
        label: str,
        created_directories: list[tuple[str, tuple[int, ...]]] | None = None,
    ) -> tuple[list[int], list[str]]:
        custody = self._posix_custody
        _require(custody is not None, f"{label} POSIX custody is unavailable")
        self.verify()
        descriptors = [os.dup(custody.directory_fd)]
        names: list[str] = []
        try:
            self._check_directory_pin("", os.fstat(descriptors[0]), label=label)
            relative_parent_parts: list[str] = []
            for part in PurePosixPath(relative).parts[:-1]:
                parent_fd = descriptors[-1]
                created_here = False
                try:
                    named = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    _require(create, f"{label} parent is missing")
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                        created_here = True
                    except FileExistsError:
                        pass
                    named = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
                _require(
                    stat.S_ISDIR(named.st_mode) and not stat.S_ISLNK(named.st_mode),
                    f"{label} parent is not a physical directory",
                )
                child_fd = os.open(
                    part,
                    os.O_RDONLY
                    | int(getattr(os, "O_DIRECTORY", 0))
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=parent_fd,
                )
                opened = os.fstat(child_fd)
                _require(
                    stat.S_ISDIR(opened.st_mode)
                    and _directory_identity(named) == _directory_identity(opened),
                    f"{label} parent identity changed while opening",
                )
                descriptors.append(child_fd)
                names.append(part)
                relative_parent_parts.append(part)
                self._check_directory_pin(
                    PurePosixPath(*relative_parent_parts).as_posix(),
                    opened,
                    label=label,
                )
                if created_here and created_directories is not None:
                    created_directories.append(
                        (
                            PurePosixPath(*relative_parent_parts).as_posix(),
                            _directory_identity(opened),
                        )
                    )
            self._verify_parent_posix(descriptors, names, label=label)
            return descriptors, names
        except BaseException:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise

    def _verify_parent_posix(
        self, descriptors: list[int], names: list[str], *, label: str
    ) -> None:
        _require(
            len(descriptors) == len(names) + 1,
            f"{label} parent descriptor chain is malformed",
        )
        for index, name in enumerate(names):
            try:
                named = os.stat(
                    name, dir_fd=descriptors[index], follow_symlinks=False
                )
                opened = os.fstat(descriptors[index + 1])
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} parent directory chain changed"
                ) from error
            _require(
                stat.S_ISDIR(named.st_mode)
                and not stat.S_ISLNK(named.st_mode)
                and _directory_identity(named) == _directory_identity(opened),
                f"{label} parent directory identity changed",
            )
            self._check_directory_pin(
                PurePosixPath(*names[: index + 1]).as_posix(),
                opened,
                label=label,
            )
        self._check_directory_pin("", os.fstat(descriptors[0]), label=label)
        self.verify()

    @staticmethod
    def _close_descriptors(descriptors: list[int]) -> None:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def _windows_path(
        self,
        relative: str,
        *,
        label: str,
        create_parents: bool,
        created_directories: list[tuple[str, tuple[int, ...]]] | None = None,
    ) -> Path:
        self.verify()
        path = self._root.joinpath(*PurePosixPath(relative).parts)
        parent = path.parent
        cursor = self._root
        self._check_directory_pin("", self._root.lstat(), label=label)
        relative_parent_parts: list[str] = []
        for part in parent.relative_to(self._root).parts:
            cursor /= part
            relative_parent_parts.append(part)
            created_here = False
            if not os.path.lexists(cursor):
                _require(create_parents, f"{label} parent is missing")
                try:
                    cursor.mkdir(mode=0o700)
                    created_here = True
                except FileExistsError:
                    pass
            info = cursor.lstat()
            _require(
                stat.S_ISDIR(info.st_mode)
                and not _is_link_or_reparse(cursor, info)
                and cursor.resolve(strict=True) == cursor,
                f"{label} parent is unsafe",
            )
            self._check_directory_pin(
                PurePosixPath(*relative_parent_parts).as_posix(),
                info,
                label=label,
            )
            if created_here and created_directories is not None:
                created_directories.append(
                    (
                        PurePosixPath(*relative_parent_parts).as_posix(),
                        _directory_identity(info),
                    )
                )
        self.verify()
        return path

    def _windows_parent_epochs(
        self, directory: Path, *, label: str
    ) -> tuple[tuple[int, ...], ...]:
        """Snapshot a physical Windows fallback chain without access times."""

        self.verify()
        try:
            relative = directory.relative_to(self._root)
        except ValueError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} parent escaped project_root"
            ) from error
        epochs = [_directory_epoch(self._root.lstat())]
        cursor = self._root
        parts: list[str] = []
        for part in relative.parts:
            cursor /= part
            parts.append(part)
            info = cursor.lstat()
            _require(
                stat.S_ISDIR(info.st_mode)
                and not _is_link_or_reparse(cursor, info),
                f"{label} parent is unsafe",
            )
            self._check_directory_pin(
                PurePosixPath(*parts).as_posix(), info, label=label
            )
            epochs.append(_directory_epoch(info))
        self.verify()
        return tuple(epochs)

    def read_descriptor(
        self,
        value: Path | str,
        *,
        label: str,
        maximum: int,
        capture: bool = False,
    ) -> tuple[dict[str, Any], bytes | None]:
        """Hash one bounded file; optionally retain its bytes."""

        descriptor, payload, _identity = self.read_descriptor_identity(
            value, label=label, maximum=maximum, capture=capture
        )
        return descriptor, payload

    def read_descriptor_identity(
        self,
        value: Path | str,
        *,
        label: str,
        maximum: int,
        capture: bool = False,
    ) -> tuple[dict[str, Any], bytes | None, tuple[int, int]]:
        """Hash one bounded file and return its held physical inode identity."""

        _require(type(maximum) is int and maximum > 0, f"{label} bound is invalid")
        relative = self._relative(value, label=label)
        if self._posix_custody is not None:
            return self._read_descriptor_posix(
                relative, label=label, maximum=maximum, capture=capture
            )
        return self._read_descriptor_windows(
            relative, label=label, maximum=maximum, capture=capture
        )

    def stat_regular_identity(
        self,
        value: Path | str,
        *,
        label: str,
    ) -> tuple[int, tuple[int, int]]:
        """Return a regular leaf's permission bits and held physical identity."""

        relative = self._relative(value, label=label)
        if self._posix_custody is not None:
            descriptors: list[int] = []
            file_fd = -1
            try:
                descriptors, names = self._open_parent_posix(
                    relative, create=False, label=label
                )
                parent_epochs = self._epochs(descriptors)
                leaf = PurePosixPath(relative).name
                named = os.stat(
                    leaf, dir_fd=descriptors[-1], follow_symlinks=False
                )
                _require(
                    stat.S_ISREG(named.st_mode)
                    and not stat.S_ISLNK(named.st_mode)
                    and int(named.st_nlink) == 1,
                    f"{label} is not one physical file",
                )
                file_fd = os.open(
                    leaf,
                    os.O_RDONLY
                    | int(getattr(os, "O_NONBLOCK", 0))
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=descriptors[-1],
                )
                opened = os.fstat(file_fd)
                _require(
                    stat.S_ISREG(opened.st_mode)
                    and int(opened.st_nlink) == 1
                    and _file_identity(named) == _file_identity(opened),
                    f"{label} identity changed while being inspected",
                )
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(descriptors, parent_epochs, label=label)
                return (
                    stat.S_IMODE(opened.st_mode),
                    (int(opened.st_dev), int(opened.st_ino)),
                )
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} physical stat failed"
                ) from error
            finally:
                if file_fd >= 0:
                    try:
                        os.close(file_fd)
                    except OSError:
                        pass
                self._close_descriptors(descriptors)

        path = self._windows_path(relative, label=label, create_parents=False)
        parent_epochs = self._windows_parent_epochs(path.parent, label=label)
        file_fd = -1
        try:
            named = path.lstat()
            _require(
                stat.S_ISREG(named.st_mode)
                and not _is_link_or_reparse(path, named)
                and int(named.st_nlink) == 1,
                f"{label} is not one physical file",
            )
            file_fd = os.open(
                path,
                os.O_RDONLY
                | int(getattr(os, "O_BINARY", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            opened = os.fstat(file_fd)
            _require(
                _file_identity(named) == _file_identity(opened),
                f"{label} identity changed while being inspected",
            )
            self.verify()
            _require(
                self._windows_parent_epochs(path.parent, label=label)
                == parent_epochs,
                f"{label} parent directory mutated during custody",
            )
            return (
                stat.S_IMODE(opened.st_mode),
                (int(opened.st_dev), int(opened.st_ino)),
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} physical stat failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass

    def stat_directory_identity(
        self,
        value: Path | str,
        *,
        label: str,
    ) -> tuple[int, tuple[int, ...]]:
        """Return a held physical directory's mode and exact identity."""

        relative = self._relative(value, label=label)
        sentinel = f"{relative}/.publication-directory-stat-v1"
        if self._posix_custody is not None:
            descriptors: list[int] = []
            try:
                descriptors, names = self._open_parent_posix(
                    sentinel, create=False, label=label
                )
                parent_epochs = self._epochs(descriptors)
                opened = os.fstat(descriptors[-1])
                _require(
                    stat.S_ISDIR(opened.st_mode),
                    f"{label} is not one physical directory",
                )
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(descriptors, parent_epochs, label=label)
                return stat.S_IMODE(opened.st_mode), _directory_identity(opened)
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} physical directory stat failed"
                ) from error
            finally:
                self._close_descriptors(descriptors)

        probe = self._windows_path(
            sentinel, label=label, create_parents=False
        )
        directory = probe.parent
        parent_epochs = self._windows_parent_epochs(directory, label=label)
        try:
            info = directory.lstat()
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} physical directory stat failed"
            ) from error
        _require(
            stat.S_ISDIR(info.st_mode)
            and not _is_link_or_reparse(directory, info)
            and self._windows_parent_epochs(directory, label=label)
            == parent_epochs,
            f"{label} changed while being inspected",
        )
        self.verify()
        return stat.S_IMODE(info.st_mode), _directory_identity(info)

    def list_directory_names(
        self,
        value: Path | str,
        *,
        label: str,
    ) -> tuple[str, ...]:
        """List one held physical directory without following a replacement."""

        relative = self._relative(value, label=label)
        sentinel = f"{relative}/.publication-directory-list-v1"
        if self._posix_custody is not None:
            descriptors: list[int] = []
            try:
                descriptors, names = self._open_parent_posix(
                    sentinel, create=False, label=label
                )
                directory_epochs = self._epochs(descriptors)
                entries = tuple(sorted(os.listdir(descriptors[-1])))
                _require(
                    all(
                        type(name) is str
                        and bool(name)
                        and name not in {".", ".."}
                        and "/" not in name
                        and "\\" not in name
                        and "\x00" not in name
                        for name in entries
                    ),
                    f"{label} contains an invalid entry name",
                )
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(descriptors, directory_epochs, label=label)
                return entries
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} physical directory listing failed"
                ) from error
            finally:
                self._close_descriptors(descriptors)

        probe = self._windows_path(
            sentinel, label=label, create_parents=False
        )
        directory = probe.parent
        directory_epochs = self._windows_parent_epochs(directory, label=label)
        try:
            entries = tuple(sorted(entry.name for entry in os.scandir(directory)))
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} physical directory listing failed"
            ) from error
        _require(
            all(
                type(name) is str
                and bool(name)
                and name not in {".", ".."}
                and "/" not in name
                and "\\" not in name
                and "\x00" not in name
                for name in entries
            )
            and self._windows_parent_epochs(directory, label=label)
            == directory_epochs,
            f"{label} changed while being listed",
        )
        self.verify()
        return entries

    def _read_descriptor_posix(
        self, relative: str, *, label: str, maximum: int, capture: bool
    ) -> tuple[dict[str, Any], bytes | None, tuple[int, int]]:
        descriptors: list[int] = []
        file_fd = -1
        chunks: list[bytes] | None = [] if capture else None
        size = 0
        digest = hashlib.sha256()
        try:
            descriptors, names = self._open_parent_posix(
                relative, create=False, label=label
            )
            parent_epochs = self._epochs(descriptors)
            parent_fd = descriptors[-1]
            leaf = PurePosixPath(relative).name
            named_before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISREG(named_before.st_mode)
                and not stat.S_ISLNK(named_before.st_mode)
                and int(named_before.st_nlink) == 1
                and 0 < int(named_before.st_size) <= maximum,
                f"{label} is not one bounded physical file",
            )
            file_fd = os.open(
                leaf,
                os.O_RDONLY
                | int(getattr(os, "O_NONBLOCK", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=parent_fd,
            )
            opened = os.fstat(file_fd)
            _require(
                stat.S_ISREG(opened.st_mode)
                and int(opened.st_nlink) == 1
                and _file_identity(named_before) == _file_identity(opened),
                f"{label} identity changed before read",
            )
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                _require(size <= maximum, f"{label} exceeded its size bound")
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            after = os.fstat(file_fd)
            named_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            self._verify_parent_posix(descriptors, names, label=label)
            self._require_epochs(
                descriptors,
                parent_epochs,
                label=label,
            )
            _require(
                _file_identity(named_before)
                == _file_identity(opened)
                == _file_identity(after)
                == _file_identity(named_after)
                and size == int(after.st_size),
                f"{label} changed while being read",
            )
            return (
                {"path": relative, "size_bytes": size, "sha256": digest.hexdigest()},
                None if chunks is None else b"".join(chunks),
                (int(after.st_dev), int(after.st_ino)),
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} physical read failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass
            self._close_descriptors(descriptors)

    def _read_descriptor_windows(
        self, relative: str, *, label: str, maximum: int, capture: bool
    ) -> tuple[dict[str, Any], bytes | None, tuple[int, int]]:
        path = self._windows_path(relative, label=label, create_parents=False)
        parent_epochs = self._windows_parent_epochs(path.parent, label=label)
        file_fd = -1
        chunks: list[bytes] | None = [] if capture else None
        size = 0
        digest = hashlib.sha256()
        try:
            named_before = path.lstat()
            _require(
                stat.S_ISREG(named_before.st_mode)
                and not _is_link_or_reparse(path, named_before)
                and int(named_before.st_nlink) == 1
                and 0 < int(named_before.st_size) <= maximum,
                f"{label} is not one bounded physical file",
            )
            file_fd = os.open(
                path,
                os.O_RDONLY
                | int(getattr(os, "O_BINARY", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            opened = os.fstat(file_fd)
            _require(
                _file_identity(named_before) == _file_identity(opened),
                f"{label} identity changed before read",
            )
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                _require(size <= maximum, f"{label} exceeded its size bound")
                digest.update(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            after = os.fstat(file_fd)
            named_after = path.lstat()
            self.verify()
            _require(
                self._windows_parent_epochs(path.parent, label=label)
                == parent_epochs,
                f"{label} parent directory mutated during custody",
            )
            _require(
                _file_identity(named_before)
                == _file_identity(opened)
                == _file_identity(after)
                == _file_identity(named_after)
                and not _is_link_or_reparse(path, named_after)
                and size == int(after.st_size),
                f"{label} changed while being read",
            )
            return (
                {"path": relative, "size_bytes": size, "sha256": digest.hexdigest()},
                None if chunks is None else b"".join(chunks),
                (int(after.st_dev), int(after.st_ino)),
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} physical read failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass

    def capture_read_namespace(
        self,
        values: list[Path | str] | tuple[Path | str, ...],
        *,
        label: str,
    ) -> tuple[tuple[str, tuple[tuple[int, ...], ...], tuple[int, ...]], ...]:
        """Pin file/parent identities around a path-based read-only callback."""

        _require(bool(values), f"{label} namespace is empty")
        entries = [
            self._capture_namespace_entry(value, label=f"{label}[{position}]")
            for position, value in enumerate(values)
        ]
        _require(
            len({entry[0] for entry in entries}) == len(entries),
            f"{label} namespace contains duplicate paths",
        )
        return tuple(entries)

    def verify_read_namespace(
        self,
        token: tuple[
            tuple[str, tuple[tuple[int, ...], ...], tuple[int, ...]], ...
        ],
        *,
        label: str,
    ) -> None:
        """Reject any file rebind or parent mutation across a callback."""

        _require(bool(token), f"{label} namespace token is empty")
        observed = tuple(
            self._capture_namespace_entry(relative, label=f"{label}[{position}]")
            for position, (relative, _parents, _leaf) in enumerate(token)
        )
        _require(observed == token, f"{label} namespace changed during cold load")

    def capture_pinned_directory_epochs(
        self, *, label: str
    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
        """Snapshot every directory identity already entrusted to this custody."""

        self._require_open()
        entries: list[tuple[str, tuple[int, ...]]] = []
        for relative in sorted(self._directory_pins):
            if self._posix_custody is not None:
                probe = (
                    ".publication-pinned-directory-probe"
                    if relative == ""
                    else f"{relative}/.publication-pinned-directory-probe"
                )
                descriptors: list[int] = []
                try:
                    descriptors, names = self._open_parent_posix(
                        probe, create=False, label=label
                    )
                    self._verify_parent_posix(descriptors, names, label=label)
                    entries.append((relative, _directory_epoch(os.fstat(descriptors[-1]))))
                finally:
                    self._close_descriptors(descriptors)
            else:
                directory = (
                    self._root
                    if relative == ""
                    else self._root.joinpath(*PurePosixPath(relative).parts)
                )
                epochs = self._windows_parent_epochs(directory, label=label)
                entries.append((relative, epochs[-1]))
        return tuple(entries)

    def verify_pinned_directory_epochs(
        self,
        token: tuple[tuple[str, tuple[int, ...]], ...],
        *,
        label: str,
    ) -> None:
        _require(
            self.capture_pinned_directory_epochs(label=label) == token,
            f"{label} pinned directory namespace changed during cold load",
        )

    @staticmethod
    def _inotify_api(*, label: str) -> tuple[Any, Any]:
        global _INOTIFY_API

        _require(
            hasattr(os, "uname") and os.uname().sysname == "Linux",
            f"{label} transient directory mutation watch is unavailable",
        )
        if _INOTIFY_API is not None:
            return _INOTIFY_API
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            initialize = libc.inotify_init1
            add_watch = libc.inotify_add_watch
        except AttributeError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} transient directory mutation watch is unavailable"
            ) from error
        initialize.argtypes = [ctypes.c_int]
        initialize.restype = ctypes.c_int
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        _INOTIFY_API = initialize, add_watch
        return _INOTIFY_API

    @classmethod
    def _begin_descriptor_mutation_watch(
        cls,
        descriptors: list[int],
        *,
        label: str,
    ) -> _PinnedDirectoryMutationWatchV1:
        """Watch held directory descriptors without reopening the namespace."""

        _require(bool(descriptors), f"{label} mutation watch is empty")
        initialize, add_watch = cls._inotify_api(label=label)
        descriptor = int(
            initialize(
                int(getattr(os, "O_NONBLOCK", 0))
                | int(getattr(os, "O_CLOEXEC", 0))
            )
        )
        if descriptor < 0:
            error_number = ctypes.get_errno()
            raise PublicationPhysicalIoV1Error(
                f"{label} transient directory mutation watch could not start: "
                f"{os.strerror(error_number)}"
            )
        token = _PinnedDirectoryMutationWatchV1(descriptor)
        try:
            identities: set[tuple[int, ...]] = set()
            for directory_fd in descriptors:
                identity = _directory_identity(os.fstat(directory_fd))
                if identity in identities:
                    continue
                identities.add(identity)
                proc_path = os.fsencode(f"/proc/self/fd/{directory_fd}")
                watch_descriptor = int(
                    add_watch(
                        descriptor,
                        proc_path,
                        _INOTIFY_MUTATION_MASK,
                    )
                )
                if watch_descriptor < 0:
                    error_number = ctypes.get_errno()
                    raise PublicationPhysicalIoV1Error(
                        f"{label} transient directory mutation watch failed: "
                        f"{os.strerror(error_number)}"
                    )
            return token
        except BaseException:
            token.close()
            raise

    def begin_read_namespace_mutation_watch(
        self,
        values: list[Path | str] | tuple[Path | str, ...],
        *,
        label: str,
    ) -> _PinnedDirectoryMutationWatchV1 | None:
        """Watch only the held parent chains used by one cold-load boundary."""

        self._require_open()
        _require(bool(values), f"{label} mutation watch namespace is empty")
        if self._posix_custody is None:
            return None
        held_directories: list[int] = []
        held_identities: set[tuple[int, ...]] = set()
        token: _PinnedDirectoryMutationWatchV1 | None = None
        try:
            for position, value in enumerate(values):
                relative = self._relative(
                    value, label=f"{label}[{position}]",
                )
                descriptors: list[int] = []
                try:
                    descriptors, names = self._open_parent_posix(
                        relative, create=False, label=f"{label}[{position}]",
                    )
                    self._verify_parent_posix(
                        descriptors, names, label=f"{label}[{position}]",
                    )
                    for item in descriptors:
                        identity = _directory_identity(os.fstat(item))
                        if identity in held_identities:
                            continue
                        duplicate = os.dup(item)
                        held_directories.append(duplicate)
                        held_identities.add(identity)
                finally:
                    self._close_descriptors(descriptors)
            token = self._begin_descriptor_mutation_watch(
                held_directories, label=label,
            )
            self.verify()
            return token
        except BaseException:
            if token is not None:
                token.close()
            raise
        finally:
            self._close_descriptors(held_directories)

    def verify_pinned_directory_mutation_watch(
        self,
        token: _PinnedDirectoryMutationWatchV1 | None,
        *,
        label: str,
    ) -> None:
        """Consume and close an owned watch, rejecting any queued mutation."""

        if token is None:
            return
        _require(not token.closed, f"{label} mutation watch is already closed")
        mutated = False
        try:
            while True:
                try:
                    payload = os.read(token.descriptor, 1024 * 1024)
                except BlockingIOError:
                    break
                except InterruptedError:
                    continue
                if not payload:
                    break
                mutated = True
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} transient directory mutation watch failed"
            ) from error
        finally:
            token.close()
        _require(
            not mutated,
            f"{label} pinned directory namespace mutated during cold load",
        )

    def _capture_namespace_entry(
        self, value: Path | str, *, label: str
    ) -> tuple[str, tuple[tuple[int, ...], ...], tuple[int, ...]]:
        relative = self._relative(value, label=label)
        if self._posix_custody is not None:
            descriptors: list[int] = []
            try:
                descriptors, names = self._open_parent_posix(
                    relative, create=False, label=label
                )
                parent_epochs = self._epochs(descriptors)
                leaf = PurePosixPath(relative).name
                named = os.stat(leaf, dir_fd=descriptors[-1], follow_symlinks=False)
                _require(
                    stat.S_ISREG(named.st_mode)
                    and not stat.S_ISLNK(named.st_mode)
                    and int(named.st_nlink) == 1,
                    f"{label} is not one physical file",
                )
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(
                    descriptors,
                    parent_epochs,
                    label=label,
                )
                return relative, parent_epochs, _file_identity(named)
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} namespace capture failed"
                ) from error
            finally:
                self._close_descriptors(descriptors)
        path = self._windows_path(relative, label=label, create_parents=False)
        parent_epochs = self._windows_parent_epochs(path.parent, label=label)
        try:
            named = path.lstat()
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} namespace capture failed"
            ) from error
        _require(
            stat.S_ISREG(named.st_mode)
            and not _is_link_or_reparse(path, named)
            and int(named.st_nlink) == 1,
            f"{label} is not one physical file",
        )
        _require(
            self._windows_parent_epochs(path.parent, label=label) == parent_epochs,
            f"{label} parent directory mutated during custody",
        )
        return relative, parent_epochs, _file_identity(named)

    @staticmethod
    def _read_exact_fd(file_fd: int, payload: bytes, *, label: str) -> None:
        os.lseek(file_fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = len(payload) + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        _require(b"".join(chunks) == payload, f"{label} exact bytes drifted")

    def _invoke_atomic_fault_step(
        self,
        callback: Callable[[str], None] | None,
        step: str,
        *,
        descriptors: list[int],
        label: str,
    ) -> None:
        if callback is None:
            return
        watch = (
            self._begin_descriptor_mutation_watch(descriptors, label=label)
            if self._posix_custody is not None
            else None
        )
        try:
            callback(step)
        except BaseException:
            if watch is not None:
                watch.close()
            raise
        self.verify_pinned_directory_mutation_watch(watch, label=label)

    def adopt_exact_durable_identity(
        self,
        value: Path | str,
        payload: bytes,
        *,
        label: str,
        mode: int = 0o444,
        expected_identity: tuple[int, int] | None = None,
        allow_empty: bool = False,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        """Cold-verify and durabilize one exact immutable causal leaf."""

        _require(type(payload) is bytes, f"{label} payload is not bytes")
        _require(type(allow_empty) is bool, f"{label} allow_empty is invalid")
        _require(bool(payload) or allow_empty, f"{label} payload is empty")
        _require(
            type(mode) is int and 0 <= mode <= 0o777,
            f"{label} mode is invalid",
        )
        relative = self._relative(value, label=label)
        if self._posix_custody is not None:
            return self._adopt_exact_durable_posix(
                relative,
                payload,
                label=label,
                mode=mode,
                expected_identity=expected_identity,
            )
        return self._adopt_exact_durable_windows(
            relative,
            payload,
            label=label,
            mode=mode,
            expected_identity=expected_identity,
        )

    def _adopt_exact_durable_posix(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        expected_identity: tuple[int, int] | None,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        descriptors: list[int] = []
        file_fd = -1
        leaf = PurePosixPath(relative).name
        try:
            descriptors, names = self._open_parent_posix(
                relative, create=False, label=label
            )
            parent_epochs = self._epochs(descriptors)
            parent_fd = descriptors[-1]
            named_before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISREG(named_before.st_mode)
                and not stat.S_ISLNK(named_before.st_mode)
                and int(named_before.st_nlink) == 1
                and self._mode_matches(stat.S_IMODE(named_before.st_mode), mode)
                and int(named_before.st_size) == len(payload),
                f"{label} is not one exact immutable physical file",
            )
            file_fd = os.open(
                leaf,
                os.O_RDONLY
                | int(getattr(os, "O_NONBLOCK", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=parent_fd,
            )
            opened = os.fstat(file_fd)
            identity = int(opened.st_dev), int(opened.st_ino)
            _require(
                _file_identity(named_before) == _file_identity(opened),
                f"{label} identity changed before durability barrier",
            )
            if expected_identity is not None:
                _require(
                    identity == expected_identity,
                    f"{label} inode identity changed before durability barrier",
                )
            self._read_exact_fd(file_fd, payload, label=label)
            os.fsync(file_fd)
            os.fsync(parent_fd)
            self._read_exact_fd(file_fd, payload, label=label)
            opened_after = os.fstat(file_fd)
            named_after = os.stat(
                leaf, dir_fd=parent_fd, follow_symlinks=False
            )
            _require(
                _file_identity(opened)
                == _file_identity(opened_after)
                == _file_identity(named_after)
                and self._mode_matches(stat.S_IMODE(opened_after.st_mode), mode)
                and int(opened_after.st_nlink) == 1
                and (int(opened_after.st_dev), int(opened_after.st_ino))
                == identity,
                f"{label} changed across durability barrier",
            )
            self._verify_parent_posix(descriptors, names, label=label)
            self._require_epochs(descriptors, parent_epochs, label=label)
            return (
                {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                identity,
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} exact durability barrier failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass
            self._close_descriptors(descriptors)

    def _adopt_exact_durable_windows(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        expected_identity: tuple[int, int] | None,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        path = self._windows_path(relative, label=label, create_parents=False)
        parent_epochs = self._windows_parent_epochs(path.parent, label=label)
        file_fd = -1
        try:
            named_before = path.lstat()
            _require(
                stat.S_ISREG(named_before.st_mode)
                and not _is_link_or_reparse(path, named_before)
                and int(named_before.st_nlink) == 1
                and int(named_before.st_size) == len(payload),
                f"{label} is not one exact immutable physical file",
            )
            file_fd = os.open(
                path,
                os.O_RDONLY
                | int(getattr(os, "O_BINARY", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            opened = os.fstat(file_fd)
            identity = int(opened.st_dev), int(opened.st_ino)
            _require(
                _file_identity(named_before) == _file_identity(opened),
                f"{label} identity changed before durability barrier",
            )
            if expected_identity is not None:
                _require(
                    identity == expected_identity,
                    f"{label} inode identity changed before durability barrier",
                )
            self._read_exact_fd(file_fd, payload, label=label)
            os.fsync(file_fd)
            self._read_exact_fd(file_fd, payload, label=label)
            opened_after = os.fstat(file_fd)
            named_after = path.lstat()
            _require(
                _file_identity(opened)
                == _file_identity(opened_after)
                == _file_identity(named_after)
                and not _is_link_or_reparse(path, named_after)
                and (int(opened_after.st_dev), int(opened_after.st_ino))
                == identity,
                f"{label} changed across durability barrier",
            )
            self.verify()
            _require(
                self._windows_parent_epochs(path.parent, label=label)
                == parent_epochs,
                f"{label} parent changed across durability barrier",
            )
            return (
                {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                identity,
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} exact durability barrier failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass

    @staticmethod
    def _atomic_transaction_key(relative: str, payload: bytes, mode: int) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        identity = f"{relative}\x00{len(payload)}\x00{digest}\x00{mode:o}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def commit_or_adopt_exact_identity(
        self,
        value: Path | str,
        payload: bytes,
        *,
        label: str,
        mode: int = 0o444,
        create_parents: bool = True,
        after_publish_step: Callable[[str], None] | None = None,
        allow_empty: bool = False,
    ) -> tuple[
        dict[str, Any], tuple[int, int], Literal["published", "adopted"]
    ]:
        """Atomically publish without replacement, or durably adopt exact bytes.

        Staging lives in a parent-controlled deterministic transaction namespace,
        outside the final output directory.  On Linux filesystems without
        ``renameat2(RENAME_NOREPLACE)`` (notably WSL DrvFS), a hard-link publish
        is used and its possible two-link crash state is recovered under the
        transaction lock before exact adoption.
        """

        _require(type(payload) is bytes, f"{label} payload is not bytes")
        _require(type(allow_empty) is bool, f"{label} allow_empty is invalid")
        _require(bool(payload) or allow_empty, f"{label} payload is empty")
        _require(
            type(mode) is int and 0 <= mode <= 0o777,
            f"{label} mode is invalid",
        )
        relative = self._relative(value, label=label)
        _require(
            relative != _ATOMIC_STAGING_ROOT
            and not relative.startswith(_ATOMIC_STAGING_ROOT + "/"),
            f"{label} aliases the parent atomic staging namespace",
        )
        if self._posix_custody is not None:
            return self._commit_or_adopt_exact_posix(
                relative,
                payload,
                label=label,
                mode=mode,
                create_parents=create_parents,
                after_publish_step=after_publish_step,
                allow_empty=allow_empty,
            )
        return self._commit_or_adopt_exact_windows(
            relative,
            payload,
            label=label,
            mode=mode,
            create_parents=create_parents,
            after_publish_step=after_publish_step,
            allow_empty=allow_empty,
        )

    def _open_atomic_staging_lock_posix(
        self, *, label: str
    ) -> tuple[list[int], list[str], int]:
        _require(fcntl is not None, f"{label} POSIX transaction lock is unavailable")
        descriptors: list[int] = []
        lock_fd = -1
        try:
            custody = self._posix_custody
            _require(
                custody is not None,
                f"{label} POSIX transaction custody is unavailable",
            )
            self.verify()
            root_fd = os.dup(custody.directory_fd)
            descriptors.append(root_fd)
            self._check_directory_pin("", os.fstat(root_fd), label=label)
            try:
                os.mkdir(_ATOMIC_STAGING_ROOT, mode=0o700, dir_fd=root_fd)
                os.fsync(root_fd)
            except FileExistsError:
                pass
            named_staging = os.stat(
                _ATOMIC_STAGING_ROOT,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            _require(
                stat.S_ISDIR(named_staging.st_mode)
                and not stat.S_ISLNK(named_staging.st_mode),
                f"{label} atomic staging root is not a physical directory",
            )
            staging_fd = os.open(
                _ATOMIC_STAGING_ROOT,
                os.O_RDONLY
                | int(getattr(os, "O_DIRECTORY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=root_fd,
            )
            descriptors.append(staging_fd)
            opened_staging = os.fstat(staging_fd)
            _require(
                stat.S_ISDIR(opened_staging.st_mode)
                and _directory_identity(named_staging)
                == _directory_identity(opened_staging),
                f"{label} atomic staging root identity changed while opening",
            )
            # Do not pin the staging directory epoch before taking this lock.
            # A concurrent exact publisher legitimately creates/removes its
            # deterministic transaction directory there.  Both publishers
            # must first converge on this held directory inode and serialize;
            # only then may the mutable staging namespace be inspected.
            staging_fd = descriptors[-1]
            lock_fd = os.open(
                _ATOMIC_STAGING_LOCK,
                os.O_RDWR
                | os.O_CREAT
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                0o600,
                dir_fd=staging_fd,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            opened = os.fstat(lock_fd)
            named = os.stat(
                _ATOMIC_STAGING_LOCK,
                dir_fd=staging_fd,
                follow_symlinks=False,
            )
            _require(
                stat.S_ISREG(opened.st_mode)
                and not stat.S_ISLNK(named.st_mode)
                and int(opened.st_nlink) == 1
                and int(opened.st_size) == 0
                and _file_identity(opened) == _file_identity(named),
                f"{label} atomic staging lock identity drifted",
            )
            os.fchmod(lock_fd, 0o600)
            os.fsync(lock_fd)
            os.fsync(staging_fd)
            opened = os.fstat(lock_fd)
            named = os.stat(
                _ATOMIC_STAGING_LOCK,
                dir_fd=staging_fd,
                follow_symlinks=False,
            )
            _require(
                stat.S_ISREG(opened.st_mode)
                and int(opened.st_nlink) == 1
                and int(opened.st_size) == 0
                and self._mode_matches(stat.S_IMODE(opened.st_mode), 0o600)
                and _file_identity(opened) == _file_identity(named),
                f"{label} atomic staging lock identity drifted",
            )
            named_staging = os.stat(
                _ATOMIC_STAGING_ROOT,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            opened_staging = os.fstat(staging_fd)
            _require(
                stat.S_ISDIR(opened_staging.st_mode)
                and _directory_identity(named_staging)
                == _directory_identity(opened_staging)
                and self._mode_matches(
                    stat.S_IMODE(opened_staging.st_mode), 0o700
                ),
                f"{label} atomic staging root identity or mode drifted",
            )
            self._check_directory_pin(
                _ATOMIC_STAGING_ROOT,
                opened_staging,
                label=f"{label} atomic staging root",
            )
            self._verify_parent_posix(
                descriptors,
                [_ATOMIC_STAGING_ROOT],
                label=f"{label} atomic staging lock",
            )
            return descriptors, [_ATOMIC_STAGING_ROOT], lock_fd
        except BaseException:
            if lock_fd >= 0:
                try:
                    os.close(lock_fd)
                except OSError:
                    pass
            self._close_descriptors(descriptors)
            raise

    @staticmethod
    def _stat_named_optional_posix(
        parent_fd: int, leaf: str
    ) -> os.stat_result | None:
        try:
            return os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _verify_exact_named_posix(
        self,
        parent_fd: int,
        leaf: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        allowed_links: frozenset[int],
    ) -> tuple[os.stat_result, tuple[int, int]]:
        file_fd = -1
        try:
            named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISREG(named.st_mode)
                and not stat.S_ISLNK(named.st_mode)
                and int(named.st_nlink) in allowed_links
                and self._mode_matches(stat.S_IMODE(named.st_mode), mode)
                and int(named.st_size) == len(payload),
                f"{label} exact staged/final identity drifted",
            )
            file_fd = os.open(
                leaf,
                os.O_RDONLY
                | int(getattr(os, "O_NONBLOCK", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=parent_fd,
            )
            opened = os.fstat(file_fd)
            _require(
                _file_identity(named) == _file_identity(opened),
                f"{label} exact staged/final inode changed while opening",
            )
            self._read_exact_fd(file_fd, payload, label=label)
            return named, (int(opened.st_dev), int(opened.st_ino))
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass

    @staticmethod
    def _atomic_record_payload(kind: str, fields: dict[str, Any]) -> bytes:
        core = {
            "schema_version": 1,
            "artifact_kind": kind,
            **fields,
        }
        core_payload = json.dumps(
            core,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        record = {
            **core,
            "record_sha256": hashlib.sha256(core_payload).hexdigest(),
        }
        return (
            json.dumps(
                record,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")

    def _commit_or_adopt_atomic_record_posix(
        self,
        parent_fd: int,
        leaf: str,
        payload: bytes,
        *,
        label: str,
    ) -> tuple[int, int]:
        """Durably create one immutable transaction record, or exact-adopt it."""

        record_fd = -1
        created = False
        try:
            try:
                record_fd = os.open(
                    leaf,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    0o600,
                    dir_fd=parent_fd,
                )
                created = True
            except FileExistsError:
                record_fd = os.open(
                    leaf,
                    os.O_RDONLY
                    | int(getattr(os, "O_NONBLOCK", 0))
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=parent_fd,
                )
            if created:
                offset = 0
                while offset < len(payload):
                    written = os.write(record_fd, payload[offset:])
                    _require(written > 0, f"{label} write stalled")
                    offset += written
                os.fchmod(record_fd, 0o444)
                os.fsync(record_fd)
                os.fsync(parent_fd)
            opened = os.fstat(record_fd)
            named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISREG(opened.st_mode)
                and not stat.S_ISLNK(named.st_mode)
                and int(opened.st_nlink) == 1
                and self._mode_matches(stat.S_IMODE(opened.st_mode), 0o444)
                and int(opened.st_size) == len(payload)
                and _file_identity(opened) == _file_identity(named),
                f"{label} identity drifted",
            )
            if created:
                os.lseek(record_fd, 0, os.SEEK_SET)
            else:
                self._read_exact_fd(record_fd, payload, label=label)
            return int(opened.st_dev), int(opened.st_ino)
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} durable commit failed"
            ) from error
        finally:
            if record_fd >= 0:
                try:
                    os.close(record_fd)
                except OSError:
                    pass

    def _remove_exact_atomic_record_posix(
        self,
        parent_fd: int,
        leaf: str,
        payload: bytes,
        *,
        label: str,
    ) -> None:
        """Remove only the exact immutable record proven in this transaction."""

        _named, identity = self._verify_exact_named_posix(
            parent_fd,
            leaf,
            payload,
            label=label,
            mode=0o444,
            allowed_links=frozenset({1}),
        )
        current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            (int(current.st_dev), int(current.st_ino)) == identity,
            f"{label} identity changed before removal",
        )
        os.unlink(leaf, dir_fd=parent_fd)
        os.fsync(parent_fd)

    @staticmethod
    def _atomic_stage_record_payloads(
        *,
        transaction_key: str,
        transaction_identity: tuple[int, ...],
        stage_identity: tuple[int, int],
        relative: str,
        payload: bytes,
        mode: int,
    ) -> tuple[bytes, bytes]:
        fields = {
            "transaction_key": transaction_key,
            "transaction_identity": list(transaction_identity),
            "stage_identity": list(stage_identity),
            "relative_path": relative,
            "payload_size_bytes": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "mode_octal": f"{mode:o}",
        }
        return (
            PhysicalRootCustodyV1._atomic_record_payload(
                "publication_atomic_stage_intent_v1", fields
            ),
            PhysicalRootCustodyV1._atomic_record_payload(
                "publication_atomic_stage_complete_v1", fields
            ),
        )

    def _commit_or_adopt_exact_posix(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        create_parents: bool,
        after_publish_step: Callable[[str], None] | None,
        allow_empty: bool,
    ) -> tuple[
        dict[str, Any], tuple[int, int], Literal["published", "adopted"]
    ]:
        lock_descriptors: list[int] = []
        lock_fd = -1
        target_descriptors: list[int] = []
        transaction_descriptors: list[int] = []
        stage_fd = -1
        stage_identity: tuple[int, int] | None = None
        stage_intent_payload: bytes | None = None
        stage_complete_payload: bytes | None = None
        transaction_key = self._atomic_transaction_key(relative, payload, mode)
        transaction_relative = (
            f"{_ATOMIC_STAGING_ROOT}/txn-{transaction_key}"
        )
        transaction_identity: tuple[int, ...] | None = None
        transaction_intent_payload: bytes | None = None

        def fault(step: str, descriptors: list[int]) -> None:
            self._invoke_atomic_fault_step(
                after_publish_step,
                step,
                descriptors=descriptors,
                label=f"{label} {step}",
            )

        try:
            lock_descriptors, _lock_names, lock_fd = (
                self._open_atomic_staging_lock_posix(label=label)
            )
            _transaction_path, created_directories = self.ensure_directory_owned(
                transaction_relative,
                label=f"{label} atomic transaction directory",
            )
            transaction_created_here = any(
                path == transaction_relative for path, _identity in created_directories
            )
            transaction_mode, transaction_identity = self.stat_directory_identity(
                transaction_relative,
                label=f"{label} atomic transaction directory",
            )
            _require(
                self._mode_matches(transaction_mode, 0o700),
                f"{label} atomic transaction directory mode drifted",
            )
            transaction_descriptors, transaction_names = self._open_parent_posix(
                f"{transaction_relative}/.publication-stage-probe",
                create=False,
                label=f"{label} atomic transaction directory",
            )
            transaction_fd = transaction_descriptors[-1]
            transaction_entries_before_intent = tuple(
                sorted(os.listdir(transaction_fd))
            )
            if _ATOMIC_TRANSACTION_INTENT not in transaction_entries_before_intent:
                _require(
                    transaction_created_here
                    and transaction_entries_before_intent == (),
                    f"{label} atomic transaction provenance intent is absent",
                )
            transaction_intent_payload = self._atomic_record_payload(
                "publication_atomic_transaction_intent_v1",
                {
                    "transaction_key": transaction_key,
                    "transaction_identity": list(transaction_identity),
                    "relative_path": relative,
                    "payload_size_bytes": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "mode_octal": f"{mode:o}",
                },
            )
            self._commit_or_adopt_atomic_record_posix(
                transaction_fd,
                _ATOMIC_TRANSACTION_INTENT,
                transaction_intent_payload,
                label=f"{label} atomic transaction provenance intent",
            )
            target_descriptors, target_names = self._open_parent_posix(
                relative,
                create=create_parents,
                label=label,
            )
            target_fd = target_descriptors[-1]
            target_leaf = PurePosixPath(relative).name
            ancestor_epochs = self._epochs(target_descriptors[:-1])
            transaction_entries = tuple(sorted(os.listdir(transaction_fd)))
            _require(
                set(transaction_entries)
                <= {
                    _ATOMIC_STAGING_LEAF,
                    *_ATOMIC_TRANSACTION_RECORDS,
                },
                f"{label} atomic transaction contains foreign entries",
            )
            final_named = self._stat_named_optional_posix(target_fd, target_leaf)
            stage_named = self._stat_named_optional_posix(
                transaction_fd, _ATOMIC_STAGING_LEAF
            )
            record_names = set(transaction_entries)
            stage_intent_present = _ATOMIC_STAGE_INTENT in record_names
            stage_complete_present = _ATOMIC_STAGE_COMPLETE in record_names
            _require(
                not stage_complete_present or stage_intent_present,
                f"{label} atomic stage completion lacks provenance intent",
            )
            if stage_named is not None:
                _require(
                    stage_intent_present,
                    f"{label} atomic stage provenance intent is absent",
                )
                stage_identity = int(stage_named.st_dev), int(stage_named.st_ino)
                stage_intent_payload, stage_complete_payload = (
                    self._atomic_stage_record_payloads(
                        transaction_key=transaction_key,
                        transaction_identity=transaction_identity,
                        stage_identity=stage_identity,
                        relative=relative,
                        payload=payload,
                        mode=mode,
                    )
                )
                self._commit_or_adopt_atomic_record_posix(
                    transaction_fd,
                    _ATOMIC_STAGE_INTENT,
                    stage_intent_payload,
                    label=f"{label} atomic stage provenance intent",
                )
                if stage_complete_present:
                    self._commit_or_adopt_atomic_record_posix(
                        transaction_fd,
                        _ATOMIC_STAGE_COMPLETE,
                        stage_complete_payload,
                        label=f"{label} atomic stage completion",
                    )
            elif stage_intent_present:
                _require(
                    final_named is not None and stage_complete_present,
                    f"{label} orphan atomic stage provenance is not recoverable",
                )
                final_identity = int(final_named.st_dev), int(final_named.st_ino)
                stage_intent_payload, stage_complete_payload = (
                    self._atomic_stage_record_payloads(
                        transaction_key=transaction_key,
                        transaction_identity=transaction_identity,
                        stage_identity=final_identity,
                        relative=relative,
                        payload=payload,
                        mode=mode,
                    )
                )
                self._commit_or_adopt_atomic_record_posix(
                    transaction_fd,
                    _ATOMIC_STAGE_INTENT,
                    stage_intent_payload,
                    label=f"{label} renamed stage provenance intent",
                )
                self._commit_or_adopt_atomic_record_posix(
                    transaction_fd,
                    _ATOMIC_STAGE_COMPLETE,
                    stage_complete_payload,
                    label=f"{label} renamed stage completion",
                )

            def remove_stage_records() -> None:
                nonlocal stage_intent_present, stage_complete_present
                if stage_complete_present:
                    _require(
                        stage_complete_payload is not None,
                        f"{label} atomic stage completion provenance is unavailable",
                    )
                    self._remove_exact_atomic_record_posix(
                        transaction_fd,
                        _ATOMIC_STAGE_COMPLETE,
                        stage_complete_payload,
                        label=f"{label} atomic stage completion",
                    )
                    stage_complete_present = False
                if stage_intent_present:
                    _require(
                        stage_intent_payload is not None,
                        f"{label} atomic stage intent provenance is unavailable",
                    )
                    self._remove_exact_atomic_record_posix(
                        transaction_fd,
                        _ATOMIC_STAGE_INTENT,
                        stage_intent_payload,
                        label=f"{label} atomic stage provenance intent",
                    )
                    stage_intent_present = False

            def remove_proven_stage(*, allowed_links: frozenset[int]) -> None:
                nonlocal stage_named
                _require(
                    stage_named is not None and stage_identity is not None,
                    f"{label} atomic stage provenance is unavailable",
                )
                current = os.stat(
                    _ATOMIC_STAGING_LEAF,
                    dir_fd=transaction_fd,
                    follow_symlinks=False,
                )
                _require(
                    stat.S_ISREG(current.st_mode)
                    and not stat.S_ISLNK(current.st_mode)
                    and int(current.st_nlink) in allowed_links
                    and (int(current.st_dev), int(current.st_ino))
                    == stage_identity,
                    f"{label} atomic stage identity changed before removal",
                )
                os.unlink(_ATOMIC_STAGING_LEAF, dir_fd=transaction_fd)
                os.fsync(transaction_fd)
                stage_named = None
                remove_stage_records()

            if final_named is not None:
                _require(
                    stat.S_ISREG(final_named.st_mode)
                    and not stat.S_ISLNK(final_named.st_mode),
                    f"{label} final output is not one physical file",
                )
                if int(final_named.st_nlink) == 2:
                    _require(
                        stage_named is not None
                        and stage_complete_present
                        and stat.S_ISREG(stage_named.st_mode)
                        and not stat.S_ISLNK(stage_named.st_mode)
                        and (int(stage_named.st_dev), int(stage_named.st_ino))
                        == (int(final_named.st_dev), int(final_named.st_ino)),
                        f"{label} two-link recovery is not transaction-owned",
                    )
                    self._verify_exact_named_posix(
                        target_fd,
                        target_leaf,
                        payload,
                        label=f"{label} linked final recovery",
                        mode=mode,
                        allowed_links=frozenset({2}),
                    )
                    remove_proven_stage(allowed_links=frozenset({2}))
                _require(
                    int(
                        os.stat(
                            target_leaf,
                            dir_fd=target_fd,
                            follow_symlinks=False,
                        ).st_nlink
                    )
                    == 1,
                    f"{label} final output has foreign hard links",
                )
                descriptor, identity = self.adopt_exact_durable_identity(
                    relative,
                    payload,
                    label=f"resumed {label}",
                    mode=mode,
                    allow_empty=allow_empty,
                )
                if stage_named is not None:
                    _require(
                        stat.S_ISREG(stage_named.st_mode)
                        and not stat.S_ISLNK(stage_named.st_mode)
                        and int(stage_named.st_nlink) == 1,
                        f"{label} stale transaction stage is foreign",
                    )
                    remove_proven_stage(allowed_links=frozenset({1}))
                else:
                    remove_stage_records()
                disposition: Literal["published", "adopted"] = "adopted"
            else:
                if stage_named is not None:
                    _require(
                        stat.S_ISREG(stage_named.st_mode)
                        and not stat.S_ISLNK(stage_named.st_mode)
                        and int(stage_named.st_nlink) == 1,
                        f"{label} stale transaction stage is foreign",
                    )
                    remove_proven_stage(allowed_links=frozenset({1}))
                    _require(
                        self._stat_named_optional_posix(
                            transaction_fd, _ATOMIC_STAGING_LEAF
                        )
                        is None,
                        f"{label} stale transaction stage was not removed",
                    )
                else:
                    remove_stage_records()
                stage_fd = os.open(
                    _ATOMIC_STAGING_LEAF,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    0o600,
                    dir_fd=transaction_fd,
                )
                created = os.fstat(stage_fd)
                _require(
                    stat.S_ISREG(created.st_mode)
                    and int(created.st_nlink) == 1,
                    f"{label} staged leaf is not one physical file",
                )
                stage_identity = int(created.st_dev), int(created.st_ino)
                stage_named = created
                stage_intent_payload, stage_complete_payload = (
                    self._atomic_stage_record_payloads(
                        transaction_key=transaction_key,
                        transaction_identity=transaction_identity,
                        stage_identity=stage_identity,
                        relative=relative,
                        payload=payload,
                        mode=mode,
                    )
                )
                self._commit_or_adopt_atomic_record_posix(
                    transaction_fd,
                    _ATOMIC_STAGE_INTENT,
                    stage_intent_payload,
                    label=f"{label} atomic stage provenance intent",
                )
                stage_intent_present = True
                midpoint = max(1, len(payload) // 2) if payload else 0
                offset = 0
                while offset < midpoint:
                    written = os.write(stage_fd, payload[offset:midpoint])
                    _require(written > 0, f"{label} staged write stalled")
                    offset += written
                fault("mid_write", [transaction_fd, target_fd])
                while offset < len(payload):
                    written = os.write(stage_fd, payload[offset:])
                    _require(written > 0, f"{label} staged write stalled")
                    offset += written
                os.fchmod(stage_fd, mode)
                os.fsync(stage_fd)
                os.fsync(transaction_fd)
                staged, verified_stage_identity = self._verify_exact_named_posix(
                    transaction_fd,
                    _ATOMIC_STAGING_LEAF,
                    payload,
                    label=f"{label} staged payload",
                    mode=mode,
                    allowed_links=frozenset({1}),
                )
                _require(
                    verified_stage_identity == stage_identity,
                    f"{label} staged inode changed before publish",
                )
                self._commit_or_adopt_atomic_record_posix(
                    transaction_fd,
                    _ATOMIC_STAGE_COMPLETE,
                    stage_complete_payload,
                    label=f"{label} atomic stage completion",
                )
                stage_complete_present = True
                fault("post_fsync_pre_publish", [transaction_fd, target_fd])
                try:
                    renamed = _rename_noreplace_posix(
                        transaction_fd,
                        _ATOMIC_STAGING_LEAF,
                        target_fd,
                        target_leaf,
                    )
                    if not renamed:
                        os.link(
                            _ATOMIC_STAGING_LEAF,
                            target_leaf,
                            src_dir_fd=transaction_fd,
                            dst_dir_fd=target_fd,
                            follow_symlinks=False,
                        )
                except FileExistsError:
                    descriptor, identity = self.adopt_exact_durable_identity(
                        relative,
                        payload,
                        label=f"raced {label}",
                        mode=mode,
                        allow_empty=allow_empty,
                    )
                    current_stage = os.stat(
                        _ATOMIC_STAGING_LEAF,
                        dir_fd=transaction_fd,
                        follow_symlinks=False,
                    )
                    _require(
                        (int(current_stage.st_dev), int(current_stage.st_ino))
                        == stage_identity,
                        f"{label} raced stage was rebound",
                    )
                    stage_named = current_stage
                    remove_proven_stage(allowed_links=frozenset({1}))
                    disposition = "adopted"
                else:
                    committed = os.stat(
                        target_leaf, dir_fd=target_fd, follow_symlinks=False
                    )
                    _require(
                        (int(committed.st_dev), int(committed.st_ino))
                        == stage_identity
                        and stat.S_ISREG(committed.st_mode)
                        and self._mode_matches(
                            stat.S_IMODE(committed.st_mode), mode
                        )
                        and int(committed.st_size) == len(payload)
                        and int(committed.st_nlink) in {1, 2},
                        f"{label} published inode drifted",
                    )
                    fault(
                        "post_publish_pre_parent_fsync",
                        [transaction_fd, target_fd],
                    )
                    if not renamed:
                        linked_stage = os.stat(
                            _ATOMIC_STAGING_LEAF,
                            dir_fd=transaction_fd,
                            follow_symlinks=False,
                        )
                        linked_final = os.stat(
                            target_leaf,
                            dir_fd=target_fd,
                            follow_symlinks=False,
                        )
                        _require(
                            int(linked_stage.st_nlink) == 2
                            and _file_identity(linked_stage)
                            == _file_identity(linked_final),
                            f"{label} hard-link publish crossbinding drifted",
                        )
                        stage_named = linked_stage
                        remove_proven_stage(allowed_links=frozenset({2}))
                    else:
                        stage_named = None
                        remove_stage_records()
                    os.fsync(transaction_fd)
                    os.fsync(target_fd)
                    descriptor, identity = self.adopt_exact_durable_identity(
                        relative,
                        payload,
                        label=f"committed {label}",
                        mode=mode,
                        allow_empty=allow_empty,
                        expected_identity=stage_identity,
                    )
                    disposition = "published"

            self._verify_parent_posix(
                target_descriptors, target_names, label=label
            )
            self._require_epochs(
                target_descriptors[:-1], ancestor_epochs, label=label
            )
            _require(
                transaction_intent_payload is not None,
                f"{label} atomic transaction intent is unavailable",
            )
            self._remove_exact_atomic_record_posix(
                transaction_fd,
                _ATOMIC_TRANSACTION_INTENT,
                transaction_intent_payload,
                label=f"{label} completed atomic transaction intent",
            )
            _require(
                os.listdir(transaction_fd) == [],
                f"{label} atomic transaction did not close cleanly",
            )
            self._close_descriptors(transaction_descriptors)
            transaction_descriptors = []
            assert transaction_identity is not None
            self.rmdir_owned_identity(
                transaction_relative,
                transaction_identity,
                label=f"{label} completed atomic transaction",
            )
            return descriptor, identity, disposition
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} atomic no-replace commit failed"
            ) from error
        finally:
            if stage_fd >= 0:
                try:
                    os.close(stage_fd)
                except OSError:
                    pass
            self._close_descriptors(transaction_descriptors)
            self._close_descriptors(target_descriptors)
            if lock_fd >= 0:
                try:
                    if fcntl is not None:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    os.close(lock_fd)
                except OSError:
                    pass
            self._close_descriptors(lock_descriptors)

    def _commit_or_adopt_exact_windows(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        create_parents: bool,
        after_publish_step: Callable[[str], None] | None,
        allow_empty: bool,
    ) -> tuple[
        dict[str, Any], tuple[int, int], Literal["published", "adopted"]
    ]:
        path = self._windows_path(
            relative, label=label, create_parents=create_parents
        )
        transaction_key = self._atomic_transaction_key(relative, payload, mode)
        transaction_relative = f"{_ATOMIC_STAGING_ROOT}/txn-{transaction_key}"
        transaction_path, _created = self.ensure_directory_owned(
            transaction_relative,
            label=f"{label} atomic transaction directory",
        )
        transaction_mode, transaction_identity = self.stat_directory_identity(
            transaction_relative,
            label=f"{label} atomic transaction directory",
        )
        _require(
            transaction_mode == 0o700 or os.name == "nt",
            f"{label} atomic transaction directory mode drifted",
        )
        stage = transaction_path / _ATOMIC_STAGING_LEAF
        entries = tuple(sorted(item.name for item in transaction_path.iterdir()))
        _require(
            set(entries) <= {_ATOMIC_STAGING_LEAF},
            f"{label} atomic transaction contains foreign entries",
        )
        if os.path.lexists(path):
            descriptor, identity = self.adopt_exact_durable_identity(
                relative,
                payload,
                label=f"resumed {label}",
                mode=mode,
                allow_empty=allow_empty,
            )
            if os.path.lexists(stage):
                info = stage.lstat()
                _require(
                    stat.S_ISREG(info.st_mode) and not _is_link_or_reparse(stage, info),
                    f"{label} stale transaction stage is foreign",
                )
                stage.unlink()
            self.rmdir_owned_identity(
                transaction_relative,
                transaction_identity,
                label=f"{label} completed atomic transaction",
            )
            return descriptor, identity, "adopted"
        if os.path.lexists(stage):
            info = stage.lstat()
            _require(
                stat.S_ISREG(info.st_mode) and not _is_link_or_reparse(stage, info),
                f"{label} stale transaction stage is foreign",
            )
            stage.unlink()
        stage_fd = -1
        callback_aborted = False
        try:
            stage_fd = os.open(
                stage,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_BINARY", 0)),
                0o600,
            )
            midpoint = max(1, len(payload) // 2) if payload else 0
            offset = 0
            if midpoint:
                offset = os.write(stage_fd, payload[:midpoint])
                _require(offset == midpoint, f"{label} staged write stalled")
            try:
                if after_publish_step is not None:
                    after_publish_step("mid_write")
            except BaseException:
                callback_aborted = True
                raise
            while offset < len(payload):
                written = os.write(stage_fd, payload[offset:])
                _require(written > 0, f"{label} staged write stalled")
                offset += written
            try:
                os.fchmod(stage_fd, mode)
            except OSError:
                pass
            os.fsync(stage_fd)
            try:
                if after_publish_step is not None:
                    after_publish_step("post_fsync_pre_publish")
            except BaseException:
                callback_aborted = True
                raise
            os.close(stage_fd)
            stage_fd = -1
            try:
                os.rename(stage, path)
            except FileExistsError:
                descriptor, identity = self.adopt_exact_durable_identity(
                    relative,
                    payload,
                    label=f"raced {label}",
                    mode=mode,
                    allow_empty=allow_empty,
                )
                stage.unlink()
                disposition: Literal["published", "adopted"] = "adopted"
            else:
                try:
                    if after_publish_step is not None:
                        after_publish_step("post_publish_pre_parent_fsync")
                except BaseException:
                    callback_aborted = True
                    raise
                descriptor, identity = self.adopt_exact_durable_identity(
                    relative,
                    payload,
                    label=f"committed {label}",
                    mode=mode,
                    allow_empty=allow_empty,
                )
                disposition = "published"
            self.rmdir_owned_identity(
                transaction_relative,
                transaction_identity,
                label=f"{label} completed atomic transaction",
            )
            return descriptor, identity, disposition
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} atomic no-replace commit failed"
            ) from error
        finally:
            if stage_fd >= 0:
                try:
                    os.close(stage_fd)
                except OSError:
                    pass
            if not callback_aborted and os.path.lexists(stage):
                try:
                    info = stage.lstat()
                    if stat.S_ISREG(info.st_mode) and not _is_link_or_reparse(stage, info):
                        stage.unlink()
                except OSError:
                    pass

    def write_exclusive(
        self,
        value: Path | str,
        payload: bytes,
        *,
        label: str,
        mode: int = 0o444,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        """Commit one immutable file and cold-read it before returning."""

        descriptor, _identity = self.write_exclusive_identity(
            value,
            payload,
            label=label,
            mode=mode,
            create_parents=create_parents,
        )
        return descriptor

    def write_exclusive_identity(
        self,
        value: Path | str,
        payload: bytes,
        *,
        label: str,
        mode: int = 0o444,
        create_parents: bool = True,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        """Commit, cold-read, and return the exact caller-owned inode."""

        _require(type(payload) is bytes and bool(payload), f"{label} payload is empty")
        relative = self._relative(value, label=label)
        if self._posix_custody is not None:
            descriptor, identity = self._write_exclusive_posix(
                relative,
                payload,
                label=label,
                mode=mode,
                create_parents=create_parents,
            )
        else:
            descriptor, identity = self._write_exclusive_windows(
                relative,
                payload,
                label=label,
                mode=mode,
                create_parents=create_parents,
            )
        try:
            observed, cold_payload, cold_identity = self.read_descriptor_identity(
                relative,
                label=f"committed {label}",
                maximum=len(payload),
                capture=True,
            )
            _require(
                observed == descriptor
                and cold_payload == payload
                and cold_identity == identity,
                f"{label} changed across immutable commit/reload",
            )
        except BaseException:
            try:
                self.unlink_owned_identity(
                    relative,
                    identity,
                    label=f"failed committed {label}",
                )
            except PublicationPhysicalIoV1Error:
                # Preserve both the original failure and any entry we can no
                # longer prove is the caller-owned inode.
                pass
            raise
        return descriptor, identity

    def _write_exclusive_posix(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        create_parents: bool,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        descriptors: list[int] = []
        file_fd = -1
        identity: tuple[int, int] | None = None
        committed = False
        leaf = PurePosixPath(relative).name
        try:
            descriptors, names = self._open_parent_posix(
                relative, create=create_parents, label=label
            )
            ancestor_epochs = self._epochs(descriptors[:-1])
            parent_fd = descriptors[-1]
            file_fd = os.open(
                leaf,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                0o600,
                dir_fd=parent_fd,
            )
            created = os.fstat(file_fd)
            _require(
                stat.S_ISREG(created.st_mode) and int(created.st_nlink) == 1,
                f"{label} created leaf is not one physical file",
            )
            identity = int(created.st_dev), int(created.st_ino)
            offset = 0
            while offset < len(payload):
                written = os.write(file_fd, payload[offset:])
                _require(written > 0, f"{label} immutable write stalled")
                offset += written
            os.fchmod(file_fd, mode)
            os.fsync(file_fd)
            after = os.fstat(file_fd)
            named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                _file_identity(after) == _file_identity(named)
                and (int(after.st_dev), int(after.st_ino)) == identity
                and int(after.st_size) == len(payload),
                f"{label} identity changed during immutable commit",
            )
            os.fsync(parent_fd)
            self._verify_parent_posix(descriptors, names, label=label)
            self._require_epochs(
                descriptors[:-1],
                ancestor_epochs,
                label=label,
            )
            committed = True
            assert identity is not None
            return (
                {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                identity,
            )
        except FileExistsError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} immutable output already exists"
            ) from error
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} immutable commit failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass
            if identity is not None and not committed and descriptors:
                parent_fd = descriptors[-1]
                try:
                    named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                    if (
                        stat.S_ISREG(named.st_mode)
                        and (int(named.st_dev), int(named.st_ino)) == identity
                    ):
                        os.unlink(leaf, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                except OSError:
                    pass
            self._close_descriptors(descriptors)

    def _write_exclusive_windows(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        create_parents: bool,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        path = self._windows_path(
            relative, label=label, create_parents=create_parents
        )
        file_fd = -1
        identity: tuple[int, int] | None = None
        committed = False
        ancestor_epochs = self._windows_parent_epochs(
            path.parent.parent if path.parent != self._root else self._root,
            label=label,
        ) if path.parent != self._root else ()
        try:
            file_fd = os.open(
                path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | int(getattr(os, "O_BINARY", 0)),
                0o600,
            )
            created = os.fstat(file_fd)
            identity = int(created.st_dev), int(created.st_ino)
            offset = 0
            while offset < len(payload):
                written = os.write(file_fd, payload[offset:])
                _require(written > 0, f"{label} immutable write stalled")
                offset += written
            try:
                os.fchmod(file_fd, mode)
            except OSError:
                pass
            os.fsync(file_fd)
            after = os.fstat(file_fd)
            named = path.lstat()
            _require(
                _file_identity(after) == _file_identity(named)
                and not _is_link_or_reparse(path, named)
                and int(after.st_size) == len(payload),
                f"{label} identity changed during immutable commit",
            )
            self.verify()
            if path.parent != self._root:
                _require(
                    self._windows_parent_epochs(path.parent.parent, label=label)
                    == ancestor_epochs,
                    f"{label} parent directory mutated during custody",
                )
            committed = True
            assert identity is not None
            return (
                {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                identity,
            )
        except FileExistsError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} immutable output already exists"
            ) from error
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} immutable commit failed"
            ) from error
        finally:
            if file_fd >= 0:
                try:
                    os.close(file_fd)
                except OSError:
                    pass
            if identity is not None and not committed:
                try:
                    named = path.lstat()
                    if (
                        stat.S_ISREG(named.st_mode)
                        and not _is_link_or_reparse(path, named)
                        and (int(named.st_dev), int(named.st_ino)) == identity
                    ):
                        path.unlink()
                except OSError:
                    pass

    def ensure_directory(
        self,
        value: Path | str,
        *,
        label: str,
    ) -> Path:
        """Create and verify one project-relative physical directory chain."""

        path, _created = self.ensure_directory_owned(value, label=label)
        return path

    def ensure_directory_owned(
        self,
        value: Path | str,
        *,
        label: str,
    ) -> tuple[Path, tuple[tuple[str, tuple[int, ...]], ...]]:
        """Create a directory chain and return exact identities created here."""

        raw = Path(value)
        if raw.is_absolute():
            try:
                relative = Path(os.path.abspath(raw)).relative_to(self._root).as_posix()
            except ValueError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} escaped project_root"
                ) from error
        else:
            relative = raw.as_posix()
        relative = canonical_relative_path_v1(relative, label=label)
        sentinel = f"{relative}/.publication-directory-custody-v1"
        created: list[tuple[str, tuple[int, ...]]] = []
        if self._posix_custody is not None:
            descriptors: list[int] = []
            try:
                descriptors, names = self._open_parent_posix(
                    sentinel,
                    create=True,
                    label=label,
                    created_directories=created,
                )
                parent_epochs = self._epochs(descriptors)
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(
                    descriptors,
                    parent_epochs,
                    label=label,
                )
            finally:
                self._close_descriptors(descriptors)
        else:
            self._windows_path(
                sentinel,
                label=label,
                create_parents=True,
                created_directories=created,
            )
            self.verify()
        return (
            self._root.joinpath(*PurePosixPath(relative).parts),
            tuple(created),
        )

    def replace_atomic(
        self,
        value: Path | str,
        payload: bytes,
        *,
        label: str,
        mode: int = 0o600,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        """Atomically replace one mutable leaf through a held parent dirfd."""

        _require(type(payload) is bytes and bool(payload), f"{label} payload is empty")
        relative = self._relative(value, label=label)
        if self._posix_custody is not None:
            descriptor, identity = self._replace_atomic_posix(
                relative,
                payload,
                label=label,
                mode=mode,
                create_parents=create_parents,
            )
        else:
            descriptor, identity = self._replace_atomic_windows(
                relative,
                payload,
                label=label,
                mode=mode,
                create_parents=create_parents,
            )
        observed, cold_payload, cold_identity = self.read_descriptor_identity(
            relative,
            label=f"committed {label}",
            maximum=len(payload),
            capture=True,
        )
        _require(
            observed == descriptor
            and cold_payload == payload
            and cold_identity == identity,
            f"{label} changed across atomic replace/reload",
        )
        return descriptor

    def _replace_atomic_posix(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        create_parents: bool,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        descriptors: list[int] = []
        temporary_fd = -1
        temporary_leaf: str | None = None
        temporary_identity: tuple[int, int] | None = None
        replaced = False
        leaf = PurePosixPath(relative).name
        try:
            descriptors, names = self._open_parent_posix(
                relative, create=create_parents, label=label
            )
            ancestor_epochs = self._epochs(descriptors[:-1])
            parent_fd = descriptors[-1]
            for _attempt in range(32):
                token = hashlib.sha256(os.urandom(32)).hexdigest()[:24]
                candidate = f".{leaf}.replace-{token}.tmp"
                try:
                    temporary_fd = os.open(
                        candidate,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | int(getattr(os, "O_NOFOLLOW", 0))
                        | int(getattr(os, "O_CLOEXEC", 0)),
                        0o600,
                        dir_fd=parent_fd,
                    )
                except FileExistsError:
                    continue
                temporary_leaf = candidate
                break
            _require(
                temporary_fd >= 0 and temporary_leaf is not None,
                f"{label} could not reserve a private replacement leaf",
            )
            created = os.fstat(temporary_fd)
            _require(
                stat.S_ISREG(created.st_mode) and int(created.st_nlink) == 1,
                f"{label} replacement leaf is not one physical file",
            )
            temporary_identity = int(created.st_dev), int(created.st_ino)
            offset = 0
            while offset < len(payload):
                written = os.write(temporary_fd, payload[offset:])
                _require(written > 0, f"{label} replacement write stalled")
                offset += written
            os.fchmod(temporary_fd, mode)
            os.fsync(temporary_fd)
            staged = os.fstat(temporary_fd)
            named_stage = os.stat(
                temporary_leaf, dir_fd=parent_fd, follow_symlinks=False
            )
            _require(
                _file_identity(staged) == _file_identity(named_stage)
                and (int(staged.st_dev), int(staged.st_ino))
                == temporary_identity
                and int(staged.st_size) == len(payload),
                f"{label} replacement identity changed before commit",
            )
            self._verify_parent_posix(descriptors, names, label=label)
            parent_identity = _directory_identity(os.fstat(parent_fd))
            os.replace(
                temporary_leaf,
                leaf,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            replaced = True
            os.fsync(parent_fd)
            # WSL DrvFS does not expose a renamed destination through any
            # directory handle while the renamed source file descriptor is
            # still open.  The staged inode and bytes were verified and
            # fsynced above; retain their identity, close that descriptor only
            # after the atomic rename, then prove the destination name resolves
            # to the same inode before the cold reload in replace_atomic().
            os.close(temporary_fd)
            temporary_fd = -1
            committed: os.stat_result | None = None
            for attempt in range(_POST_RENAME_VISIBILITY_ATTEMPTS):
                try:
                    committed = os.stat(
                        leaf,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    break
                except FileNotFoundError:
                    if attempt + 1 == _POST_RENAME_VISIBILITY_ATTEMPTS:
                        raise
                    os.close(parent_fd)
                    descriptors[-1] = -1
                    if names:
                        ancestor_fd = descriptors[-2]
                        parent_name = names[-1]
                        named_parent = os.stat(
                            parent_name,
                            dir_fd=ancestor_fd,
                            follow_symlinks=False,
                        )
                        parent_fd = os.open(
                            parent_name,
                            os.O_RDONLY
                            | int(getattr(os, "O_DIRECTORY", 0))
                            | int(getattr(os, "O_NOFOLLOW", 0))
                            | int(getattr(os, "O_CLOEXEC", 0)),
                            dir_fd=ancestor_fd,
                        )
                        reopened_parent = os.fstat(parent_fd)
                        _require(
                            stat.S_ISDIR(named_parent.st_mode)
                            and not stat.S_ISLNK(named_parent.st_mode)
                            and _directory_identity(named_parent)
                            == _directory_identity(reopened_parent)
                            == parent_identity,
                            f"{label} replacement parent drifted while re-anchoring",
                        )
                    else:
                        custody = self._posix_custody
                        _require(
                            custody is not None,
                            f"{label} POSIX custody disappeared",
                        )
                        parent_fd = os.dup(custody.directory_fd)
                        reopened_parent = os.fstat(parent_fd)
                        _require(
                            stat.S_ISDIR(reopened_parent.st_mode)
                            and _directory_identity(reopened_parent)
                            == parent_identity,
                            f"{label} replacement root drifted while re-anchoring",
                        )
                    descriptors[-1] = parent_fd
                    self._verify_parent_posix(descriptors, names, label=label)
                    self._require_epochs(
                        descriptors[:-1],
                        ancestor_epochs,
                        label=label,
                    )
                    time.sleep(_POST_RENAME_VISIBILITY_DELAY_S)
            assert committed is not None
            _require(
                _file_rename_identity(staged) == _file_rename_identity(committed)
                and (int(committed.st_dev), int(committed.st_ino))
                == temporary_identity,
                f"{label} committed replacement inode drifted",
            )
            self._verify_parent_posix(descriptors, names, label=label)
            self._require_epochs(
                descriptors[:-1],
                ancestor_epochs,
                label=label,
            )
            assert temporary_identity is not None
            return (
                {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                temporary_identity,
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} atomic replacement failed"
            ) from error
        finally:
            if temporary_fd >= 0:
                try:
                    os.close(temporary_fd)
                except OSError:
                    pass
            if (
                not replaced
                and temporary_leaf is not None
                and temporary_identity is not None
                and descriptors
            ):
                parent_fd = descriptors[-1]
                try:
                    named = os.stat(
                        temporary_leaf,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    if (
                        stat.S_ISREG(named.st_mode)
                        and (int(named.st_dev), int(named.st_ino))
                        == temporary_identity
                    ):
                        os.unlink(temporary_leaf, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                except OSError:
                    pass
            self._close_descriptors(descriptors)

    def _replace_atomic_windows(
        self,
        relative: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
        create_parents: bool,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        path = self._windows_path(
            relative, label=label, create_parents=create_parents
        )
        temporary = path.parent / (
            f".{path.name}.replace-"
            f"{hashlib.sha256(os.urandom(32)).hexdigest()[:24]}.tmp"
        )
        temporary_fd = -1
        replaced = False
        temporary_identity: tuple[int, int] | None = None
        ancestor_epochs = self._windows_parent_epochs(
            path.parent.parent, label=label
        ) if path.parent != self._root else ()
        try:
            temporary_fd = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | int(getattr(os, "O_BINARY", 0)),
                0o600,
            )
            offset = 0
            while offset < len(payload):
                written = os.write(temporary_fd, payload[offset:])
                _require(written > 0, f"{label} replacement write stalled")
                offset += written
            try:
                os.fchmod(temporary_fd, mode)
            except OSError:
                pass
            os.fsync(temporary_fd)
            staged = os.fstat(temporary_fd)
            temporary_identity = int(staged.st_dev), int(staged.st_ino)
            os.close(temporary_fd)
            temporary_fd = -1
            self.verify()
            os.replace(temporary, path)
            replaced = True
            committed = path.lstat()
            _require(
                _file_rename_identity(staged) == _file_rename_identity(committed)
                and not _is_link_or_reparse(path, committed),
                f"{label} committed replacement inode drifted",
            )
            self.verify()
            if path.parent != self._root:
                _require(
                    self._windows_parent_epochs(path.parent.parent, label=label)
                    == ancestor_epochs,
                    f"{label} parent directory mutated during custody",
                )
            assert temporary_identity is not None
            return (
                {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                temporary_identity,
            )
        except PublicationPhysicalIoV1Error:
            raise
        except OSError as error:
            raise PublicationPhysicalIoV1Error(
                f"{label} atomic replacement failed"
            ) from error
        finally:
            if temporary_fd >= 0:
                try:
                    os.close(temporary_fd)
                except OSError:
                    pass
            if not replaced:
                try:
                    named = temporary.lstat()
                    if (
                        temporary_identity is not None
                        and stat.S_ISREG(named.st_mode)
                        and not _is_link_or_reparse(temporary, named)
                        and (int(named.st_dev), int(named.st_ino))
                        == temporary_identity
                    ):
                        temporary.unlink()
                except (FileNotFoundError, OSError):
                    pass

    def unlink_owned_identity(
        self,
        value: Path | str,
        expected_identity: tuple[int, int],
        *,
        label: str,
    ) -> None:
        """Remove one caller-owned leaf without following a replaced parent."""

        _require(
            type(expected_identity) is tuple
            and len(expected_identity) == 2
            and all(type(item) is int and item >= 0 for item in expected_identity),
            f"{label} owned identity is invalid",
        )
        relative = self._relative(value, label=label)
        leaf = PurePosixPath(relative).name
        if self._posix_custody is not None:
            descriptors: list[int] = []
            try:
                descriptors, names = self._open_parent_posix(
                    relative, create=False, label=label
                )
                ancestor_epochs = self._epochs(descriptors[:-1])
                parent_fd = descriptors[-1]
                named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                _require(
                    stat.S_ISREG(named.st_mode)
                    and (int(named.st_dev), int(named.st_ino))
                    == expected_identity,
                    f"{label} no longer names the owned file",
                )
                os.unlink(leaf, dir_fd=parent_fd)
                os.fsync(parent_fd)
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(
                    descriptors[:-1],
                    ancestor_epochs,
                    label=label,
                )
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} owned removal failed"
                ) from error
            finally:
                self._close_descriptors(descriptors)
            return
        path = self._windows_path(
            relative, label=label, create_parents=False
        )
        info = path.lstat()
        _require(
            stat.S_ISREG(info.st_mode)
            and not _is_link_or_reparse(path, info)
            and (int(info.st_dev), int(info.st_ino)) == expected_identity,
            f"{label} no longer names the owned file",
        )
        path.unlink()
        self.verify()

    def rmdir_owned_identity(
        self,
        value: Path | str,
        expected_identity: tuple[int, ...],
        *,
        label: str,
    ) -> None:
        """Remove one empty caller-created directory by its exact identity."""

        _require(
            type(expected_identity) is tuple
            and len(expected_identity) == len(_directory_identity(self._root.lstat()))
            and all(type(item) is int and item >= 0 for item in expected_identity),
            f"{label} owned directory identity is invalid",
        )
        relative = self._relative(value, label=label)
        leaf = PurePosixPath(relative).name
        if self._posix_custody is not None:
            descriptors: list[int] = []
            directory_fd = -1
            try:
                descriptors, names = self._open_parent_posix(
                    relative, create=False, label=label
                )
                ancestor_epochs = self._epochs(descriptors[:-1])
                parent_fd = descriptors[-1]
                named = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                _require(
                    stat.S_ISDIR(named.st_mode)
                    and not stat.S_ISLNK(named.st_mode)
                    and _directory_identity(named) == expected_identity,
                    f"{label} no longer names the owned directory",
                )
                directory_fd = os.open(
                    leaf,
                    os.O_RDONLY
                    | int(getattr(os, "O_DIRECTORY", 0))
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=parent_fd,
                )
                opened = os.fstat(directory_fd)
                _require(
                    stat.S_ISDIR(opened.st_mode)
                    and _directory_identity(opened) == expected_identity,
                    f"{label} owned directory identity changed while opening",
                )
                _require(
                    os.listdir(directory_fd) == [],
                    f"{label} owned directory is not empty",
                )
                os.close(directory_fd)
                directory_fd = -1
                os.rmdir(leaf, dir_fd=parent_fd)
                os.fsync(parent_fd)
                self._verify_parent_posix(descriptors, names, label=label)
                self._require_epochs(
                    descriptors[:-1],
                    ancestor_epochs,
                    label=label,
                )
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} owned directory removal failed"
                ) from error
            finally:
                if directory_fd >= 0:
                    try:
                        os.close(directory_fd)
                    except OSError:
                        pass
                self._close_descriptors(descriptors)
        else:
            path = self._windows_path(
                relative, label=label, create_parents=False
            )
            info = path.lstat()
            _require(
                stat.S_ISDIR(info.st_mode)
                and not _is_link_or_reparse(path, info)
                and _directory_identity(info) == expected_identity,
                f"{label} no longer names the owned directory",
            )
            try:
                with os.scandir(path) as entries:
                    empty = next(entries, None) is None
                _require(
                    empty,
                    f"{label} owned directory is not empty",
                )
                path.rmdir()
                try:
                    parent_fd = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(parent_fd)
                    finally:
                        os.close(parent_fd)
                except OSError:
                    pass
                self.verify()
            except PublicationPhysicalIoV1Error:
                raise
            except OSError as error:
                raise PublicationPhysicalIoV1Error(
                    f"{label} owned directory removal failed"
                ) from error
        for pinned in tuple(self._directory_pins):
            if pinned == relative or pinned.startswith(relative + "/"):
                del self._directory_pins[pinned]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._posix_custody is not None:
            self._posix_custody.close()

    def __enter__(self) -> "PhysicalRootCustodyV1":
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = [
    "PhysicalRootCustodyV1",
    "PublicationPhysicalIoV1Error",
    "canonical_relative_path_v1",
]
