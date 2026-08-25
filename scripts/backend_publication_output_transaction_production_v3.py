#!/usr/bin/env python3
"""Parent-owned production output transaction for launcher ABI v3.

The immutable arm/dispatch ABI and the hardened filesystem/process custody live
in the existing v3 modules.  This module deliberately uses distinct production
artifact kinds and only creates an accepted result after a caller-pinned,
read-only semantic evidence validator accepts the exact held evidence bytes.
The nonpublication engineering transaction remains byte- and schema-stable.
"""

from __future__ import annotations

import builtins
import copy
import dis
import hashlib
import marshal
import os
from pathlib import Path
import stat
import sys
import types
from typing import Any, Callable, Iterable, Mapping, Sequence

import backend_publication_output_transaction_v3 as engineering
import backend_publication_process_supervisor_v3 as process_supervisor
from backend_publication_dispatch_v3 import (
    ARM_CONTRACT_FILENAME,
    CAPTURE_STDERR_FILENAME,
    CAPTURE_STDOUT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
    BackendPublicationDispatchV3Error,
    build_backend_publication_command_v3,
    parse_backend_publication_arm_contract_v3_bytes,
    validate_backend_publication_arm_contract_v3,
)
from backend_publication_process_supervisor_v3 import (
    BackendPublicationProcessSupervisorV3Error,
    run_backend_publication_process_v3 as _run_backend_publication_process_v3,
)


SCHEMA_VERSION = 3
PRODUCTION_EXECUTION_SCOPE = "full_publication_measurement_v3"
ARM_AUTHORITY_KIND = (
    "vast_backend_publication_production_arm_contract_file_authority_v3"
)
FENCE_KIND = "vast_backend_publication_production_launch_fence_v3"
SEMANTIC_REQUEST_KIND = (
    "vast_backend_publication_production_semantic_evidence_request_v3"
)
SEMANTIC_ASSESSMENT_KIND = (
    "vast_backend_publication_production_semantic_evidence_assessment_v3"
)
SEMANTIC_VALIDATOR_IDENTITY_KIND = (
    "vast_backend_publication_production_semantic_validator_identity_v3"
)
RESULT_KIND = "vast_backend_publication_production_launcher_result_v3"
RECEIPT_KIND = "vast_backend_publication_production_output_receipt_v3"
RECEIPT_AUTHORITY_KIND = (
    "vast_backend_publication_production_output_receipt_authority_v3"
)
PRODUCTION_RUNTIME_BIND_MOUNT_KIND = (
    "vast_backend_publication_production_runtime_bind_mount_v3"
)

MAX_CONTROL_JSON_BYTES = engineering.MAX_CONTROL_JSON_BYTES
MAX_EVIDENCE_FILE_BYTES = engineering.MAX_EVIDENCE_FILE_BYTES
MAX_EVIDENCE_AGGREGATE_BYTES = engineering.MAX_EVIDENCE_AGGREGATE_BYTES
MAX_EVIDENCE_FILES = engineering.MAX_EVIDENCE_FILES
MAX_TRANSACTION_NAMESPACE_ENTRIES = engineering.MAX_TRANSACTION_NAMESPACE_ENTRIES
MAX_SEMANTIC_VALIDATOR_MODULE_BYTES = 8 * 1024 * 1024
MAX_PRODUCTION_RUNTIME_PYTHON_BYTES = 128 * 1024 * 1024

_DETERMINISTIC_VALIDATOR_BUILTINS = frozenset(
    {
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "range",
        "reversed",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)
_FORBIDDEN_VALIDATOR_OPCODES = frozenset(
    {"DELETE_GLOBAL", "IMPORT_FROM", "IMPORT_NAME", "STORE_GLOBAL"}
)

PRODUCTION_ACCEPTANCE_CLAIM_FIELDS = (
    "accepted_measurement_evidence",
    "publication_output_accepted",
    "publication_ready",
    "promotable",
    "semantic_evidence_validated",
    "external_pins_validated",
    "process_tree_quiescent",
)

BackendPublicationOutputProductionV3Error = (
    engineering.BackendPublicationOutputTransactionV3Error
)
SemanticEvidenceValidator = Callable[[dict[str, object]], Mapping[str, Any]]


def run_backend_publication_process_v3(
    argv: Sequence[str],
    *,
    cwd: Path,
    _python_descriptor: int | None = None,
    _launcher_descriptor: int | None = None,
    _cwd_descriptor: int | None = None,
    _supervisor_descriptor: int | None = None,
    _invocation_descriptor: int | None = None,
) -> process_supervisor.BackendPublicationProcessRunV3:
    """Production-only held-fd facade; the engineering supervisor ABI is intact."""

    descriptors = (
        _python_descriptor,
        _launcher_descriptor,
        _cwd_descriptor,
        _supervisor_descriptor,
        _invocation_descriptor,
    )
    if os.name == "nt":
        if any(value is not None for value in descriptors):
            raise BackendPublicationProcessSupervisorV3Error(
                "production POSIX held descriptors were supplied on Windows"
            )
        return _run_backend_publication_process_v3(argv, cwd=cwd)
    if any(type(value) is not int or value < 3 for value in descriptors):
        raise BackendPublicationProcessSupervisorV3Error(
            "production POSIX held descriptors are unavailable"
        )
    return process_supervisor._run_backend_publication_process_from_held_fds_production_v3(  # noqa: SLF001
        argv,
        cwd=cwd,
        python_descriptor=_python_descriptor,
        launcher_descriptor=_launcher_descriptor,
        cwd_descriptor=_cwd_descriptor,
        supervisor_descriptor=_supervisor_descriptor,
        invocation_descriptor=_invocation_descriptor,
    )


def _runtime_relative_path(value: Any, *, label: str) -> Path:
    relative = Path(str(value))
    if (
        type(value) is not str
        or not value
        or "\0" in value
        or relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BackendPublicationOutputProductionV3Error(
            f"production runtime bind mount {label} is invalid"
        )
    return relative


def build_production_runtime_bind_mount_contract_v3(
    *,
    source_runtime_root: Path,
    project_runtime_mount: str,
    source_python_relative_path: str = "bin/python",
) -> dict[str, Any]:
    """Pin a WSL runtime contract without weakening the root-relative descriptor.

    The source must live on ext4, be created with ``venv --copies`` so its
    Python leaf is a unique plain file, and be mounted read-only at the declared
    project-relative location.  The dispatch runtime-binding identity must be
    this contract's ``binding_sha256`` and its Python descriptor must name the
    mounted project-relative leaf.
    """

    source_root = Path(source_runtime_root)
    mount_relative = _runtime_relative_path(
        project_runtime_mount, label="project-relative path"
    )
    python_relative = _runtime_relative_path(
        source_python_relative_path, label="Python relative path"
    )
    source_root_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    python_parent_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    python_hold: engineering._HeldFile | None = None  # noqa: SLF001
    try:
        source_root_hold = engineering._DirectoryHold(source_root)  # noqa: SLF001
        cursor = source_root
        for part in python_relative.parts[:-1]:
            cursor = cursor / part
            try:
                info = cursor.lstat()
            except OSError as error:
                raise BackendPublicationOutputProductionV3Error(
                    "production runtime bind mount Python ancestor is missing"
                ) from error
            if not stat.S_ISDIR(info.st_mode) or engineering._is_link_or_reparse(info):  # noqa: SLF001
                raise BackendPublicationOutputProductionV3Error(
                    "production runtime bind mount Python ancestor is unsafe"
                )
        python_path = cursor / python_relative.name
        try:
            python_info = python_path.lstat()
        except OSError as error:
            raise BackendPublicationOutputProductionV3Error(
                "production runtime bind mount Python is missing"
            ) from error
        if (
            not stat.S_ISREG(python_info.st_mode)
            or engineering._is_link_or_reparse(python_info)  # noqa: SLF001
            or int(python_info.st_nlink) != 1
        ):
            raise BackendPublicationOutputProductionV3Error(
                "production runtime Python must be a unique plain file; rebuild the venv with --copies"
            )
        python_parent_hold = engineering._DirectoryHold(cursor)  # noqa: SLF001
        python_hold = engineering._HeldFile(  # noqa: SLF001
            python_parent_hold,
            python_relative.name,
            label="production runtime source Python",
            limit=MAX_PRODUCTION_RUNTIME_PYTHON_BYTES,
            allow_empty=False,
        )
        python_hold.verify()
        python_parent_hold.verify()
        source_root_hold.verify()
        project_python = (mount_relative / python_relative).as_posix()
        value: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": PRODUCTION_RUNTIME_BIND_MOUNT_KIND,
            "source_runtime_root": str(source_root),
            "source_python_relative_path": python_relative.as_posix(),
            "source_python_size_bytes": len(python_hold.payload),
            "source_python_sha256": python_hold.digest,
            "project_runtime_mount": mount_relative.as_posix(),
            "project_python_path": project_python,
            "runtime_filesystem": "ext4",
            "source_runtime_mount_read_only": True,
            "runtime_mount_read_only": True,
        }
        return engineering._seal(value, "binding_sha256")  # noqa: SLF001
    finally:
        if python_hold is not None:
            python_hold.close(suppress=False)
        if python_parent_hold is not None:
            python_parent_hold.close(suppress=False)
        if source_root_hold is not None:
            source_root_hold.close(suppress=False)


def _mountinfo_path(value: str) -> str:
    decoded = value
    for escaped, replacement in (
        ("\\040", " "),
        ("\\011", "\t"),
        ("\\012", "\n"),
        ("\\134", "\\"),
    ):
        decoded = decoded.replace(escaped, replacement)
    return decoded


def _linux_mountinfo_v3() -> list[tuple[str, frozenset[str], str]]:
    try:
        payload = Path("/proc/self/mountinfo").read_bytes()
    except OSError as error:
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount inventory is unavailable"
        ) from error
    if not payload or len(payload) > 4 * 1024 * 1024:
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount inventory is invalid"
        )
    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount inventory is invalid"
        ) from error
    records: list[tuple[str, frozenset[str], str]] = []
    for line in lines:
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError as error:
            raise BackendPublicationOutputProductionV3Error(
                "production runtime bind mount inventory is invalid"
            ) from error
        if len(fields) < 10 or separator < 6 or separator + 2 >= len(fields):
            raise BackendPublicationOutputProductionV3Error(
                "production runtime bind mount inventory is invalid"
            )
        records.append(
            (
                _mountinfo_path(fields[4]),
                frozenset(fields[5].split(",")),
                fields[separator + 1],
            )
        )
    return records


def preflight_production_runtime_bind_mount_v3(
    *,
    project_root: Path,
    expected_python_executable: Mapping[str, Any],
    expected_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the exact ext4 read-only bind before acquiring runtime custody."""

    if os.name == "nt" or not sys.platform.startswith("linux"):
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount preflight requires Linux"
        )
    if type(expected_binding) is not dict:
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount contract is not an object"
        )
    fields = {
        "schema_version",
        "artifact_kind",
        "source_runtime_root",
        "source_python_relative_path",
        "source_python_size_bytes",
        "source_python_sha256",
        "project_runtime_mount",
        "project_python_path",
        "runtime_filesystem",
        "source_runtime_mount_read_only",
        "runtime_mount_read_only",
        "binding_sha256",
    }
    if set(expected_binding) != fields:
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount contract fields drifted"
        )
    rebuilt = build_production_runtime_bind_mount_contract_v3(
        source_runtime_root=Path(str(expected_binding.get("source_runtime_root"))),
        project_runtime_mount=str(expected_binding.get("project_runtime_mount")),
        source_python_relative_path=str(
            expected_binding.get("source_python_relative_path")
        ),
    )
    if dict(expected_binding) != rebuilt:
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount contract is tampered or drifted"
        )
    descriptor = dict(expected_python_executable)
    if (
        type(expected_python_executable) is not dict
        or descriptor.get("path") != rebuilt["project_python_path"]
        or descriptor.get("size_bytes") != rebuilt["source_python_size_bytes"]
        or descriptor.get("sha256") != rebuilt["source_python_sha256"]
    ):
        raise BackendPublicationOutputProductionV3Error(
            "production runtime bind mount Python descriptor is not crossbound"
        )

    root_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    source_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    target_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    target_parent: engineering._DirectoryHold | None = None  # noqa: SLF001
    target_python: engineering._HeldFile | None = None  # noqa: SLF001
    try:
        root = Path(project_root)
        source = Path(rebuilt["source_runtime_root"])
        target = root / rebuilt["project_runtime_mount"]
        root_hold = engineering._DirectoryHold(root)  # noqa: SLF001
        source_hold = engineering._DirectoryHold(source)  # noqa: SLF001
        target_hold = engineering._DirectoryHold(target)  # noqa: SLF001
        records = _linux_mountinfo_v3()
        target_records = [record for record in records if record[0] == str(target)]
        if (
            len(target_records) != 1
            or "ro" not in target_records[0][1]
            or target_records[0][2] != "ext4"
        ):
            raise BackendPublicationOutputProductionV3Error(
                "production runtime target must be an exact ext4 read-only bind mount"
            )
        source_text = str(source)
        source_records = [
            record
            for record in records
            if source_text == record[0]
        ]
        if (
            len(source_records) != 1
            or "ro" not in source_records[0][1]
            or source_records[0][2] != "ext4"
        ):
            raise BackendPublicationOutputProductionV3Error(
                "production runtime source must be an exact ext4 read-only mount"
            )
        source_identity = (
            int(source_hold.before.st_dev),
            int(source_hold.before.st_ino),
            int(stat.S_IFMT(source_hold.before.st_mode)),
        )
        target_identity = (
            int(target_hold.before.st_dev),
            int(target_hold.before.st_ino),
            int(stat.S_IFMT(target_hold.before.st_mode)),
        )
        if source_identity != target_identity:
            raise BackendPublicationOutputProductionV3Error(
                "production runtime target is not bound to the pinned source root"
            )
        target_parent, target_python = engineering._external_file_hold(  # noqa: SLF001
            root,
            descriptor,
            label="production bind-mounted Python executable",
        )
        source_python = source / rebuilt["source_python_relative_path"]
        source_python_info = source_python.lstat()
        target_python_info = os.fstat(target_python.descriptor)
        if (
            int(source_python_info.st_dev),
            int(source_python_info.st_ino),
            int(stat.S_IFMT(source_python_info.st_mode)),
        ) != (
            int(target_python_info.st_dev),
            int(target_python_info.st_ino),
            int(stat.S_IFMT(target_python_info.st_mode)),
        ):
            raise BackendPublicationOutputProductionV3Error(
                "production runtime Python is not sourced from the read-only bind"
            )
        target_python.verify()
        target_parent.verify()
        target_hold.verify()
        source_hold.verify()
        root_hold.verify()
        return copy.deepcopy(rebuilt)
    finally:
        if target_python is not None:
            target_python.close(suppress=False)
        for held_directory in (target_parent, target_hold, source_hold, root_hold):
            if held_directory is not None:
                held_directory.close(suppress=False)


def _validate_durable_parent_artifact_pin(
    value: Mapping[str, Any] | None,
    *,
    expected_state: str,
    held: engineering._HeldFile,  # noqa: SLF001
) -> dict[str, Any]:
    """Validate a pin loaded from durable storage outside the child namespace.

    The caller must not reconstruct this value from the transaction directory
    during resume.  Its authority is precisely that a parent persisted the raw
    artifact descriptor before losing the original live transaction context.
    """

    if type(value) is not dict or set(value) != {
        "state",
        "path",
        "size_bytes",
        "sha256",
    }:
        raise BackendPublicationOutputProductionV3Error(
            "production resume durable parent artifact pin fields drifted"
        )
    if value.get("state") != expected_state:
        raise BackendPublicationOutputProductionV3Error(
            "production resume durable parent artifact pin state drifted"
        )
    descriptor = engineering._descriptor(  # noqa: SLF001
        {
            "path": value.get("path"),
            "size_bytes": value.get("size_bytes"),
            "sha256": value.get("sha256"),
        },
        label="durable parent artifact pin",
        allow_empty=False,
    )
    if descriptor != held.file_descriptor():
        raise BackendPublicationOutputProductionV3Error(
            "production resume durable parent artifact pin raw descriptor drifted"
        )
    return {"state": expected_state, **descriptor}


def _validator_code_objects(code: types.CodeType) -> Iterable[types.CodeType]:
    yield code
    for constant in code.co_consts:
        if type(constant) is types.CodeType:
            yield from _validator_code_objects(constant)


def _semantic_validator_identity_material(
    validator: SemanticEvidenceValidator,
) -> dict[str, Any]:
    if type(validator) is not types.FunctionType:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator must be a plain function"
        )
    if (
        validator.__name__.startswith("<")
        or validator.__qualname__ != validator.__name__
        or validator.__closure__ is not None
        or validator.__defaults__ is not None
        or validator.__kwdefaults__ is not None
        or bool(validator.__dict__)
    ):
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator must be a stateless top-level function"
        )
    module = sys.modules.get(validator.__module__)
    if module is None or getattr(module, validator.__name__, None) is not validator:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator is not its module's top-level function"
        )
    module_file = getattr(module, "__file__", None)
    if type(module_file) is not str or not module_file:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator module has no exact file bytes"
        )

    used_globals: set[str] = set()
    for code in _validator_code_objects(validator.__code__):
        for instruction in dis.get_instructions(code):
            if instruction.opname in _FORBIDDEN_VALIDATOR_OPCODES:
                raise BackendPublicationOutputProductionV3Error(
                    "production semantic evidence validator contains stateful bytecode"
                )
            if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}:
                used_globals.add(str(instruction.argval))
    if not used_globals <= _DETERMINISTIC_VALIDATOR_BUILTINS:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator depends on module/global state"
        )
    builtin_namespace = validator.__globals__.get("__builtins__", builtins)
    if isinstance(builtin_namespace, types.ModuleType):
        builtin_namespace = vars(builtin_namespace)
    if type(builtin_namespace) is not dict or any(
        name in validator.__globals__
        or builtin_namespace.get(name) is not getattr(builtins, name)
        for name in used_globals
    ):
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator builtin binding drifted"
        )

    module_path = Path(module_file)
    module_parent: engineering._DirectoryHold | None = None  # noqa: SLF001
    module_hold: engineering._HeldFile | None = None  # noqa: SLF001
    try:
        module_parent = engineering._DirectoryHold(module_path.parent)  # noqa: SLF001
        module_hold = engineering._HeldFile(  # noqa: SLF001
            module_parent,
            module_path.name,
            label="semantic evidence validator module",
            limit=MAX_SEMANTIC_VALIDATOR_MODULE_BYTES,
            allow_empty=False,
        )
        module_hold.verify()
        module_parent.verify()
        code_payload = marshal.dumps(validator.__code__)
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": SEMANTIC_VALIDATOR_IDENTITY_KIND,
            "module_name": validator.__module__,
            "module_path": str(module_path),
            "module_size_bytes": len(module_hold.payload),
            "module_sha256": module_hold.digest,
            "function_name": validator.__name__,
            "function_qualname": validator.__qualname__,
            "code_size_bytes": len(code_payload),
            "code_sha256": hashlib.sha256(code_payload).hexdigest(),
        }
    finally:
        if module_hold is not None:
            module_hold.close(suppress=False)
        if module_parent is not None:
            module_parent.close(suppress=False)


def semantic_evidence_validator_identity_v3(
    validator: SemanticEvidenceValidator,
) -> str:
    """Hash the exact stateless callback code and its unique plain module bytes."""

    return engineering._canonical_sha(  # noqa: SLF001
        _semantic_validator_identity_material(validator)
    )


def _claims(value: bool) -> dict[str, bool]:
    return {field: value for field in PRODUCTION_ACCEPTANCE_CLAIM_FIELDS}


def _arm_authority_material(prepared: Mapping[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARM_AUTHORITY_KIND,
        "status": "prepared_production_arm_not_executed",
        "execution_scope": PRODUCTION_EXECUTION_SCOPE,
        "path": prepared["path"],
        "size_bytes": prepared["size_bytes"],
        "sha256": prepared["sha256"],
        "content_sha256": prepared["content_sha256"],
        "dispatch_resolution_sha256": prepared["dispatch_resolution_sha256"],
        "run_identity_sha256": prepared["run_identity_sha256"],
        **_claims(False),
    }
    return engineering._seal(value, "authority_sha256")  # noqa: SLF001


def prepare_backend_publication_production_transaction_v3(
    *,
    output_dir: Path,
    arm_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a fresh transaction namespace and immutable ABI-v3 arm."""

    prepared = engineering.prepare_backend_publication_engineering_transaction_v3(
        output_dir=output_dir,
        arm_contract=arm_contract,
    )
    return _arm_authority_material(prepared)


def _fence_material(
    arm: Mapping[str, Any], *, arm_descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    dispatch = arm["dispatch_resolution"]
    execution = arm["full_publication_execution_binding"]
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": FENCE_KIND,
        "status": "production_launch_fenced_not_yet_accepted",
        "execution_scope": PRODUCTION_EXECUTION_SCOPE,
        "arm_contract": engineering._descriptor(  # noqa: SLF001
            dict(arm_descriptor), label="arm contract", allow_empty=False
        ),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "python_executable": copy.deepcopy(dispatch["python_executable"]),
        "publication_launcher": copy.deepcopy(dispatch["publication_launcher"]),
        **_claims(False),
    }
    return engineering._seal(value, "fence_sha256")  # noqa: SLF001


def _validate_fence(
    observed: Any,
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _fence_material(arm, arm_descriptor=arm_descriptor)
    if type(observed) is not dict or observed != expected:
        raise BackendPublicationOutputProductionV3Error(
            "production backend launch fence is tampered, replayed, or crossbound"
        )
    engineering._validate_self_hash(  # noqa: SLF001
        observed, "fence_sha256", label="production launch fence"
    )
    return copy.deepcopy(expected)


def _semantic_assessment(
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
    evidence: Sequence[engineering._HeldFile],  # noqa: SLF001
    validator: SemanticEvidenceValidator,
    validator_identity_sha256: str,
) -> dict[str, Any]:
    if semantic_evidence_validator_identity_v3(validator) != validator_identity_sha256:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator identity drifted"
        )
    descriptors = engineering._evidence_descriptors(evidence)  # noqa: SLF001
    aggregate_sha256 = engineering._evidence_aggregate_sha(descriptors)  # noqa: SLF001
    request: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": SEMANTIC_REQUEST_KIND,
        "arm_contract": copy.deepcopy(dict(arm)),
        "arm_contract_file": copy.deepcopy(dict(arm_descriptor)),
        "evidence_files": copy.deepcopy(descriptors),
        "evidence_aggregate_sha256": aggregate_sha256,
        "evidence_payloads": {
            str(held.file_descriptor()["path"]): bytes(held.payload)
            for held in evidence
        },
    }
    try:
        decision = validator(request)
    except Exception as error:
        raise BackendPublicationOutputProductionV3Error(
            f"production semantic evidence validator failed: {error}"
        ) from error
    if type(decision) is not dict or set(decision) != {
        "accepted",
        "status",
        "details",
    }:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator returned an invalid decision"
        )
    accepted = decision.get("accepted")
    status = decision.get("status")
    details = decision.get("details")
    if (
        type(accepted) is not bool
        or status not in {"accepted", "rejected"}
        or (status == "accepted") is not accepted
        or type(details) is not dict
    ):
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator returned an invalid decision"
        )
    try:
        engineering._canonical_bytes(details)  # noqa: SLF001
    except (TypeError, ValueError) as error:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence details are not canonical JSON"
        ) from error
    assessment: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": SEMANTIC_ASSESSMENT_KIND,
        "status": status,
        "accepted_measurement_evidence": accepted,
        "semantic_evidence_validated": accepted,
        "validator_identity_sha256": validator_identity_sha256,
        "arm_contract": engineering._descriptor(  # noqa: SLF001
            dict(arm_descriptor), label="arm contract", allow_empty=False
        ),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "evidence_files": copy.deepcopy(descriptors),
        "evidence_aggregate_sha256": aggregate_sha256,
        "details": copy.deepcopy(details),
    }
    assessment = engineering._seal(assessment, "assessment_sha256")  # noqa: SLF001
    if accepted is not True:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence was rejected"
        )
    return assessment


def _result_material(
    arm: Mapping[str, Any],
    *,
    arm_descriptor: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    stdout_descriptor: Mapping[str, Any],
    stderr_descriptor: Mapping[str, Any],
    process_observation: Mapping[str, Any],
    evidence_descriptors: Sequence[Mapping[str, Any]],
    semantic_assessment: Mapping[str, Any],
) -> dict[str, Any]:
    dispatch = arm["dispatch_resolution"]
    execution = arm["full_publication_execution_binding"]
    evidence = [
        engineering._descriptor(dict(item), label="launcher evidence", allow_empty=False)  # noqa: SLF001
        for item in evidence_descriptors
    ]
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RESULT_KIND,
        "status": "completed_publishable_process_evidence_accepted",
        "execution_scope": PRODUCTION_EXECUTION_SCOPE,
        "arm_contract": engineering._descriptor(  # noqa: SLF001
            dict(arm_descriptor), label="arm contract", allow_empty=False
        ),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "launch_fence": engineering._descriptor(  # noqa: SLF001
            dict(fence_descriptor), label="launch fence", allow_empty=False
        ),
        "launch_fence_content_sha256": fence["fence_sha256"],
        "process_observation": copy.deepcopy(dict(process_observation)),
        "stdout_capture": engineering._descriptor(  # noqa: SLF001
            dict(stdout_descriptor), label="stdout capture"
        ),
        "stderr_capture": engineering._descriptor(  # noqa: SLF001
            dict(stderr_descriptor), label="stderr capture"
        ),
        "evidence_files": evidence,
        "evidence_aggregate_sha256": engineering._evidence_aggregate_sha(  # noqa: SLF001
            evidence
        ),
        "semantic_evidence_assessment": copy.deepcopy(dict(semantic_assessment)),
        "semantic_evidence_assessment_sha256": semantic_assessment[
            "assessment_sha256"
        ],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": arm["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": arm[
            "resource_capability_grant_sha256"
        ],
        "model_parity_grant_sha256": arm["model_parity_grant_sha256"],
        "model_parity_acceptance_binding_sha256": arm[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": arm[
            "identity_artifact_binding_sha256"
        ],
        **_claims(True),
    }
    return engineering._seal(value, "result_sha256")  # noqa: SLF001


def _receipt_material(
    arm: Mapping[str, Any],
    *,
    arm_descriptor: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    stdout_descriptor: Mapping[str, Any],
    stderr_descriptor: Mapping[str, Any],
    result_descriptor: Mapping[str, Any],
    result: Mapping[str, Any],
    evidence_descriptors: Sequence[Mapping[str, Any]],
    semantic_assessment: Mapping[str, Any],
) -> dict[str, Any]:
    dispatch = arm["dispatch_resolution"]
    execution = arm["full_publication_execution_binding"]
    evidence = [
        engineering._descriptor(dict(item), label="launcher evidence", allow_empty=False)  # noqa: SLF001
        for item in evidence_descriptors
    ]
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RECEIPT_KIND,
        "status": "committed_publishable_launcher_output",
        "execution_scope": PRODUCTION_EXECUTION_SCOPE,
        "arm_contract": engineering._descriptor(  # noqa: SLF001
            dict(arm_descriptor), label="arm contract", allow_empty=False
        ),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "launch_fence": engineering._descriptor(  # noqa: SLF001
            dict(fence_descriptor), label="launch fence", allow_empty=False
        ),
        "launch_fence_content_sha256": fence["fence_sha256"],
        "stdout_capture": engineering._descriptor(  # noqa: SLF001
            dict(stdout_descriptor), label="stdout capture"
        ),
        "stderr_capture": engineering._descriptor(  # noqa: SLF001
            dict(stderr_descriptor), label="stderr capture"
        ),
        "launcher_result": engineering._descriptor(  # noqa: SLF001
            dict(result_descriptor), label="launcher result", allow_empty=False
        ),
        "launcher_result_content_sha256": result["result_sha256"],
        "evidence_files": evidence,
        "evidence_aggregate_sha256": engineering._evidence_aggregate_sha(  # noqa: SLF001
            evidence
        ),
        "semantic_evidence_assessment": copy.deepcopy(dict(semantic_assessment)),
        "semantic_evidence_assessment_sha256": semantic_assessment[
            "assessment_sha256"
        ],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": arm["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": arm[
            "resource_capability_grant_sha256"
        ],
        "model_parity_grant_sha256": arm["model_parity_grant_sha256"],
        "model_parity_acceptance_binding_sha256": arm[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": arm[
            "identity_artifact_binding_sha256"
        ],
        **_claims(True),
    }
    return engineering._seal(value, "receipt_sha256")  # noqa: SLF001


def _authority_material(
    arm: Mapping[str, Any],
    *,
    receipt_descriptor: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    execution = arm["full_publication_execution_binding"]
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RECEIPT_AUTHORITY_KIND,
        "status": "accepted_publishable_backend_output",
        "execution_scope": PRODUCTION_EXECUTION_SCOPE,
        **engineering._descriptor(  # noqa: SLF001
            dict(receipt_descriptor), label="output receipt", allow_empty=False
        ),
        "content_sha256": receipt["receipt_sha256"],
        "arm_contract": copy.deepcopy(receipt["arm_contract"]),
        "launcher_result": copy.deepcopy(receipt["launcher_result"]),
        "evidence_files": copy.deepcopy(receipt["evidence_files"]),
        "evidence_aggregate_sha256": receipt["evidence_aggregate_sha256"],
        "semantic_evidence_assessment": copy.deepcopy(
            receipt["semantic_evidence_assessment"]
        ),
        "semantic_evidence_assessment_sha256": receipt[
            "semantic_evidence_assessment_sha256"
        ],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "dispatch_resolution_sha256": arm["dispatch_resolution"][
            "resolution_sha256"
        ],
        **_claims(True),
    }
    return engineering._seal(value, "authority_sha256")  # noqa: SLF001


def _validate_result_material(
    observed: Any,
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    stdout: engineering._HeldFile,  # noqa: SLF001
    stderr: engineering._HeldFile,  # noqa: SLF001
    evidence: Sequence[engineering._HeldFile],  # noqa: SLF001
    command: Sequence[str],
    cwd: Path,
    process_contract: Mapping[str, Any],
    semantic_assessment: Mapping[str, Any],
) -> dict[str, Any]:
    if type(observed) is not dict:
        raise BackendPublicationOutputProductionV3Error(
            "production launcher result is not an object"
        )
    process = engineering._validate_process_observation(  # noqa: SLF001
        observed.get("process_observation"),
        stdout=stdout.payload,
        stderr=stderr.payload,
        command=command,
        cwd=cwd,
        process_contract=process_contract,
    )
    expected = _result_material(
        arm,
        arm_descriptor=arm_descriptor,
        fence_descriptor=fence_descriptor,
        fence=fence,
        stdout_descriptor=stdout.file_descriptor(),
        stderr_descriptor=stderr.file_descriptor(),
        process_observation=process,
        evidence_descriptors=engineering._evidence_descriptors(evidence),  # noqa: SLF001
        semantic_assessment=semantic_assessment,
    )
    if observed != expected:
        raise BackendPublicationOutputProductionV3Error(
            "production launcher result is tampered, replayed, or crossbound"
        )
    engineering._validate_self_hash(  # noqa: SLF001
        observed, "result_sha256", label="production launcher result"
    )
    return copy.deepcopy(expected)


def _validate_receipt_material(
    observed: Any,
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    stdout: engineering._HeldFile,  # noqa: SLF001
    stderr: engineering._HeldFile,  # noqa: SLF001
    result: Mapping[str, Any],
    result_descriptor: Mapping[str, Any],
    evidence: Sequence[engineering._HeldFile],  # noqa: SLF001
    semantic_assessment: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _receipt_material(
        arm,
        arm_descriptor=arm_descriptor,
        fence_descriptor=fence_descriptor,
        fence=fence,
        stdout_descriptor=stdout.file_descriptor(),
        stderr_descriptor=stderr.file_descriptor(),
        result_descriptor=result_descriptor,
        result=result,
        evidence_descriptors=engineering._evidence_descriptors(evidence),  # noqa: SLF001
        semantic_assessment=semantic_assessment,
    )
    if type(observed) is not dict or observed != expected:
        raise BackendPublicationOutputProductionV3Error(
            "production output receipt is tampered, replayed, or crossbound"
        )
    engineering._validate_self_hash(  # noqa: SLF001
        observed, "receipt_sha256", label="production output receipt"
    )
    return copy.deepcopy(expected)


def run_or_resume_backend_publication_production_transaction_v3(
    *,
    project_root: Path,
    output_dir: Path,
    expected_arm_contract_file_sha256: str,
    execution_scope: str,
    expected_coordinate: Mapping[str, Any],
    expected_python_executable: Mapping[str, Any],
    expected_publication_launcher: Mapping[str, Any],
    expected_launcher_invocation_sha256: str,
    expected_backend_runtime_grant_sha256: str,
    expected_identity_artifact_binding_sha256: str,
    expected_cell_identity_sha256: str,
    expected_validation_record_sha256: str,
    expected_runtime_binding_identity_sha256: str,
    expected_dispatch_resolution_sha256: str,
    expected_full_publication_execution_binding: Mapping[str, Any],
    expected_resource_capability_grant_sha256: str,
    expected_model_parity_grant_sha256: str,
    expected_model_parity_acceptance_binding_sha256: str,
    expected_runtime_inputs: Mapping[str, Any],
    expected_launcher_evidence_files: Iterable[str],
    expected_semantic_validator_identity_sha256: str,
    semantic_evidence_validator: SemanticEvidenceValidator,
    expected_durable_parent_artifact_pin: Mapping[str, Any] | None = None,
    expected_production_runtime_bind_mount: Mapping[str, Any] | None = None,
    _fault_hook: Callable[[str], None] | None = None,
    _allow_spawn: bool = True,
    _allow_finalize: bool = True,
) -> dict[str, Any]:
    """Run or conservatively resume one externally pinned production v3 arm."""

    if execution_scope != PRODUCTION_EXECUTION_SCOPE:
        raise BackendPublicationOutputProductionV3Error(
            "backend publication production v3 execution scope is invalid"
        )
    expected_validator_identity = engineering._valid_sha(  # noqa: SLF001
        expected_semantic_validator_identity_sha256,
        label="semantic evidence validator identity",
    )
    validator_identity = semantic_evidence_validator_identity_v3(
        semantic_evidence_validator
    )
    if validator_identity != expected_validator_identity:
        raise BackendPublicationOutputProductionV3Error(
            "production semantic evidence validator identity differs from its pin"
        )
    root_path = Path(project_root)
    output_path = Path(output_dir)
    expected_file_sha = engineering._valid_sha(  # noqa: SLF001
        expected_arm_contract_file_sha256, label="arm contract raw file"
    )
    evidence_names = sorted(
        engineering._direct_child_name(item, label="launcher evidence")  # noqa: SLF001
        for item in expected_launcher_evidence_files
    )
    if (
        not evidence_names
        or len({name.casefold() for name in evidence_names}) != len(evidence_names)
    ):
        raise BackendPublicationOutputProductionV3Error(
            "production expected evidence set is invalid"
        )
    if len(evidence_names) > MAX_EVIDENCE_FILES:
        raise BackendPublicationOutputProductionV3Error(
            "production expected evidence set exceeds its entry bound"
        )
    engineering._assert_plain_output_chain(root_path, output_path)  # noqa: SLF001

    output_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    project_hold: engineering._DirectoryHold | None = None  # noqa: SLF001
    directory_holds: list[engineering._DirectoryHold] = []  # noqa: SLF001
    file_holds: list[engineering._HeldFile] = []  # noqa: SLF001
    primary: BaseException | None = None
    semantic_commit = False
    receipt_hold: engineering._HeldFile | None = None  # noqa: SLF001
    try:
        output_hold = engineering._DirectoryHold(output_path)  # noqa: SLF001
        project_hold = engineering._DirectoryHold(root_path)  # noqa: SLF001
        directory_holds.extend([output_hold, project_hold])
        arm_hold = engineering._HeldFile(  # noqa: SLF001
            output_hold,
            ARM_CONTRACT_FILENAME,
            label="arm contract",
            limit=MAX_CONTROL_JSON_BYTES,
            allow_empty=False,
        )
        file_holds.append(arm_hold)
        if arm_hold.digest != expected_file_sha:
            raise BackendPublicationOutputProductionV3Error(
                "production arm contract raw file SHA-256 drifted"
            )
        try:
            arm = parse_backend_publication_arm_contract_v3_bytes(
                arm_hold.payload,
                expected_file_sha256=expected_file_sha,
            )
            arm = validate_backend_publication_arm_contract_v3(
                arm,
                expected_dispatch_resolution_sha256=expected_dispatch_resolution_sha256,
                expected_full_publication_execution_binding=(
                    expected_full_publication_execution_binding
                ),
                expected_resource_capability_grant_sha256=(
                    expected_resource_capability_grant_sha256
                ),
                expected_model_parity_grant_sha256=(
                    expected_model_parity_grant_sha256
                ),
                expected_model_parity_acceptance_binding_sha256=(
                    expected_model_parity_acceptance_binding_sha256
                ),
                expected_runtime_inputs=expected_runtime_inputs,
                expected_launcher_evidence_files=evidence_names,
            )
        except BackendPublicationDispatchV3Error as error:
            raise BackendPublicationOutputProductionV3Error(
                f"production arm contract external binding failed: {error}"
            ) from error
        runtime = arm["runtime_inputs"]
        if (
            runtime["project_root"] != str(root_path)
            or runtime["output_dir"] != str(output_path)
            or runtime["arm_contract_path"]
            != str(output_path / ARM_CONTRACT_FILENAME)
        ):
            raise BackendPublicationOutputProductionV3Error(
                "production transaction paths differ from the pinned arm"
            )
        resolution = arm["dispatch_resolution"]
        try:
            command = build_backend_publication_command_v3(
                resolution,
                expected_coordinate=expected_coordinate,
                expected_python_executable=expected_python_executable,
                expected_publication_launcher=expected_publication_launcher,
                expected_launcher_invocation_sha256=(
                    expected_launcher_invocation_sha256
                ),
                expected_backend_runtime_grant_sha256=(
                    expected_backend_runtime_grant_sha256
                ),
                expected_identity_artifact_binding_sha256=(
                    expected_identity_artifact_binding_sha256
                ),
                expected_cell_identity_sha256=expected_cell_identity_sha256,
                expected_validation_record_sha256=expected_validation_record_sha256,
                expected_runtime_binding_identity_sha256=(
                    expected_runtime_binding_identity_sha256
                ),
                project_root=root_path,
                arm_contract_path=output_path / ARM_CONTRACT_FILENAME,
                arm_contract_file_sha256=expected_file_sha,
                output_dir=output_path,
            )
        except BackendPublicationDispatchV3Error as error:
            raise BackendPublicationOutputProductionV3Error(
                f"production v3 command binding failed: {error}"
            ) from error

        if expected_production_runtime_bind_mount is not None:
            runtime_binding = preflight_production_runtime_bind_mount_v3(
                project_root=root_path,
                expected_python_executable=expected_python_executable,
                expected_binding=expected_production_runtime_bind_mount,
            )
            if runtime_binding["binding_sha256"] != engineering._valid_sha(  # noqa: SLF001
                expected_runtime_binding_identity_sha256,
                label="production runtime bind mount identity",
            ):
                raise BackendPublicationOutputProductionV3Error(
                    "production runtime bind mount differs from the dispatch identity"
                )

        python_parent, python_hold = engineering._external_file_hold(  # noqa: SLF001
            root_path, expected_python_executable, label="Python executable"
        )
        launcher_parent, launcher_hold = engineering._external_file_hold(  # noqa: SLF001
            root_path, expected_publication_launcher, label="publication launcher"
        )
        directory_holds.extend([python_parent, launcher_parent])
        file_holds.extend([python_hold, launcher_hold])
        supervisor_parent: engineering._DirectoryHold | None = None  # noqa: SLF001
        supervisor_hold: engineering._HeldFile | None = None  # noqa: SLF001
        invocation_hold: engineering._HeldFile | None = None  # noqa: SLF001
        if os.name != "nt":
            supervisor_path = Path(process_supervisor.__file__)
            try:
                supervisor_path.relative_to(root_path)
            except ValueError as error:
                raise BackendPublicationOutputProductionV3Error(
                    "production supervisor source is outside the held project root"
                ) from error
            supervisor_parent = engineering._DirectoryHold(  # noqa: SLF001
                supervisor_path.parent
            )
            try:
                supervisor_hold = engineering._HeldFile(  # noqa: SLF001
                    supervisor_parent,
                    supervisor_path.name,
                    label="production process supervisor source",
                    limit=MAX_SEMANTIC_VALIDATOR_MODULE_BYTES,
                    allow_empty=False,
                )
                invocation_hold = engineering._HeldFile(  # noqa: SLF001
                    supervisor_parent,
                    "backend_publication_launcher_invocation_v3.py",
                    label="production supervisor invocation dependency",
                    limit=MAX_SEMANTIC_VALIDATOR_MODULE_BYTES,
                    allow_empty=False,
                )
            except BaseException:
                if supervisor_hold is not None:
                    supervisor_hold.close(suppress=True)
                supervisor_parent.close(suppress=True)
                raise
            directory_holds.append(supervisor_parent)
            file_holds.extend([supervisor_hold, invocation_hold])
        arm_descriptor = arm_hold.file_descriptor()
        states = engineering._expected_sets(evidence_names)  # noqa: SLF001
        observed_names = output_hold.names()

        if observed_names == states["prepared"]:
            if expected_durable_parent_artifact_pin is not None:
                raise BackendPublicationOutputProductionV3Error(
                    "production prepared transaction received a stale durable parent artifact pin"
                )
            if _allow_spawn is not True:
                raise BackendPublicationOutputProductionV3Error(
                    "production read-only validation cannot spawn a prepared arm"
                )
            fence = _fence_material(arm, arm_descriptor=arm_descriptor)
            fence_hold = engineering._create_new_held(  # noqa: SLF001
                output_hold,
                LAUNCH_FENCE_FILENAME,
                engineering._canonical_file_bytes(fence),  # noqa: SLF001
                label="production launch fence",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            file_holds.append(fence_hold)
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold, states["fenced"], label="production fenced transaction"
            )
            if _fault_hook is not None:
                _fault_hook("after_fence_commit")
            try:
                process_options: dict[str, int] = {}
                if os.name != "nt":
                    process_options = {
                        "_python_descriptor": python_hold.descriptor,
                        "_launcher_descriptor": launcher_hold.descriptor,
                        "_cwd_descriptor": project_hold.descriptor,
                        "_supervisor_descriptor": supervisor_hold.descriptor,
                        "_invocation_descriptor": invocation_hold.descriptor,
                    }
                process_run = run_backend_publication_process_v3(
                    command,
                    cwd=root_path,
                    **process_options,
                )
            except BackendPublicationProcessSupervisorV3Error as error:
                raise BackendPublicationOutputProductionV3Error(
                    f"production backend v3 process failed: {error}"
                ) from error
            process_observation = engineering._validate_process_observation(  # noqa: SLF001
                process_run.observation,
                stdout=process_run.stdout,
                stderr=process_run.stderr,
                command=command,
                cwd=root_path,
                process_contract=resolution["launcher_invocation"]["process_contract"],
            )
            if _fault_hook is not None:
                _fault_hook("after_process_success")
            arm_hold.verify()
            python_hold.verify()
            launcher_hold.verify()
            python_parent.verify()
            launcher_parent.verify()
            if supervisor_hold is not None and invocation_hold is not None:
                supervisor_hold.verify()
                invocation_hold.verify()
                assert supervisor_parent is not None
                supervisor_parent.verify()
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["fenced"] | set(evidence_names),
                label="production launcher-completed transaction",
            )
            evidence_holds = engineering._open_evidence(  # noqa: SLF001
                output_hold, evidence_names
            )
            file_holds.extend(evidence_holds)
            stdout_hold = engineering._create_new_held(  # noqa: SLF001
                output_hold,
                CAPTURE_STDOUT_FILENAME,
                process_run.stdout,
                label="stdout capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
            )
            stderr_hold = engineering._create_new_held(  # noqa: SLF001
                output_hold,
                CAPTURE_STDERR_FILENAME,
                process_run.stderr,
                label="stderr capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
            )
            file_holds.extend([stdout_hold, stderr_hold])
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["captured"],
                label="production captured transaction",
            )
            if _fault_hook is not None:
                _fault_hook("after_captures_commit")
            semantic_assessment = _semantic_assessment(
                arm=arm,
                arm_descriptor=arm_descriptor,
                evidence=evidence_holds,
                validator=semantic_evidence_validator,
                validator_identity_sha256=validator_identity,
            )
            result = _result_material(
                arm,
                arm_descriptor=arm_descriptor,
                fence_descriptor=fence_hold.file_descriptor(),
                fence=fence,
                stdout_descriptor=stdout_hold.file_descriptor(),
                stderr_descriptor=stderr_hold.file_descriptor(),
                process_observation=process_observation,
                evidence_descriptors=engineering._evidence_descriptors(  # noqa: SLF001
                    evidence_holds
                ),
                semantic_assessment=semantic_assessment,
            )
            result_hold = engineering._create_new_held(  # noqa: SLF001
                output_hold,
                LAUNCHER_RESULT_FILENAME,
                engineering._canonical_file_bytes(result),  # noqa: SLF001
                label="production launcher result",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            file_holds.append(result_hold)
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["result"],
                label="production result transaction",
            )
            if _fault_hook is not None:
                _fault_hook("after_result_commit")
        elif observed_names in {frozenset(states["result"]), frozenset(states["committed"])}:
            resume_state = (
                "committed" if OUTPUT_RECEIPT_FILENAME in observed_names else "result"
            )
            if expected_durable_parent_artifact_pin is None:
                raise BackendPublicationOutputProductionV3Error(
                    "production transaction is ambiguous without a durable parent artifact pin"
                )
            fence_hold = engineering._HeldFile(  # noqa: SLF001
                output_hold,
                LAUNCH_FENCE_FILENAME,
                label="production launch fence",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            stdout_hold = engineering._HeldFile(  # noqa: SLF001
                output_hold,
                CAPTURE_STDOUT_FILENAME,
                label="stdout capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
            )
            stderr_hold = engineering._HeldFile(  # noqa: SLF001
                output_hold,
                CAPTURE_STDERR_FILENAME,
                label="stderr capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
            )
            evidence_holds = engineering._open_evidence(  # noqa: SLF001
                output_hold, evidence_names
            )
            result_hold = engineering._HeldFile(  # noqa: SLF001
                output_hold,
                LAUNCHER_RESULT_FILENAME,
                label="production launcher result",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            file_holds.extend(
                [fence_hold, stdout_hold, stderr_hold, *evidence_holds, result_hold]
            )
            if resume_state == "committed":
                receipt_hold = engineering._HeldFile(  # noqa: SLF001
                    output_hold,
                    OUTPUT_RECEIPT_FILENAME,
                    label="production output receipt",
                    limit=MAX_CONTROL_JSON_BYTES,
                    allow_empty=False,
                )
                file_holds.append(receipt_hold)
            _validate_durable_parent_artifact_pin(
                expected_durable_parent_artifact_pin,
                expected_state=resume_state,
                held=result_hold if resume_state == "result" else receipt_hold,
            )
            fence = _validate_fence(
                engineering._load_control(  # noqa: SLF001
                    fence_hold, label="production launch fence"
                ),
                arm=arm,
                arm_descriptor=arm_descriptor,
            )
            semantic_assessment = _semantic_assessment(
                arm=arm,
                arm_descriptor=arm_descriptor,
                evidence=evidence_holds,
                validator=semantic_evidence_validator,
                validator_identity_sha256=validator_identity,
            )
            result = _validate_result_material(
                engineering._load_control(  # noqa: SLF001
                    result_hold, label="production launcher result"
                ),
                arm=arm,
                arm_descriptor=arm_descriptor,
                fence=fence,
                fence_descriptor=fence_hold.file_descriptor(),
                stdout=stdout_hold,
                stderr=stderr_hold,
                evidence=evidence_holds,
                command=command,
                cwd=root_path,
                process_contract=resolution["launcher_invocation"]["process_contract"],
                semantic_assessment=semantic_assessment,
            )
        else:
            allowed_partial = set().union(*states.values())
            if (
                observed_names <= allowed_partial
                and LAUNCH_FENCE_FILENAME in observed_names
            ):
                raise BackendPublicationOutputProductionV3Error(
                    "production transaction is ambiguous after its launch fence"
                )
            raise BackendPublicationOutputProductionV3Error(
                "production transaction namespace is invalid or contains extras"
            )

        if output_hold.names() == states["result"]:
            if _allow_finalize is not True:
                raise BackendPublicationOutputProductionV3Error(
                    "production read-only validation cannot finalize a result-only transaction"
                )
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["result"],
                label="production precommit result transaction",
            )
            for held in file_holds:
                held.verify()
            for held_directory in directory_holds:
                held_directory.verify()
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["result"],
                label="production terminal precommit result transaction",
            )
            receipt = _receipt_material(
                arm,
                arm_descriptor=arm_descriptor,
                fence_descriptor=fence_hold.file_descriptor(),
                fence=fence,
                stdout_descriptor=stdout_hold.file_descriptor(),
                stderr_descriptor=stderr_hold.file_descriptor(),
                result_descriptor=result_hold.file_descriptor(),
                result=result,
                evidence_descriptors=engineering._evidence_descriptors(  # noqa: SLF001
                    evidence_holds
                ),
                semantic_assessment=semantic_assessment,
            )
            receipt_payload = engineering._canonical_file_bytes(receipt)  # noqa: SLF001
            receipt_descriptor = {
                "path": OUTPUT_RECEIPT_FILENAME,
                "size_bytes": len(receipt_payload),
                "sha256": hashlib.sha256(receipt_payload).hexdigest(),
            }
            authority = _authority_material(
                arm,
                receipt_descriptor=receipt_descriptor,
                receipt=receipt,
            )
            receipt_hold = engineering._create_new_held(  # noqa: SLF001
                output_hold,
                OUTPUT_RECEIPT_FILENAME,
                receipt_payload,
                label="production output receipt",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            file_holds.append(receipt_hold)
            semantic_commit = True
            if _fault_hook is not None:
                _fault_hook("after_receipt_commit")
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["committed"],
                label="production committed transaction",
            )
            for held in file_holds:
                held.verify()
            for held_directory in directory_holds:
                held_directory.verify()
            engineering._assert_exact_namespace(  # noqa: SLF001
                output_hold,
                states["committed"],
                label="production terminal committed transaction",
            )
            return authority

        if receipt_hold is None:
            raise BackendPublicationOutputProductionV3Error(
                "production committed resume lost durable receipt custody"
            )
        receipt = _validate_receipt_material(
            engineering._load_control(  # noqa: SLF001
                receipt_hold, label="production output receipt"
            ),
            arm=arm,
            arm_descriptor=arm_descriptor,
            fence=fence,
            fence_descriptor=fence_hold.file_descriptor(),
            stdout=stdout_hold,
            stderr=stderr_hold,
            result=result,
            result_descriptor=result_hold.file_descriptor(),
            evidence=evidence_holds,
            semantic_assessment=semantic_assessment,
        )
        engineering._assert_exact_namespace(  # noqa: SLF001
            output_hold,
            states["committed"],
            label="production committed transaction",
        )
        for held in file_holds:
            held.verify()
        for held_directory in directory_holds:
            held_directory.verify()
        engineering._assert_exact_namespace(  # noqa: SLF001
            output_hold,
            states["committed"],
            label="production terminal committed transaction",
        )
        authority = _authority_material(
            arm,
            receipt_descriptor=receipt_hold.file_descriptor(),
            receipt=receipt,
        )
        semantic_commit = True
        return authority
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_primary = primary
        if cleanup_primary is None and semantic_commit:
            cleanup_primary = BackendPublicationOutputProductionV3Error(
                "postcommit production resource release is not attested"
            )
        try:
            engineering._close_holds(file_holds, primary=cleanup_primary)  # noqa: SLF001
        finally:
            for held_directory in reversed(directory_holds):
                try:
                    held_directory.close(suppress=cleanup_primary is not None)
                except BaseException as close_error:
                    if cleanup_primary is None:
                        raise close_error


def validate_backend_publication_production_transaction_v3(
    **kwargs: Any,
) -> dict[str, Any]:
    """Read-only validate a committed production transaction."""

    if any(
        name in kwargs for name in ("_allow_spawn", "_allow_finalize", "_fault_hook")
    ):
        raise BackendPublicationOutputProductionV3Error(
            "production read-only validation received unsafe private controls"
        )
    return run_or_resume_backend_publication_production_transaction_v3(
        **kwargs,
        _allow_spawn=False,
        _allow_finalize=False,
    )


__all__ = [
    "ARM_AUTHORITY_KIND",
    "BackendPublicationOutputProductionV3Error",
    "FENCE_KIND",
    "MAX_CONTROL_JSON_BYTES",
    "MAX_EVIDENCE_AGGREGATE_BYTES",
    "MAX_EVIDENCE_FILE_BYTES",
    "MAX_EVIDENCE_FILES",
    "MAX_TRANSACTION_NAMESPACE_ENTRIES",
    "PRODUCTION_ACCEPTANCE_CLAIM_FIELDS",
    "PRODUCTION_EXECUTION_SCOPE",
    "PRODUCTION_RUNTIME_BIND_MOUNT_KIND",
    "RECEIPT_AUTHORITY_KIND",
    "RECEIPT_KIND",
    "RESULT_KIND",
    "SEMANTIC_ASSESSMENT_KIND",
    "SEMANTIC_REQUEST_KIND",
    "SEMANTIC_VALIDATOR_IDENTITY_KIND",
    "prepare_backend_publication_production_transaction_v3",
    "build_production_runtime_bind_mount_contract_v3",
    "preflight_production_runtime_bind_mount_v3",
    "run_or_resume_backend_publication_production_transaction_v3",
    "semantic_evidence_validator_identity_v3",
    "validate_backend_publication_production_transaction_v3",
]
