#!/usr/bin/env python3
"""Pure ABI-v3 dispatch material for a parent-owned publication transaction.

This module validates and cross-binds declarative material only.  It never
reads a file, authorizes publication, attests executed bytes, or starts a
process.  The stable transaction call order is:

1. build and externally validate the dispatch resolution;
2. build and externally validate the arm contract;
3. obtain its unique bytes with ``canonical_backend_publication_arm_contract_bytes_v3``;
4. commit those bytes immutably and retain their raw-file SHA-256;
5. require the committed root/output/contract paths to equal ``runtime_inputs``;
6. call ``build_backend_publication_command_v3`` with every external pin;
7. pass the returned tuple unchanged to the bounded process supervisor.

The transaction layer owns physical descriptor rehashing, no-link custody,
fencing, result/receipt commits, and the comparison between semantic arm paths
and command paths.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from backend_publication_launcher_invocation_v3 import (
    INPUT_PROTOCOL_IDENTITY_SHA256,
    OUTPUT_PROTOCOL_IDENTITY_SHA256,
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)


SCHEMA_VERSION = 3
DISPATCH_RESOLUTION_KIND = "vast_backend_publication_dispatch_resolution_v3"
COORDINATE_KIND = "vast_backend_publication_coordinate_v3"
ARM_CONTRACT_KIND = "vast_backend_publication_arm_dispatch_contract_v3"
OUTPUT_PROTOCOL_KIND = "vast_backend_publication_launcher_output_protocol_v3"
EXECUTION_BINDING_KIND = "vast_full_publication_arm_execution_binding"

ARM_CONTRACT_FILENAME = "backend_publication_arm_contract.json"
LAUNCH_FENCE_FILENAME = "backend_publication_launch_fence_v3.json"
CAPTURE_STDOUT_FILENAME = "backend_publication_stdout_v3.bin"
CAPTURE_STDERR_FILENAME = "backend_publication_stderr_v3.bin"
LAUNCHER_RESULT_FILENAME = "backend_publication_launcher_result_v3.json"
OUTPUT_RECEIPT_FILENAME = "backend_publication_output_receipt_v3.json"
MAX_ARM_CONTRACT_BYTES = 1024 * 1024

SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS: tuple[int | float, ...] = (16.7, 33.3, 50, 100, 500)
SCENARIO_TO_TOPOLOGY = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_COORDINATE_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "deadline_ms",
})
_RESOLUTION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "coordinate", "coordinate_sha256",
    "backend_runtime_grant_sha256", "identity_artifact_binding_sha256",
    "cell_identity_sha256", "validation_record_sha256",
    "runtime_binding_identity_sha256", "python_executable",
    "publication_launcher", "launcher_invocation",
    "launcher_invocation_sha256", "input_protocol_identity_sha256",
    "output_protocol_identity_sha256", "publication_execution_authorized",
    "publication_ready", "executed_bytes_attested",
    "accepted_measurement_evidence_emitted", "resolution_sha256",
})
_EXECUTION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "run_identity_sha256", "sequence",
    "pair_id", "attempt", "arm_id",
})
_RUNTIME_INPUT_FIELDS = frozenset({
    "system", "scenario", "topology_kind", "codec", "policy",
    "deadline_ms", "dataset", "streams", "duration_s", "repeat_index",
    "base_seed", "run_seed", "run_id", "project_root", "output_dir",
    "arm_contract_path",
})
_PROTOCOL_FIELDS = frozenset({
    "schema_version", "artifact_kind", "input_protocol_identity_sha256",
    "output_protocol_identity_sha256", "launcher_evidence_files",
    "controller_owned_files", "parent_finalizer_owned_files",
    "reserved_files", "commit_order", "atomicity",
    "accepted_measurement_evidence_emitted",
    "publication_execution_authorized", "publication_ready",
    "executed_bytes_attested", "protocol_sha256",
})
_ARM_FIELDS = frozenset({
    "schema_version", "artifact_kind", "full_publication_execution_binding",
    "resource_capability_grant_sha256", "model_parity_grant_sha256",
    "model_parity_acceptance_binding_sha256",
    "backend_runtime_grant_sha256", "identity_artifact_binding_sha256",
    "dispatch_resolution", "runtime_inputs", "launcher_output_protocol",
    "publication_execution_authorized", "publication_ready",
    "executed_bytes_attested", "accepted_measurement_evidence_emitted",
    "contract_sha256",
})
_CONTROLLER_FILES = (ARM_CONTRACT_FILENAME,)
_FINALIZER_FILES = (
    LAUNCH_FENCE_FILENAME,
    CAPTURE_STDOUT_FILENAME,
    CAPTURE_STDERR_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
)
_RESERVED_FILES = tuple(sorted((*_CONTROLLER_FILES, *_FINALIZER_FILES)))
_WINDOWS_RESERVED_STEMS = frozenset({
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
})


class BackendPublicationDispatchV3Error(ValueError):
    """ABI-v3 dispatch material is ambiguous, unpinned, or crossbound wrongly."""


def _assert_exact_json_tree(value: Any, active: set[int] | None = None) -> None:
    """Reject Python values whose JSON encoding is lossy or ambiguous."""

    if active is None:
        active = set()
    value_type = type(value)
    if value is None or value_type in {str, bool, int}:
        return
    if value_type is float:
        if not math.isfinite(value):
            raise BackendPublicationDispatchV3Error(
                "backend publication v3 JSON contains a non-finite number"
            )
        return
    if value_type not in {dict, list}:
        raise BackendPublicationDispatchV3Error(
            "backend publication v3 material contains a non-JSON type"
        )
    identity = id(value)
    if identity in active:
        raise BackendPublicationDispatchV3Error(
            "backend publication v3 JSON contains a cycle"
        )
    active.add(identity)
    try:
        if value_type is dict:
            if any(type(key) is not str for key in value):
                raise BackendPublicationDispatchV3Error(
                    "backend publication v3 JSON object keys must be strings"
                )
            for item in value.values():
                _assert_exact_json_tree(item, active)
        else:
            for item in value:
                _assert_exact_json_tree(item, active)
    except RecursionError as error:
        raise BackendPublicationDispatchV3Error(
            "backend publication v3 JSON nesting is invalid"
        ) from error
    finally:
        active.remove(identity)


def _canonical_bytes(value: Any) -> bytes:
    _assert_exact_json_tree(value)
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendPublicationDispatchV3Error(
            "backend publication v3 material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: Any, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise BackendPublicationDispatchV3Error(f"{label} SHA-256 is invalid")
    return value


def _is_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _mapping_copy(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BackendPublicationDispatchV3Error(f"{label} must be a mapping")
    try:
        return copy.deepcopy(dict(value))
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendPublicationDispatchV3Error(
            f"{label} mapping is invalid"
        ) from error


def _plain_text(value: Any, *, label: str) -> str:
    if (
        type(value) is not str or not value or value != value.strip()
        or len(value) > 256 or any(ord(character) < 32 for character in value)
    ):
        raise BackendPublicationDispatchV3Error(f"{label} is invalid")
    return value


def _canonical_relative_descendant(value: Any, *, label: str) -> str:
    if type(value) is not str or not value or "\\" in value or "\0" in value:
        raise BackendPublicationDispatchV3Error(f"{label} path is invalid")
    try:
        value.encode("ascii")
    except UnicodeError as error:
        raise BackendPublicationDispatchV3Error(
            f"{label} path must be portable ASCII"
        ) from error
    relative = PurePosixPath(value)
    if (
        relative.is_absolute() or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BackendPublicationDispatchV3Error(
            f"{label} path is not a canonical relative descendant"
        )
    for part in relative.parts:
        stem = part.split(".", 1)[0].casefold()
        if (
            ":" in part or part.endswith((" ", "."))
            or stem in _WINDOWS_RESERVED_STEMS
        ):
            raise BackendPublicationDispatchV3Error(
                f"{label} path is not portable"
            )
    return value


def _direct_child_name(value: Any, *, label: str) -> str:
    name = _canonical_relative_descendant(value, label=label)
    if len(PurePosixPath(name).parts) != 1:
        raise BackendPublicationDispatchV3Error(
            f"{label} must be a canonical direct-child filename"
        )
    return name


def _descriptor(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        raise BackendPublicationDispatchV3Error(f"{label} descriptor fields drifted")
    descriptor = {
        "path": _canonical_relative_descendant(value.get("path"), label=label),
        "size_bytes": value.get("size_bytes"),
        "sha256": _sha256(value.get("sha256"), label=label),
    }
    if (
        type(descriptor["size_bytes"]) is not int
        or descriptor["size_bytes"] <= 0
    ):
        raise BackendPublicationDispatchV3Error(
            f"{label} descriptor size is invalid"
        )
    return descriptor


def _coordinate(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _COORDINATE_FIELDS:
        raise BackendPublicationDispatchV3Error(
            "backend publication v3 coordinate fields drifted"
        )
    deadline = value.get("deadline_ms")
    exact_deadline = next(
        (
            candidate for candidate in DEADLINES_MS
            if type(deadline) is type(candidate) and deadline == candidate
        ),
        None,
    )
    if (
        type(value.get("system")) is not str or value["system"] not in SYSTEMS
        or type(value.get("codec")) is not str or value["codec"] not in CODECS
        or type(value.get("topology_kind")) is not str
        or value["topology_kind"] not in TOPOLOGIES
        or type(value.get("policy")) is not str or value["policy"] not in POLICIES
        or exact_deadline is None
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication v3 coordinate is not canonical"
        )
    return {
        "system": value["system"],
        "codec": value["codec"],
        "topology_kind": value["topology_kind"],
        "policy": value["policy"],
        "deadline_ms": exact_deadline,
    }


def backend_publication_coordinate_sha256_v3(
    coordinate: Mapping[str, Any],
) -> str:
    """Return the closed v3 coordinate identity used by dispatch and arm input."""

    normalized = _coordinate(_mapping_copy(coordinate, label="coordinate"))
    return _canonical_sha({
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": COORDINATE_KIND,
        "coordinate": normalized,
    })


def _validate_resolution_internal(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _RESOLUTION_FIELDS:
        raise BackendPublicationDispatchV3Error(
            "backend publication dispatch resolution v3 fields drifted"
        )
    coordinate = _coordinate(value.get("coordinate"))
    python = _descriptor(value.get("python_executable"), label="Python executable")
    launcher = _descriptor(
        value.get("publication_launcher"), label="publication launcher"
    )
    if python["path"].casefold() == launcher["path"].casefold():
        raise BackendPublicationDispatchV3Error(
            "interpreter and launcher descriptors alias one path"
        )
    try:
        invocation = validate_publication_launcher_invocation_v3(
            value.get("launcher_invocation")
        )
    except Exception as error:
        raise BackendPublicationDispatchV3Error(
            "backend publication dispatch requires the exact frozen ABI v3"
        ) from error
    unsigned = {
        key: item for key, item in value.items() if key != "resolution_sha256"
    }
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or value.get("artifact_kind") != DISPATCH_RESOLUTION_KIND
        or value.get("coordinate_sha256")
        != backend_publication_coordinate_sha256_v3(coordinate)
        or any(not _is_sha256(value.get(field)) for field in (
            "backend_runtime_grant_sha256", "identity_artifact_binding_sha256",
            "cell_identity_sha256", "validation_record_sha256",
            "runtime_binding_identity_sha256", "launcher_invocation_sha256",
            "resolution_sha256",
        ))
        or value.get("launcher_invocation_sha256")
        != invocation["invocation_sha256"]
        or value.get("input_protocol_identity_sha256")
        != invocation["input_protocol_identity_sha256"]
        or value.get("output_protocol_identity_sha256")
        != invocation["output_protocol_identity_sha256"]
        or value.get("publication_execution_authorized") is not False
        or value.get("publication_ready") is not False
        or value.get("executed_bytes_attested") is not False
        or value.get("accepted_measurement_evidence_emitted") is not False
        or value.get("resolution_sha256") != _canonical_sha(unsigned)
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication dispatch resolution v3 is invalid"
        )
    return copy.deepcopy(value)


def build_backend_publication_dispatch_resolution_v3(
    *,
    coordinate: Mapping[str, Any],
    python_executable: Mapping[str, Any],
    publication_launcher: Mapping[str, Any],
    launcher_invocation: Mapping[str, Any],
    backend_runtime_grant_sha256: str,
    identity_artifact_binding_sha256: str,
    cell_identity_sha256: str,
    validation_record_sha256: str,
    runtime_binding_identity_sha256: str,
) -> dict[str, Any]:
    """Build one canonical resolution; this construction grants no authority.

    The descriptors and identity hashes must originate in a separately
    validated authority graph.  Call the public validator with those external
    expected values before a transaction materializes argv.
    """

    normalized_coordinate = _coordinate(
        _mapping_copy(coordinate, label="coordinate")
    )
    python = _descriptor(
        _mapping_copy(python_executable, label="Python executable"),
        label="Python executable",
    )
    launcher = _descriptor(
        _mapping_copy(publication_launcher, label="publication launcher"),
        label="publication launcher",
    )
    try:
        invocation = validate_publication_launcher_invocation_v3(
            _mapping_copy(launcher_invocation, label="launcher invocation")
        )
    except Exception as error:
        raise BackendPublicationDispatchV3Error(
            "backend publication dispatch requires the exact frozen ABI v3"
        ) from error
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": DISPATCH_RESOLUTION_KIND,
        "coordinate": normalized_coordinate,
        "coordinate_sha256": backend_publication_coordinate_sha256_v3(
            normalized_coordinate
        ),
        "backend_runtime_grant_sha256": _sha256(
            backend_runtime_grant_sha256, label="backend runtime grant"
        ),
        "identity_artifact_binding_sha256": _sha256(
            identity_artifact_binding_sha256, label="identity artifact binding"
        ),
        "cell_identity_sha256": _sha256(
            cell_identity_sha256, label="qualified cell identity"
        ),
        "validation_record_sha256": _sha256(
            validation_record_sha256, label="qualification validation record"
        ),
        "runtime_binding_identity_sha256": _sha256(
            runtime_binding_identity_sha256, label="runtime binding identity"
        ),
        "python_executable": python,
        "publication_launcher": launcher,
        "launcher_invocation": invocation,
        "launcher_invocation_sha256": invocation["invocation_sha256"],
        "input_protocol_identity_sha256": invocation[
            "input_protocol_identity_sha256"
        ],
        "output_protocol_identity_sha256": invocation[
            "output_protocol_identity_sha256"
        ],
        "publication_execution_authorized": False,
        "publication_ready": False,
        "executed_bytes_attested": False,
        "accepted_measurement_evidence_emitted": False,
    }
    value["resolution_sha256"] = _canonical_sha(value)
    return _validate_resolution_internal(value)


def validate_backend_publication_dispatch_resolution_v3(
    value: Any,
    *,
    expected_coordinate: Mapping[str, Any],
    expected_python_executable: Mapping[str, Any],
    expected_publication_launcher: Mapping[str, Any],
    expected_launcher_invocation_sha256: str,
    expected_backend_runtime_grant_sha256: str,
    expected_identity_artifact_binding_sha256: str,
    expected_cell_identity_sha256: str,
    expected_validation_record_sha256: str,
    expected_runtime_binding_identity_sha256: str,
) -> dict[str, Any]:
    """Validate a resolution against mandatory, caller-owned external pins."""

    checked = _validate_resolution_internal(value)
    expected = {
        "coordinate": _coordinate(
            _mapping_copy(expected_coordinate, label="expected coordinate")
        ),
        "python_executable": _descriptor(
            _mapping_copy(
                expected_python_executable, label="expected Python executable"
            ),
            label="expected Python executable",
        ),
        "publication_launcher": _descriptor(
            _mapping_copy(
                expected_publication_launcher,
                label="expected publication launcher",
            ),
            label="expected publication launcher",
        ),
        "launcher_invocation_sha256": _sha256(
            expected_launcher_invocation_sha256,
            label="expected launcher invocation",
        ),
        "backend_runtime_grant_sha256": _sha256(
            expected_backend_runtime_grant_sha256,
            label="expected backend runtime grant",
        ),
        "identity_artifact_binding_sha256": _sha256(
            expected_identity_artifact_binding_sha256,
            label="expected identity artifact binding",
        ),
        "cell_identity_sha256": _sha256(
            expected_cell_identity_sha256, label="expected qualified cell identity"
        ),
        "validation_record_sha256": _sha256(
            expected_validation_record_sha256,
            label="expected qualification validation record",
        ),
        "runtime_binding_identity_sha256": _sha256(
            expected_runtime_binding_identity_sha256,
            label="expected runtime binding identity",
        ),
    }
    if any(checked[field] != item for field, item in expected.items()):
        raise BackendPublicationDispatchV3Error(
            "backend publication dispatch resolution differs from external pins"
        )
    return copy.deepcopy(checked)


def _evidence_names(values: Iterable[Any]) -> list[str]:
    if isinstance(values, (str, bytes, bytearray)):
        raise BackendPublicationDispatchV3Error(
            "launcher evidence filenames must be an iterable of strings"
        )
    try:
        names = [
            _direct_child_name(value, label="launcher evidence")
            for value in values
        ]
    except TypeError as error:
        raise BackendPublicationDispatchV3Error(
            "launcher evidence filenames are invalid"
        ) from error
    folded = [name.casefold() for name in names]
    reserved = {name.casefold() for name in _RESERVED_FILES}
    if (
        not names or len(set(folded)) != len(names)
        or any(name in reserved for name in folded)
    ):
        raise BackendPublicationDispatchV3Error(
            "launcher evidence filenames collide or are empty"
        )
    return sorted(names)


def backend_publication_launcher_output_protocol_v3(
    launcher_evidence_files: Iterable[str],
) -> dict[str, Any]:
    """Build the closed child/controller/finalizer output ownership protocol."""

    evidence = _evidence_names(launcher_evidence_files)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": OUTPUT_PROTOCOL_KIND,
        "input_protocol_identity_sha256": INPUT_PROTOCOL_IDENTITY_SHA256,
        "output_protocol_identity_sha256": OUTPUT_PROTOCOL_IDENTITY_SHA256,
        "launcher_evidence_files": evidence,
        "controller_owned_files": list(_CONTROLLER_FILES),
        "parent_finalizer_owned_files": list(_FINALIZER_FILES),
        "reserved_files": list(_RESERVED_FILES),
        "commit_order": list(_FINALIZER_FILES),
        "atomicity": (
            "fence_before_spawn_then_captures_then_result_then_receipt_last_v3"
        ),
        "accepted_measurement_evidence_emitted": False,
        "publication_execution_authorized": False,
        "publication_ready": False,
        "executed_bytes_attested": False,
    }
    value["protocol_sha256"] = _canonical_sha(value)
    return value


def validate_backend_publication_launcher_output_protocol_v3(
    value: Any, *, expected_launcher_evidence_files: Iterable[str],
) -> dict[str, Any]:
    """Validate exact v3 ownership and a caller-pinned evidence filename set."""

    if type(value) is not dict or set(value) != _PROTOCOL_FIELDS:
        raise BackendPublicationDispatchV3Error(
            "backend publication launcher output protocol v3 fields drifted"
        )
    expected = backend_publication_launcher_output_protocol_v3(
        expected_launcher_evidence_files
    )
    if value != expected:
        raise BackendPublicationDispatchV3Error(
            "backend publication launcher output protocol v3 drifted"
        )
    return copy.deepcopy(expected)


def _execution_binding(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _EXECUTION_FIELDS:
        raise BackendPublicationDispatchV3Error(
            "full publication execution binding fields drifted"
        )
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("artifact_kind") != EXECUTION_BINDING_KIND
        or not _is_sha256(value.get("run_identity_sha256"))
        or type(value.get("sequence")) is not int or value["sequence"] < 0
        or type(value.get("attempt")) is not int or value["attempt"] < 1
    ):
        raise BackendPublicationDispatchV3Error(
            "full publication execution binding is invalid"
        )
    _plain_text(value.get("pair_id"), label="execution pair id")
    _plain_text(value.get("arm_id"), label="execution arm id")
    return copy.deepcopy(value)


def _raw_path_has_dot_segment(value: str) -> bool:
    return any(component in {".", ".."} for component in re.split(r"[\\/]", value))


def _canonical_absolute_path(value: Any, *, label: str) -> tuple[str, Path]:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise BackendPublicationDispatchV3Error(f"{label} path is invalid") from error
    if (
        type(raw) is not str or not raw or "\0" in raw
        or _raw_path_has_dot_segment(raw) or os.path.normpath(raw) != raw
        or raw.startswith(("\\\\", "//"))
    ):
        raise BackendPublicationDispatchV3Error(
            f"{label} path is not lexically canonical"
        )
    path = Path(raw)
    if not path.is_absolute():
        raise BackendPublicationDispatchV3Error(f"{label} path is not absolute")
    return raw, path


def _checked_path_binding(
    *, project_root: Any, output_dir: Any, arm_contract_path: Any,
) -> tuple[str, Path, str, Path, str, Path]:
    root_text, root = _canonical_absolute_path(project_root, label="project root")
    output_text, output = _canonical_absolute_path(output_dir, label="output directory")
    arm_text, arm = _canonical_absolute_path(
        arm_contract_path, label="arm contract"
    )
    try:
        relative = output.relative_to(root)
    except ValueError as error:
        raise BackendPublicationDispatchV3Error(
            "output directory escaped project root"
        ) from error
    if not relative.parts:
        raise BackendPublicationDispatchV3Error(
            "output directory must be a strict project-root descendant"
        )
    expected_arm = output / ARM_CONTRACT_FILENAME
    if os.path.normcase(str(arm)) != os.path.normcase(str(expected_arm)):
        raise BackendPublicationDispatchV3Error(
            "arm contract must be the fixed output direct child"
        )
    return root_text, root, output_text, output, arm_text, arm


def _runtime_inputs(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _RUNTIME_INPUT_FIELDS:
        raise BackendPublicationDispatchV3Error(
            "backend publication runtime input v3 fields drifted"
        )
    coordinate = _coordinate({field: value.get(field) for field in _COORDINATE_FIELDS})
    scenario = value.get("scenario")
    if (
        type(scenario) is not str
        or SCENARIO_TO_TOPOLOGY.get(scenario) != coordinate["topology_kind"]
        or type(value.get("dataset")) is not dict
        or type(value.get("streams")) is not int or value["streams"] <= 0
        or type(value.get("duration_s")) is not int or value["duration_s"] <= 0
        or type(value.get("repeat_index")) is not int or value["repeat_index"] < 0
        or type(value.get("base_seed")) is not int or value["base_seed"] < 0
        or type(value.get("run_seed")) is not int or value["run_seed"] < 0
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication runtime input v3 is invalid"
        )
    _plain_text(value.get("run_id"), label="runtime run id")
    _canonical_bytes(value["dataset"])
    root_text, _root, output_text, _output, arm_text, _arm = _checked_path_binding(
        project_root=value.get("project_root"),
        output_dir=value.get("output_dir"),
        arm_contract_path=value.get("arm_contract_path"),
    )
    return copy.deepcopy({
        **value,
        **coordinate,
        "project_root": root_text,
        "output_dir": output_text,
        "arm_contract_path": arm_text,
    })


def _validate_arm_internal(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _ARM_FIELDS:
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract v3 fields drifted"
        )
    dispatch = _validate_resolution_internal(value.get("dispatch_resolution"))
    execution = _execution_binding(value.get("full_publication_execution_binding"))
    runtime = _runtime_inputs(value.get("runtime_inputs"))
    protocol_value = value.get("launcher_output_protocol")
    if type(protocol_value) is not dict:
        raise BackendPublicationDispatchV3Error(
            "backend publication launcher output protocol v3 is missing"
        )
    protocol = validate_backend_publication_launcher_output_protocol_v3(
        protocol_value,
        expected_launcher_evidence_files=protocol_value.get(
            "launcher_evidence_files", []
        ),
    )
    runtime_coordinate = {
        field: runtime[field] for field in _COORDINATE_FIELDS
    }
    unsigned = {
        key: item for key, item in value.items() if key != "contract_sha256"
    }
    serialized_size = len(_canonical_bytes(value)) + 1
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != SCHEMA_VERSION
        or value.get("artifact_kind") != ARM_CONTRACT_KIND
        or any(not _is_sha256(value.get(field)) for field in (
            "resource_capability_grant_sha256", "model_parity_grant_sha256",
            "model_parity_acceptance_binding_sha256",
            "backend_runtime_grant_sha256", "identity_artifact_binding_sha256",
            "contract_sha256",
        ))
        or value.get("backend_runtime_grant_sha256")
        != dispatch["backend_runtime_grant_sha256"]
        or value.get("identity_artifact_binding_sha256")
        != dispatch["identity_artifact_binding_sha256"]
        or runtime_coordinate != dispatch["coordinate"]
        or protocol["input_protocol_identity_sha256"]
        != dispatch["input_protocol_identity_sha256"]
        or protocol["output_protocol_identity_sha256"]
        != dispatch["output_protocol_identity_sha256"]
        or value.get("publication_execution_authorized") is not False
        or value.get("publication_ready") is not False
        or value.get("executed_bytes_attested") is not False
        or value.get("accepted_measurement_evidence_emitted") is not False
        or value.get("contract_sha256") != _canonical_sha(unsigned)
        or serialized_size > MAX_ARM_CONTRACT_BYTES
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract v3 is invalid or crossbound wrongly"
        )
    return copy.deepcopy(value)


def build_backend_publication_arm_contract_v3(
    *,
    dispatch_resolution: Mapping[str, Any],
    full_publication_execution_binding: Mapping[str, Any],
    resource_capability_grant_sha256: str,
    model_parity_grant_sha256: str,
    model_parity_acceptance_binding_sha256: str,
    runtime_inputs: Mapping[str, Any],
    launcher_evidence_files: Iterable[str],
) -> dict[str, Any]:
    """Build the canonical v3 launcher input with closed output ownership.

    The returned contract remains non-authorizing.  Its canonical raw bytes and
    raw file SHA must be committed and pinned by the parent transaction.
    """

    dispatch = _validate_resolution_internal(_mapping_copy(
        dispatch_resolution, label="dispatch resolution"
    ))
    execution = _execution_binding(_mapping_copy(
        full_publication_execution_binding, label="execution binding"
    ))
    runtime = _runtime_inputs(_mapping_copy(
        runtime_inputs, label="runtime inputs"
    ))
    protocol = backend_publication_launcher_output_protocol_v3(
        launcher_evidence_files
    )
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARM_CONTRACT_KIND,
        "full_publication_execution_binding": execution,
        "resource_capability_grant_sha256": _sha256(
            resource_capability_grant_sha256, label="resource capability grant"
        ),
        "model_parity_grant_sha256": _sha256(
            model_parity_grant_sha256, label="model parity grant"
        ),
        "model_parity_acceptance_binding_sha256": _sha256(
            model_parity_acceptance_binding_sha256,
            label="model parity acceptance binding",
        ),
        "backend_runtime_grant_sha256": dispatch[
            "backend_runtime_grant_sha256"
        ],
        "identity_artifact_binding_sha256": dispatch[
            "identity_artifact_binding_sha256"
        ],
        "dispatch_resolution": dispatch,
        "runtime_inputs": runtime,
        "launcher_output_protocol": protocol,
        "publication_execution_authorized": False,
        "publication_ready": False,
        "executed_bytes_attested": False,
        "accepted_measurement_evidence_emitted": False,
    }
    value["contract_sha256"] = _canonical_sha(value)
    return _validate_arm_internal(value)


def validate_backend_publication_arm_contract_v3(
    value: Any,
    *,
    expected_dispatch_resolution_sha256: str,
    expected_full_publication_execution_binding: Mapping[str, Any],
    expected_resource_capability_grant_sha256: str,
    expected_model_parity_grant_sha256: str,
    expected_model_parity_acceptance_binding_sha256: str,
    expected_runtime_inputs: Mapping[str, Any],
    expected_launcher_evidence_files: Iterable[str],
) -> dict[str, Any]:
    """Validate arm semantics against caller-owned execution and grant pins."""

    checked = _validate_arm_internal(value)
    expected = {
        "dispatch_resolution_sha256": _sha256(
            expected_dispatch_resolution_sha256,
            label="expected dispatch resolution",
        ),
        "full_publication_execution_binding": _execution_binding(
            _mapping_copy(
                expected_full_publication_execution_binding,
                label="expected execution binding",
            )
        ),
        "resource_capability_grant_sha256": _sha256(
            expected_resource_capability_grant_sha256,
            label="expected resource capability grant",
        ),
        "model_parity_grant_sha256": _sha256(
            expected_model_parity_grant_sha256,
            label="expected model parity grant",
        ),
        "model_parity_acceptance_binding_sha256": _sha256(
            expected_model_parity_acceptance_binding_sha256,
            label="expected model parity acceptance binding",
        ),
        "runtime_inputs": _runtime_inputs(_mapping_copy(
            expected_runtime_inputs, label="expected runtime inputs"
        )),
        "launcher_output_protocol": (
            backend_publication_launcher_output_protocol_v3(
                expected_launcher_evidence_files
            )
        ),
    }
    if (
        checked["dispatch_resolution"]["resolution_sha256"]
        != expected["dispatch_resolution_sha256"]
        or checked["full_publication_execution_binding"]
        != expected["full_publication_execution_binding"]
        or checked["resource_capability_grant_sha256"]
        != expected["resource_capability_grant_sha256"]
        or checked["model_parity_grant_sha256"]
        != expected["model_parity_grant_sha256"]
        or checked["model_parity_acceptance_binding_sha256"]
        != expected["model_parity_acceptance_binding_sha256"]
        or checked["runtime_inputs"] != expected["runtime_inputs"]
        or checked["launcher_output_protocol"]
        != expected["launcher_output_protocol"]
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract differs from external pins"
        )
    return copy.deepcopy(checked)


def canonical_backend_publication_arm_contract_bytes_v3(value: Any) -> bytes:
    """Return the only accepted on-disk arm bytes: canonical ASCII JSON + LF."""

    checked = _validate_arm_internal(value)
    payload = _canonical_bytes(checked) + b"\n"
    if len(payload) > MAX_ARM_CONTRACT_BYTES:
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract v3 exceeds its byte bound"
        )
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BackendPublicationDispatchV3Error(
                "backend publication arm contract v3 has duplicate JSON keys"
            )
        value[key] = item
    return value


def parse_backend_publication_arm_contract_v3_bytes(
    payload: bytes, *, expected_file_sha256: str,
) -> dict[str, Any]:
    """Parse unique canonical bytes under a mandatory raw-file SHA-256 pin."""

    expected = _sha256(expected_file_sha256, label="arm contract raw file")
    if (
        type(payload) is not bytes or not payload
        or len(payload) > MAX_ARM_CONTRACT_BYTES
        or hashlib.sha256(payload).hexdigest() != expected
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract raw bytes or SHA-256 are invalid"
        )
    try:
        decoded = json.loads(
            payload.decode("ascii"), object_pairs_hook=_unique_object
        )
    except BackendPublicationDispatchV3Error:
        raise
    except (
        UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError,
    ) as error:
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract v3 JSON is invalid"
        ) from error
    checked = _validate_arm_internal(decoded)
    if payload != canonical_backend_publication_arm_contract_bytes_v3(checked):
        raise BackendPublicationDispatchV3Error(
            "backend publication arm contract v3 bytes are not canonical"
        )
    return copy.deepcopy(checked)


def build_backend_publication_command_v3(
    dispatch_resolution: Mapping[str, Any],
    *,
    expected_coordinate: Mapping[str, Any],
    expected_python_executable: Mapping[str, Any],
    expected_publication_launcher: Mapping[str, Any],
    expected_launcher_invocation_sha256: str,
    expected_backend_runtime_grant_sha256: str,
    expected_identity_artifact_binding_sha256: str,
    expected_cell_identity_sha256: str,
    expected_validation_record_sha256: str,
    expected_runtime_binding_identity_sha256: str,
    project_root: Path | str,
    arm_contract_path: Path | str,
    arm_contract_file_sha256: str,
    output_dir: Path | str,
) -> tuple[str, ...]:
    """Return exact immutable ABI-v3 argv after all external semantic pins.

    This function performs lexical path binding only.  The parent transaction
    remains responsible for physical no-link/no-reparse checks and executed-byte
    custody immediately before its shell-free supervisor starts the process.
    """

    checked = validate_backend_publication_dispatch_resolution_v3(
        dispatch_resolution,
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
    )
    root_text, root, output_text, _output, arm_text, _arm = _checked_path_binding(
        project_root=project_root,
        output_dir=output_dir,
        arm_contract_path=arm_contract_path,
    )
    file_sha = _sha256(
        arm_contract_file_sha256, label="arm contract raw file"
    )
    python_relative = PurePosixPath(checked["python_executable"]["path"])
    launcher_relative = PurePosixPath(checked["publication_launcher"]["path"])
    values = {
        "python_executable": str(root.joinpath(*python_relative.parts)),
        "launcher_path": str(root.joinpath(*launcher_relative.parts)),
        "project_root": root_text,
        "arm_contract_path": arm_text,
        "arm_contract_file_sha256": file_sha,
        "output_dir": output_text,
    }
    invocation = checked["launcher_invocation"]
    argv = tuple(
        values.get(token[1:-1], token)
        for token in invocation["argv_template"]
    )
    expected_declaration = publication_launcher_invocation_v3_contract()
    if (
        invocation != expected_declaration or len(argv) != 10
        or any(type(token) is not str or not token for token in argv)
    ):
        raise BackendPublicationDispatchV3Error(
            "backend publication command v3 does not match the frozen ABI"
        )
    return argv


__all__ = [
    "ARM_CONTRACT_FILENAME",
    "ARM_CONTRACT_KIND",
    "CAPTURE_STDERR_FILENAME",
    "CAPTURE_STDOUT_FILENAME",
    "COORDINATE_KIND",
    "DEADLINES_MS",
    "DISPATCH_RESOLUTION_KIND",
    "BackendPublicationDispatchV3Error",
    "INPUT_PROTOCOL_IDENTITY_SHA256",
    "LAUNCHER_RESULT_FILENAME",
    "LAUNCH_FENCE_FILENAME",
    "MAX_ARM_CONTRACT_BYTES",
    "OUTPUT_PROTOCOL_KIND",
    "OUTPUT_PROTOCOL_IDENTITY_SHA256",
    "OUTPUT_RECEIPT_FILENAME",
    "SCHEMA_VERSION",
    "backend_publication_coordinate_sha256_v3",
    "backend_publication_launcher_output_protocol_v3",
    "build_backend_publication_arm_contract_v3",
    "build_backend_publication_command_v3",
    "build_backend_publication_dispatch_resolution_v3",
    "canonical_backend_publication_arm_contract_bytes_v3",
    "parse_backend_publication_arm_contract_v3_bytes",
    "validate_backend_publication_arm_contract_v3",
    "validate_backend_publication_dispatch_resolution_v3",
    "validate_backend_publication_launcher_output_protocol_v3",
]
