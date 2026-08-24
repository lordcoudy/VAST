#!/usr/bin/env python3
"""Read-only ABI-v3 scaffold for publication launchers that remain blocked."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True

from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)


BLOCKED_EXIT_CODE = 78
MAX_ARM_CONTRACT_BYTES = 1024 * 1024
ARM_CONTRACT_FILENAME = "backend_publication_arm_contract.json"
ASSESSMENT_KIND = "vast_fail_closed_publication_launcher_v3_assessment"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class CheckpointPublicationLauncherGuardV3Error(RuntimeError):
    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CheckpointPublicationLauncherGuardV3Error(
                "arm_contract_json_not_unique"
            )
        result[key] = value
    return result


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


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


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def _is_lexically_canonical(path: Path) -> bool:
    text = str(path)
    return os.path.normpath(text) == text


def _raw_path_has_dot_segment(value: str) -> bool:
    return any(component in {".", ".."} for component in re.split(r"[\\/]", value))


def _canonical_directory(path: Path, *, blocker: str) -> Path:
    supplied = Path(path)
    if not supplied.is_absolute() or not _is_lexically_canonical(supplied):
        raise CheckpointPublicationLauncherGuardV3Error(blocker)
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise CheckpointPublicationLauncherGuardV3Error(blocker) from exc
    if (
        not _same_path(supplied, resolved)
        or not stat.S_ISDIR(info.st_mode)
        or _is_link_or_reparse(info)
    ):
        raise CheckpointPublicationLauncherGuardV3Error(blocker)
    return resolved


def _assert_plain_descendant(root: Path, output: Path) -> None:
    try:
        relative = output.relative_to(root)
    except ValueError as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "output_dir_escaped_project_root"
        ) from exc
    if not relative.parts:
        raise CheckpointPublicationLauncherGuardV3Error(
            "output_dir_escaped_project_root"
        )
    current = root
    for component in relative.parts:
        if component in {"", ".", ".."}:
            raise CheckpointPublicationLauncherGuardV3Error(
                "output_dir_escaped_project_root"
            )
        current = current / component
        try:
            info = current.lstat()
        except OSError as exc:
            raise CheckpointPublicationLauncherGuardV3Error(
                "output_dir_not_canonical_plain_directory"
            ) from exc
        if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
            raise CheckpointPublicationLauncherGuardV3Error(
                "output_dir_not_canonical_plain_directory"
            )


def _read_pinned_canonical_contract(
    *,
    project_root: Path,
    output_dir: Path,
    arm_contract: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_file_sha256_invalid"
        )
    root = _canonical_directory(
        project_root, blocker="project_root_not_canonical_plain_directory"
    )
    output = _canonical_directory(
        output_dir, blocker="output_dir_not_canonical_plain_directory"
    )
    _assert_plain_descendant(root, output)
    try:
        root_before = _snapshot(root.lstat())
        output_before = _snapshot(output.lstat())
    except OSError as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_identity_changed"
        ) from exc
    expected = output / ARM_CONTRACT_FILENAME
    supplied = Path(arm_contract)
    if (
        not supplied.is_absolute()
        or not _is_lexically_canonical(supplied)
        or not _same_path(supplied, expected)
    ):
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_path_not_fixed_direct_child"
        )
    try:
        resolved = supplied.resolve(strict=True)
        before_path = supplied.lstat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_path_not_fixed_direct_child"
        ) from exc
    if (
        not _same_path(resolved, expected)
        or _is_link_or_reparse(before_path)
        or not stat.S_ISREG(before_path.st_mode)
        or int(before_path.st_nlink) != 1
        or int(before_path.st_size) <= 0
        or int(before_path.st_size) > MAX_ARM_CONTRACT_BYTES
    ):
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_path_not_fixed_direct_child"
        )
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        descriptor = os.open(supplied, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or int(opened.st_nlink) != 1
            or int(opened.st_size) <= 0
            or int(opened.st_size) > MAX_ARM_CONTRACT_BYTES
            or (int(opened.st_dev), int(opened.st_ino))
            != (int(before_path.st_dev), int(before_path.st_ino))
        ):
            raise CheckpointPublicationLauncherGuardV3Error(
                "arm_contract_identity_changed"
            )
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_ARM_CONTRACT_BYTES + 1 - observed),
            )
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > MAX_ARM_CONTRACT_BYTES:
                raise CheckpointPublicationLauncherGuardV3Error(
                    "arm_contract_size_out_of_bounds"
                )
        payload = b"".join(chunks)
        after_handle = os.fstat(descriptor)
        after_path = supplied.lstat()
    except CheckpointPublicationLauncherGuardV3Error:
        raise
    except OSError as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_identity_changed"
        ) from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise CheckpointPublicationLauncherGuardV3Error(
                    "arm_contract_identity_changed"
                ) from exc
    try:
        root_after = _snapshot(root.lstat())
        output_after = _snapshot(output.lstat())
    except OSError as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_identity_changed"
        ) from exc
    if (
        _snapshot(opened) != _snapshot(after_handle)
        or _snapshot(before_path) != _snapshot(after_path)
        or (int(after_path.st_dev), int(after_path.st_ino))
        != (int(after_handle.st_dev), int(after_handle.st_ino))
        or len(payload) != int(after_handle.st_size)
        or root_after != root_before
        or output_after != output_before
    ):
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_identity_changed"
        )
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_file_sha256_mismatch"
        )
    try:
        decoded = json.loads(
            payload.decode("ascii"), object_pairs_hook=_unique_object
        )
    except CheckpointPublicationLauncherGuardV3Error:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_json_invalid"
        ) from exc
    if type(decoded) is not dict:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_json_not_unique"
        )
    try:
        canonical = _canonical(decoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_json_invalid"
        ) from exc
    if payload != canonical:
        raise CheckpointPublicationLauncherGuardV3Error(
            "arm_contract_bytes_not_canonical"
        )
    return decoded


def _assessment(
    *,
    system: str,
    contract_sha256: str | None,
    physical_contract_validated: bool,
    blockers: list[str],
) -> dict[str, Any]:
    declaration = validate_publication_launcher_invocation_v3(
        publication_launcher_invocation_v3_contract()
    )
    return {
        "schema_version": 3,
        "artifact_kind": ASSESSMENT_KIND,
        "system": system,
        "invocation_contract_sha256": declaration["invocation_sha256"],
        "contract_file_sha256": contract_sha256,
        "contract_bytes_externally_pinned": physical_contract_validated,
        "canonical_contract_bytes_validated": physical_contract_validated,
        "arm_contract_v3_semantics_validated": False,
        "system_coordinate_validated": False,
        "no_write_custody_attested": False,
        "project_or_output_filesystem_writes_performed": False,
        "local_module_bytecode_writes_disabled_after_wrapper_start": True,
        "python_startup_filesystem_writes_attested": False,
        "execution_authorized": False,
        "publication_capable": False,
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
        "blockers": blockers,
    }


def run_fail_closed_publication_launcher_v3(
    argv: Sequence[str] | None,
    *,
    expected_system: str,
    implementation_blocker: str,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    exact_argv = (
        len(arguments) == 8
        and all(type(item) is str for item in arguments)
        and arguments[0] == "--project-root"
        and arguments[2] == "--arm-contract"
        and arguments[4] == "--arm-contract-sha256"
        and arguments[6] == "--output-dir"
    )
    if not exact_argv:
        value = _assessment(
            system=expected_system,
            contract_sha256=None,
            physical_contract_validated=False,
            blockers=["invocation_argv_v3_not_exact"],
        )
        print(_canonical(value).decode("ascii"), end="")
        return BLOCKED_EXIT_CODE
    contract_sha256 = arguments[5]
    raw_path_blocker = next(
        (
            blocker
            for index, blocker in (
                (1, "project_root_not_canonical_plain_directory"),
                (3, "arm_contract_path_not_fixed_direct_child"),
                (7, "output_dir_not_canonical_plain_directory"),
            )
            if _raw_path_has_dot_segment(arguments[index])
        ),
        None,
    )
    if raw_path_blocker is not None:
        value = _assessment(
            system=expected_system,
            contract_sha256=contract_sha256,
            physical_contract_validated=False,
            blockers=[raw_path_blocker],
        )
        print(_canonical(value).decode("ascii"), end="")
        return BLOCKED_EXIT_CODE
    try:
        _read_pinned_canonical_contract(
            project_root=Path(arguments[1]),
            output_dir=Path(arguments[7]),
            arm_contract=Path(arguments[3]),
            expected_sha256=contract_sha256,
        )
    except CheckpointPublicationLauncherGuardV3Error as exc:
        value = _assessment(
            system=expected_system,
            contract_sha256=contract_sha256,
            physical_contract_validated=False,
            blockers=[exc.blocker],
        )
        print(_canonical(value).decode("ascii"), end="")
        return BLOCKED_EXIT_CODE
    value = _assessment(
        system=expected_system,
        contract_sha256=contract_sha256,
        physical_contract_validated=True,
        blockers=[
            "arm_contract_v3_schema_not_implemented",
            "launcher_execution_not_implemented",
            "parent_owned_v3_result_receipt_finalizer_not_implemented",
            implementation_blocker,
        ],
    )
    print(_canonical(value).decode("ascii"), end="")
    return BLOCKED_EXIT_CODE


__all__ = [
    "ARM_CONTRACT_FILENAME",
    "ASSESSMENT_KIND",
    "BLOCKED_EXIT_CODE",
    "CheckpointPublicationLauncherGuardV3Error",
    "MAX_ARM_CONTRACT_BYTES",
    "run_fail_closed_publication_launcher_v3",
]
