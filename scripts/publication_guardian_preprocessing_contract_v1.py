#!/usr/bin/env python3
"""Materialize one receipt-bound preprocessing contract before guardian startup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


sys.dont_write_bytecode = True


SCHEMA_VERSION = 1
CONTRACT_FILENAME = "checkpoint_analytics_preprocessing_contract.v1.json"
RECEIPT_FILENAME = "checkpoint_analytics_preprocessing_contract.v1.receipt.json"
RECEIPT_KIND = "vast_guardian_preprocessing_contract_materialization_v1"
AUTHORITY_KIND = "vast_guardian_preprocessing_contract_authority_v1"
SCOPE = "qualification_guardian_preprocessing_only"
FROZEN_PREPROCESSING_CONTRACT_SHA256 = (
    "0307abfe6c5f652cc06f3f3df8ecf5050e5ed29b9ed5f40cb6fe728f47627090"
)
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
REFRESH_BLOCKERS = (
    "analytics_worker:cpu_identity_changed_requires_parity_refresh",
    "analytics_worker:gpu_identity_changed_requires_parity_refresh",
)
# DrvFS without the metadata mount option projects chmod(0444) as 0555.  Both
# representations deny every write bit; descriptor, payload, and inode identity
# remain independently verified before either representation is accepted.
_IMMUTABLE_OUTPUT_MODES = frozenset({0o444, 0o555})
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_V4_TRANSACTION_FIELDS = _DESCRIPTOR_FIELDS | {
    "transaction_sha256",
    "files_sha256",
    "output_segments_sha256",
    "execution_bundle_count",
    "execution_bundles_sha256",
}
_TRANSACTION_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "accepted",
    "publication_ready",
    "authorization_eligible",
    "systems",
    "cell_count",
    "hardware_resource_collector",
    "image_identity_patch",
    "image_identity_patch_sha256",
    "accepted_model_parity_manifest",
    "accepted_model_parity_assessment",
    "accepted_model_parity_receipt",
    "model_parity_acceptance_binding_sha256",
    "model_parity_acceptance_schema_version",
    "image_patch_resolution",
    "fragments",
    "candidate",
    "bootstrap",
    "blockers",
    "receipt_sha256",
}
_CANDIDATE_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "policy_contract_sha256",
    "qualification_index",
    "candidate_manifest",
    "blockers",
    "sha256",
}
_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "accepted",
    "publication_ready",
    "authorization_eligible",
    "preprocessing_contract",
    "preprocessing_contract_content_sha256",
    "accepted_model_parity_manifest",
    "accepted_model_parity_assessment",
    "accepted_model_parity_receipt",
    "model_parity_acceptance_binding",
    "model_parity_acceptance_binding_sha256",
    "model_parity_acceptance_files",
    "model_parity_acceptance_files_sha256",
    "model_parity_refresh_authority",
    "model_parity_refresh_authority_sha256",
    "model_parity_transaction_index",
    "qualification_transaction_receipt",
    "qualification_transaction_receipt_sha256",
    "qualification_index",
    "candidate_manifest",
    "candidate_receipt",
    "candidate_receipt_identity_sha256",
    "policy_contract_sha256",
    "blockers",
    "receipt_sha256",
}
_AUTHORITY_FIELDS = {
    "schema_version",
    "artifact_kind",
    "preprocessing_contract_content_sha256",
    "preprocessing_contract_file_sha256",
    "materialization_receipt_identity_sha256",
    "materialization_receipt_file_sha256",
    "qualification_transaction_receipt_sha256",
    "candidate_manifest_file_sha256",
    "candidate_receipt_identity_sha256",
    "model_parity_acceptance_binding_sha256",
    "policy_contract_sha256",
    "accepted_model_parity_manifest_file_sha256",
    "accepted_model_parity_assessment_file_sha256",
    "accepted_model_parity_receipt_file_sha256",
    "model_parity_acceptance_binding_file_sha256",
    "model_parity_acceptance_files_sha256",
    "model_parity_refresh_authority_sha256",
    "model_parity_transaction_index_file_sha256",
    "model_parity_transaction_sha256",
}


class GuardianPreprocessingContractV1Error(RuntimeError):
    """The pre-guardian contract materialization or its custody drifted."""


AcceptanceLoader = Callable[..., dict[str, Any]]


def _fail(message: str) -> None:
    raise GuardianPreprocessingContractV1Error(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise GuardianPreprocessingContractV1Error(
            "guardian preprocessing value is not canonical JSON"
        ) from error


def _semantic_sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _is_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    observed = info if info is not None else path.lstat()
    attributes = int(getattr(observed, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    junction = getattr(os.path, "isjunction", lambda _path: False)
    return stat.S_ISLNK(observed.st_mode) or bool(attributes & reparse) or junction(path)


def _physical_root(project_root: Path | str) -> Path:
    root = Path(os.path.abspath(os.fspath(project_root)))
    try:
        info = root.lstat()
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise GuardianPreprocessingContractV1Error(
            "project_root is unavailable"
        ) from error
    _require(
        stat.S_ISDIR(info.st_mode)
        and not _is_reparse(root, info)
        and resolved == root,
        "project_root must be one physical directory",
    )
    return root


def _under_root(root: Path, value: Path | str, *, label: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        text = raw.as_posix()
        pure = PurePosixPath(text)
        _require(
            bool(text)
            and pure.as_posix() == text
            and not pure.is_absolute()
            and all(part not in {"", ".", ".."} for part in pure.parts),
            f"{label} path is not canonical relative",
        )
        raw = root.joinpath(*pure.parts)
    path = Path(os.path.abspath(os.fspath(raw)))
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GuardianPreprocessingContractV1Error(
            f"{label} escaped project_root"
        ) from error
    return path


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_uid),
        int(info.st_gid),
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
        int(info.st_uid),
        int(info.st_gid),
    )


def _open_posix_directory_chain(
    directory: Path, *, label: str
) -> list[tuple[int, str | None]]:
    _require(
        os.name == "posix"
        and int(getattr(os, "O_NOFOLLOW", 0)) != 0
        and int(getattr(os, "O_DIRECTORY", 0)) != 0
        and os.open in os.supports_dir_fd,
        f"{label} requires POSIX dirfd/openat custody",
    )
    anchor = Path(directory.anchor)
    _require(anchor.is_absolute(), f"{label} directory anchor is invalid")
    flags = (
        os.O_RDONLY
        | int(os.O_NOFOLLOW)
        | int(os.O_DIRECTORY)
        | int(getattr(os, "O_CLOEXEC", 0))
    )
    chain: list[tuple[int, str | None]] = []
    try:
        descriptor = os.open(anchor, flags)
        root_info = os.fstat(descriptor)
        _require(stat.S_ISDIR(root_info.st_mode), f"{label} anchor is not a directory")
        chain.append((descriptor, None))
        for part in directory.relative_to(anchor).parts:
            parent_fd = chain[-1][0]
            descriptor = os.open(part, flags, dir_fd=parent_fd)
            opened = os.fstat(descriptor)
            named = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISDIR(opened.st_mode)
                and not stat.S_ISLNK(named.st_mode)
                and _directory_identity(opened) == _directory_identity(named),
                f"{label} directory component identity drifted",
            )
            chain.append((descriptor, part))
        return chain
    except GuardianPreprocessingContractV1Error:
        for descriptor, _part in reversed(chain):
            os.close(descriptor)
        raise
    except OSError as error:
        for descriptor, _part in reversed(chain):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise GuardianPreprocessingContractV1Error(
            f"cannot establish {label} dirfd custody"
        ) from error


def _verify_posix_directory_chain(
    chain: list[tuple[int, str | None]], *, label: str
) -> None:
    for index in range(1, len(chain)):
        descriptor, part = chain[index]
        parent_fd = chain[index - 1][0]
        _require(part is not None, f"{label} directory chain is invalid")
        try:
            opened = os.fstat(descriptor)
            named = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise GuardianPreprocessingContractV1Error(
                f"{label} directory chain changed"
            ) from error
        _require(
            stat.S_ISDIR(opened.st_mode)
            and not stat.S_ISLNK(named.st_mode)
            and _directory_identity(opened) == _directory_identity(named),
            f"{label} directory chain identity changed",
        )


def _canonical_child_name(value: object, *, label: str) -> str:
    _require(
        type(value) is str
        and value not in {"", ".", ".."}
        and PurePosixPath(value).parts == (value,)
        and PurePosixPath(value).as_posix() == value,
        f"{label} child name is not canonical",
    )
    return value


class DirectoryFdCustodyV1:
    """Own one POSIX directory namespace through a verified descriptor chain."""

    def __init__(
        self,
        path: Path,
        chain: list[tuple[int, str | None]],
        *,
        label: str,
    ) -> None:
        self._path = path
        self._chain = chain
        self._label = label
        self._closed = False

    @classmethod
    def open_existing(
        cls, directory: Path | str, *, label: str
    ) -> "DirectoryFdCustodyV1":
        path = Path(os.path.abspath(os.fspath(directory)))
        chain = _open_posix_directory_chain(path, label=label)
        try:
            _verify_posix_directory_chain(chain, label=label)
            return cls(path, chain, label=label)
        except BaseException:
            for descriptor, _part in reversed(chain):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise

    @property
    def path(self) -> Path:
        self._require_open()
        return self._path

    @property
    def directory_fd(self) -> int:
        self._require_open()
        return self._chain[-1][0]

    def _require_open(self) -> None:
        _require(not self._closed and bool(self._chain), f"{self._label} custody is closed")

    def verify(self) -> None:
        self._require_open()
        _verify_posix_directory_chain(self._chain, label=self._label)

    def _open_child_directory(self, name: str) -> int:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(os.O_NOFOLLOW)
            | int(os.O_DIRECTORY)
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=self.directory_fd,
        )
        try:
            opened = os.fstat(descriptor)
            named = os.stat(name, dir_fd=self.directory_fd, follow_symlinks=False)
            _require(
                stat.S_ISDIR(opened.st_mode)
                and not stat.S_ISLNK(named.st_mode)
                and _directory_identity(opened) == _directory_identity(named),
                f"{self._label} created directory identity drifted",
            )
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def mkdir_child_exclusive(
        self, child_name: str, *, mode: int = 0o700
    ) -> None:
        """Create and enter one child with mkdirat/openat custody."""

        name = _canonical_child_name(child_name, label=self._label)
        self.verify()
        parent_fd = self.directory_fd
        created_identity: tuple[int, ...] | None = None
        child_fd = -1
        entered_child = False
        try:
            os.mkdir(name, mode=mode, dir_fd=parent_fd)
            created = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            _require(
                stat.S_ISDIR(created.st_mode) and not stat.S_ISLNK(created.st_mode),
                f"{self._label} created child is not a physical directory",
            )
            created_identity = _directory_identity(created)
            child_fd = self._open_child_directory(name)
            opened = os.fstat(child_fd)
            _require(
                _directory_identity(opened) == created_identity,
                f"{self._label} created child identity changed",
            )
            os.fsync(parent_fd)
            self._chain.append((child_fd, name))
            child_fd = -1
            entered_child = True
            self._path /= name
            self.verify()
        except (GuardianPreprocessingContractV1Error, OSError) as error:
            if child_fd >= 0:
                try:
                    os.close(child_fd)
                except OSError:
                    pass
            if entered_child:
                held_child_fd, held_name = self._chain.pop()
                _require(
                    held_name == name,
                    f"{self._label} created child chain changed",
                )
                self._path = self._path.parent
                try:
                    os.close(held_child_fd)
                except OSError:
                    pass
            if created_identity is not None:
                try:
                    named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if (
                        stat.S_ISDIR(named.st_mode)
                        and _directory_identity(named) == created_identity
                    ):
                        os.rmdir(name, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                except OSError:
                    pass
            if isinstance(error, GuardianPreprocessingContractV1Error):
                raise
            raise GuardianPreprocessingContractV1Error(
                f"cannot create {self._label} child with dirfd custody"
            ) from error

    def _assert_owned(self, name: str, identity: tuple[int, int]) -> os.stat_result:
        named = os.stat(name, dir_fd=self.directory_fd, follow_symlinks=False)
        _require(
            stat.S_ISREG(named.st_mode)
            and not stat.S_ISLNK(named.st_mode)
            and int(named.st_nlink) == 1
            and (int(named.st_dev), int(named.st_ino)) == identity,
            f"owned rollback target changed: {name}",
        )
        return named

    def assert_owned(self, child_name: str, identity: tuple[int, int]) -> None:
        name = _canonical_child_name(child_name, label=self._label)
        self.verify()
        self._assert_owned(name, identity)
        self.verify()

    def _unlink_owned_at(self, name: str, identity: tuple[int, int]) -> None:
        try:
            self._assert_owned(name, identity)
        except FileNotFoundError:
            return
        os.unlink(name, dir_fd=self.directory_fd)
        os.fsync(self.directory_fd)

    def write_exclusive(
        self, child_name: str, payload: bytes, *, mode: int = 0o400
    ) -> tuple[int, int]:
        """Create one file with openat and clean only the inode created here."""

        name = _canonical_child_name(child_name, label=self._label)
        _require(type(payload) is bytes, f"{self._label} payload must be bytes")
        self.verify()
        descriptor = -1
        identity: tuple[int, int] | None = None
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | int(os.O_NOFOLLOW)
                | int(getattr(os, "O_CLOEXEC", 0)),
                0o600,
                dir_fd=self.directory_fd,
            )
            created = os.fstat(descriptor)
            _require(
                stat.S_ISREG(created.st_mode) and int(created.st_nlink) == 1,
                f"{self._label} created file is not one physical file",
            )
            identity = int(created.st_dev), int(created.st_ino)
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                _require(written > 0, f"write stalled for {name}")
                offset += written
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
            after = os.fstat(descriptor)
            named = os.stat(name, dir_fd=self.directory_fd, follow_symlinks=False)
            _require(
                _file_identity(after) == _file_identity(named)
                and (int(after.st_dev), int(after.st_ino)) == identity,
                f"{self._label} created file identity changed",
            )
            os.fsync(self.directory_fd)
            self.verify()
            return identity
        except (GuardianPreprocessingContractV1Error, OSError) as error:
            if identity is not None:
                try:
                    self._unlink_owned_at(name, identity)
                except (GuardianPreprocessingContractV1Error, OSError) as cleanup_error:
                    raise GuardianPreprocessingContractV1Error(
                        f"{self._label} exclusive write failed and owned cleanup failed"
                    ) from cleanup_error
            if isinstance(error, GuardianPreprocessingContractV1Error):
                raise
            raise GuardianPreprocessingContractV1Error(
                f"exclusive dirfd write failed for {name}: {error}"
            ) from error
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def unlink_owned(self, child_name: str, identity: tuple[int, int]) -> None:
        """Unlink an owned inode through the held directory, even after rename."""

        name = _canonical_child_name(child_name, label=self._label)
        chain_error: GuardianPreprocessingContractV1Error | None = None
        try:
            self.verify()
        except GuardianPreprocessingContractV1Error as error:
            chain_error = error
        try:
            self._unlink_owned_at(name, identity)
        except OSError as error:
            raise GuardianPreprocessingContractV1Error(
                f"cannot unlink owned {self._label} file"
            ) from error
        if chain_error is None:
            self.verify()
        else:
            raise chain_error

    def fsync(self) -> None:
        self.verify()
        os.fsync(self.directory_fd)
        self.verify()

    def fsync_parent(self) -> None:
        self._require_open()
        _require(len(self._chain) > 1, f"{self._label} has no parent custody")
        self.verify()
        os.fsync(self._chain[-2][0])
        self.verify()

    def chmod(self, mode: int) -> None:
        self.verify()
        os.fchmod(self.directory_fd, mode)
        os.fsync(self.directory_fd)
        self.verify()

    def remove_empty_leaf(self) -> None:
        """Remove the held leaf only when its parent still names that inode."""

        self._require_open()
        _require(len(self._chain) > 1, f"{self._label} anchor cannot be removed")
        chain_error: GuardianPreprocessingContractV1Error | None = None
        try:
            self.verify()
        except GuardianPreprocessingContractV1Error as error:
            chain_error = error
        leaf_fd, name = self._chain[-1]
        parent_fd = self._chain[-2][0]
        _require(name is not None, f"{self._label} leaf name is invalid")
        opened = os.fstat(leaf_fd)
        try:
            named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise GuardianPreprocessingContractV1Error(
                f"{self._label} parent no longer owns the cleanup leaf"
            ) from error
        _require(
            stat.S_ISDIR(opened.st_mode)
            and _directory_identity(opened) == _directory_identity(named),
            f"{self._label} cleanup leaf identity changed",
        )
        _require(not os.listdir(leaf_fd), f"{self._label} cleanup leaf is not empty")
        os.rmdir(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        os.close(leaf_fd)
        self._chain.pop()
        self._path = self._path.parent
        if chain_error is None:
            self.verify()
        else:
            raise chain_error

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor, _part in reversed(self._chain):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self._chain.clear()

    def __enter__(self) -> "DirectoryFdCustodyV1":
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _read_file_fd_custody(path: Path, *, label: str) -> bytes:
    if os.name == "posix":
        chain = _open_posix_directory_chain(path.parent, label=label)
        descriptor = -1
        try:
            parent_fd = chain[-1][0]
            descriptor = os.open(
                path.name,
                os.O_RDONLY
                | int(os.O_NOFOLLOW)
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=parent_fd,
            )
            before = os.fstat(descriptor)
            named_before = os.stat(
                path.name, dir_fd=parent_fd, follow_symlinks=False
            )
            _require(
                stat.S_ISREG(before.st_mode)
                and not stat.S_ISLNK(named_before.st_mode)
                and int(before.st_nlink) == 1
                and _file_identity(before) == _file_identity(named_before),
                f"{label} must be one canonical physical file",
            )
            payload = bytearray()
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                payload.extend(chunk)
            after = os.fstat(descriptor)
            named_after = os.stat(
                path.name, dir_fd=parent_fd, follow_symlinks=False
            )
            _verify_posix_directory_chain(chain, label=label)
            _require(
                _file_identity(before)
                == _file_identity(after)
                == _file_identity(named_after)
                and len(payload) == int(before.st_size),
                f"{label} changed or was replaced while being read",
            )
            return bytes(payload)
        except GuardianPreprocessingContractV1Error:
            raise
        except OSError as error:
            raise GuardianPreprocessingContractV1Error(
                f"cannot read {label} with fd custody"
            ) from error
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            for directory_fd, _part in reversed(chain):
                try:
                    os.close(directory_fd)
                except OSError:
                    pass

    descriptor = -1
    try:
        named_before = path.lstat()
        _require(
            stat.S_ISREG(named_before.st_mode)
            and not _is_reparse(path, named_before)
            and int(named_before.st_nlink) == 1
            and path.resolve(strict=True) == path,
            f"{label} must be one canonical physical file",
        )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_CLOEXEC", 0))
            | int(getattr(os, "O_BINARY", 0)),
        )
        before = os.fstat(descriptor)
        _require(
            _file_identity(before) == _file_identity(named_before),
            f"{label} identity changed before read",
        )
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        named_after = path.lstat()
        _require(
            not _is_reparse(path, named_after)
            and _file_identity(before)
            == _file_identity(after)
            == _file_identity(named_after)
            and len(payload) == int(before.st_size),
            f"{label} changed or was replaced while being read",
        )
        return bytes(payload)
    except GuardianPreprocessingContractV1Error:
        raise
    except OSError as error:
        raise GuardianPreprocessingContractV1Error(
            f"cannot read {label} with fd custody"
        ) from error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _physical_file(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    _read_file_fd_custody(path, label=label)
    return path


def _physical_directory(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    if os.name == "posix":
        chain = _open_posix_directory_chain(path, label=label)
        try:
            _verify_posix_directory_chain(chain, label=label)
        finally:
            for descriptor, _part in reversed(chain):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        return path
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise GuardianPreprocessingContractV1Error(f"{label} is missing") from error
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_reparse(path, info) and resolved == path,
        f"{label} must be one canonical physical directory",
    )
    return path


def _stable_bytes(root: Path, value: Path | str, *, label: str) -> bytes:
    path = _under_root(root, value, label=label)
    return _read_file_fd_custody(path, label=label)


def read_file_bytes_fd_custody_v1(
    path: Path | str, *, label: str
) -> bytes:
    """Read one absolute physical file through stable descriptor custody."""

    target = Path(os.path.abspath(os.fspath(path)))
    return _read_file_fd_custody(target, label=label)


def _descriptor(root: Path, value: Path | str, *, label: str) -> dict[str, Any]:
    path = _under_root(root, value, label=label)
    payload = _stable_bytes(root, path, label=label)
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _descriptor_shape(value: object, *, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS, f"{label} fields drifted")
    descriptor = dict(value)
    raw = descriptor.get("path")
    _require(
        type(raw) is str
        and bool(raw)
        and PurePosixPath(raw).as_posix() == raw
        and not PurePosixPath(raw).is_absolute()
        and all(part not in {"", ".", ".."} for part in PurePosixPath(raw).parts)
        and type(descriptor.get("size_bytes")) is int
        and descriptor["size_bytes"] > 0
        and _valid_sha(descriptor.get("sha256")),
        f"{label} descriptor is invalid",
    )
    return descriptor


def _verified_descriptor(root: Path, value: object, *, label: str) -> tuple[dict[str, Any], Path]:
    expected = _descriptor_shape(value, label=label)
    path = _physical_file(root, expected["path"], label=label)
    observed = _descriptor(root, path, label=label)
    _require(observed == expected, f"{label} descriptor drifted")
    return expected, path


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "canonical JSON contains a duplicate key")
        result[key] = value
    return result


def _read_canonical_json(
    root: Path, path: Path | str, *, label: str
) -> dict[str, Any]:
    payload = _stable_bytes(root, path, label=label)
    try:
        value = json.loads(
            payload.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                GuardianPreprocessingContractV1Error(
                    f"{label} contains invalid JSON constant {item}"
                )
            ),
        )
    except GuardianPreprocessingContractV1Error:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise GuardianPreprocessingContractV1Error(f"{label} is invalid JSON") from error
    _require(
        type(value) is dict and payload == _canonical(value) + b"\n",
        f"{label} is not canonical JSON",
    )
    return value


def _read_manifest(
    root: Path, path: Path | str, *, label: str
) -> dict[str, Any]:
    payload = _stable_bytes(root, path, label=label)
    try:
        text = payload.decode("utf-8")
        try:
            value = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=lambda item: (_ for _ in ()).throw(
                    GuardianPreprocessingContractV1Error(
                        f"{label} contains invalid JSON constant {item}"
                    )
                ),
            )
        except json.JSONDecodeError:
            import yaml

            value = yaml.safe_load(text)
    except (UnicodeError, OSError, ValueError, ModuleNotFoundError) as error:
        raise GuardianPreprocessingContractV1Error(f"{label} is invalid YAML/JSON") from error
    _require(type(value) is dict, f"{label} must be a mapping")
    return value


def _self_hash(value: Mapping[str, Any], field: str, *, label: str) -> str:
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    _require(
        _valid_sha(claimed) and claimed == _semantic_sha(unsigned),
        f"{label} self identity drifted",
    )
    return str(claimed)


def _validate_candidate(
    root: Path,
    transaction: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = transaction.get("candidate")
    _require(
        type(candidate) is dict and set(candidate) == {"index", "manifest", "receipt"},
        "qualification transaction candidate fields drifted",
    )
    index_descriptor, _index_path = _verified_descriptor(
        root, candidate["index"], label="qualification candidate index"
    )
    manifest_descriptor, manifest_path = _verified_descriptor(
        root, candidate["manifest"], label="qualification candidate manifest"
    )
    receipt_descriptor, receipt_path = _verified_descriptor(
        root, candidate["receipt"], label="qualification candidate receipt"
    )
    manifest = _read_canonical_json(
        root, manifest_path, label="qualification candidate manifest"
    )
    _require(
        set(manifest)
        == {
            "schema_version",
            "artifact_kind",
            "policy_scope",
            "policy_contract_sha256",
            "systems",
        }
        and manifest.get("schema_version") == 1
        and manifest.get("artifact_kind") == "vast_publication_policy_capability_manifest"
        and manifest.get("policy_scope") == "analytics_only"
        and _valid_sha(manifest.get("policy_contract_sha256"))
        and type(manifest.get("systems")) is dict
        and set(manifest["systems"]) == set(SYSTEMS),
        "qualification candidate manifest identity drifted",
    )
    receipt = _read_canonical_json(
        root, receipt_path, label="qualification candidate receipt"
    )
    _require(
        set(receipt) == _CANDIDATE_RECEIPT_FIELDS
        and receipt.get("schema_version") == 1
        and receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_candidate_receipt"
        and receipt.get("status") == "qualification_candidate_not_accepted"
        and receipt.get("accepted") is False
        and receipt.get("publication_ready") is False
        and receipt.get("scope") == "forced_resource_qualification_pilots_only"
        and receipt.get("policy_contract_sha256") == manifest["policy_contract_sha256"]
        and receipt.get("qualification_index") == index_descriptor
        and receipt.get("candidate_manifest") == manifest_descriptor
        and type(receipt.get("blockers")) is list
        and "candidate_is_not_a_full_publication_authority" in receipt["blockers"],
        "qualification candidate receipt binding drifted",
    )
    receipt_identity = _self_hash(
        receipt, "sha256", label="qualification candidate receipt"
    )
    return {
        "index": index_descriptor,
        "manifest": manifest_descriptor,
        "receipt": receipt_descriptor,
        "candidate_receipt_identity_sha256": receipt_identity,
        "policy_contract_sha256": manifest["policy_contract_sha256"],
    }


def _validate_transaction(
    root: Path, transaction_path: Path | str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    transaction_descriptor = _descriptor(
        root, transaction_path, label="qualification transaction receipt"
    )
    path = _physical_file(
        root, transaction_path, label="qualification transaction receipt"
    )
    transaction = _read_canonical_json(
        root, path, label="qualification transaction receipt"
    )
    resolution = transaction.get("image_patch_resolution")
    _require(
        set(transaction) == _TRANSACTION_FIELDS
        and transaction.get("schema_version") == 2
        and transaction.get("artifact_kind")
        == "vast_publication_policy_qualification_input_transaction_v2"
        and transaction.get("status") == "qualification_inputs_materialized_nonaccepted"
        and transaction.get("scope") == "forced_resource_qualification_pilots_only"
        and transaction.get("accepted") is False
        and transaction.get("publication_ready") is False
        and transaction.get("authorization_eligible") is False
        and transaction.get("systems") == list(SYSTEMS)
        and transaction.get("cell_count") == 32
        and transaction.get("model_parity_acceptance_schema_version") == 4
        and _valid_sha(transaction.get("model_parity_acceptance_binding_sha256"))
        and type(resolution) is dict
        and set(resolution)
        == {"candidate_binding_eligible", "resolved_blockers", "resolution"}
        and resolution.get("candidate_binding_eligible") is False
        and resolution.get("resolved_blockers") == list(REFRESH_BLOCKERS)
        and resolution.get("resolution") == "physical_patch_bound_v4_parity_refresh"
        and type(transaction.get("blockers")) is list
        and "transaction_is_not_full_publication_authority" in transaction["blockers"],
        "qualification transaction receipt identity drifted",
    )
    transaction_identity = _self_hash(
        transaction, "receipt_sha256", label="qualification transaction receipt"
    )
    for field, label in (
        ("hardware_resource_collector", "hardware resource collector"),
        ("accepted_model_parity_manifest", "accepted model-parity manifest"),
        ("accepted_model_parity_assessment", "accepted model-parity assessment"),
        ("accepted_model_parity_receipt", "accepted model-parity receipt"),
    ):
        descriptor, _path = _verified_descriptor(
            root, transaction.get(field), label=label
        )
        if field == "hardware_resource_collector":
            _require(
                descriptor["path"] == "scripts/collect_metrics.py",
                "qualification hardware resource collector path drifted",
            )
    candidate = _validate_candidate(root, transaction)
    return (
        dict(transaction),
        candidate,
        {
            **transaction_descriptor,
            "receipt_sha256": transaction_identity,
        },
    )


def _default_acceptance_loader(
    *, project_root: Path, receipt_path: Path
) -> dict[str, Any]:
    from checkpoint_model_parity_acceptance_v4 import (
        load_verified_model_parity_acceptance_v4,
    )

    return load_verified_model_parity_acceptance_v4(
        project_root=project_root,
        receipt_path=receipt_path,
    )


def _v4_transaction_binding(value: object) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _V4_TRANSACTION_FIELDS,
        "model-parity v4 transaction binding fields drifted",
    )
    transaction = dict(value)
    descriptor = _descriptor_shape(
        {key: transaction[key] for key in _DESCRIPTOR_FIELDS},
        label="model-parity v4 transaction index",
    )
    _require(
        descriptor["path"].endswith("/transaction_index.json")
        and transaction.get("execution_bundle_count") == 480
        and all(
            _valid_sha(transaction.get(field))
            for field in (
                "transaction_sha256",
                "files_sha256",
                "output_segments_sha256",
                "execution_bundles_sha256",
            )
        ),
        "model-parity v4 transaction binding identity drifted",
    )
    return transaction


def _v4_files(value: object, claimed_sha256: object) -> list[dict[str, Any]]:
    _require(
        type(value) is list and len(value) == 50,
        "model-parity v4 acceptance file coverage is not exact 50",
    )
    files = [
        _descriptor_shape(item, label=f"model-parity v4 acceptance file {index}")
        for index, item in enumerate(value)
    ]
    _require(
        len({item["path"] for item in files}) == 50
        and _valid_sha(claimed_sha256)
        and claimed_sha256 == _semantic_sha(files),
        "model-parity v4 acceptance file identity drifted",
    )
    return files


def _load_verified_acceptance_material(
    *,
    root: Path,
    transaction: Mapping[str, Any],
    acceptance_loader: AcceptanceLoader,
    expected_preprocessing_contract_sha256: str,
) -> dict[str, Any]:
    manifest_descriptor, manifest_path = _verified_descriptor(
        root,
        transaction.get("accepted_model_parity_manifest"),
        label="accepted model-parity manifest",
    )
    assessment_descriptor, _assessment_path = _verified_descriptor(
        root,
        transaction.get("accepted_model_parity_assessment"),
        label="accepted model-parity assessment",
    )
    acceptance_receipt_descriptor, acceptance_receipt_path = _verified_descriptor(
        root,
        transaction.get("accepted_model_parity_receipt"),
        label="accepted model-parity receipt",
    )
    try:
        binding = acceptance_loader(
            project_root=root,
            receipt_path=acceptance_receipt_path,
        )
    except GuardianPreprocessingContractV1Error:
        raise
    except Exception as error:
        raise GuardianPreprocessingContractV1Error(
            f"model-parity v4 acceptance chain rejected input: {error}"
        ) from error
    files = _v4_files(
        binding.get("files") if type(binding) is dict else None,
        binding.get("files_sha256") if type(binding) is dict else None,
    )
    transaction_index = _v4_transaction_binding(
        binding.get("transaction_index") if type(binding) is dict else None
    )
    refresh_authority = (
        binding.get("refresh_authority") if type(binding) is dict else None
    )
    _require(
        type(binding) is dict
        and binding.get("accepted_assessment") == assessment_descriptor,
        "model-parity v4 assessment cross-link drifted",
    )
    _require(
        type(binding) is dict
        and binding.get("schema_version") == 4
        and binding.get("artifact_kind")
        == "vast_verified_model_parity_acceptance_binding_v4"
        and _valid_sha(binding.get("binding_sha256"))
        and binding.get("binding_sha256")
        == transaction.get("model_parity_acceptance_binding_sha256")
        and binding.get("accepted_manifest") == manifest_descriptor
        and binding.get("receipt") == acceptance_receipt_descriptor,
        "model-parity v4 acceptance binding cross-link drifted",
    )
    _require(
        type(refresh_authority) is dict,
        "model-parity v4 refresh authority drifted",
    )
    acceptance_receipt = _read_canonical_json(
        root,
        acceptance_receipt_path,
        label="accepted model-parity receipt",
    )
    binding_relative = acceptance_receipt.get("acceptance_binding_path")
    _require(
        type(binding_relative) is str,
        "accepted model-parity receipt lacks its acceptance binding path",
    )
    binding_path = _physical_file(
        root, binding_relative, label="accepted model-parity binding"
    )
    binding_descriptor = _descriptor(
        root, binding_path, label="accepted model-parity binding"
    )
    binding_document = _read_canonical_json(
        root, binding_path, label="accepted model-parity binding"
    )
    _require(
        binding_document == binding
        and _self_hash(
            binding_document,
            "binding_sha256",
            label="accepted model-parity binding",
        )
        == transaction["model_parity_acceptance_binding_sha256"],
        "accepted model-parity binding file drifted",
    )
    manifest = _read_manifest(
        root, manifest_path, label="accepted model-parity manifest"
    )
    contract = manifest.get("preprocessing_contract")
    _require(
        manifest.get("schema_version") == 4
        and manifest.get("artifact_kind")
        == "checkpoint_analytics_model_parity_manifest_v4"
        and type(contract) is dict
        and _valid_sha(expected_preprocessing_contract_sha256)
        and _semantic_sha(contract) == expected_preprocessing_contract_sha256,
        "accepted preprocessing contract identity drifted",
    )
    return {
        "contract": json.loads(_canonical(contract).decode("ascii")),
        "manifest": manifest_descriptor,
        "assessment": assessment_descriptor,
        "acceptance_receipt": acceptance_receipt_descriptor,
        "acceptance_binding": binding_descriptor,
        "acceptance_binding_sha256": binding["binding_sha256"],
        "files": files,
        "files_sha256": binding["files_sha256"],
        "refresh_authority": json.loads(
            _canonical(refresh_authority).decode("ascii")
        ),
        "refresh_authority_sha256": _semantic_sha(refresh_authority),
        "transaction_index": transaction_index,
    }


_MATERIALIZATION_INTENT_ROOT = ".publication-guardian-materialization-intents-v1"


def _planned_descriptor(root: Path, path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _commit_or_adopt_atomic_leaf(
    custody: PhysicalRootCustodyV1,
    path: Path,
    payload: bytes,
    *,
    label: str,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    expected = _planned_descriptor(custody.root, path, payload)

    def physical_step(step: str) -> None:
        if after_physical_commit_step is not None:
            after_physical_commit_step(step, path)

    try:
        observed, identity, disposition = custody.commit_or_adopt_exact_identity(
            expected["path"],
            payload,
            label=label,
            mode=0o444,
            create_parents=True,
            after_publish_step=physical_step,
        )
        cold, cold_payload, cold_identity = custody.read_descriptor_identity(
            expected["path"],
            label=f"committed {label}",
            maximum=len(payload),
            capture=True,
        )
        mode, stat_identity = custody.stat_regular_identity(
            expected["path"], label=f"committed {label} mode"
        )
    except PublicationPhysicalIoV1Error as error:
        raise GuardianPreprocessingContractV1Error(
            f"atomic materialization commit/adoption failed for {path.name}: {error}"
        ) from error
    _require(
        disposition in {"published", "adopted"}
        and observed == expected
        and cold == expected
        and cold_payload == payload
        and cold_identity == identity == stat_identity
        and mode in _IMMUTABLE_OUTPUT_MODES,
        f"atomic materialization identity drifted for {path.name}",
    )
    return expected


def _commit_receipt_last_bundle_v1(
    *,
    root: Path,
    output: Path,
    intent_kind: str,
    ordered_payloads: Sequence[tuple[str, bytes]],
    label: str,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resume only a bundle with a precommitted exact parent-owned intent."""

    _require(
        len(ordered_payloads) == 2
        and ordered_payloads[0][0] != ordered_payloads[1][0]
        and all(type(payload) is bytes and bool(payload) for _name, payload in ordered_payloads),
        f"{label} ordered receipt-last payloads are invalid",
    )
    output_relative = output.relative_to(root).as_posix()
    planned = {
        name: _planned_descriptor(root, output / name, payload)
        for name, payload in ordered_payloads
    }
    intent_unsigned = {
        "schema_version": 1,
        "artifact_kind": intent_kind,
        "status": "receipt_last_materialization_intent",
        "output_relative_path": output_relative,
        "ordered_files": [planned[name] for name, _payload in ordered_payloads],
    }
    intent = {
        **intent_unsigned,
        "intent_sha256": _semantic_sha(intent_unsigned),
    }
    intent_payload = _canonical(intent) + b"\n"
    intent_key = hashlib.sha256(
        f"{intent_kind}\0{output_relative}".encode("utf-8")
    ).hexdigest()
    intent_path = root / _MATERIALIZATION_INTENT_ROOT / f"{intent_key}.json"
    output_preexisting = os.path.lexists(output)
    intent_preexisting = os.path.lexists(intent_path)
    _require(
        not output_preexisting or intent_preexisting,
        f"{label} output already exists without its parent-owned intent; overwrite refused",
    )
    allowed = {name for name, _payload in ordered_payloads}
    receipt_name = ordered_payloads[-1][0]
    try:
        with PhysicalRootCustodyV1.open(root, label=f"{label} project_root") as custody:
            _commit_or_adopt_atomic_leaf(
                custody,
                intent_path,
                intent_payload,
                label=f"{label} materialization intent",
                after_physical_commit_step=after_physical_commit_step,
            )
            destination = custody.ensure_directory(output, label=f"{label} output")
            names = set(
                custody.list_directory_names(
                    destination, label=f"{label} output namespace"
                )
            )
            _require(names <= allowed, f"{label} output namespace contains a foreign entry")
            _require(
                receipt_name not in names or names == allowed,
                f"{label} receipt exists without its complete predecessor set",
            )
            committed: dict[str, dict[str, Any]] = {}
            for name, payload in ordered_payloads:
                committed[name] = _commit_or_adopt_atomic_leaf(
                    custody,
                    destination / name,
                    payload,
                    label=f"{label} {name}",
                    after_physical_commit_step=after_physical_commit_step,
                )
            _require(
                set(
                    custody.list_directory_names(
                        destination, label=f"committed {label} output namespace"
                    )
                )
                == allowed,
                f"committed {label} output namespace drifted",
            )
            custody.verify()
        if os.name == "posix":
            with DirectoryFdCustodyV1.open_existing(output, label=label) as directory:
                directory.chmod(0o555)
                directory.fsync()
                directory.fsync_parent()
                directory.verify()
        with PhysicalRootCustodyV1.open(
            root, label=f"cold {label} project_root"
        ) as custody:
            _require(
                set(
                    custody.list_directory_names(
                        output, label=f"cold {label} output namespace"
                    )
                )
                == allowed,
                f"cold {label} output namespace drifted",
            )
            for name, payload in ordered_payloads:
                descriptor, cold_payload, _identity = custody.read_descriptor_identity(
                    output / name,
                    label=f"cold {label} {name}",
                    maximum=len(payload),
                    capture=True,
                )
                mode, _stat_identity = custody.stat_regular_identity(
                    output / name, label=f"cold {label} {name} mode"
                )
                _require(
                    descriptor == planned[name]
                    and cold_payload == payload
                    and mode in _IMMUTABLE_OUTPUT_MODES,
                    f"cold {label} output drifted: {name}",
                )
            custody.verify()
    except GuardianPreprocessingContractV1Error:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise GuardianPreprocessingContractV1Error(
            f"{label} receipt-last atomic materialization failed"
        ) from error
    return committed


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_CLOEXEC", 0))
            | int(getattr(os, "O_DIRECTORY", 0)),
        )
        os.fsync(descriptor)
    except OSError as error:
        raise GuardianPreprocessingContractV1Error(
            f"cannot fsync guardian preprocessing directory: {error}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _rollback_owned(path: Path, identity: tuple[int, int] | None) -> None:
    if identity is None or not os.path.lexists(path):
        return
    info = path.lstat()
    _require(
        not _is_reparse(path, info)
        and stat.S_ISREG(info.st_mode)
        and (int(info.st_dev), int(info.st_ino)) == identity,
        f"owned rollback target changed: {path.name}",
    )
    if os.name != "posix":
        os.chmod(path, 0o600)
    path.unlink()


def validate_guardian_preprocessing_authority_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        isinstance(value, Mapping) and set(value) == _AUTHORITY_FIELDS,
        "guardian preprocessing authority fields drifted",
    )
    authority = dict(value)
    _require(
        authority.get("schema_version") == 1
        and authority.get("artifact_kind") == AUTHORITY_KIND
        and all(
            _valid_sha(authority.get(field))
            for field in _AUTHORITY_FIELDS - {"schema_version", "artifact_kind"}
        ),
        "guardian preprocessing authority identities drifted",
    )
    return authority


def materialize_guardian_preprocessing_contract_v1(
    *,
    project_root: Path | str,
    qualification_transaction_receipt_path: Path | str,
    output_dir: Path | str,
    acceptance_loader: AcceptanceLoader = _default_acceptance_loader,
    expected_preprocessing_contract_sha256: str = (
        FROZEN_PREPROCESSING_CONTRACT_SHA256
    ),
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Path | str]:
    """Commit the canonical contract first and its provenance receipt last."""

    root = _physical_root(project_root)
    _require(callable(acceptance_loader), "model-parity acceptance loader is invalid")
    output = _under_root(root, output_dir, label="guardian preprocessing output_dir")
    transaction_path = _physical_file(
        root,
        qualification_transaction_receipt_path,
        label="qualification transaction receipt",
    )
    _require(
        output != root,
        "guardian preprocessing output must be a dedicated directory",
    )
    _require(
        transaction_path.parent != output
        and transaction_path.parent not in output.parents,
        "guardian preprocessing output must stay outside qualification transaction tree",
    )
    transaction, candidate, transaction_record = _validate_transaction(
        root, transaction_path
    )
    acceptance = _load_verified_acceptance_material(
        root=root,
        transaction=transaction,
        acceptance_loader=acceptance_loader,
        expected_preprocessing_contract_sha256=(
            expected_preprocessing_contract_sha256
        ),
    )
    contract_path = output / CONTRACT_FILENAME
    receipt_path = output / RECEIPT_FILENAME
    contract_payload = _canonical(acceptance["contract"]) + b"\n"
    contract_descriptor = _planned_descriptor(root, contract_path, contract_payload)
    receipt_unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RECEIPT_KIND,
        "status": "materialized_from_verified_v4_acceptance",
        "scope": SCOPE,
        "accepted": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "preprocessing_contract": contract_descriptor,
        "preprocessing_contract_content_sha256": expected_preprocessing_contract_sha256,
        "accepted_model_parity_manifest": acceptance["manifest"],
        "accepted_model_parity_assessment": acceptance["assessment"],
        "accepted_model_parity_receipt": acceptance["acceptance_receipt"],
        "model_parity_acceptance_binding": acceptance["acceptance_binding"],
        "model_parity_acceptance_binding_sha256": acceptance["acceptance_binding_sha256"],
        "model_parity_acceptance_files": acceptance["files"],
        "model_parity_acceptance_files_sha256": acceptance["files_sha256"],
        "model_parity_refresh_authority": acceptance["refresh_authority"],
        "model_parity_refresh_authority_sha256": acceptance["refresh_authority_sha256"],
        "model_parity_transaction_index": acceptance["transaction_index"],
        "qualification_transaction_receipt": {
            key: transaction_record[key] for key in _DESCRIPTOR_FIELDS
        },
        "qualification_transaction_receipt_sha256": transaction_record["receipt_sha256"],
        "qualification_index": candidate["index"],
        "candidate_manifest": candidate["manifest"],
        "candidate_receipt": candidate["receipt"],
        "candidate_receipt_identity_sha256": candidate["candidate_receipt_identity_sha256"],
        "policy_contract_sha256": candidate["policy_contract_sha256"],
        "blockers": ["guardian_preprocessing_materialization_is_not_publication_authority"],
    }
    receipt = {**receipt_unsigned, "receipt_sha256": _semantic_sha(receipt_unsigned)}
    receipt_payload = _canonical(receipt) + b"\n"
    _commit_receipt_last_bundle_v1(
        root=root,
        output=output,
        intent_kind="vast_guardian_preprocessing_materialization_intent_v1",
        ordered_payloads=(
            (CONTRACT_FILENAME, contract_payload),
            (RECEIPT_FILENAME, receipt_payload),
        ),
        label="guardian preprocessing",
        after_physical_commit_step=after_physical_commit_step,
    )
    loaded = load_guardian_preprocessing_contract_v1(
        project_root=root,
        preprocessing_contract_path=contract_path,
        materialization_receipt_path=receipt_path,
        candidate_manifest_path=_physical_file(
            root, candidate["manifest"]["path"], label="qualification candidate manifest"
        ),
        acceptance_loader=acceptance_loader,
        expected_preprocessing_contract_sha256=expected_preprocessing_contract_sha256,
    )
    _require(
        loaded["preprocessing_contract"] == acceptance["contract"],
        "post-commit preprocessing contract drifted",
    )
    return {
        "contract_path": contract_path,
        "receipt_path": receipt_path,
        "preprocessing_contract_sha256": expected_preprocessing_contract_sha256,
    }


def load_guardian_preprocessing_contract_v1(
    *,
    project_root: Path | str,
    preprocessing_contract_path: Path | str,
    materialization_receipt_path: Path | str,
    candidate_manifest_path: Path | str,
    acceptance_loader: AcceptanceLoader = _default_acceptance_loader,
    expected_preprocessing_contract_sha256: str = (
        FROZEN_PREPROCESSING_CONTRACT_SHA256
    ),
) -> dict[str, Any]:
    """Verify the receipt, source transaction/candidate, and extracted contract."""

    root = _physical_root(project_root)
    _require(callable(acceptance_loader), "model-parity acceptance loader is invalid")
    contract_descriptor = _descriptor(
        root, preprocessing_contract_path, label="guardian preprocessing contract"
    )
    contract_path = _physical_file(
        root, preprocessing_contract_path, label="guardian preprocessing contract"
    )
    receipt_descriptor = _descriptor(
        root, materialization_receipt_path, label="guardian preprocessing receipt"
    )
    receipt_path = _physical_file(
        root, materialization_receipt_path, label="guardian preprocessing receipt"
    )
    _require(
        contract_path.parent == receipt_path.parent
        and contract_path.name == CONTRACT_FILENAME
        and receipt_path.name == RECEIPT_FILENAME,
        "guardian preprocessing contract/receipt namespace drifted",
    )
    receipt = _read_canonical_json(
        root, receipt_path, label="guardian preprocessing receipt"
    )
    _require(
        set(receipt) == _RECEIPT_FIELDS
        and receipt.get("schema_version") == 1
        and receipt.get("artifact_kind") == RECEIPT_KIND
        and receipt.get("status") == "materialized_from_verified_v4_acceptance"
        and receipt.get("scope") == SCOPE
        and receipt.get("accepted") is False
        and receipt.get("publication_ready") is False
        and receipt.get("authorization_eligible") is False
        and receipt.get("preprocessing_contract") == contract_descriptor
        and receipt.get("preprocessing_contract_content_sha256")
        == expected_preprocessing_contract_sha256
        and type(receipt.get("blockers")) is list
        and receipt["blockers"]
        == ["guardian_preprocessing_materialization_is_not_publication_authority"],
        "guardian preprocessing receipt identity drifted",
    )
    receipt_identity_sha = _self_hash(
        receipt, "receipt_sha256", label="guardian preprocessing receipt"
    )
    contract = _read_canonical_json(
        root, contract_path, label="guardian preprocessing contract"
    )
    _require(
        _valid_sha(expected_preprocessing_contract_sha256)
        and _semantic_sha(contract) == expected_preprocessing_contract_sha256,
        "guardian preprocessing contract content identity drifted",
    )
    transaction_descriptor, transaction_path = _verified_descriptor(
        root,
        receipt.get("qualification_transaction_receipt"),
        label="qualification transaction receipt",
    )
    transaction, candidate, transaction_record = _validate_transaction(
        root, transaction_path
    )
    _require(
        transaction_descriptor
        == {key: transaction_record[key] for key in _DESCRIPTOR_FIELDS}
        and receipt.get("qualification_transaction_receipt_sha256")
        == transaction_record["receipt_sha256"]
        and receipt.get("qualification_index") == candidate["index"]
        and receipt.get("candidate_manifest") == candidate["manifest"]
        and receipt.get("candidate_receipt") == candidate["receipt"]
        and receipt.get("candidate_receipt_identity_sha256")
        == candidate["candidate_receipt_identity_sha256"]
        and receipt.get("policy_contract_sha256")
        == candidate["policy_contract_sha256"],
        "guardian preprocessing transaction/candidate binding drifted",
    )
    requested_candidate_descriptor = _descriptor(
        root, candidate_manifest_path, label="requested candidate manifest"
    )
    _require(
        requested_candidate_descriptor == candidate["manifest"],
        "requested candidate manifest differs from guardian preprocessing receipt",
    )
    verified_acceptance = _load_verified_acceptance_material(
        root=root,
        transaction=transaction,
        acceptance_loader=acceptance_loader,
        expected_preprocessing_contract_sha256=(
            expected_preprocessing_contract_sha256
        ),
    )
    receipt_files = _v4_files(
        receipt.get("model_parity_acceptance_files"),
        receipt.get("model_parity_acceptance_files_sha256"),
    )
    receipt_transaction_index = _v4_transaction_binding(
        receipt.get("model_parity_transaction_index")
    )
    receipt_refresh = receipt.get("model_parity_refresh_authority")
    _require(
        verified_acceptance["manifest"]
        == receipt.get("accepted_model_parity_manifest")
        == transaction["accepted_model_parity_manifest"]
        and verified_acceptance["assessment"]
        == receipt.get("accepted_model_parity_assessment")
        == transaction["accepted_model_parity_assessment"]
        and verified_acceptance["acceptance_receipt"]
        == receipt.get("accepted_model_parity_receipt")
        == transaction["accepted_model_parity_receipt"]
        and verified_acceptance["acceptance_binding"]
        == receipt.get("model_parity_acceptance_binding")
        and verified_acceptance["acceptance_binding_sha256"]
        == receipt.get("model_parity_acceptance_binding_sha256")
        == transaction["model_parity_acceptance_binding_sha256"]
        and verified_acceptance["files"] == receipt_files
        and verified_acceptance["files_sha256"]
        == receipt.get("model_parity_acceptance_files_sha256")
        and type(receipt_refresh) is dict
        and verified_acceptance["refresh_authority"] == receipt_refresh
        and verified_acceptance["refresh_authority_sha256"]
        == receipt.get("model_parity_refresh_authority_sha256")
        == _semantic_sha(receipt_refresh)
        and verified_acceptance["transaction_index"]
        == receipt_transaction_index,
        "guardian preprocessing model-parity acceptance binding drifted",
    )
    _require(
        verified_acceptance["contract"] == contract,
        "guardian preprocessing contract differs from accepted model-parity manifest",
    )
    authority = validate_guardian_preprocessing_authority_v1(
        {
            "schema_version": 1,
            "artifact_kind": AUTHORITY_KIND,
            "preprocessing_contract_content_sha256": (
                expected_preprocessing_contract_sha256
            ),
            "preprocessing_contract_file_sha256": contract_descriptor["sha256"],
            "materialization_receipt_identity_sha256": receipt_identity_sha,
            "materialization_receipt_file_sha256": receipt_descriptor["sha256"],
            "qualification_transaction_receipt_sha256": transaction_record[
                "receipt_sha256"
            ],
            "candidate_manifest_file_sha256": candidate["manifest"]["sha256"],
            "candidate_receipt_identity_sha256": candidate[
                "candidate_receipt_identity_sha256"
            ],
            "model_parity_acceptance_binding_sha256": verified_acceptance[
                "acceptance_binding_sha256"
            ],
            "policy_contract_sha256": candidate["policy_contract_sha256"],
            "accepted_model_parity_manifest_file_sha256": verified_acceptance[
                "manifest"
            ]["sha256"],
            "accepted_model_parity_assessment_file_sha256": verified_acceptance[
                "assessment"
            ]["sha256"],
            "accepted_model_parity_receipt_file_sha256": verified_acceptance[
                "acceptance_receipt"
            ]["sha256"],
            "model_parity_acceptance_binding_file_sha256": verified_acceptance[
                "acceptance_binding"
            ]["sha256"],
            "model_parity_acceptance_files_sha256": verified_acceptance[
                "files_sha256"
            ],
            "model_parity_refresh_authority_sha256": verified_acceptance[
                "refresh_authority_sha256"
            ],
            "model_parity_transaction_index_file_sha256": verified_acceptance[
                "transaction_index"
            ]["sha256"],
            "model_parity_transaction_sha256": verified_acceptance[
                "transaction_index"
            ]["transaction_sha256"],
        }
    )
    return {
        "preprocessing_contract": contract,
        "receipt": receipt,
        "authority": authority,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--qualification-transaction-receipt", type=Path, required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = materialize_guardian_preprocessing_contract_v1(
            project_root=args.project_root,
            qualification_transaction_receipt_path=(
                args.qualification_transaction_receipt
            ),
            output_dir=args.output_dir,
        )
    except (OSError, GuardianPreprocessingContractV1Error) as error:
        print(f"guardian preprocessing materialization blocked: {error}", file=sys.stderr)
        return 78
    print(
        json.dumps(
            {
                key: value.as_posix() if isinstance(value, Path) else value
                for key, value in result.items()
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORITY_KIND",
    "CONTRACT_FILENAME",
    "DirectoryFdCustodyV1",
    "FROZEN_PREPROCESSING_CONTRACT_SHA256",
    "GuardianPreprocessingContractV1Error",
    "RECEIPT_FILENAME",
    "RECEIPT_KIND",
    "load_guardian_preprocessing_contract_v1",
    "main",
    "materialize_guardian_preprocessing_contract_v1",
    "read_file_bytes_fd_custody_v1",
    "validate_guardian_preprocessing_authority_v1",
]
