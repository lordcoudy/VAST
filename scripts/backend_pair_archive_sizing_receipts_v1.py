#!/usr/bin/env python3
"""Post-Q4 physical pair archives and operator-neutral sizing receipts.

Exactly one qualification pair is accepted for each
system/codec/policy/deadline coordinate.  Each pair contains the two topology
arms and their production-v3 output-receipt authorities.  No full-run result,
estimate, or caller supplied archive size is accepted.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterator, Mapping, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - publication commits execute in WSL.
    fcntl = None  # type: ignore[assignment]

from backend_publication_dispatch_v3 import (
    parse_backend_publication_arm_contract_v3_bytes,
)
from backend_runtime_qualification_v4_persistence import (
    BackendRuntimeQualificationV4PersistenceError,
    _PhysicalRegistry,
    _atomic_immutable,
    _descriptor_for,
    _is_link,
    _output_directory,
    _path_in_root,
    _root,
    load_backend_runtime_qualification_v4_binding,
)
from publication_guardian_preprocessing_contract_v1 import (
    DirectoryFdCustodyV1,
    GuardianPreprocessingContractV1Error,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS: tuple[int | float, ...] = (16.7, 33.3, 50, 100, 500)
SCHEMA_VERSION = 1
INPUT_KIND = "vast_backend_pair_archive_sizing_input_v1"
RECEIPT_KIND = "vast_backend_pair_archive_sizing_receipt_v1"
INDEX_KIND = "vast_backend_pair_archive_sizing_index_v1"
AUTHORITY_ENVELOPE_KIND = (
    "vast_persisted_backend_production_output_receipt_authority_v1"
)
STATUS = "accepted_post_q4_pair_archive_sizing"
SCOPE = "backend_q4_qualification_pair_archive_sizing_only"
INDEX_FILENAME = "checkpoint_backend_pair_archive_sizing_index_v1.json"
_ARCHIVE_MAGIC = b"VAST-BACKEND-Q4-PAIR-ARCHIVE-V1\0"
_ARCHIVE_JOURNAL_ROOT = ".backend-pair-archive-streaming-v1"
_ARCHIVE_INTENT_NAME = "intent.json"
_ARCHIVE_STAGE_NAME = "payload.stage"
_ARCHIVE_CHUNK_SIZE = 1024 * 1024
_AT_FDCWD = -100
_AT_SYMLINK_FOLLOW = 0x400
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_CLAIMS = (
    "accepted_measurement_evidence", "publication_output_accepted",
    "publication_ready", "promotable", "semantic_evidence_validated",
    "external_pins_validated", "process_tree_quiescent",
)
_AUTHORITY_FIELDS = {
    "schema_version", "artifact_kind", "status", "execution_scope",
    "path", "size_bytes", "sha256", "content_sha256", "arm_contract",
    "launcher_result", "durable_process_journal_response", "evidence_files",
    "evidence_aggregate_sha256",
    "semantic_evidence_assessment", "semantic_evidence_assessment_sha256",
    "full_publication_execution_binding", "run_identity_sha256",
    "dispatch_resolution_sha256", *_CLAIMS, "authority_sha256",
}
_RECEIPT_FIELDS = {
    "schema_version", "artifact_kind", "status", "execution_scope",
    "arm_contract", "arm_contract_content_sha256", "launch_fence",
    "launch_fence_content_sha256", "stdout_capture", "stderr_capture",
    "launcher_result", "launcher_result_content_sha256",
    "durable_process_journal_response", "evidence_files",
    "evidence_aggregate_sha256", "semantic_evidence_assessment",
    "semantic_evidence_assessment_sha256",
    "full_publication_execution_binding", "run_identity_sha256",
    "dispatch_resolution_sha256", "cell_identity_sha256",
    "launcher_invocation_sha256", "backend_runtime_grant_sha256",
    "resource_capability_grant_sha256", "model_parity_grant_sha256",
    "model_parity_acceptance_binding_sha256",
    "identity_artifact_binding_sha256", *_CLAIMS, "receipt_sha256",
}
_ARM_SUMMARY_FIELDS = {
    "topology_kind", "output_receipt_authority",
    "output_receipt_authority_sha256", "production_output_receipt",
    "production_output_receipt_sha256", "arm_payload", "arm_contract_sha256",
    "cell_identity_sha256", "validation_record_sha256", "execution_pair_id",
    "execution_arm_id",
}


class BackendPairArchiveSizingReceiptsV1Error(RuntimeError):
    """Post-Q4 pair sizing input or physical archive closure is unsafe."""


def _fail(message: str) -> None:
    raise BackendPairArchiveSizingReceiptsV1Error(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            "pair sizing material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        _fail(f"{label} is not a SHA-256 identity")
    return value


def _relative(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        _fail(f"{label} path is invalid")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if (
        "\\" in value or ":" in value or "\0" in value or "//" in value
        or value.endswith("/") or posix.is_absolute() or windows.drive
        or windows.root or posix.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        _fail(f"{label} path is unsafe")
    return value


def _descriptor(value: Any, label: str, *, allow_empty: bool = False) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        _fail(f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    if type(size) is not int or size < 0 or (not allow_empty and size == 0):
        _fail(f"{label} descriptor size drifted")
    return {
        "path": _relative(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _canonical_object(payload: bytes, label: str, *, identity_field: str) -> dict[str, Any]:
    value = _decode_canonical_object(payload, label)
    if value.get(identity_field) != _canonical_sha({
        key: item for key, item in value.items() if key != identity_field
    }):
        _fail(f"{label} self-hash drifted")
    return value


def _decode_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        _fail(f"{label} is not canonical JSON with one trailing LF")
    try:
        value = json.loads(payload[:-1].decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"{label} is invalid JSON"
        ) from error
    if type(value) is not dict or payload != _canonical_bytes(value) + b"\n":
        _fail(f"{label} canonical bytes drifted")
    return value


def _joined_descriptor(
    parent: str, value: Any, label: str, *, allow_empty: bool = False,
) -> dict[str, Any]:
    embedded = _descriptor(value, label, allow_empty=allow_empty)
    if len(PurePosixPath(embedded["path"]).parts) != 1:
        _fail(f"{label} must be a direct transaction child")
    base = PurePosixPath(parent).parent
    return {**embedded, "path": (base / embedded["path"]).as_posix()}


def _coordinate(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "system", "codec", "policy", "deadline_ms"
    }:
        _fail("pair sizing coordinate fields drifted")
    deadline = value.get("deadline_ms")
    matches = [item for item in DEADLINES_MS if float(item) == float(deadline)] \
        if type(deadline) in {int, float} else []
    result = {
        "system": value.get("system"), "codec": value.get("codec"),
        "policy": value.get("policy"),
        "deadline_ms": matches[0] if len(matches) == 1 else None,
    }
    if (
        result["system"] not in SYSTEMS or result["codec"] not in CODECS
        or result["policy"] not in POLICIES or result["deadline_ms"] is None
    ):
        _fail("pair sizing coordinate is outside frozen Q4 coverage")
    return result


def _expected_coordinates() -> list[dict[str, Any]]:
    return [
        {
            "system": system, "codec": codec, "policy": policy,
            "deadline_ms": deadline,
        }
        for system in SYSTEMS for codec in CODECS for policy in POLICIES
        for deadline in DEADLINES_MS
    ]


def _pair_input(value: Any, *, expected: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "coordinate", "arms", "pair_identity_sha256"
    }:
        _fail("pair sizing input fields drifted")
    coordinate = _coordinate(value["coordinate"])
    if coordinate != dict(expected):
        _fail("pair sizing input order/coordinate drifted")
    arms = value.get("arms")
    if type(arms) is not dict or set(arms) != set(TOPOLOGIES):
        _fail("pair sizing input requires both topology arms")
    normalized_arms: dict[str, dict[str, Any]] = {}
    for topology in TOPOLOGIES:
        item = arms[topology]
        if type(item) is not dict or set(item) != {
            "output_receipt_authority", "arm_payload"
        }:
            _fail(f"pair sizing {topology} arm input fields drifted")
        normalized_arms[topology] = {
            "output_receipt_authority": _descriptor(
                item["output_receipt_authority"],
                f"pair sizing {topology} output receipt authority",
            ),
            "arm_payload": _descriptor(
                item["arm_payload"], f"pair sizing {topology} arm payload",
            ),
        }
    identity_material = {
        "coordinate": coordinate,
        "arms": normalized_arms,
    }
    if value.get("pair_identity_sha256") != _canonical_sha(identity_material):
        _fail("pair sizing input identity drifted")
    return {**identity_material, "pair_identity_sha256": value["pair_identity_sha256"]}


def _validate_input(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "q4_binding_index", "pairs", "coverage", "input_sha256",
    }
    if (
        type(value) is not dict or set(value) != fields
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != INPUT_KIND
        or value.get("status") != "persisted_post_q4_pair_sizing_input"
        or value.get("qualification_scope") != SCOPE
        or value.get("coverage") != {
            "pair_count": 280, "topology_arm_count": 560,
            "arms_per_pair": 2,
        }
    ):
        _fail("pair sizing input header/coverage drifted")
    q4 = _descriptor(value.get("q4_binding_index"), "pair sizing Q4 binding")
    pairs = value.get("pairs")
    expected = _expected_coordinates()
    if type(pairs) is not list or len(pairs) != len(expected):
        _fail("pair sizing input requires exactly 280 qualification pairs")
    normalized = [
        _pair_input(item, expected=expected[position])
        for position, item in enumerate(pairs)
    ]
    material = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": INPUT_KIND,
        "status": "persisted_post_q4_pair_sizing_input",
        "qualification_scope": SCOPE,
        "q4_binding_index": q4,
        "pairs": normalized,
        "coverage": {
            "pair_count": 280, "topology_arm_count": 560,
            "arms_per_pair": 2,
        },
    }
    if value.get("input_sha256") != _canonical_sha(material):
        _fail("pair sizing input self-hash drifted")
    material["input_sha256"] = value["input_sha256"]
    return material


def build_backend_pair_archive_sizing_input_v1(
    *, q4_binding_index: Mapping[str, Any],
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the pure 280-pair input; this function grants no trust."""
    if isinstance(pairs, (str, bytes)) or not isinstance(pairs, Sequence):
        _fail("pair sizing pairs are invalid")
    expected = _expected_coordinates()
    if len(pairs) != len(expected):
        _fail("pair sizing input requires exactly 280 qualification pairs")
    normalized_pairs: list[dict[str, Any]] = []
    for position, raw in enumerate(pairs):
        if type(raw) is not dict or set(raw) != {"coordinate", "arms"}:
            _fail(f"pair sizing source pair[{position}] fields drifted")
        coordinate = _coordinate(raw["coordinate"])
        if coordinate != expected[position]:
            _fail("pair sizing source pair order/coordinate drifted")
        arms = raw["arms"]
        if type(arms) is not dict or set(arms) != set(TOPOLOGIES):
            _fail("pair sizing source requires exactly two topology arms")
        normalized_arms: dict[str, dict[str, Any]] = {}
        for topology in TOPOLOGIES:
            arm = arms[topology]
            if type(arm) is not dict or set(arm) != {
                "output_receipt_authority", "arm_payload"
            }:
                _fail(f"pair sizing source {topology} arm fields drifted")
            normalized_arms[topology] = {
                "output_receipt_authority": _descriptor(
                    arm["output_receipt_authority"],
                    f"pair sizing source {topology} authority",
                ),
                "arm_payload": _descriptor(
                    arm["arm_payload"],
                    f"pair sizing source {topology} arm payload",
                ),
            }
        item: dict[str, Any] = {
            "coordinate": coordinate, "arms": normalized_arms,
        }
        item["pair_identity_sha256"] = _canonical_sha(item)
        normalized_pairs.append(item)
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": INPUT_KIND,
        "status": "persisted_post_q4_pair_sizing_input",
        "qualification_scope": SCOPE,
        "q4_binding_index": _descriptor(
            dict(q4_binding_index), "pair sizing Q4 binding",
        ),
        "pairs": normalized_pairs,
        "coverage": {
            "pair_count": 280, "topology_arm_count": 560,
            "arms_per_pair": 2,
        },
    }
    material["input_sha256"] = _canonical_sha(material)
    return _validate_input(material)


def _read_json(
    registry: _PhysicalRegistry, descriptor: Mapping[str, Any], label: str,
    *, identity_field: str,
) -> tuple[dict[str, Any], bytes]:
    try:
        payload = registry.read(descriptor, label)
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    return _canonical_object(payload, label, identity_field=identity_field), payload


def _accepted_claims(value: Mapping[str, Any], label: str) -> None:
    if any(value.get(field) is not True for field in _CLAIMS):
        _fail(f"{label} production acceptance claims are incomplete")


def _evidence_aggregate(descriptors: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        b"VAST:backend-publication-evidence-set:v3\0"
        + _canonical_bytes([dict(item) for item in descriptors])
    ).hexdigest()


def persist_backend_production_output_receipt_authority_v1(
    *, project_root: Path | str, transaction_dir: Path | str,
    authority: Mapping[str, Any], output_path: Path | str,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Persist a returned live authority without mutating transaction namespace."""
    try:
        root = _root(project_root)
        transaction = _path_in_root(root, transaction_dir, "production transaction")
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    if not transaction.is_dir():
        _fail("production transaction path is not a directory")
    cursor = root
    for part in transaction.relative_to(root).parts:
        cursor /= part
        if _is_link(cursor):
            _fail("production transaction path contains a link/reparse point")
    value = copy.deepcopy(dict(authority))
    if (
        set(value) != _AUTHORITY_FIELDS
        or value.get("schema_version") != 4
        or value.get("artifact_kind")
        != "vast_backend_publication_production_output_receipt_authority_v4"
        or value.get("status") != "accepted_publishable_backend_output"
        or value.get("execution_scope") != "full_publication_measurement_v3"
        or value.get("authority_sha256") != _canonical_sha({
            key: item for key, item in value.items()
            if key != "authority_sha256"
        })
    ):
        _fail("production output receipt authority cannot be persisted")
    _accepted_claims(value, "production output receipt authority")
    receipt = _joined_descriptor(
        (transaction / "authority-base.json").relative_to(root).as_posix(),
        {field: value[field] for field in _DESCRIPTOR_FIELDS},
        "production output receipt",
    )
    try:
        _PhysicalRegistry(root).read(receipt, "production output receipt")
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    requested = Path(output_path)
    candidate = requested if requested.is_absolute() else root / requested
    if candidate.name != requested.name or candidate.suffix.lower() != ".json":
        _fail("persisted production authority output filename is invalid")
    try:
        parent = _output_directory(root, candidate.parent)
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    final = parent / candidate.name
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": AUTHORITY_ENVELOPE_KIND,
        "transaction_directory": transaction.relative_to(root).as_posix(),
        "authority": value,
        "authority_sha256": value["authority_sha256"],
    }
    envelope["envelope_sha256"] = _canonical_sha(envelope)
    try:
        _atomic_immutable(
            root,
            final,
            envelope,
            after_publish_step=after_publish_step,
        )
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    return _descriptor_for(root, final)


def _validate_arm_authority(
    *, registry: _PhysicalRegistry, authority_descriptor: Mapping[str, Any],
    arm_payload_descriptor: Mapping[str, Any], coordinate: Mapping[str, Any],
    topology: str, q4_system: Mapping[str, Any],
) -> dict[str, Any]:
    authority_record = _descriptor(
        authority_descriptor, f"{topology} output receipt authority",
    )
    try:
        authority_payload = registry.read(
            authority_record, f"{topology} output receipt authority",
        )
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    persisted = _decode_canonical_object(
        authority_payload, f"{topology} output receipt authority",
    )
    if persisted.get("artifact_kind") == AUTHORITY_ENVELOPE_KIND:
        if (
            set(persisted) != {
                "schema_version", "artifact_kind", "transaction_directory",
                "authority", "authority_sha256", "envelope_sha256",
            }
            or persisted.get("schema_version") != SCHEMA_VERSION
            or persisted.get("envelope_sha256") != _canonical_sha({
                key: item for key, item in persisted.items()
                if key != "envelope_sha256"
            })
        ):
            _fail(f"{topology} persisted authority envelope drifted")
        authority = persisted.get("authority")
        transaction_directory = _relative(
            persisted.get("transaction_directory"),
            f"{topology} persisted authority transaction directory",
        )
        if (
            type(authority) is not dict
            or persisted.get("authority_sha256")
            != authority.get("authority_sha256")
        ):
            _fail(f"{topology} persisted authority content binding drifted")
        receipt_parent = f"{transaction_directory}/authority-base.json"
    else:
        authority = persisted
        receipt_parent = authority_record["path"]
    if authority.get("authority_sha256") != _canonical_sha({
        key: item for key, item in authority.items()
        if key != "authority_sha256"
    }):
        _fail(f"{topology} output receipt authority self-hash drifted")
    if (
        set(authority) != _AUTHORITY_FIELDS
        or authority.get("schema_version") != 4
        or authority.get("artifact_kind")
        != "vast_backend_publication_production_output_receipt_authority_v4"
        or authority.get("status") != "accepted_publishable_backend_output"
        or authority.get("execution_scope") != "full_publication_measurement_v3"
    ):
        _fail(f"{topology} output receipt authority header drifted")
    _accepted_claims(authority, f"{topology} output receipt authority")

    receipt_descriptor = _joined_descriptor(
        receipt_parent,
        {field: authority[field] for field in _DESCRIPTOR_FIELDS},
        f"{topology} production output receipt",
    )
    receipt, _ = _read_json(
        registry, receipt_descriptor, f"{topology} production output receipt",
        identity_field="receipt_sha256",
    )
    if (
        set(receipt) != _RECEIPT_FIELDS
        or receipt.get("schema_version") != 4
        or receipt.get("artifact_kind")
        != "vast_backend_publication_production_output_receipt_v4"
        or receipt.get("status") != "committed_publishable_launcher_output"
        or receipt.get("execution_scope") != "full_publication_measurement_v3"
        or authority.get("content_sha256") != receipt.get("receipt_sha256")
    ):
        _fail(f"{topology} production output receipt header/binding drifted")
    _accepted_claims(receipt, f"{topology} production output receipt")
    mirrored = (
        "arm_contract", "launcher_result", "durable_process_journal_response",
        "evidence_files",
        "evidence_aggregate_sha256", "semantic_evidence_assessment",
        "semantic_evidence_assessment_sha256",
        "full_publication_execution_binding", "run_identity_sha256",
        "dispatch_resolution_sha256", *_CLAIMS,
    )
    if any(authority.get(field) != receipt.get(field) for field in mirrored):
        _fail(f"{topology} authority/output receipt cross-binding drifted")

    arm_descriptor = _joined_descriptor(
        receipt_descriptor["path"], receipt.get("arm_contract"),
        f"{topology} arm payload",
    )
    expected_arm = _descriptor(
        arm_payload_descriptor, f"{topology} declared arm payload",
    )
    if arm_descriptor != expected_arm:
        _fail(f"{topology} exact arm payload descriptor drifted")
    try:
        arm_payload = registry.read(arm_descriptor, f"{topology} arm payload")
        arm = parse_backend_publication_arm_contract_v3_bytes(
            arm_payload, expected_file_sha256=arm_descriptor["sha256"],
        )
    except Exception as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"{topology} arm payload rejected: {error}"
        ) from error
    dispatch = arm["dispatch_resolution"]
    observed_coordinate = dispatch["coordinate"]
    expected_coordinate = {
        **dict(coordinate), "topology_kind": topology,
    }
    if observed_coordinate != expected_coordinate:
        _fail(f"{topology} arm coordinate drifted")
    runtime_inputs = arm["runtime_inputs"]
    execution = arm["full_publication_execution_binding"]
    if runtime_inputs.get("repeat_index") != 0:
        _fail(f"{topology} arm is not the single post-Q4 qualification run")
    if (
        receipt.get("arm_contract_content_sha256") != arm["contract_sha256"]
        or receipt.get("full_publication_execution_binding") != execution
        or receipt.get("run_identity_sha256") != execution["run_identity_sha256"]
        or receipt.get("dispatch_resolution_sha256")
        != dispatch["resolution_sha256"]
        or receipt.get("cell_identity_sha256")
        != dispatch["cell_identity_sha256"]
        or receipt.get("launcher_invocation_sha256")
        != dispatch["launcher_invocation_sha256"]
        or receipt.get("backend_runtime_grant_sha256")
        != arm["backend_runtime_grant_sha256"]
        or receipt.get("identity_artifact_binding_sha256")
        != arm["identity_artifact_binding_sha256"]
    ):
        _fail(f"{topology} arm/receipt execution binding drifted")
    q4_cells = q4_system.get("qualified_cells")
    matches = [
        cell for cell in q4_cells if all(
            cell.get(field) == expected_coordinate[field]
            for field in (
                "system", "codec", "topology_kind", "policy", "deadline_ms"
            )
        )
    ] if type(q4_cells) is list else []
    if (
        len(matches) != 1
        or matches[0].get("cell_identity_sha256")
        != dispatch["cell_identity_sha256"]
        or matches[0].get("validation_record_sha256")
        != dispatch["validation_record_sha256"]
        or q4_system.get("runtime_binding_identity_sha256")
        != dispatch["runtime_binding_identity_sha256"]
        or matches[0].get("launcher_invocation_sha256")
        != dispatch["launcher_invocation_sha256"]
    ):
        _fail(f"{topology} arm is not bound to exact authenticated Q4 cell")

    semantic = receipt.get("semantic_evidence_assessment")
    if (
        type(semantic) is not dict
        or semantic.get("assessment_sha256")
        != _canonical_sha({
            key: item for key, item in semantic.items()
            if key != "assessment_sha256"
        })
        or semantic.get("assessment_sha256")
        != receipt.get("semantic_evidence_assessment_sha256")
        or semantic.get("status") != "accepted"
        or semantic.get("accepted_measurement_evidence") is not True
        or semantic.get("semantic_evidence_validated") is not True
    ):
        _fail(f"{topology} semantic evidence assessment drifted")
    evidence = receipt.get("evidence_files")
    if (
        type(evidence) is not list or not evidence
        or evidence != sorted(evidence, key=lambda item: item.get("path", ""))
        or receipt.get("evidence_aggregate_sha256") != _evidence_aggregate(evidence)
    ):
        _fail(f"{topology} evidence descriptor set drifted")

    closure: dict[str, dict[str, Any]] = {
        authority_record["path"]: authority_record,
        receipt_descriptor["path"]: receipt_descriptor,
        arm_descriptor["path"]: arm_descriptor,
    }
    for role, embedded, allow_empty in (
        ("launch fence", receipt["launch_fence"], False),
        ("stdout capture", receipt["stdout_capture"], True),
        ("stderr capture", receipt["stderr_capture"], True),
        ("launcher result", receipt["launcher_result"], False),
    ):
        descriptor = _joined_descriptor(
            receipt_descriptor["path"], embedded, f"{topology} {role}",
            allow_empty=allow_empty,
        )
        registry.read(descriptor, f"{topology} {role}")
        closure[descriptor["path"]] = descriptor
    for position, embedded in enumerate(evidence):
        descriptor = _joined_descriptor(
            receipt_descriptor["path"], embedded,
            f"{topology} evidence[{position}]",
        )
        registry.read(descriptor, f"{topology} evidence[{position}]")
        closure[descriptor["path"]] = descriptor
    return {
        "topology_kind": topology,
        "output_receipt_authority": authority_record,
        "output_receipt_authority_sha256": authority["authority_sha256"],
        "production_output_receipt": receipt_descriptor,
        "production_output_receipt_sha256": receipt["receipt_sha256"],
        "arm_payload": arm_descriptor,
        "arm_contract_sha256": arm["contract_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "validation_record_sha256": dispatch["validation_record_sha256"],
        "execution_pair_id": execution["pair_id"],
        "execution_arm_id": execution["arm_id"],
        "archive_entries": [closure[path] for path in sorted(closure)],
    }


def _write_all(handle: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(handle, view)
        if written <= 0:
            _fail("pair archive write made no progress")
        view = view[written:]


def _archive_manifest(
    *, coordinate: Mapping[str, Any], pair_identity_sha256: str,
    arms: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for arm in arms:
        topology = str(arm["topology_kind"])
        for descriptor in arm["archive_entries"]:
            entries.append({
                "topology_kind": topology,
                "archive_path": f"{topology}/{descriptor['path']}",
                "source": copy.deepcopy(descriptor),
            })
    entries.sort(key=lambda item: item["archive_path"])
    paths = [item["archive_path"] for item in entries]
    if len(paths) != len(set(paths)):
        _fail("pair archive namespace contains duplicate paths")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_backend_q4_pair_archive_v1",
        "qualification_scope": SCOPE,
        "coordinate": copy.deepcopy(dict(coordinate)),
        "pair_identity_sha256": _sha(
            pair_identity_sha256, "pair archive identity",
        ),
        "entries": entries,
    }
    value["manifest_sha256"] = _canonical_sha(value)
    return value


def _archive_filename(coordinate: Mapping[str, Any]) -> str:
    deadline = format(float(coordinate["deadline_ms"]), "g").replace(".", "p")
    return (
        f"checkpoint_backend_q4_pair_{coordinate['system']}_{coordinate['codec']}_"
        f"{coordinate['policy']}_d{deadline}.vastpair"
    )


def _receipt_filename(coordinate: Mapping[str, Any]) -> str:
    return _archive_filename(coordinate).replace(
        ".vastpair", "_sizing_receipt_v1.json"
    )


def _archive_directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(getattr(info, "st_uid", 0)), int(getattr(info, "st_gid", 0)),
    )


def _archive_file_snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(info.st_nlink), int(info.st_size), int(info.st_mtime_ns),
        int(info.st_ctime_ns), int(getattr(info, "st_uid", 0)),
        int(getattr(info, "st_gid", 0)),
    )


def _archive_stat_optional(
    directory: DirectoryFdCustodyV1, name: str,
) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory.directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _require_archive_transaction_entries(
    transaction: DirectoryFdCustodyV1,
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    transaction.verify()
    entries = frozenset(os.listdir(transaction.directory_fd))
    if entries != expected:
        _fail(f"{label} transaction entry set drifted")
    transaction.verify()


def _archive_chunks(
    manifest: Mapping[str, Any], registry: _PhysicalRegistry,
) -> Iterator[bytes]:
    manifest_payload = _canonical_bytes(dict(manifest))
    yield _ARCHIVE_MAGIC
    yield len(manifest_payload).to_bytes(8, "big")
    yield manifest_payload
    for item in manifest["entries"]:
        source = item["source"]
        yield int(source["size_bytes"]).to_bytes(8, "big")
        try:
            yield from registry.iter_read(
                source,
                f"pair archive source {item['archive_path']}",
                chunk_size=_ARCHIVE_CHUNK_SIZE,
            )
        except BackendRuntimeQualificationV4PersistenceError as error:
            raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error


def _expected_archive_descriptor(
    *, root: Path, final: Path, manifest: Mapping[str, Any],
    registry: _PhysicalRegistry,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    for chunk in _archive_chunks(manifest, registry):
        digest.update(chunk)
        size += len(chunk)
    return {
        "path": final.relative_to(root).as_posix(),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def _archive_intent(
    *, descriptor: Mapping[str, Any], manifest_sha256: str,
) -> tuple[str, dict[str, Any]]:
    transaction_key = hashlib.sha256(
        b"VAST:backend-pair-archive-streaming-transaction:v1\0"
        + _canonical_bytes({
            "target": dict(descriptor),
            "manifest_sha256": manifest_sha256,
            "mode": "0444",
        })
    ).hexdigest()
    transaction = f"{_ARCHIVE_JOURNAL_ROOT}/txn-{transaction_key}"
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_backend_pair_archive_streaming_intent_v1",
        "transaction_key": transaction_key,
        "target": copy.deepcopy(dict(descriptor)),
        "manifest_sha256": manifest_sha256,
        "stage_path": f"{transaction}/{_ARCHIVE_STAGE_NAME}",
        "committed_mode": "0444",
    }
    value["intent_sha256"] = _canonical_sha(value)
    return transaction, value


def _verify_archive_named(
    directory: DirectoryFdCustodyV1,
    name: str,
    expected: Mapping[str, Any],
    *,
    label: str,
    allowed_links: frozenset[int],
    mode_enforced: bool,
) -> tuple[int, int]:
    descriptor = -1
    try:
        directory.verify()
        named_before = os.stat(
            name, dir_fd=directory.directory_fd, follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(named_before.st_mode)
            or stat.S_ISLNK(named_before.st_mode)
            or int(named_before.st_nlink) not in allowed_links
            or int(named_before.st_size) != expected["size_bytes"]
            or (
                mode_enforced
                and stat.S_IMODE(named_before.st_mode) != 0o444
            )
        ):
            _fail(f"{label} physical identity/mode/size drifted")
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_NONBLOCK", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=directory.directory_fd,
        )
        opened = os.fstat(descriptor)
        if _archive_file_snapshot(named_before) != _archive_file_snapshot(opened):
            _fail(f"{label} identity changed while opening")
        digest = hashlib.sha256()
        observed = 0
        while True:
            chunk = os.read(descriptor, _ARCHIVE_CHUNK_SIZE)
            if not chunk:
                break
            observed += len(chunk)
            if observed > expected["size_bytes"]:
                _fail(f"{label} exceeded expected size")
            digest.update(chunk)
        os.fsync(descriptor)
        opened_after = os.fstat(descriptor)
        named_after = os.stat(
            name, dir_fd=directory.directory_fd, follow_symlinks=False,
        )
        if (
            observed != expected["size_bytes"]
            or digest.hexdigest() != expected["sha256"]
            or _archive_file_snapshot(opened)
            != _archive_file_snapshot(opened_after)
            or _archive_file_snapshot(opened_after)
            != _archive_file_snapshot(named_after)
        ):
            _fail(f"{label} bytes or stable identity drifted")
        directory.verify()
        return int(opened_after.st_dev), int(opened_after.st_ino)
    except BackendPairArchiveSizingReceiptsV1Error:
        raise
    except OSError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"{label} physical verification failed: {error}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _link_open_archive_noreplace(
    source_fd: int, destination_fd: int, destination_name: str,
) -> None:
    """Hard-link the held source inode, never a later same-name replacement."""

    libc = ctypes.CDLL(None, use_errno=True)
    linkat = libc.linkat
    linkat.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_int,
    ]
    linkat.restype = ctypes.c_int
    source = f"/proc/self/fd/{source_fd}".encode("ascii")
    ctypes.set_errno(0)
    result = int(linkat(
        _AT_FDCWD,
        ctypes.c_char_p(source),
        destination_fd,
        ctypes.c_char_p(os.fsencode(destination_name)),
        _AT_SYMLINK_FOLLOW,
    ))
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number))
    raise OSError(error_number, os.strerror(error_number))


def _commit_archive(
    *, root: Path, output: Path, coordinate: Mapping[str, Any],
    pair_identity_sha256: str, arms: Sequence[Mapping[str, Any]],
    registry: _PhysicalRegistry,
    after_publish_step: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], str]:
    """Stream one archive through a deterministic parent-owned WAL."""

    if os.name != "posix" or fcntl is None:
        _fail("pair archive streaming commit requires WSL/POSIX custody")
    manifest = _archive_manifest(
        coordinate=coordinate, pair_identity_sha256=pair_identity_sha256,
        arms=arms,
    )
    final = output / _archive_filename(coordinate)
    expected = _expected_archive_descriptor(
        root=root, final=final, manifest=manifest, registry=registry,
    )
    transaction_relative, intent = _archive_intent(
        descriptor=expected,
        manifest_sha256=manifest["manifest_sha256"],
    )
    intent_payload = _canonical_bytes(intent) + b"\n"
    intent_path = root / transaction_relative / _ARCHIVE_INTENT_NAME
    intent_fd = -1
    stage_fd = -1

    def fault(
        step: str,
        transaction: DirectoryFdCustodyV1,
        destination: DirectoryFdCustodyV1,
    ) -> None:
        transaction.verify()
        destination.verify()
        if after_publish_step is not None:
            after_publish_step(step)
        transaction.verify()
        destination.verify()

    try:
        with PhysicalRootCustodyV1.open(
            root, label="pair archive streaming project_root",
        ) as physical:
            output_relative = output.relative_to(root).as_posix()
            if output != root:
                physical.ensure_directory(
                    output_relative, label="pair archive output directory",
                )
                _output_mode, output_identity = physical.stat_directory_identity(
                    output_relative, label="pair archive output directory",
                )
            else:
                output_identity = None
            physical.ensure_directory(
                _ARCHIVE_JOURNAL_ROOT,
                label="pair archive journal root",
            )
            journal_mode, _journal_identity = physical.stat_directory_identity(
                _ARCHIVE_JOURNAL_ROOT,
                label="pair archive journal root",
            )
            if physical.permission_modes_enforced and journal_mode != 0o700:
                _fail("pair archive journal root mode drifted")
            physical.ensure_directory(
                transaction_relative,
                label="pair archive transaction directory",
            )
            transaction_mode, transaction_identity = (
                physical.stat_directory_identity(
                    transaction_relative,
                    label="pair archive transaction directory",
                )
            )
            if physical.permission_modes_enforced and transaction_mode != 0o700:
                _fail("pair archive transaction directory mode drifted")
            try:
                intent_descriptor, intent_identity, _intent_disposition = (
                    _atomic_immutable(root, intent_path, intent)
                )
            except BackendRuntimeQualificationV4PersistenceError as error:
                raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
            if intent_descriptor != {
                "path": intent_path.relative_to(root).as_posix(),
                "size_bytes": len(intent_payload),
                "sha256": hashlib.sha256(intent_payload).hexdigest(),
            }:
                _fail("pair archive intent descriptor drifted")

            with DirectoryFdCustodyV1.open_existing(
                output, label="pair archive output directory",
            ) as destination, DirectoryFdCustodyV1.open_existing(
                root / transaction_relative,
                label="pair archive transaction directory",
            ) as transaction:
                if (
                    output_identity is not None
                    and _archive_directory_identity(
                        os.fstat(destination.directory_fd)
                    ) != output_identity
                ):
                    _fail("pair archive output directory was rebound")
                if _archive_directory_identity(
                    os.fstat(transaction.directory_fd)
                ) != transaction_identity:
                    _fail("pair archive transaction directory was rebound")
                entries = set(os.listdir(transaction.directory_fd))
                if not entries <= {_ARCHIVE_INTENT_NAME, _ARCHIVE_STAGE_NAME}:
                    _fail("pair archive transaction contains foreign entries")
                if _ARCHIVE_INTENT_NAME not in entries:
                    _fail("pair archive transaction intent is missing")

                intent_fd = os.open(
                    _ARCHIVE_INTENT_NAME,
                    os.O_RDONLY
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=transaction.directory_fd,
                )
                fcntl.flock(intent_fd, fcntl.LOCK_EX)
                locked_entries = frozenset(os.listdir(transaction.directory_fd))
                if (
                    _ARCHIVE_INTENT_NAME not in locked_entries
                    or not locked_entries
                    <= frozenset({_ARCHIVE_INTENT_NAME, _ARCHIVE_STAGE_NAME})
                ):
                    _fail("pair archive locked transaction contains foreign entries")
                intent_named = os.stat(
                    _ARCHIVE_INTENT_NAME,
                    dir_fd=transaction.directory_fd,
                    follow_symlinks=False,
                )
                intent_opened = os.fstat(intent_fd)
                if (
                    not stat.S_ISREG(intent_opened.st_mode)
                    or stat.S_ISLNK(intent_named.st_mode)
                    or int(intent_opened.st_nlink) != 1
                    or (int(intent_opened.st_dev), int(intent_opened.st_ino))
                    != intent_identity
                    or _archive_file_snapshot(intent_opened)
                    != _archive_file_snapshot(intent_named)
                    or (
                        physical.permission_modes_enforced
                        and stat.S_IMODE(intent_opened.st_mode) != 0o444
                    )
                ):
                    _fail("pair archive intent identity drifted")
                observed_intent = bytearray()
                while True:
                    chunk = os.read(intent_fd, 64 * 1024)
                    if not chunk:
                        break
                    observed_intent.extend(chunk)
                    if len(observed_intent) > len(intent_payload):
                        _fail("pair archive intent bytes drifted")
                if bytes(observed_intent) != intent_payload:
                    _fail("pair archive intent bytes drifted")
                os.fsync(intent_fd)
                transaction.fsync()

                final_named = _archive_stat_optional(destination, final.name)
                stage_named = _archive_stat_optional(
                    transaction, _ARCHIVE_STAGE_NAME,
                )
                if final_named is not None:
                    if (
                        not stat.S_ISREG(final_named.st_mode)
                        or stat.S_ISLNK(final_named.st_mode)
                    ):
                        _fail("immutable pair archive collision is not a file")
                    final_links = int(final_named.st_nlink)
                    if final_links == 2:
                        if (
                            stage_named is None
                            or not stat.S_ISREG(stage_named.st_mode)
                            or stat.S_ISLNK(stage_named.st_mode)
                            or _archive_file_snapshot(stage_named)
                            != _archive_file_snapshot(final_named)
                        ):
                            _fail("pair archive two-link recovery is not WAL-owned")
                        recovered_identity = _verify_archive_named(
                            destination,
                            final.name,
                            expected,
                            label="linked pair archive recovery",
                            allowed_links=frozenset({2}),
                            mode_enforced=physical.permission_modes_enforced,
                        )
                        if recovered_identity != (
                            int(stage_named.st_dev), int(stage_named.st_ino)
                        ):
                            _fail("pair archive recovery inode crossbind drifted")
                        current_stage = os.stat(
                            _ARCHIVE_STAGE_NAME,
                            dir_fd=transaction.directory_fd,
                            follow_symlinks=False,
                        )
                        if (
                            int(current_stage.st_nlink) != 2
                            or (int(current_stage.st_dev), int(current_stage.st_ino))
                            != recovered_identity
                        ):
                            _fail("pair archive recovery stage was replaced")
                        os.unlink(
                            _ARCHIVE_STAGE_NAME,
                            dir_fd=transaction.directory_fd,
                        )
                        transaction.fsync()
                        destination.fsync()
                    elif final_links == 1:
                        if stage_named is not None:
                            _fail("pair archive completed WAL contains a foreign stage")
                    else:
                        _fail("pair archive final has foreign hard links")
                    _verify_archive_named(
                        destination,
                        final.name,
                        expected,
                        label="resumed immutable pair archive",
                        allowed_links=frozenset({1}),
                        mode_enforced=physical.permission_modes_enforced,
                    )
                    destination.fsync()
                    transaction.fsync()
                    _require_archive_transaction_entries(
                        transaction,
                        frozenset({_ARCHIVE_INTENT_NAME}),
                        label="resumed pair archive",
                    )
                    physical.verify()
                    return expected, manifest["manifest_sha256"]

                if stage_named is None:
                    stage_fd = os.open(
                        _ARCHIVE_STAGE_NAME,
                        os.O_RDWR
                        | os.O_CREAT
                        | os.O_EXCL
                        | int(getattr(os, "O_NOFOLLOW", 0))
                        | int(getattr(os, "O_CLOEXEC", 0)),
                        0o600,
                        dir_fd=transaction.directory_fd,
                    )
                    os.fchmod(stage_fd, 0o600)
                    transaction.fsync()
                    stage_named = os.stat(
                        _ARCHIVE_STAGE_NAME,
                        dir_fd=transaction.directory_fd,
                        follow_symlinks=False,
                    )
                else:
                    if (
                        not stat.S_ISREG(stage_named.st_mode)
                        or stat.S_ISLNK(stage_named.st_mode)
                        or int(stage_named.st_nlink) != 1
                        or (
                            physical.permission_modes_enforced
                            and stat.S_IMODE(stage_named.st_mode) not in {0o600, 0o444}
                        )
                    ):
                        _fail("pair archive WAL stage is foreign")
                    observed_stage_mode = stat.S_IMODE(stage_named.st_mode)
                    stage_fd = os.open(
                        _ARCHIVE_STAGE_NAME,
                        (
                            os.O_RDONLY
                            if (
                                physical.permission_modes_enforced
                                and observed_stage_mode == 0o444
                            )
                            else os.O_RDWR
                        )
                        | int(getattr(os, "O_NOFOLLOW", 0))
                        | int(getattr(os, "O_CLOEXEC", 0)),
                        dir_fd=transaction.directory_fd,
                    )
                stage_opened = os.fstat(stage_fd)
                current_stage = os.stat(
                    _ARCHIVE_STAGE_NAME,
                    dir_fd=transaction.directory_fd,
                    follow_symlinks=False,
                )
                if (
                    _archive_file_snapshot(stage_opened)
                    != _archive_file_snapshot(current_stage)
                    or not stat.S_ISREG(stage_opened.st_mode)
                    or int(stage_opened.st_nlink) != 1
                ):
                    _fail("pair archive WAL stage identity changed while opening")
                stage_identity = int(stage_opened.st_dev), int(stage_opened.st_ino)
                stage_mode = stat.S_IMODE(stage_opened.st_mode)
                if (
                    not physical.permission_modes_enforced
                    or stage_mode == 0o600
                ):
                    os.ftruncate(stage_fd, 0)
                    os.lseek(stage_fd, 0, os.SEEK_SET)
                    emitted = False
                    digest = hashlib.sha256()
                    observed_size = 0
                    for chunk in _archive_chunks(manifest, registry):
                        _write_all(stage_fd, chunk)
                        digest.update(chunk)
                        observed_size += len(chunk)
                        if not emitted:
                            emitted = True
                            fault("mid_write", transaction, destination)
                    if (
                        observed_size != expected["size_bytes"]
                        or digest.hexdigest() != expected["sha256"]
                    ):
                        _fail("pair archive staged stream descriptor drifted")
                    os.fchmod(stage_fd, 0o444)
                    os.fsync(stage_fd)
                    transaction.fsync()
                elif stage_mode != 0o444:
                    _fail("pair archive WAL stage mode drifted")

                verified_stage_identity = _verify_archive_named(
                    transaction,
                    _ARCHIVE_STAGE_NAME,
                    expected,
                    label="durable pair archive WAL stage",
                    allowed_links=frozenset({1}),
                    mode_enforced=physical.permission_modes_enforced,
                )
                if verified_stage_identity != stage_identity:
                    _fail("pair archive WAL stage inode changed")
                fault("post_fsync_pre_publish", transaction, destination)
                verified_stage_identity = _verify_archive_named(
                    transaction,
                    _ARCHIVE_STAGE_NAME,
                    expected,
                    label="pre-publish pair archive WAL stage",
                    allowed_links=frozenset({1}),
                    mode_enforced=physical.permission_modes_enforced,
                )
                if verified_stage_identity != stage_identity:
                    _fail("pair archive WAL stage was replaced before publish")
                _require_archive_transaction_entries(
                    transaction,
                    frozenset({_ARCHIVE_INTENT_NAME, _ARCHIVE_STAGE_NAME}),
                    label="pre-publish pair archive",
                )
                try:
                    _link_open_archive_noreplace(
                        stage_fd, destination.directory_fd, final.name,
                    )
                except FileExistsError as error:
                    raise BackendPairArchiveSizingReceiptsV1Error(
                        f"immutable pair archive collision: {final.name}"
                    ) from error
                linked_stage = os.stat(
                    _ARCHIVE_STAGE_NAME,
                    dir_fd=transaction.directory_fd,
                    follow_symlinks=False,
                )
                linked_final = os.stat(
                    final.name,
                    dir_fd=destination.directory_fd,
                    follow_symlinks=False,
                )
                if (
                    (int(linked_stage.st_dev), int(linked_stage.st_ino))
                    != stage_identity
                    or _archive_file_snapshot(linked_stage)
                    != _archive_file_snapshot(linked_final)
                    or int(linked_final.st_nlink) != 2
                ):
                    _fail("pair archive hard-link publish crossbind drifted")
                fault(
                    "post_publish_pre_parent_fsync",
                    transaction,
                    destination,
                )
                current_stage = os.stat(
                    _ARCHIVE_STAGE_NAME,
                    dir_fd=transaction.directory_fd,
                    follow_symlinks=False,
                )
                if (
                    int(current_stage.st_nlink) != 2
                    or (int(current_stage.st_dev), int(current_stage.st_ino))
                    != stage_identity
                ):
                    _fail("pair archive linked stage was replaced")
                os.unlink(_ARCHIVE_STAGE_NAME, dir_fd=transaction.directory_fd)
                transaction.fsync()
                destination.fsync()
                committed_identity = _verify_archive_named(
                    destination,
                    final.name,
                    expected,
                    label="committed pair archive",
                    allowed_links=frozenset({1}),
                    mode_enforced=physical.permission_modes_enforced,
                )
                if committed_identity != stage_identity:
                    _fail("pair archive final inode changed after commit")
                destination.fsync()
                transaction.fsync()
                _require_archive_transaction_entries(
                    transaction,
                    frozenset({_ARCHIVE_INTENT_NAME}),
                    label="committed pair archive",
                )
                physical.verify()
                return expected, manifest["manifest_sha256"]
    except BackendPairArchiveSizingReceiptsV1Error:
        raise
    except (PublicationPhysicalIoV1Error, GuardianPreprocessingContractV1Error) as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"pair archive physical custody failed: {error}"
        ) from error
    except OSError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"pair archive streaming commit failed: {error}"
        ) from error
    finally:
        if stage_fd >= 0:
            try:
                os.close(stage_fd)
            except OSError:
                pass
        if intent_fd >= 0:
            try:
                if fcntl is not None:
                    fcntl.flock(intent_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(intent_fd)
            except OSError:
                pass


def _validate_archive_payload(
    payload: bytes, *, expected_descriptor: Mapping[str, Any],
    expected_coordinate: Mapping[str, Any], expected_pair_identity: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    if not payload.startswith(_ARCHIVE_MAGIC):
        _fail("pair archive magic drifted")
    cursor = len(_ARCHIVE_MAGIC)
    if len(payload) < cursor + 8:
        _fail("pair archive manifest length is truncated")
    manifest_size = int.from_bytes(payload[cursor:cursor + 8], "big")
    cursor += 8
    manifest_end = cursor + manifest_size
    if manifest_size <= 0 or manifest_end > len(payload):
        _fail("pair archive manifest is truncated")
    try:
        manifest = json.loads(payload[cursor:manifest_end].decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            "pair archive manifest is invalid"
        ) from error
    cursor = manifest_end
    if (
        type(manifest) is not dict
        or payload[manifest_end - manifest_size:manifest_end]
        != _canonical_bytes(manifest)
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("artifact_kind") != "vast_backend_q4_pair_archive_v1"
        or manifest.get("qualification_scope") != SCOPE
        or manifest.get("coordinate") != dict(expected_coordinate)
        or manifest.get("pair_identity_sha256") != expected_pair_identity
        or manifest.get("manifest_sha256") != expected_manifest_sha256
        or manifest.get("manifest_sha256") != _canonical_sha({
            key: item for key, item in manifest.items()
            if key != "manifest_sha256"
        })
    ):
        _fail("pair archive manifest identity/cross-binding drifted")
    entries = manifest.get("entries")
    if type(entries) is not list or not entries:
        _fail("pair archive entry set is empty")
    paths: list[str] = []
    for position, item in enumerate(entries):
        if type(item) is not dict or set(item) != {
            "topology_kind", "archive_path", "source"
        }:
            _fail(f"pair archive entry[{position}] fields drifted")
        path = _relative(item["archive_path"], f"pair archive entry[{position}]")
        source = _descriptor(
            item["source"], f"pair archive entry[{position}] source",
            allow_empty=True,
        )
        if item["topology_kind"] not in TOPOLOGIES or not path.startswith(
            f"{item['topology_kind']}/"
        ):
            _fail(f"pair archive entry[{position}] topology namespace drifted")
        if len(payload) < cursor + 8:
            _fail(f"pair archive entry[{position}] length is truncated")
        observed_size = int.from_bytes(payload[cursor:cursor + 8], "big")
        cursor += 8
        end = cursor + observed_size
        if end > len(payload):
            _fail(f"pair archive entry[{position}] payload is truncated")
        observed = payload[cursor:end]
        cursor = end
        if (
            observed_size != source["size_bytes"]
            or hashlib.sha256(observed).hexdigest() != source["sha256"]
        ):
            _fail(f"pair archive entry[{position}] physical payload drifted")
        paths.append(path)
    if paths != sorted(paths) or len(paths) != len(set(paths)) or cursor != len(payload):
        _fail("pair archive entry order/namespace/trailing bytes drifted")
    if (
        len(payload) != expected_descriptor["size_bytes"]
        or hashlib.sha256(payload).hexdigest() != expected_descriptor["sha256"]
    ):
        _fail("pair archive descriptor drifted")
    return manifest


def materialize_backend_pair_archive_sizing_receipts_v1(
    *, project_root: Path | str, input_path: Path | str,
    output_dir: Path | str,
    after_physical_commit_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Physically validate 560 post-Q4 arms and commit 280 sizing receipts."""
    try:
        root = _root(project_root)
        source_path = _path_in_root(root, input_path, "pair sizing input")
        source_descriptor = _descriptor_for(root, source_path)
        registry = _PhysicalRegistry(root)
        source_payload = registry.read(source_descriptor, "pair sizing input")
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    source = _validate_input(_canonical_object(
        source_payload, "pair sizing input", identity_field="input_sha256",
    ))
    if source["q4_binding_index"] != _descriptor_for(
        root, _path_in_root(
            root, source["q4_binding_index"]["path"], "pair sizing Q4 binding",
        ),
    ):
        _fail("pair sizing Q4 binding descriptor drifted before loading")
    try:
        q4 = load_backend_runtime_qualification_v4_binding(
            project_root=root,
            binding_index_path=source["q4_binding_index"]["path"],
        )
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"pair sizing authenticated Q4 binding rejected: {error}"
        ) from error
    if (
        q4.get("authorization_eligible") is not True
        or q4.get("validation_trust_status")
        != "authenticated_persisted_physical_q4_v4"
        or q4.get("binding_index") != source["q4_binding_index"]
    ):
        _fail("pair sizing source is not the authenticated persisted Q4 binding")
    try:
        for position, descriptor in enumerate(q4["physical_files"]):
            registry.read(descriptor, f"pair sizing Q4 physical file[{position}]")
        output = _output_directory(root, output_dir)
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error

    receipt_entries: list[dict[str, Any]] = []
    sizing_rows: list[dict[str, Any]] = []
    q4_systems = q4["systems"]
    for position, pair in enumerate(source["pairs"]):
        coordinate = pair["coordinate"]
        q4_system = q4_systems[coordinate["system"]]
        arms = [
            _validate_arm_authority(
                registry=registry,
                authority_descriptor=pair["arms"][topology][
                    "output_receipt_authority"
                ],
                arm_payload_descriptor=pair["arms"][topology]["arm_payload"],
                coordinate=coordinate, topology=topology,
                q4_system=q4_system,
            )
            for topology in TOPOLOGIES
        ]
        if (
            len({item["execution_pair_id"] for item in arms}) != 1
            or len({item["execution_arm_id"] for item in arms}) != 2
        ):
            _fail(f"pair sizing pair[{position}] execution pair/arm identity drifted")
        archive, manifest_sha = _commit_archive(
            root=root, output=output, coordinate=coordinate,
            pair_identity_sha256=pair["pair_identity_sha256"], arms=arms,
            registry=registry,
            after_publish_step=(
                None
                if after_physical_commit_step is None
                else lambda step, position=position: after_physical_commit_step(
                    f"archive:{position}:{step}"
                )
            ),
        )
        archive_sources = [
            descriptor
            for arm in arms for descriptor in arm["archive_entries"]
        ]
        arm_summaries = [
            {key: copy.deepcopy(value) for key, value in arm.items()
             if key != "archive_entries"}
            for arm in arms
        ]
        receipt: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": RECEIPT_KIND,
            "status": STATUS,
            "qualification_scope": SCOPE,
            "source_input_sha256": source["input_sha256"],
            "q4_binding_identity_sha256": q4["identity_binding_sha256"],
            "coordinate": copy.deepcopy(coordinate),
            "pair_identity_sha256": pair["pair_identity_sha256"],
            "arms": arm_summaries,
            "archive": archive,
            "archive_manifest_sha256": manifest_sha,
            "archive_source_set_sha256": _canonical_sha(archive_sources),
            "observed_pair_archive_bytes": archive["size_bytes"],
            "full_run_data_accepted": False,
            "configuration_evidence_accepted_mutated": False,
        }
        receipt["pair_receipt_sha256"] = _canonical_sha(receipt)
        receipt_path = output / _receipt_filename(coordinate)
        try:
            _atomic_immutable(
                root,
                receipt_path,
                receipt,
                after_publish_step=(
                    None
                    if after_physical_commit_step is None
                    else lambda step, position=position: after_physical_commit_step(
                        f"receipt:{position}:{step}"
                    )
                ),
            )
        except BackendRuntimeQualificationV4PersistenceError as error:
            raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
        receipt_descriptor = _descriptor_for(root, receipt_path)
        receipt_entries.append({
            "coordinate": copy.deepcopy(coordinate),
            "pair_identity_sha256": pair["pair_identity_sha256"],
            "receipt": receipt_descriptor,
            "pair_receipt_sha256": receipt["pair_receipt_sha256"],
            "archive": archive,
            "archive_manifest_sha256": manifest_sha,
            "observed_pair_archive_bytes": archive["size_bytes"],
        })
        sizing_rows.append({
            **copy.deepcopy(coordinate),
            "observed_pair_archive_bytes": archive["size_bytes"],
            "pair_receipt_sha256": receipt["pair_receipt_sha256"],
        })
    try:
        registry.revalidate()
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    index: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": INDEX_KIND,
        "status": STATUS,
        "qualification_scope": SCOPE,
        "source_input": source_descriptor,
        "source_input_sha256": source["input_sha256"],
        "q4_binding_index": source["q4_binding_index"],
        "q4_binding_identity_sha256": q4["identity_binding_sha256"],
        "pairs": receipt_entries,
        "sizing_rows": sizing_rows,
        "coverage": {
            "pair_count": 280, "topology_arm_count": 560,
            "arms_per_pair": 2,
        },
        "full_run_data_accepted": False,
        "configuration_evidence_accepted_mutated": False,
    }
    index["index_sha256"] = _canonical_sha(index)
    index_path = output / INDEX_FILENAME
    try:
        _atomic_immutable(
            root,
            index_path,
            index,
            after_publish_step=(
                None
                if after_physical_commit_step is None
                else lambda step: after_physical_commit_step(f"index:{step}")
            ),
        )
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    # Reloading validates every persisted receipt and every archive payload.
    rows = load_operator_sizing_rows_v1(
        project_root=root, index_path=index_path,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_backend_pair_archive_sizing_materialization_v1",
        "status": STATUS,
        "index": _descriptor_for(root, index_path),
        "index_sha256": index["index_sha256"],
        "sizing_rows": rows,
    }


def _validate_receipt(
    value: Any, *, entry: Mapping[str, Any], index: Mapping[str, Any],
) -> dict[str, Any]:
    fields = {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "source_input_sha256", "q4_binding_identity_sha256", "coordinate",
        "pair_identity_sha256", "arms", "archive",
        "archive_manifest_sha256", "archive_source_set_sha256",
        "observed_pair_archive_bytes", "full_run_data_accepted",
        "configuration_evidence_accepted_mutated", "pair_receipt_sha256",
    }
    if (
        type(value) is not dict or set(value) != fields
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != RECEIPT_KIND
        or value.get("status") != STATUS
        or value.get("qualification_scope") != SCOPE
        or value.get("source_input_sha256") != index["source_input_sha256"]
        or value.get("q4_binding_identity_sha256")
        != index["q4_binding_identity_sha256"]
        or value.get("coordinate") != entry["coordinate"]
        or value.get("pair_identity_sha256") != entry["pair_identity_sha256"]
        or value.get("archive") != entry["archive"]
        or value.get("archive_manifest_sha256")
        != entry["archive_manifest_sha256"]
        or value.get("observed_pair_archive_bytes")
        != entry["observed_pair_archive_bytes"]
        or value.get("full_run_data_accepted") is not False
        or value.get("configuration_evidence_accepted_mutated") is not False
        or value.get("pair_receipt_sha256")
        != entry["pair_receipt_sha256"]
    ):
        _fail("persisted pair sizing receipt cross-binding drifted")
    arms = value.get("arms")
    if (
        type(arms) is not list or len(arms) != 2
        or any(type(item) is not dict or set(item) != _ARM_SUMMARY_FIELDS
               for item in arms)
        or [item.get("topology_kind") for item in arms] != list(TOPOLOGIES)
        or len({item.get("production_output_receipt_sha256") for item in arms})
        != 2
        or any(not _SHA_RE.fullmatch(str(item.get(
            "output_receipt_authority_sha256"
        ))) for item in arms)
    ):
        _fail("persisted pair sizing receipt arm authority set drifted")
    return copy.deepcopy(value)


def load_operator_sizing_rows_v1(
    *, project_root: Path | str, index_path: Path | str,
) -> list[dict[str, Any]]:
    """Physically reload the commit-last index as 280 neutral sizing rows."""
    try:
        root = _root(project_root)
        path = _path_in_root(root, index_path, "pair sizing index")
        if path.name != INDEX_FILENAME:
            _fail("pair sizing index filename drifted")
        descriptor = _descriptor_for(root, path)
        registry = _PhysicalRegistry(root)
        payload = registry.read(descriptor, "pair sizing index")
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    index = _canonical_object(
        payload, "pair sizing index", identity_field="index_sha256",
    )
    fields = {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "source_input", "source_input_sha256", "q4_binding_index",
        "q4_binding_identity_sha256", "pairs", "sizing_rows", "coverage",
        "full_run_data_accepted", "configuration_evidence_accepted_mutated",
        "index_sha256",
    }
    if (
        set(index) != fields or index.get("schema_version") != SCHEMA_VERSION
        or index.get("artifact_kind") != INDEX_KIND
        or index.get("status") != STATUS
        or index.get("qualification_scope") != SCOPE
        or index.get("coverage") != {
            "pair_count": 280, "topology_arm_count": 560,
            "arms_per_pair": 2,
        }
        or index.get("full_run_data_accepted") is not False
        or index.get("configuration_evidence_accepted_mutated") is not False
        or not _SHA_RE.fullmatch(str(index.get("source_input_sha256")))
        or not _SHA_RE.fullmatch(str(index.get("q4_binding_identity_sha256")))
    ):
        _fail("pair sizing index header/coverage drifted")
    source_descriptor = _descriptor(
        index.get("source_input"), "pair sizing index source input",
    )
    source_value, _ = _read_json(
        registry, source_descriptor, "pair sizing index source input",
        identity_field="input_sha256",
    )
    source_value = _validate_input(source_value)
    if (
        source_value["input_sha256"] != index["source_input_sha256"]
        or source_value["q4_binding_index"] != index["q4_binding_index"]
    ):
        _fail("pair sizing index/source input cross-binding drifted")
    try:
        q4 = load_backend_runtime_qualification_v4_binding(
            project_root=root,
            binding_index_path=source_value["q4_binding_index"]["path"],
        )
        for position, q4_file in enumerate(q4["physical_files"]):
            registry.read(q4_file, f"pair sizing reload Q4 file[{position}]")
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(
            f"pair sizing reload authenticated Q4 binding rejected: {error}"
        ) from error
    if (
        q4["binding_index"] != source_value["q4_binding_index"]
        or q4["identity_binding_sha256"]
        != index["q4_binding_identity_sha256"]
    ):
        _fail("pair sizing index authenticated Q4 identity drifted")
    pairs = index.get("pairs")
    rows = index.get("sizing_rows")
    expected = _expected_coordinates()
    if (
        type(pairs) is not list or len(pairs) != 280
        or type(rows) is not list or len(rows) != 280
    ):
        _fail("pair sizing index requires exactly 280 pairs/rows")
    normalized_rows: list[dict[str, Any]] = []
    for position, (entry, row, coordinate) in enumerate(
        zip(pairs, rows, expected, strict=True)
    ):
        entry_fields = {
            "coordinate", "pair_identity_sha256", "receipt",
            "pair_receipt_sha256", "archive", "archive_manifest_sha256",
            "observed_pair_archive_bytes",
        }
        if (
            type(entry) is not dict or set(entry) != entry_fields
            or entry.get("coordinate") != coordinate
            or not _SHA_RE.fullmatch(str(entry.get("pair_identity_sha256")))
            or not _SHA_RE.fullmatch(str(entry.get("pair_receipt_sha256")))
            or not _SHA_RE.fullmatch(str(entry.get("archive_manifest_sha256")))
        ):
            _fail(f"pair sizing index pair[{position}] drifted")
        source_pair = source_value["pairs"][position]
        if entry["pair_identity_sha256"] != source_pair["pair_identity_sha256"]:
            _fail(f"pair sizing index pair[{position}] source identity drifted")
        receipt_descriptor = _descriptor(
            entry["receipt"], f"pair sizing receipt[{position}]",
        )
        archive_descriptor = _descriptor(
            entry["archive"], f"pair sizing archive[{position}]",
        )
        if (
            entry["observed_pair_archive_bytes"]
            != archive_descriptor["size_bytes"]
            or entry["observed_pair_archive_bytes"] <= 0
        ):
            _fail(f"pair sizing index pair[{position}] archive size drifted")
        receipt, _ = _read_json(
            registry, receipt_descriptor, f"pair sizing receipt[{position}]",
            identity_field="pair_receipt_sha256",
        )
        checked_receipt = _validate_receipt(
            receipt, entry=entry, index=index,
        )
        # The index and pair receipts are self-hashed, not externally signed.
        # Re-run the production-v3 authority/receipt/arm validators against the
        # original physical sources so a coherently rehashed archive/index set
        # cannot manufacture a sizing row.
        revalidated_arms = [
            _validate_arm_authority(
                registry=registry,
                authority_descriptor=source_pair["arms"][topology][
                    "output_receipt_authority"
                ],
                arm_payload_descriptor=source_pair["arms"][topology][
                    "arm_payload"
                ],
                coordinate=coordinate,
                topology=topology,
                q4_system=q4["systems"][coordinate["system"]],
            )
            for topology in TOPOLOGIES
        ]
        revalidated_summaries = [
            {
                key: copy.deepcopy(value)
                for key, value in arm.items()
                if key != "archive_entries"
            }
            for arm in revalidated_arms
        ]
        if (
            checked_receipt["arms"] != revalidated_summaries
            or len({arm["execution_pair_id"] for arm in revalidated_arms}) != 1
            or len({arm["execution_arm_id"] for arm in revalidated_arms}) != 2
        ):
            _fail(f"pair sizing receipt[{position}] live arm closure drifted")
        try:
            archive_payload = registry.read(
                archive_descriptor, f"pair sizing archive[{position}]",
            )
        except BackendRuntimeQualificationV4PersistenceError as error:
            raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
        manifest = _validate_archive_payload(
            archive_payload, expected_descriptor=archive_descriptor,
            expected_coordinate=coordinate,
            expected_pair_identity=entry["pair_identity_sha256"],
            expected_manifest_sha256=entry["archive_manifest_sha256"],
        )
        expected_manifest = _archive_manifest(
            coordinate=coordinate,
            pair_identity_sha256=entry["pair_identity_sha256"],
            arms=revalidated_arms,
        )
        if manifest != expected_manifest:
            _fail(f"pair sizing archive[{position}] live source closure drifted")
        if checked_receipt["archive_source_set_sha256"] != _canonical_sha([
            item["source"] for item in manifest["entries"]
        ]):
            _fail(f"pair sizing receipt[{position}] archive source set drifted")
        manifest_sources = {
            item["source"]["path"]: item["source"]
            for item in manifest["entries"]
        }
        for arm in checked_receipt["arms"]:
            topology = arm["topology_kind"]
            source_arm = source_pair["arms"][topology]
            if (
                arm["output_receipt_authority"]
                != source_arm["output_receipt_authority"]
                or arm["arm_payload"] != source_arm["arm_payload"]
                or manifest_sources.get(
                    arm["output_receipt_authority"]["path"]
                ) != arm["output_receipt_authority"]
                or manifest_sources.get(arm["arm_payload"]["path"])
                != arm["arm_payload"]
            ):
                _fail(f"pair sizing receipt[{position}] source arm drifted")
        expected_row = {
            **coordinate,
            "observed_pair_archive_bytes": archive_descriptor["size_bytes"],
            "pair_receipt_sha256": entry["pair_receipt_sha256"],
        }
        if row != expected_row:
            _fail(f"pair sizing row[{position}] cross-binding drifted")
        normalized_rows.append(expected_row)
    try:
        registry.revalidate()
    except BackendRuntimeQualificationV4PersistenceError as error:
        raise BackendPairArchiveSizingReceiptsV1Error(str(error)) from error
    return normalized_rows


# Compatibility spelling for the downstream capacity consumer.  The rows are
# operator-neutral and imply no account, library, quota, or placement policy.
load_seafile_sizing_rows_v1 = load_operator_sizing_rows_v1


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize or reload exact post-Q4 pair archive sizing",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    materialize = commands.add_parser("materialize")
    materialize.add_argument("--project-root", type=Path, required=True)
    materialize.add_argument("--input", type=Path, required=True)
    materialize.add_argument("--output-dir", type=Path, required=True)
    rows = commands.add_parser("rows")
    rows.add_argument("--project-root", type=Path, required=True)
    rows.add_argument("--index", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "materialize":
            value = materialize_backend_pair_archive_sizing_receipts_v1(
                project_root=arguments.project_root,
                input_path=arguments.input,
                output_dir=arguments.output_dir,
            )
        else:
            sizing_rows = load_operator_sizing_rows_v1(
                project_root=arguments.project_root,
                index_path=arguments.index,
            )
            value = {
                "sizing_rows": sizing_rows,
            }
    except BackendPairArchiveSizingReceiptsV1Error as error:
        parser.error(str(error))
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = [
    "AUTHORITY_ENVELOPE_KIND", "BackendPairArchiveSizingReceiptsV1Error",
    "CODECS", "DEADLINES_MS",
    "INDEX_FILENAME", "INDEX_KIND", "INPUT_KIND", "POLICIES",
    "RECEIPT_KIND", "SCHEMA_VERSION", "SCOPE", "STATUS", "SYSTEMS",
    "TOPOLOGIES", "build_backend_pair_archive_sizing_input_v1",
    "load_operator_sizing_rows_v1",
    "load_seafile_sizing_rows_v1",
    "materialize_backend_pair_archive_sizing_receipts_v1",
    "persist_backend_production_output_receipt_authority_v1",
]


if __name__ == "__main__":
    raise SystemExit(_main())
