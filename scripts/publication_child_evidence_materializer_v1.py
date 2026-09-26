#!/usr/bin/env python3
"""Crash-resumable parent custody for one native child-evidence namespace.

The native runtime wrappers write into container-private scratch first.  This
module is the host-side boundary that copies the declared files into the
caller's deterministic output directory.  A parent-owned intent is committed
before the first output leaf and a receipt, including the exact output inode
identities, is committed last.  Partial prefixes are recoverable only while the
matching intent exists; a different payload set must use a different output
directory (a new attempt).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
    canonical_relative_path_v1,
)


INTENT_ROOT_V1 = ".publication-child-evidence-intents-v1"
RECEIPT_ROOT_V1 = ".publication-child-evidence-receipts-v1"
INTENT_KIND_V1 = "vast_publication_child_evidence_group_intent_v1"
RECEIPT_KIND_V1 = "vast_publication_child_evidence_group_receipt_v1"
MAX_GROUP_METADATA_BYTES = 4 * 1024 * 1024


class PublicationChildEvidenceMaterializerV1Error(RuntimeError):
    """The child evidence set could not cross the parent custody boundary."""


PhysicalFaultHook = Callable[[str], None]


def _fail(message: str) -> None:
    raise PublicationChildEvidenceMaterializerV1Error(message)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        payload = json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise PublicationChildEvidenceMaterializerV1Error(
            "child evidence metadata is not canonical JSON"
        ) from error
    return payload


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)[:-1]).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result[field] = _canonical_sha(result)
    return result


def _canonical_relative(root: Path, value: Path | str, *, label: str) -> str:
    absolute = Path(os.path.abspath(os.fspath(value)))
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError as error:
        raise PublicationChildEvidenceMaterializerV1Error(
            f"{label} escaped project_root"
        ) from error
    try:
        return canonical_relative_path_v1(relative, label=label)
    except PublicationPhysicalIoV1Error as error:
        raise PublicationChildEvidenceMaterializerV1Error(str(error)) from error


def _leaf_name(value: Any, *, label: str) -> str:
    if type(value) is not str or not value or PurePosixPath(value).name != value:
        _fail(f"{label} is not one canonical leaf name")
    try:
        return canonical_relative_path_v1(value, label=label)
    except PublicationPhysicalIoV1Error as error:
        raise PublicationChildEvidenceMaterializerV1Error(str(error)) from error


def _load_canonical_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationChildEvidenceMaterializerV1Error(
            f"{label} is not canonical JSON"
        ) from error
    if type(value) is not dict or _canonical_bytes(value) != payload:
        _fail(f"{label} is not canonical JSON")
    return value


def _validated_receipt(
    value: Mapping[str, Any],
    *,
    output_relative: str,
    output_identity: tuple[int, ...],
    intent_descriptor: Mapping[str, Any],
    intent_sha256: str,
    source_records: Sequence[Mapping[str, Any]],
) -> list[tuple[int, int]]:
    receipt = copy.deepcopy(dict(value))
    supplied_sha = receipt.pop("receipt_sha256", None)
    if (
        set(value)
        != {
            "schema_version",
            "artifact_kind",
            "status",
            "output_directory",
            "output_directory_identity",
            "intent",
            "intent_sha256",
            "leaves",
            "receipt_sha256",
        }
        or value.get("schema_version") != 1
        or value.get("artifact_kind") != RECEIPT_KIND_V1
        or value.get("status") != "committed_child_evidence_group"
        or value.get("output_directory") != output_relative
        or value.get("output_directory_identity") != list(output_identity)
        or value.get("intent") != dict(intent_descriptor)
        or value.get("intent_sha256") != intent_sha256
        or supplied_sha != _canonical_sha(receipt)
        or type(value.get("leaves")) is not list
        or len(value["leaves"]) != len(source_records)
    ):
        _fail("child evidence group receipt drifted")

    identities: list[tuple[int, int]] = []
    for position, (leaf, source) in enumerate(
        zip(value["leaves"], source_records, strict=True)
    ):
        expected_output = {
            "path": f"{output_relative}/{source['target_name']}",
            "size_bytes": source["source_descriptor"]["size_bytes"],
            "sha256": source["source_descriptor"]["sha256"],
        }
        if (
            type(leaf) is not dict
            or set(leaf)
            != {
                "target_name",
                "source_name",
                "source",
                "output",
                "output_identity",
            }
            or leaf.get("target_name") != source["target_name"]
            or leaf.get("source_name") != source["source_name"]
            or leaf.get("source") != source["source_descriptor"]
            or leaf.get("output") != expected_output
            or type(leaf.get("output_identity")) is not list
            or len(leaf["output_identity"]) != 2
            or any(type(item) is not int or item < 0 for item in leaf["output_identity"])
        ):
            _fail(f"child evidence group receipt leaf[{position}] drifted")
        identities.append(tuple(leaf["output_identity"]))
    return identities


def materialize_publication_child_evidence_group_v1(
    *,
    project_root: Path | str,
    source_dir: Path | str,
    output_dir: Path | str,
    target_names: Sequence[str],
    evidence_mapping: Mapping[str, str],
    allowed_preexisting_names: Sequence[str],
    maximum_bytes: int,
    label: str,
    after_physical_commit_step: PhysicalFaultHook | None = None,
) -> tuple[dict[str, Any], ...]:
    """Publish exactly one declared evidence group, or resume its exact prefix.

    The callback receives ``intent:<step>``, ``leaf:<name>:<step>``, and
    ``receipt:<step>`` labels, where ``step`` is one of the three fault windows
    implemented by :class:`PhysicalRootCustodyV1`.
    """

    if type(label) is not str or not label:
        _fail("child evidence group label is empty")
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        _fail(f"{label} maximum_bytes is invalid")
    if after_physical_commit_step is not None and not callable(
        after_physical_commit_step
    ):
        _fail(f"{label} physical fault hook is not callable")
    if type(target_names) not in {tuple, list} or not target_names:
        _fail(f"{label} target namespace is empty")
    ordered_targets = tuple(
        _leaf_name(value, label=f"{label} target[{position}]")
        for position, value in enumerate(target_names)
    )
    if len(set(ordered_targets)) != len(ordered_targets):
        _fail(f"{label} target namespace contains duplicates")
    if type(allowed_preexisting_names) not in {tuple, list}:
        _fail(f"{label} allowed preexisting namespace is invalid")
    baseline_names = tuple(
        _leaf_name(value, label=f"{label} preexisting[{position}]")
        for position, value in enumerate(allowed_preexisting_names)
    )
    if (
        len(set(baseline_names)) != len(baseline_names)
        or set(baseline_names) & set(ordered_targets)
    ):
        _fail(f"{label} allowed preexisting namespace overlaps or duplicates")
    if type(evidence_mapping) is not dict or set(evidence_mapping) != set(
        ordered_targets
    ):
        _fail(f"{label} evidence mapping does not match the target namespace")
    source_names = tuple(
        _leaf_name(
            evidence_mapping[target], label=f"{label} source[{position}]"
        )
        for position, target in enumerate(ordered_targets)
    )
    if len(set(source_names)) != len(source_names):
        _fail(f"{label} source namespace contains duplicates")

    try:
        source_absolute = Path(os.path.abspath(os.fspath(source_dir)))
        with (
            PhysicalRootCustodyV1.open(
                source_absolute.parent, label=f"{label} source parent"
            ) as source_custody,
            PhysicalRootCustodyV1.open(
                project_root, label=f"{label} project root"
            ) as custody,
        ):
            root = custody.root
            source_relative = _canonical_relative(
                source_custody.root,
                source_absolute,
                label=f"{label} source directory",
            )
            output_relative = _canonical_relative(
                root, output_dir, label=f"{label} output directory"
            )
            _source_mode, _source_directory_identity = (
                source_custody.stat_directory_identity(
                    source_relative, label=f"{label} source directory"
                )
            )
            _output_mode, output_identity = custody.stat_directory_identity(
                output_relative, label=f"{label} output directory"
            )
            if source_custody.list_directory_names(
                source_relative, label=f"{label} source namespace"
            ) != tuple(sorted(source_names)):
                _fail(f"{label} source evidence namespace drifted")

            source_records: list[dict[str, Any]] = []
            for position, (target_name, source_name) in enumerate(
                zip(ordered_targets, source_names, strict=True)
            ):
                descriptor, _payload, identity = (
                    source_custody.read_descriptor_identity(
                        f"{source_relative}/{source_name}",
                        label=f"{label} source evidence[{position}]",
                        maximum=maximum_bytes,
                        capture=False,
                    )
                )
                source_records.append(
                    {
                        "target_name": target_name,
                        "source_name": source_name,
                        "source_descriptor": descriptor,
                        "source_identity": identity,
                    }
                )

            def capture_baseline() -> list[dict[str, Any]]:
                observed: list[dict[str, Any]] = []
                for position, name in enumerate(baseline_names):
                    mode, stat_identity = custody.stat_regular_identity(
                        f"{output_relative}/{name}",
                        label=f"{label} baseline output[{position}]",
                    )
                    descriptor, _payload, read_identity = (
                        custody.read_descriptor_identity(
                            f"{output_relative}/{name}",
                            label=f"{label} baseline output[{position}]",
                            maximum=maximum_bytes,
                            capture=False,
                        )
                    )
                    if stat_identity != read_identity:
                        _fail(f"{label} baseline output[{position}] was rebound")
                    observed.append(
                        {
                            "name": name,
                            "mode": mode,
                            "descriptor": descriptor,
                            "identity": list(read_identity),
                        }
                    )
                return observed

            baseline_records = capture_baseline()

            intent = _seal(
                {
                    "schema_version": 1,
                    "artifact_kind": INTENT_KIND_V1,
                    "status": "prepared_child_evidence_group",
                    "source_directory": source_relative,
                    "source_directory_identity": list(
                        _source_directory_identity
                    ),
                    "output_directory": output_relative,
                    "output_directory_identity": list(output_identity),
                    "baseline": baseline_records,
                    "leaves": [
                        {
                            "target_name": record["target_name"],
                            "source_name": record["source_name"],
                            "source": record["source_descriptor"],
                            "output": {
                                "path": (
                                    f"{output_relative}/{record['target_name']}"
                                ),
                                "size_bytes": record["source_descriptor"][
                                    "size_bytes"
                                ],
                                "sha256": record["source_descriptor"]["sha256"],
                            },
                        }
                        for record in source_records
                    ],
                },
                "intent_sha256",
            )
            intent_payload = _canonical_bytes(intent)
            group_key = hashlib.sha256(output_relative.encode("ascii")).hexdigest()
            intent_name = f"group-{group_key}.json"
            receipt_name = f"group-{group_key}.json"
            custody.ensure_directory(
                INTENT_ROOT_V1, label=f"{label} intent root"
            )
            custody.ensure_directory(
                RECEIPT_ROOT_V1, label=f"{label} receipt root"
            )
            intent_names = custody.list_directory_names(
                INTENT_ROOT_V1, label=f"{label} intent root"
            )
            receipt_names = custody.list_directory_names(
                RECEIPT_ROOT_V1, label=f"{label} receipt root"
            )
            has_intent = intent_name in intent_names
            has_receipt = receipt_name in receipt_names
            if has_receipt and not has_intent:
                _fail(f"{label} receipt exists without its parent intent")

            output_names = custody.list_directory_names(
                output_relative, label=f"{label} output namespace"
            )
            target_prefix = set(output_names) & set(ordered_targets)
            expected_partial = set(baseline_names) | target_prefix
            if has_receipt:
                if output_names != tuple(sorted((*baseline_names, *ordered_targets))):
                    _fail(f"{label} committed output namespace drifted")
            elif has_intent:
                if set(output_names) != expected_partial:
                    _fail(f"{label} partial output namespace contains foreign entries")
            elif set(output_names) != set(baseline_names):
                _fail(f"{label} unowned preexisting output prefix")

            def callback(prefix: str) -> PhysicalFaultHook | None:
                if after_physical_commit_step is None:
                    return None
                return lambda step: after_physical_commit_step(f"{prefix}:{step}")

            intent_descriptor, _intent_identity, _intent_disposition = (
                custody.commit_or_adopt_exact_identity(
                    f"{INTENT_ROOT_V1}/{intent_name}",
                    intent_payload,
                    label=f"{label} group intent",
                    mode=0o444,
                    create_parents=False,
                    after_publish_step=callback("intent"),
                )
            )

            output_descriptors: list[dict[str, Any]] = []
            output_identities: list[tuple[int, int]] = []
            for position, record in enumerate(source_records):
                source_descriptor, source_payload, source_identity = (
                    source_custody.read_descriptor_identity(
                        record["source_descriptor"]["path"],
                        label=f"{label} held source evidence[{position}]",
                        maximum=maximum_bytes,
                        capture=True,
                    )
                )
                if (
                    source_payload is None
                    or source_descriptor != record["source_descriptor"]
                    or source_identity != record["source_identity"]
                ):
                    _fail(f"{label} source evidence[{position}] changed before commit")
                descriptor, identity, _disposition = (
                    custody.commit_or_adopt_exact_identity(
                        f"{output_relative}/{record['target_name']}",
                        source_payload,
                        label=f"{label} output evidence[{position}]",
                        mode=0o444,
                        create_parents=False,
                        after_publish_step=callback(
                            f"leaf:{record['target_name']}"
                        ),
                    )
                )
                output_descriptors.append(descriptor)
                output_identities.append(identity)

            if custody.list_directory_names(
                output_relative, label=f"{label} completed output namespace"
            ) != tuple(sorted((*baseline_names, *ordered_targets))):
                _fail(f"{label} completed output namespace drifted")
            if capture_baseline() != baseline_records:
                _fail(f"{label} baseline output namespace drifted")

            expected_receipt = _seal(
                {
                    "schema_version": 1,
                    "artifact_kind": RECEIPT_KIND_V1,
                    "status": "committed_child_evidence_group",
                    "output_directory": output_relative,
                    "output_directory_identity": list(output_identity),
                    "intent": intent_descriptor,
                    "intent_sha256": intent["intent_sha256"],
                    "leaves": [
                        {
                            "target_name": record["target_name"],
                            "source_name": record["source_name"],
                            "source": record["source_descriptor"],
                            "output": output_descriptor,
                            "output_identity": list(output_leaf_identity),
                        }
                        for record, output_descriptor, output_leaf_identity in zip(
                            source_records,
                            output_descriptors,
                            output_identities,
                            strict=True,
                        )
                    ],
                },
                "receipt_sha256",
            )
            receipt_payload = _canonical_bytes(expected_receipt)
            receipt_descriptor, committed_receipt_identity, _receipt_disposition = (
                custody.commit_or_adopt_exact_identity(
                    f"{RECEIPT_ROOT_V1}/{receipt_name}",
                    receipt_payload,
                    label=f"{label} group receipt",
                    mode=0o444,
                    create_parents=False,
                    after_publish_step=callback("receipt"),
                )
            )
            cold_descriptor, cold_receipt, cold_receipt_identity = (
                custody.read_descriptor_identity(
                    receipt_descriptor["path"],
                    label=f"{label} committed group receipt",
                    maximum=MAX_GROUP_METADATA_BYTES,
                    capture=True,
                )
            )
            if (
                cold_descriptor != receipt_descriptor
                or cold_receipt != receipt_payload
                or cold_receipt_identity != committed_receipt_identity
            ):
                _fail(f"{label} group receipt changed after commit")
            parsed_receipt = _load_canonical_object(
                receipt_payload, label=f"{label} group receipt"
            )
            if _validated_receipt(
                parsed_receipt,
                output_relative=output_relative,
                output_identity=output_identity,
                intent_descriptor=intent_descriptor,
                intent_sha256=intent["intent_sha256"],
                source_records=source_records,
            ) != output_identities:
                _fail(f"{label} group receipt output identities drifted")
            return tuple(output_descriptors)
    except PublicationChildEvidenceMaterializerV1Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise PublicationChildEvidenceMaterializerV1Error(
            f"{label} physical materialization failed"
        ) from error


__all__ = [
    "INTENT_KIND_V1",
    "INTENT_ROOT_V1",
    "PublicationChildEvidenceMaterializerV1Error",
    "RECEIPT_KIND_V1",
    "RECEIPT_ROOT_V1",
    "materialize_publication_child_evidence_group_v1",
]
