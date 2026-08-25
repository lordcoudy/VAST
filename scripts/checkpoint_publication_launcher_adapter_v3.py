#!/usr/bin/env python3
"""Child-only ABI-v3 adapter core for topology-specific native runtimes.

The parent transaction owns the launch fence, bounded captures, launcher
result, detached receipt, and receipt authority.  This module owns none of
those files.  It validates one already committed arm, dispatches exactly one
backend/topology callback, and accepts only the arm-declared direct-child
evidence namespace.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

sys.dont_write_bytecode = True

from backend_publication_dispatch_v3 import (
    ARM_CONTRACT_FILENAME,
    CAPTURE_STDERR_FILENAME,
    CAPTURE_STDOUT_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
    BackendPublicationDispatchV3Error,
    canonical_backend_publication_arm_contract_bytes_v3,
    parse_backend_publication_arm_contract_v3_bytes,
)
from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)
from checkpoint_publication_launcher_guard_v3 import (
    CheckpointPublicationLauncherGuardV3Error,
    _raw_path_has_dot_segment,
    _read_pinned_canonical_contract,
)


EXIT_SUCCESS = 0
EXIT_TRANSIENT = 75
EXIT_PERMANENT = 78
ASSESSMENT_KIND = "vast_native_publication_launcher_adapter_assessment_v3"
TOPOLOGIES = ("independent_processes", "shared_video_dag")
MAX_EVIDENCE_FILES = 64
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_EVIDENCE_BYTES = 256 * 1024 * 1024
_PARENT_OWNED_FILES = frozenset({
    ARM_CONTRACT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    CAPTURE_STDOUT_FILENAME,
    CAPTURE_STDERR_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
})
_INITIAL_PARENT_FILES = frozenset({
    ARM_CONTRACT_FILENAME,
    LAUNCH_FENCE_FILENAME,
})


class NativePublicationLauncherV3Error(RuntimeError):
    """The child adapter or its fixed runtime contract is invalid."""

    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


class NativePublicationTransientErrorV3(NativePublicationLauncherV3Error):
    """The exact native runtime may be retried by a new parent transaction."""


class NativePublicationPermanentErrorV3(NativePublicationLauncherV3Error):
    """The arm/runtime contract is permanently blocked."""


@dataclass(frozen=True)
class NativePublicationOutcomeV3:
    """Non-authorizing terminal status returned by a native runtime hook."""

    exit_code: int
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.exit_code) is not int or self.exit_code not in {
            EXIT_SUCCESS, EXIT_TRANSIENT, EXIT_PERMANENT,
        }:
            raise NativePublicationPermanentErrorV3(
                "native_runtime_exit_code_outside_closed_v3_set"
            )
        if (
            type(self.blockers) is not tuple
            or any(type(value) is not str or not value for value in self.blockers)
            or len(set(self.blockers)) != len(self.blockers)
            or (self.exit_code == EXIT_SUCCESS and self.blockers)
            or (self.exit_code != EXIT_SUCCESS and not self.blockers)
        ):
            raise NativePublicationPermanentErrorV3(
                "native_runtime_terminal_blockers_invalid"
            )


@dataclass(frozen=True)
class NativePublicationRequestV3:
    """Sanitized, caller-pinned input passed to one topology-specific hook."""

    system: str
    topology_kind: str
    scenario: str
    project_root: Path
    output_dir: Path
    arm_contract_path: Path
    arm_contract_file_sha256: str
    run_id: str
    arm_id: str
    runtime_inputs: Mapping[str, Any]
    launcher_evidence_files: tuple[str, ...]
    environment: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    native_argv: tuple[str, ...] = ()


NativeTopologyRunnerV3 = Callable[
    [NativePublicationRequestV3], NativePublicationOutcomeV3
]


@dataclass(frozen=True)
class _PinnedFile:
    path: Path
    snapshot: tuple[int, ...]
    sha256: str


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


def _print_assessment(value: Mapping[str, Any]) -> None:
    print(_canonical(dict(value)).decode("ascii"), end="")


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


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _pin_plain_file(path: Path, *, blocker: str, allow_empty: bool) -> _PinnedFile:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(before)
            or int(before.st_nlink) != 1
            or (not allow_empty and int(before.st_size) <= 0)
        ):
            raise OSError(blocker)
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise NativePublicationPermanentErrorV3(blocker) from error
    if _snapshot(before) != _snapshot(after) or len(payload) != int(after.st_size):
        raise NativePublicationPermanentErrorV3(blocker)
    return _PinnedFile(
        path=path,
        snapshot=_snapshot(after),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _require_pin_unchanged(pin: _PinnedFile) -> None:
    try:
        current = pin.path.lstat()
        if (
            _snapshot(current) != pin.snapshot
            or _is_link_or_reparse(current)
            or not stat.S_ISREG(current.st_mode)
            or int(current.st_nlink) != 1
            or hashlib.sha256(pin.path.read_bytes()).hexdigest() != pin.sha256
        ):
            raise OSError("changed")
    except OSError as error:
        raise NativePublicationPermanentErrorV3(
            "parent_owned_input_mutated_by_native_runtime"
        ) from error


def _namespace_names(output_dir: Path) -> frozenset[str]:
    try:
        names = [entry.name for entry in output_dir.iterdir()]
    except OSError as error:
        raise NativePublicationPermanentErrorV3(
            "output_namespace_unreadable"
        ) from error
    if len(names) != len({name.casefold() for name in names}):
        raise NativePublicationPermanentErrorV3(
            "output_namespace_casefold_collision"
        )
    return frozenset(names)


def _initial_namespace(output_dir: Path) -> tuple[_PinnedFile, _PinnedFile]:
    names = _namespace_names(output_dir)
    if names != _INITIAL_PARENT_FILES:
        if names & (_PARENT_OWNED_FILES - _INITIAL_PARENT_FILES):
            blocker = "parent_owned_namespace_collision"
        elif LAUNCH_FENCE_FILENAME not in names:
            blocker = "parent_launch_fence_missing"
        else:
            blocker = "output_namespace_not_parent_owned_initial_state"
        raise NativePublicationPermanentErrorV3(blocker)
    arm = _pin_plain_file(
        output_dir / ARM_CONTRACT_FILENAME,
        blocker="parent_arm_contract_custody_invalid",
        allow_empty=False,
    )
    fence = _pin_plain_file(
        output_dir / LAUNCH_FENCE_FILENAME,
        blocker="parent_launch_fence_custody_invalid",
        allow_empty=False,
    )
    return arm, fence


def _validate_evidence_file(path: Path) -> int:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(before)
            or int(before.st_nlink) != 1
            or int(before.st_size) <= 0
            or int(before.st_size) > MAX_EVIDENCE_FILE_BYTES
        ):
            raise OSError("invalid")
        with path.open("rb") as source:
            observed = 0
            digest = hashlib.sha256()
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                observed += len(chunk)
                if observed > MAX_EVIDENCE_FILE_BYTES:
                    raise OSError("oversized")
                digest.update(chunk)
        after = path.lstat()
    except OSError as error:
        raise NativePublicationPermanentErrorV3(
            "launcher_evidence_custody_invalid"
        ) from error
    if (
        _snapshot(before) != _snapshot(after)
        or observed != int(after.st_size)
        or not digest.hexdigest()
    ):
        raise NativePublicationPermanentErrorV3(
            "launcher_evidence_custody_invalid"
        )
    return observed


def _audit_terminal_namespace(
    *,
    output_dir: Path,
    evidence_names: tuple[str, ...],
    require_complete: bool,
    arm_pin: _PinnedFile,
    fence_pin: _PinnedFile,
) -> bool:
    _require_pin_unchanged(arm_pin)
    _require_pin_unchanged(fence_pin)
    observed = _namespace_names(output_dir)
    if observed & (_PARENT_OWNED_FILES - _INITIAL_PARENT_FILES):
        raise NativePublicationPermanentErrorV3(
            "parent_owned_namespace_collision"
        )
    allowed = _INITIAL_PARENT_FILES | frozenset(evidence_names)
    if not observed <= allowed:
        raise NativePublicationPermanentErrorV3(
            "native_runtime_created_undeclared_output"
        )
    expected = _INITIAL_PARENT_FILES | frozenset(evidence_names)
    complete = observed == expected
    if require_complete and not complete:
        raise NativePublicationPermanentErrorV3(
            "launcher_evidence_namespace_incomplete"
        )
    total = 0
    for name in evidence_names:
        path = output_dir / name
        if name in observed:
            total += _validate_evidence_file(path)
            if total > MAX_TOTAL_EVIDENCE_BYTES:
                raise NativePublicationPermanentErrorV3(
                    "launcher_evidence_total_size_exceeded"
                )
    return complete


def _assessment(
    *,
    system: str,
    contract_sha256: str | None,
    topology_kind: str | None,
    physical_contract_validated: bool,
    semantic_contract_validated: bool,
    namespace_validated: bool,
    native_runtime_invoked: bool,
    native_runtime_exit_code: int | None,
    exact_evidence_validated: bool,
    blockers: Sequence[str],
) -> dict[str, Any]:
    invocation = validate_publication_launcher_invocation_v3(
        publication_launcher_invocation_v3_contract()
    )
    return {
        "schema_version": 3,
        "artifact_kind": ASSESSMENT_KIND,
        "system": system,
        "topology_kind": topology_kind,
        "invocation_contract_sha256": invocation["invocation_sha256"],
        "contract_file_sha256": contract_sha256,
        "contract_bytes_externally_pinned": physical_contract_validated,
        "canonical_contract_bytes_validated": physical_contract_validated,
        "arm_contract_v3_semantics_validated": semantic_contract_validated,
        "system_coordinate_validated": semantic_contract_validated,
        "parent_owned_namespace_validated": namespace_validated,
        "no_write_custody_attested": namespace_validated,
        "no_parent_transaction_ownership": True,
        "native_runtime_invoked": native_runtime_invoked,
        "native_runtime_exit_code": native_runtime_exit_code,
        "native_runtime_environment": {},
        "native_runtime_argv_from_environment": False,
        "exact_child_evidence_validated": exact_evidence_validated,
        "project_or_output_filesystem_writes_performed": native_runtime_invoked,
        "local_module_bytecode_writes_disabled_after_wrapper_start": True,
        "python_startup_filesystem_writes_attested": False,
        "execution_authorized": False,
        "publication_capable": False,
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
        "blockers": list(blockers),
    }


def _emit_preflight_failure(
    *,
    system: str,
    contract_sha256: str | None,
    blocker: str,
    physical: bool = False,
    semantic: bool = False,
    namespace: bool = False,
) -> int:
    _print_assessment(_assessment(
        system=system,
        contract_sha256=contract_sha256,
        topology_kind=None,
        physical_contract_validated=physical,
        semantic_contract_validated=semantic,
        namespace_validated=namespace,
        native_runtime_invoked=False,
        native_runtime_exit_code=None,
        exact_evidence_validated=False,
        blockers=(blocker,),
    ))
    return EXIT_PERMANENT


def run_native_publication_launcher_adapter_v3(
    argv: Sequence[str] | None,
    *,
    expected_system: str,
    native_topology_runners: Mapping[str, NativeTopologyRunnerV3],
    readiness_blockers: Sequence[str] = (),
) -> int:
    """Validate, dispatch once, and return only the closed 0/75/78 set."""

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
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=None,
            blocker="invocation_argv_v3_not_exact",
        )
    contract_sha = arguments[5]
    raw_blocker = next((
        blocker
        for index, blocker in (
            (1, "project_root_not_canonical_plain_directory"),
            (3, "arm_contract_path_not_fixed_direct_child"),
            (7, "output_dir_not_canonical_plain_directory"),
        )
        if _raw_path_has_dot_segment(arguments[index])
    ), None)
    if raw_blocker is not None:
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker=raw_blocker,
        )
    root = Path(arguments[1])
    arm_path = Path(arguments[3])
    output = Path(arguments[7])
    try:
        decoded = _read_pinned_canonical_contract(
            project_root=root,
            output_dir=output,
            arm_contract=arm_path,
            expected_sha256=contract_sha,
        )
    except CheckpointPublicationLauncherGuardV3Error as error:
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker=error.blocker,
        )
    try:
        canonical = canonical_backend_publication_arm_contract_bytes_v3(decoded)
        arm = parse_backend_publication_arm_contract_v3_bytes(
            canonical,
            expected_file_sha256=contract_sha,
        )
    except BackendPublicationDispatchV3Error:
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker="arm_contract_v3_semantics_invalid",
            physical=True,
        )
    runtime = arm["runtime_inputs"]
    topology = str(runtime["topology_kind"])
    if (
        runtime["system"] != expected_system
        or arm["dispatch_resolution"]["coordinate"]["system"] != expected_system
    ):
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker="arm_contract_system_coordinate_mismatch",
            physical=True,
            semantic=True,
        )
    if (
        os.path.normcase(str(root))
        != os.path.normcase(str(runtime["project_root"]))
        or os.path.normcase(str(output))
        != os.path.normcase(str(runtime["output_dir"]))
        or os.path.normcase(str(arm_path))
        != os.path.normcase(str(runtime["arm_contract_path"]))
    ):
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker="launcher_argv_runtime_path_binding_mismatch",
            physical=True,
            semantic=True,
        )
    evidence_names = tuple(
        arm["launcher_output_protocol"]["launcher_evidence_files"]
    )
    if (
        not evidence_names
        or len(evidence_names) > MAX_EVIDENCE_FILES
        or len({name.casefold() for name in evidence_names}) != len(evidence_names)
    ):
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker="launcher_evidence_set_out_of_bounds",
            physical=True,
            semantic=True,
        )
    try:
        arm_pin, fence_pin = _initial_namespace(output)
    except NativePublicationPermanentErrorV3 as error:
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker=error.blocker,
            physical=True,
            semantic=True,
        )
    blockers = tuple(readiness_blockers)
    if (
        any(type(value) is not str or not value for value in blockers)
        or len(set(blockers)) != len(blockers)
    ):
        blockers = ("launcher_readiness_blockers_invalid",)
    if blockers:
        _print_assessment(_assessment(
            system=expected_system,
            contract_sha256=contract_sha,
            topology_kind=topology,
            physical_contract_validated=True,
            semantic_contract_validated=True,
            namespace_validated=True,
            native_runtime_invoked=False,
            native_runtime_exit_code=None,
            exact_evidence_validated=False,
            blockers=blockers,
        ))
        return EXIT_PERMANENT
    if (
        set(native_topology_runners) != set(TOPOLOGIES)
        or any(not callable(native_topology_runners[value]) for value in TOPOLOGIES)
    ):
        return _emit_preflight_failure(
            system=expected_system,
            contract_sha256=contract_sha,
            blocker="native_topology_runner_table_invalid",
            physical=True,
            semantic=True,
            namespace=True,
        )
    execution = arm["full_publication_execution_binding"]
    request = NativePublicationRequestV3(
        system=expected_system,
        topology_kind=topology,
        scenario=str(runtime["scenario"]),
        project_root=root,
        output_dir=output,
        arm_contract_path=arm_path,
        arm_contract_file_sha256=contract_sha,
        run_id=str(runtime["run_id"]),
        arm_id=str(execution["arm_id"]),
        runtime_inputs=MappingProxyType(copy.deepcopy(runtime)),
        launcher_evidence_files=evidence_names,
    )
    outcome: NativePublicationOutcomeV3
    try:
        returned = native_topology_runners[topology](request)
        if type(returned) is not NativePublicationOutcomeV3:
            raise NativePublicationPermanentErrorV3(
                "native_runtime_terminal_outcome_invalid"
            )
        outcome = returned
    except NativePublicationTransientErrorV3 as error:
        outcome = NativePublicationOutcomeV3(
            exit_code=EXIT_TRANSIENT, blockers=(error.blocker,)
        )
    except NativePublicationPermanentErrorV3 as error:
        outcome = NativePublicationOutcomeV3(
            exit_code=EXIT_PERMANENT, blockers=(error.blocker,)
        )
    except Exception:
        outcome = NativePublicationOutcomeV3(
            exit_code=EXIT_PERMANENT,
            blockers=("native_runtime_unclassified_failure",),
        )
    exact_evidence = False
    try:
        exact_evidence = _audit_terminal_namespace(
            output_dir=output,
            evidence_names=evidence_names,
            require_complete=outcome.exit_code == EXIT_SUCCESS,
            arm_pin=arm_pin,
            fence_pin=fence_pin,
        )
    except NativePublicationPermanentErrorV3 as error:
        outcome = NativePublicationOutcomeV3(
            exit_code=EXIT_PERMANENT, blockers=(error.blocker,)
        )
        exact_evidence = False
    _print_assessment(_assessment(
        system=expected_system,
        contract_sha256=contract_sha,
        topology_kind=topology,
        physical_contract_validated=True,
        semantic_contract_validated=True,
        namespace_validated=True,
        native_runtime_invoked=True,
        native_runtime_exit_code=outcome.exit_code,
        exact_evidence_validated=exact_evidence,
        blockers=outcome.blockers,
    ))
    return outcome.exit_code


__all__ = [
    "ASSESSMENT_KIND",
    "EXIT_PERMANENT",
    "EXIT_SUCCESS",
    "EXIT_TRANSIENT",
    "MAX_EVIDENCE_FILES",
    "MAX_EVIDENCE_FILE_BYTES",
    "MAX_TOTAL_EVIDENCE_BYTES",
    "NativePublicationLauncherV3Error",
    "NativePublicationOutcomeV3",
    "NativePublicationPermanentErrorV3",
    "NativePublicationRequestV3",
    "NativePublicationTransientErrorV3",
    "NativeTopologyRunnerV3",
    "TOPOLOGIES",
    "run_native_publication_launcher_adapter_v3",
]
