#!/usr/bin/env python3
"""Read-only guard for publication launchers that are not yet implementable."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

from backend_publication_output_receipt import (
    ARM_CONTRACT_FILENAME,
    BackendPublicationOutputReceiptError,
    validate_backend_publication_arm_contract,
)


BLOCKED_EXIT_CODE = 78
MAX_ARM_CONTRACT_BYTES = 1024 * 1024


class CheckpointPublicationLauncherGuardError(RuntimeError):
    """The immutable publication input is unsafe, swapped, or cross-dispatched."""


def _is_link_or_reparse(path: Path) -> bool:
    return _info_is_link_or_reparse(path.lstat())


def _info_is_link_or_reparse(info: Any) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _stable_identity(info: Any) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(info.st_nlink),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _file_identity(info: Any) -> tuple[int, int]:
    return (int(info.st_dev), int(info.st_ino))


def _checked_output_root(output_dir: Path) -> Path:
    supplied = Path(output_dir)
    if not supplied.is_absolute():
        raise CheckpointPublicationLauncherGuardError(
            "output directory is not an absolute canonical path"
        )
    try:
        root = supplied.resolve(strict=True)
    except OSError as error:
        raise CheckpointPublicationLauncherGuardError(
            "output directory is missing"
        ) from error
    if supplied != root or not root.is_dir() or _is_link_or_reparse(root):
        raise CheckpointPublicationLauncherGuardError(
            "output directory is not a canonical plain directory"
        )
    return root


def _checked_root_identity(root: Path, expected_identity: tuple[int, int]) -> Any:
    try:
        info = root.lstat()
    except OSError as error:
        raise CheckpointPublicationLauncherGuardError(
            "output directory changed while reading the arm contract"
        ) from error
    if (
        _info_is_link_or_reparse(info)
        or not stat.S_ISDIR(info.st_mode)
        or _file_identity(info) != expected_identity
    ):
        raise CheckpointPublicationLauncherGuardError(
            "output directory changed while reading the arm contract"
        )
    return info


def load_and_validate_blocked_publication_arm_contract(
    *,
    arm_contract_path: Path,
    output_dir: Path,
    expected_system: str,
) -> dict[str, Any]:
    """Physically read and validate the one fixed immutable arm contract.

    This helper is intentionally read-only.  It returns the validated contract
    so a future real launcher can consume it, but it never executes a backend,
    materializes evidence, or calls the output-receipt commit API.
    """
    if type(expected_system) is not str or not expected_system:
        raise CheckpointPublicationLauncherGuardError(
            "expected system coordinate is invalid"
        )
    root = _checked_output_root(Path(output_dir))
    root_before = root.lstat()
    root_identity = _file_identity(root_before)
    supplied = Path(arm_contract_path)
    expected = root / ARM_CONTRACT_FILENAME
    if not supplied.is_absolute():
        raise CheckpointPublicationLauncherGuardError(
            "arm contract does not use the fixed path"
        )
    try:
        resolved = supplied.resolve(strict=True)
        expected_resolved = expected.resolve(strict=True)
    except OSError as error:
        raise CheckpointPublicationLauncherGuardError(
            "arm contract is missing from the fixed path"
        ) from error
    if supplied != expected or resolved != expected_resolved:
        raise CheckpointPublicationLauncherGuardError(
            "arm contract does not use the fixed path"
        )
    _checked_root_identity(root, root_identity)
    descriptor: int | None = None
    try:
        parent_before = expected.parent.lstat()
        if (
            _info_is_link_or_reparse(parent_before)
            or not stat.S_ISDIR(parent_before.st_mode)
            or _file_identity(parent_before) != root_identity
        ):
            raise CheckpointPublicationLauncherGuardError(
                "output directory changed before opening the arm contract"
            )
        path_before = expected.lstat()
        if _info_is_link_or_reparse(path_before):
            raise CheckpointPublicationLauncherGuardError(
                "arm contract contains a link/reparse point"
            )
        if not stat.S_ISREG(path_before.st_mode):
            raise CheckpointPublicationLauncherGuardError(
                "arm contract is not a regular file"
            )
        if int(path_before.st_nlink) != 1:
            raise CheckpointPublicationLauncherGuardError(
                "arm contract hardlink alias is prohibited"
            )
        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        descriptor = os.open(expected, flags)
        before = os.fstat(descriptor)
        if before.st_size <= 0 or before.st_size > MAX_ARM_CONTRACT_BYTES:
            raise CheckpointPublicationLauncherGuardError(
                "arm contract size is outside the bounded range"
            )
        parent_opened = expected.parent.lstat()
        path_opened = expected.lstat()
        if (
            _info_is_link_or_reparse(parent_opened)
            or not stat.S_ISDIR(parent_opened.st_mode)
            or _file_identity(parent_before) != root_identity
            or _file_identity(parent_opened) != root_identity
            or _info_is_link_or_reparse(path_opened)
            or not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(path_opened.st_mode)
            or int(before.st_nlink) != 1
            or int(path_opened.st_nlink) != 1
            or _file_identity(path_before) != _file_identity(before)
            or _file_identity(path_opened) != _file_identity(before)
            or _stable_identity(path_before) != _stable_identity(path_opened)
        ):
            raise CheckpointPublicationLauncherGuardError(
                "arm contract path changed while opening"
            )
        chunks: list[bytes] = []
        observed_bytes = 0
        while True:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_ARM_CONTRACT_BYTES + 1 - observed_bytes),
            )
            if not chunk:
                break
            chunks.append(chunk)
            observed_bytes += len(chunk)
            if observed_bytes > MAX_ARM_CONTRACT_BYTES:
                raise CheckpointPublicationLauncherGuardError(
                    "arm contract size exceeded the bounded read"
                )
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        path_after = expected.lstat()
        parent_after = expected.parent.lstat()
    except CheckpointPublicationLauncherGuardError:
        raise
    except OSError as error:
        raise CheckpointPublicationLauncherGuardError(
            f"arm contract cannot be read: {error}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (
        _stable_identity(before) != _stable_identity(after)
        or len(payload) != int(after.st_size)
        or _info_is_link_or_reparse(parent_after)
        or not stat.S_ISDIR(parent_after.st_mode)
        or _file_identity(parent_after) != root_identity
        or _info_is_link_or_reparse(path_after)
        or _stable_identity(path_opened) != _stable_identity(path_after)
        or _file_identity(path_after) != _file_identity(after)
    ):
        raise CheckpointPublicationLauncherGuardError(
            "arm contract changed while reading"
        )
    _checked_root_identity(root, root_identity)
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CheckpointPublicationLauncherGuardError(
            "arm contract is not valid JSON"
        ) from error
    try:
        contract = validate_backend_publication_arm_contract(decoded)
    except BackendPublicationOutputReceiptError as error:
        raise CheckpointPublicationLauncherGuardError(
            f"arm contract content is invalid: {error}"
        ) from error
    runtime = contract["runtime_inputs"]
    contract_output = Path(runtime["output_dir"])
    try:
        resolved_contract_output = contract_output.resolve(strict=True)
    except OSError as error:
        raise CheckpointPublicationLauncherGuardError(
            "arm contract output directory is missing"
        ) from error
    if contract_output != root or resolved_contract_output != root:
        raise CheckpointPublicationLauncherGuardError(
            "arm contract output directory is replayed/swapped"
        )
    if runtime["system"] != expected_system:
        raise CheckpointPublicationLauncherGuardError(
            "arm contract system coordinate is cross-dispatched"
        )
    _checked_root_identity(root, root_identity)
    return contract


def run_fail_closed_publication_launcher(
    argv: Sequence[str] | None,
    *,
    expected_system: str,
    blocker: str,
) -> int:
    """Accept only ABI-v2 argv, validate its input, then block without writes."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if (
        len(arguments) != 4
        or any(type(argument) is not str for argument in arguments)
        or arguments[0] != "--arm-contract"
        or arguments[2] != "--output-dir"
    ):
        print(
            f"{expected_system} publication launcher is blocked: "
            "closed invocation ABI requires exactly --arm-contract PATH "
            "--output-dir PATH; plan/introspection arguments are prohibited",
            file=sys.stderr,
        )
        return BLOCKED_EXIT_CODE
    try:
        load_and_validate_blocked_publication_arm_contract(
            arm_contract_path=Path(arguments[1]),
            output_dir=Path(arguments[3]),
            expected_system=expected_system,
        )
    except CheckpointPublicationLauncherGuardError as error:
        print(
            f"{expected_system} publication launcher is blocked: {error}",
            file=sys.stderr,
        )
        return BLOCKED_EXIT_CODE
    print(
        f"{expected_system} publication launcher is blocked: {blocker}; "
        "native execution and exact policy-aware pre-final evidence are absent, "
        "so launcher result/output receipt commit is prohibited",
        file=sys.stderr,
    )
    return BLOCKED_EXIT_CODE
