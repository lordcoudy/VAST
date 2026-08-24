#!/usr/bin/env python3
"""Pure closed catalog for a persisted Q4 validation graph candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_backend_runtime_qualification_v4_catalog"
STATUS = "persisted_validation_graph_candidate"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)
COORDINATE_FIELDS = (
    "system", "codec", "topology_kind", "policy", "deadline_ms", "cell_index",
)

Q4_INPUT_SCHEMA_VERSION = 4
Q4_INPUT_KIND = "vast_backend_runtime_qualification_v4_input_index"
Q4_VALIDATOR_SCHEMA_VERSION = 1
Q4_VALIDATOR_KIND = "vast_backend_runtime_validator_authority_q4"
RUNNER_AUTHORITY_SCHEMA_VERSION = 1
RUNNER_AUTHORITY_KIND = "vast_backend_runtime_validation_runner_authority"
ABI_V3_SCHEMA_VERSION = 3
ABI_V3_KIND = "vast_backend_publication_launcher_invocation_v3"
RECORDS_V2_SCHEMA_VERSION = 2
RECORDS_V2_CONTEXT_KIND = "vast_backend_runtime_validation_system_context_v2"
RECORDS_V2_REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RECORDS_V2_RECORD_KIND = "vast_backend_runtime_cell_validation_record_v2"
RECORDS_V2_SHARD_KIND = "vast_backend_runtime_validation_system_shard_v2"
RECORDS_V2_INDEX_KIND = "vast_backend_runtime_validation_record_set_index_v2"

_SHA_PATTERN = r"[0-9a-f]{64}"
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind", "descriptor",
    "content_identity_sha256",
})
_INDEX_GLOBAL_FIELDS = frozenset({
    "q4_input_ref", "q4_input_sha256",
    "q4_validator_authority_ref", "q4_validator_authority_sha256",
    "runner_authority_ref", "runner_authority_sha256",
    "publication_launcher_invocation_v3_ref",
    "publication_launcher_invocation_v3_sha256",
    "runner_invocation_identity_sha256",
})
_INDEX_SHARD_FIELDS = frozenset({
    "system", "system_shard_ref", "system_shard_sha256",
    "context_ref", "context_sha256", "validation_record_set_sha256",
})
_INDEX_FLAT_FIELDS = frozenset({"coordinate", "validation_record_ref"})
_INDEX_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "validation_records_authenticated",
    *_INDEX_GLOBAL_FIELDS, "system_shards", "system_shard_set_sha256",
    "validation_records", "validation_record_global_set_sha256",
    "coverage", "index_sha256",
})
_CELL_FIELDS = frozenset({
    "coordinate", "validation_request_ref", "validation_record_ref",
})
_COVERAGE = {
    "system_count": 4, "contexts_per_system": 1, "shards_per_system": 1,
    "cells_per_system": 140, "validation_request_count": 560,
    "validation_record_count": 560,
}
_COVERAGE_FIELDS = frozenset(_COVERAGE)
_CATALOG_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "qualification_accepted",
    "trusted_replay_completed", "deterministic_replay_assessed",
    "post_run_per_arm_evidence_required",
    "configuration_evidence_accepted_mutated", "authorization_eligible",
    "execution_authorized", "validation_records_authenticated",
    "q4_input_ref", "q4_input_sha256", "q4_validator_authority_ref",
    "q4_validator_authority_sha256", "runner_authority_ref",
    "runner_authority_sha256", "publication_launcher_invocation_v3_ref",
    "publication_launcher_invocation_v3_sha256",
    "runner_invocation_identity_sha256", "records_v2_global_index_ref",
    "records_v2_global_index_sha256", "system_graphs",
    "system_context_set_sha256", "system_shard_set_sha256",
    "validation_cells", "validation_request_global_set_sha256",
    "validation_record_global_set_sha256", "coverage", "catalog_sha256",
})


class BackendRuntimeQualificationV4CatalogError(ValueError):
    """The candidate catalog, a supplied graph, or an external pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeQualificationV4CatalogError(message)


def canonical_identity(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeQualificationV4CatalogError(
            "catalog material is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str
             and re.fullmatch(_SHA_PATTERN, value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _path(value: Any, label: str) -> str:
    _require(
        type(value) is str and bool(value)
        and not value.startswith(("/", "\\")) and not value.endswith("/")
        and "\\" not in value and ":" not in value and "\x00" not in value
        and "//" not in value,
        f"{label} path is unsafe",
    )
    parts = value.split("/")
    _require(all(
        part not in ("", ".", "..") and not part.endswith((".", " "))
        and not any(ord(character) < 32 for character in part)
        and part.split(".", 1)[0].upper() not in _RESERVED
        for part in parts
    ), f"{label} path is unsafe")
    return value


def _typed_ref(
    value: Any, label: str, *, schema_version: int, artifact_kind: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _TYPED_REF_FIELDS,
             f"{label} typed reference fields drifted")
    _require(type(value.get("artifact_schema_version")) is int
             and value.get("artifact_schema_version") == schema_version,
             f"{label} schema version drifted")
    _require(type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == artifact_kind,
             f"{label} artifact kind drifted")
    descriptor = value.get("descriptor")
    _require(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    size = descriptor.get("size_bytes")
    _require(type(size) is int and 0 < size <= 8 * 1024 * 1024 * 1024,
             f"{label} size is invalid")
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": {
            "path": _path(descriptor.get("path"), label),
            "size_bytes": size,
            "sha256": _sha(descriptor.get("sha256"), f"{label} file"),
        },
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} semantic"
        ),
    }


def _pinned_ref(
    value: Any, pin: Any, label: str, *, schema_version: int,
    artifact_kind: str,
) -> dict[str, Any]:
    checked = _typed_ref(
        value, label, schema_version=schema_version, artifact_kind=artifact_kind,
    )
    _require(checked["content_identity_sha256"] == _sha(pin, label),
             f"{label} semantic pin drifted")
    return checked


def _deadline_position(value: Any) -> int:
    _require(type(value) in {int, float} and math.isfinite(float(value)),
             "deadline type drifted")
    positions = [
        position for position, expected in enumerate(DEADLINES_MS)
        if type(value) is type(expected) and value == expected
    ]
    _require(len(positions) == 1, "deadline value/type drifted")
    return positions[0]


def _coordinate_for_index(cell_index: int) -> dict[str, Any]:
    _require(type(cell_index) is int and 0 <= cell_index < 560,
             "cell index is invalid")
    remaining, deadline_position = divmod(cell_index, len(DEADLINES_MS))
    remaining, policy_position = divmod(remaining, len(POLICIES))
    remaining, topology_position = divmod(remaining, len(TOPOLOGIES))
    system_codec_position, codec_position = divmod(remaining, len(CODECS))
    return {
        "system": SYSTEMS[system_codec_position],
        "codec": CODECS[codec_position],
        "topology_kind": TOPOLOGIES[topology_position],
        "policy": POLICIES[policy_position],
        "deadline_ms": DEADLINES_MS[deadline_position],
        "cell_index": cell_index,
    }


def _coordinate(value: Any, expected_index: int) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == set(COORDINATE_FIELDS),
             "coordinate fields drifted")
    system = value.get("system")
    codec = value.get("codec")
    topology = value.get("topology_kind")
    policy = value.get("policy")
    deadline = value.get("deadline_ms")
    cell_index = value.get("cell_index")
    _require(type(system) is str and system in SYSTEMS
             and type(codec) is str and codec in CODECS
             and type(topology) is str and topology in TOPOLOGIES
             and type(policy) is str and policy in POLICIES,
             "coordinate value drifted")
    _deadline_position(deadline)
    _require(type(cell_index) is int and cell_index == expected_index,
             "coordinate ordinal drifted")
    checked = {field: copy.deepcopy(value[field]) for field in COORDINATE_FIELDS}
    _require(checked == _coordinate_for_index(expected_index),
             "coordinate ordering drifted")
    return checked


def _unsigned_identity(value: Mapping[str, Any], field: str) -> str:
    return canonical_identity({
        key: copy.deepcopy(item) for key, item in value.items() if key != field
    })


def _distinct_refs(references: Sequence[Mapping[str, Any]]) -> None:
    paths = [item["descriptor"]["path"].casefold() for item in references]
    files = [item["descriptor"]["sha256"] for item in references]
    contents = [item["content_identity_sha256"] for item in references]
    _require(len(paths) == len(set(paths)), "typed reference path is duplicated")
    _require(len(files) == len(set(files)),
             "typed reference file identity is duplicated")
    _require(len(contents) == len(set(contents)),
             "typed reference semantic identity is duplicated")


def _assert_catalog_identity_namespace(
    value: Mapping[str, Any], *, catalog_sha256: Any | None = None,
) -> None:
    references: list[tuple[Mapping[str, Any], str | None]] = [
        (value["q4_input_ref"], "q4_input"),
        (value["q4_validator_authority_ref"], "q4_validator_authority"),
        (value["runner_authority_ref"], "runner_authority"),
        (
            value["publication_launcher_invocation_v3_ref"],
            "publication_launcher_invocation_v3",
        ),
        (value["records_v2_global_index_ref"], "records_v2_global_index"),
    ]
    aggregates: list[tuple[str, str]] = [
        ("q4_input", value["q4_input_sha256"]),
        ("q4_validator_authority", value["q4_validator_authority_sha256"]),
        ("runner_authority", value["runner_authority_sha256"]),
        (
            "publication_launcher_invocation_v3",
            value["publication_launcher_invocation_v3_sha256"],
        ),
        ("runner_invocation", value["runner_invocation_identity_sha256"]),
        ("records_v2_global_index", value["records_v2_global_index_sha256"]),
    ]
    for item in value["system_graphs"]:
        system = item["system"]
        context_label = f"system_context:{system}"
        shard_label = f"system_shard:{system}"
        references.extend((
            (item["context_ref"], context_label),
            (item["system_shard_ref"], shard_label),
        ))
        aggregates.extend((
            (context_label, item["context_sha256"]),
            (shard_label, item["system_shard_sha256"]),
            (
                f"validation_record_set:{system}",
                item["validation_record_set_sha256"],
            ),
        ))
    references.extend(
        (item["validation_request_ref"], None)
        for item in value["validation_cells"]
    )
    references.extend(
        (item["validation_record_ref"], None)
        for item in value["validation_cells"]
    )
    aggregates.extend((
        ("system_context_set", value["system_context_set_sha256"]),
        ("system_shard_set", value["system_shard_set_sha256"]),
        (
            "validation_request_global_set",
            value["validation_request_global_set_sha256"],
        ),
        (
            "validation_record_global_set",
            value["validation_record_global_set_sha256"],
        ),
    ))
    if catalog_sha256 is not None:
        aggregates.append(("catalog", _sha(catalog_sha256, "catalog")))

    checked_aggregates = [
        (label, _sha(identity, f"{label} aggregate"))
        for label, identity in aggregates
    ]
    aggregate_identities = [identity for _, identity in checked_aggregates]
    _require(len(aggregate_identities) == len(set(aggregate_identities)),
             "aggregate identity namespace collided")
    labels_by_identity = {
        identity: label for label, identity in checked_aggregates
    }
    for reference, allowed_label in references:
        file_identity = reference["descriptor"]["sha256"]
        content_identity = reference["content_identity_sha256"]
        _require(file_identity not in labels_by_identity,
                 "artifact file identity collided with an aggregate")
        collision = labels_by_identity.get(content_identity)
        _require(collision is None or collision == allowed_label,
                 "artifact semantic identity collided with an aggregate")


def _root_refs(
    *, q4_input_ref: Any, q4_validator_authority_ref: Any,
    runner_authority_ref: Any, publication_launcher_invocation_v3_ref: Any,
    expected_q4_input_sha256: Any,
    expected_q4_validator_authority_sha256: Any,
    expected_runner_authority_sha256: Any,
    expected_publication_launcher_invocation_v3_sha256: Any,
) -> dict[str, Any]:
    return {
        "q4_input_ref": _pinned_ref(
            q4_input_ref, expected_q4_input_sha256, "Q4 input",
            schema_version=Q4_INPUT_SCHEMA_VERSION, artifact_kind=Q4_INPUT_KIND,
        ),
        "q4_validator_authority_ref": _pinned_ref(
            q4_validator_authority_ref,
            expected_q4_validator_authority_sha256, "Q4 validator authority",
            schema_version=Q4_VALIDATOR_SCHEMA_VERSION,
            artifact_kind=Q4_VALIDATOR_KIND,
        ),
        "runner_authority_ref": _pinned_ref(
            runner_authority_ref, expected_runner_authority_sha256,
            "runner authority", schema_version=RUNNER_AUTHORITY_SCHEMA_VERSION,
            artifact_kind=RUNNER_AUTHORITY_KIND,
        ),
        "publication_launcher_invocation_v3_ref": _pinned_ref(
            publication_launcher_invocation_v3_ref,
            expected_publication_launcher_invocation_v3_sha256,
            "launcher invocation ABI v3", schema_version=ABI_V3_SCHEMA_VERSION,
            artifact_kind=ABI_V3_KIND,
        ),
    }


def _coverage(value: Any, *, index: bool = False) -> dict[str, int]:
    expected = ({
        "system_count": 4, "cells_per_system": 140,
        "validation_record_count": 560,
    } if index else _COVERAGE)
    _require(type(value) is dict and set(value) == set(expected),
             "coverage fields drifted")
    _require(all(type(value[field]) is int and value[field] == amount
                 for field, amount in expected.items()),
             "coverage values drifted")
    return copy.deepcopy(expected)


def _record_index(
    value: Any, *, roots: Mapping[str, Any],
    expected_semantic_sha256: Any,
    expected_runner_invocation_identity_sha256: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    _require(type(value) is dict and set(value) == _INDEX_FIELDS,
             "records-v2 global index fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == RECORDS_V2_SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == RECORDS_V2_INDEX_KIND
             and type(value.get("status")) is str
             and value.get("status") == "persisted_for_deterministic_replay_v2",
             "records-v2 global index header drifted")
    _require(value.get("authorization_eligible") is False
             and value.get("execution_authorized") is False
             and value.get("validation_records_authenticated") is False,
             "records-v2 global index made an authorizing claim")

    root_pairs = (
        ("q4_input_ref", "q4_input_sha256"),
        ("q4_validator_authority_ref", "q4_validator_authority_sha256"),
        ("runner_authority_ref", "runner_authority_sha256"),
        ("publication_launcher_invocation_v3_ref",
         "publication_launcher_invocation_v3_sha256"),
    )
    for ref_field, sha_field in root_pairs:
        _require(value.get(ref_field) == roots[ref_field]
                 and value.get(sha_field)
                 == roots[ref_field]["content_identity_sha256"],
                 f"records-v2 index {ref_field} drifted")
    invocation_sha = _sha(
        expected_runner_invocation_identity_sha256,
        "expected runner invocation identity",
    )
    _require(value.get("runner_invocation_identity_sha256") == invocation_sha,
             "records-v2 runner invocation identity drifted")

    raw_systems = value.get("system_shards")
    _require(type(raw_systems) is list and len(raw_systems) == len(SYSTEMS),
             "records-v2 index requires four system graphs")
    systems: list[dict[str, Any]] = []
    for position, system in enumerate(SYSTEMS):
        item = raw_systems[position]
        _require(type(item) is dict and set(item) == _INDEX_SHARD_FIELDS
                 and type(item.get("system")) is str
                 and item.get("system") == system,
                 "records-v2 system graph membership/order drifted")
        shard = _typed_ref(
            item.get("system_shard_ref"), f"{system} shard",
            schema_version=RECORDS_V2_SCHEMA_VERSION,
            artifact_kind=RECORDS_V2_SHARD_KIND,
        )
        context = _typed_ref(
            item.get("context_ref"), f"{system} context",
            schema_version=RECORDS_V2_SCHEMA_VERSION,
            artifact_kind=RECORDS_V2_CONTEXT_KIND,
        )
        shard_sha = _sha(item.get("system_shard_sha256"), f"{system} shard")
        context_sha = _sha(item.get("context_sha256"), f"{system} context")
        _require(shard["content_identity_sha256"] == shard_sha
                 and context["content_identity_sha256"] == context_sha,
                 "records-v2 system graph semantic reference drifted")
        systems.append({
            "system": system,
            "system_shard_ref": shard,
            "system_shard_sha256": shard_sha,
            "context_ref": context,
            "context_sha256": context_sha,
            "validation_record_set_sha256": _sha(
                item.get("validation_record_set_sha256"),
                f"{system} validation-record set",
            ),
        })
    _require(value.get("system_shard_set_sha256")
             == canonical_identity(systems),
             "records-v2 system-shard set commitment drifted")

    raw_records = value.get("validation_records")
    _require(type(raw_records) is list and len(raw_records) == 560,
             "records-v2 index requires exactly 560 records")
    flat: list[dict[str, Any]] = []
    for position, item in enumerate(raw_records):
        _require(type(item) is dict and set(item) == _INDEX_FLAT_FIELDS,
                 "records-v2 flattened entry fields drifted")
        flat.append({
            "coordinate": _coordinate(item.get("coordinate"), position),
            "validation_record_ref": _typed_ref(
                item.get("validation_record_ref"),
                f"validation record {position}",
                schema_version=RECORDS_V2_SCHEMA_VERSION,
                artifact_kind=RECORDS_V2_RECORD_KIND,
            ),
        })
    for position, system in enumerate(SYSTEMS):
        first = position * 140
        shard_entries = [
            {
                **copy.deepcopy(item["coordinate"]),
                "validation_record_ref": copy.deepcopy(
                    item["validation_record_ref"]
                ),
            }
            for item in flat[first:first + 140]
        ]
        _require(
            systems[position]["validation_record_set_sha256"]
            == canonical_identity(shard_entries),
            f"{system} validation-record set commitment drifted",
        )
    _require(value.get("validation_record_global_set_sha256")
             == canonical_identity(flat),
             "records-v2 global record-set commitment drifted")
    _coverage(value.get("coverage"), index=True)
    index_sha = _sha(value.get("index_sha256"), "records-v2 global index")
    _require(index_sha == _unsigned_identity(value, "index_sha256")
             == _sha(expected_semantic_sha256,
                     "expected records-v2 global index"),
             "records-v2 global index semantic identity drifted")
    return copy.deepcopy(value), systems, flat


def _ordered_refs(
    value: Any, *, count: int, label: str, artifact_kind: str,
) -> list[dict[str, Any]]:
    _require(type(value) in {list, tuple} and len(value) == count,
             f"{label} membership count drifted")
    return [
        _typed_ref(
            item, f"{label} {position}",
            schema_version=RECORDS_V2_SCHEMA_VERSION,
            artifact_kind=artifact_kind,
        )
        for position, item in enumerate(value)
    ]


def _catalog_material(
    *, q4_input_ref: Mapping[str, Any],
    q4_validator_authority_ref: Mapping[str, Any],
    runner_authority_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    records_v2_global_index: Mapping[str, Any],
    records_v2_global_index_ref: Mapping[str, Any],
    system_context_refs: Sequence[Mapping[str, Any]],
    system_shard_refs: Sequence[Mapping[str, Any]],
    validation_request_refs: Sequence[Mapping[str, Any]],
    validation_record_refs: Sequence[Mapping[str, Any]],
    expected_q4_input_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_records_v2_global_index_sha256: str,
    expected_system_context_set_sha256: str,
    expected_system_shard_set_sha256: str,
    expected_validation_request_global_set_sha256: str,
    expected_validation_record_global_set_sha256: str,
) -> dict[str, Any]:
    roots = _root_refs(
        q4_input_ref=q4_input_ref,
        q4_validator_authority_ref=q4_validator_authority_ref,
        runner_authority_ref=runner_authority_ref,
        publication_launcher_invocation_v3_ref=(
            publication_launcher_invocation_v3_ref
        ),
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
    )
    checked_index, index_systems, index_records = _record_index(
        records_v2_global_index, roots=roots,
        expected_semantic_sha256=expected_records_v2_global_index_sha256,
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    )
    index_ref = _pinned_ref(
        records_v2_global_index_ref,
        expected_records_v2_global_index_sha256, "records-v2 global index",
        schema_version=RECORDS_V2_SCHEMA_VERSION,
        artifact_kind=RECORDS_V2_INDEX_KIND,
    )
    _require(index_ref["content_identity_sha256"]
             == checked_index["index_sha256"],
             "records-v2 global index reference drifted")

    contexts = _ordered_refs(
        system_context_refs, count=4, label="system context",
        artifact_kind=RECORDS_V2_CONTEXT_KIND,
    )
    shards = _ordered_refs(
        system_shard_refs, count=4, label="system shard",
        artifact_kind=RECORDS_V2_SHARD_KIND,
    )
    requests = _ordered_refs(
        validation_request_refs, count=560, label="validation request",
        artifact_kind=RECORDS_V2_REQUEST_KIND,
    )
    records = _ordered_refs(
        validation_record_refs, count=560, label="validation record",
        artifact_kind=RECORDS_V2_RECORD_KIND,
    )
    _require(contexts == [item["context_ref"] for item in index_systems]
             and shards == [item["system_shard_ref"] for item in index_systems],
             "system context/shard parent membership drifted")
    _require(records == [item["validation_record_ref"]
                         for item in index_records],
             "validation-record membership/order drifted")

    system_graphs = copy.deepcopy(index_systems)
    context_projection = [
        {"system": item["system"], "context_ref": item["context_ref"],
         "context_sha256": item["context_sha256"]}
        for item in system_graphs
    ]
    context_root = canonical_identity(context_projection)
    shard_root = canonical_identity(system_graphs)
    request_projection = [
        {"coordinate": _coordinate_for_index(position),
         "validation_request_ref": requests[position]}
        for position in range(560)
    ]
    request_root = canonical_identity(request_projection)
    record_projection = [
        {"coordinate": _coordinate_for_index(position),
         "validation_record_ref": records[position]}
        for position in range(560)
    ]
    record_root = canonical_identity(record_projection)
    _require(context_root == _sha(
        expected_system_context_set_sha256, "expected system-context set"
    ), "system-context set root drifted")
    _require(shard_root == checked_index["system_shard_set_sha256"]
             == _sha(expected_system_shard_set_sha256,
                     "expected system-shard set"),
             "system-shard set root drifted")
    _require(request_root == _sha(
        expected_validation_request_global_set_sha256,
        "expected global validation-request set",
    ), "global validation-request set root drifted")
    _require(record_root == checked_index["validation_record_global_set_sha256"]
             == _sha(expected_validation_record_global_set_sha256,
                     "expected global validation-record set"),
             "global validation-record set root drifted")

    unique_refs = [
        roots["q4_input_ref"], roots["q4_validator_authority_ref"],
        roots["runner_authority_ref"],
        roots["publication_launcher_invocation_v3_ref"], index_ref,
        *contexts, *shards, *requests, *records,
    ]
    _distinct_refs(unique_refs)
    cells = [
        {"coordinate": _coordinate_for_index(position),
         "validation_request_ref": requests[position],
         "validation_record_ref": records[position]}
        for position in range(560)
    ]
    return {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "status": STATUS, "qualification_accepted": False,
        "trusted_replay_completed": False,
        "deterministic_replay_assessed": False,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
        "authorization_eligible": False, "execution_authorized": False,
        "validation_records_authenticated": False,
        "q4_input_ref": roots["q4_input_ref"],
        "q4_input_sha256": roots["q4_input_ref"]["content_identity_sha256"],
        "q4_validator_authority_ref": roots["q4_validator_authority_ref"],
        "q4_validator_authority_sha256": (
            roots["q4_validator_authority_ref"]["content_identity_sha256"]
        ),
        "runner_authority_ref": roots["runner_authority_ref"],
        "runner_authority_sha256": (
            roots["runner_authority_ref"]["content_identity_sha256"]
        ),
        "publication_launcher_invocation_v3_ref": (
            roots["publication_launcher_invocation_v3_ref"]
        ),
        "publication_launcher_invocation_v3_sha256": (
            roots["publication_launcher_invocation_v3_ref"]
            ["content_identity_sha256"]
        ),
        "runner_invocation_identity_sha256": _sha(
            expected_runner_invocation_identity_sha256,
            "expected runner invocation identity",
        ),
        "records_v2_global_index_ref": index_ref,
        "records_v2_global_index_sha256": checked_index["index_sha256"],
        "system_graphs": system_graphs,
        "system_context_set_sha256": context_root,
        "system_shard_set_sha256": shard_root,
        "validation_cells": cells,
        "validation_request_global_set_sha256": request_root,
        "validation_record_global_set_sha256": record_root,
        "coverage": copy.deepcopy(_COVERAGE),
    }


def _validate_catalog_shape(
    value: Any, expected: Mapping[str, Any], expected_catalog_sha256: Any,
) -> None:
    _require(type(value) is dict and set(value) == _CATALOG_FIELDS,
             "catalog fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND
             and type(value.get("status")) is str
             and value.get("status") == STATUS,
             "catalog header drifted")
    exact_flags = {
        "qualification_accepted": False,
        "trusted_replay_completed": False,
        "deterministic_replay_assessed": False,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
        "authorization_eligible": False,
        "execution_authorized": False,
        "validation_records_authenticated": False,
    }
    _require(all(value.get(field) is required
                 for field, required in exact_flags.items()),
             "catalog made an invalid evidence or authorization claim")

    root_specs = (
        ("q4_input_ref", Q4_INPUT_SCHEMA_VERSION, Q4_INPUT_KIND),
        ("q4_validator_authority_ref", Q4_VALIDATOR_SCHEMA_VERSION,
         Q4_VALIDATOR_KIND),
        ("runner_authority_ref", RUNNER_AUTHORITY_SCHEMA_VERSION,
         RUNNER_AUTHORITY_KIND),
        ("publication_launcher_invocation_v3_ref", ABI_V3_SCHEMA_VERSION,
         ABI_V3_KIND),
        ("records_v2_global_index_ref", RECORDS_V2_SCHEMA_VERSION,
         RECORDS_V2_INDEX_KIND),
    )
    for field, version, kind in root_specs:
        _require(_typed_ref(
            value.get(field), field, schema_version=version, artifact_kind=kind,
        ) == expected[field], f"catalog {field} drifted")
    for field in (
        "q4_input_sha256", "q4_validator_authority_sha256",
        "runner_authority_sha256",
        "publication_launcher_invocation_v3_sha256",
        "runner_invocation_identity_sha256",
        "records_v2_global_index_sha256", "system_context_set_sha256",
        "system_shard_set_sha256",
        "validation_request_global_set_sha256",
        "validation_record_global_set_sha256",
    ):
        _require(_sha(value.get(field), field) == expected[field],
                 f"catalog {field} drifted")

    raw_systems = value.get("system_graphs")
    _require(type(raw_systems) is list and len(raw_systems) == 4,
             "catalog system-graph membership drifted")
    checked_systems: list[dict[str, Any]] = []
    for position, system in enumerate(SYSTEMS):
        item = raw_systems[position]
        _require(type(item) is dict and set(item) == _INDEX_SHARD_FIELDS
                 and type(item.get("system")) is str
                 and item.get("system") == system,
                 "catalog system-graph fields/order drifted")
        checked_systems.append({
            "system": system,
            "system_shard_ref": _typed_ref(
                item.get("system_shard_ref"), f"catalog {system} shard",
                schema_version=RECORDS_V2_SCHEMA_VERSION,
                artifact_kind=RECORDS_V2_SHARD_KIND,
            ),
            "system_shard_sha256": _sha(
                item.get("system_shard_sha256"), f"catalog {system} shard"
            ),
            "context_ref": _typed_ref(
                item.get("context_ref"), f"catalog {system} context",
                schema_version=RECORDS_V2_SCHEMA_VERSION,
                artifact_kind=RECORDS_V2_CONTEXT_KIND,
            ),
            "context_sha256": _sha(
                item.get("context_sha256"), f"catalog {system} context"
            ),
            "validation_record_set_sha256": _sha(
                item.get("validation_record_set_sha256"),
                f"catalog {system} record set",
            ),
        })
    _require(checked_systems == expected["system_graphs"],
             "catalog system graphs drifted")

    raw_cells = value.get("validation_cells")
    _require(type(raw_cells) is list and len(raw_cells) == 560,
             "catalog requires exactly 560 validation cells")
    checked_cells: list[dict[str, Any]] = []
    for position, item in enumerate(raw_cells):
        _require(type(item) is dict and set(item) == _CELL_FIELDS,
                 "catalog validation-cell fields drifted")
        checked_cells.append({
            "coordinate": _coordinate(item.get("coordinate"), position),
            "validation_request_ref": _typed_ref(
                item.get("validation_request_ref"),
                f"catalog validation request {position}",
                schema_version=RECORDS_V2_SCHEMA_VERSION,
                artifact_kind=RECORDS_V2_REQUEST_KIND,
            ),
            "validation_record_ref": _typed_ref(
                item.get("validation_record_ref"),
                f"catalog validation record {position}",
                schema_version=RECORDS_V2_SCHEMA_VERSION,
                artifact_kind=RECORDS_V2_RECORD_KIND,
            ),
        })
    _require(checked_cells == expected["validation_cells"],
             "catalog validation-cell graph drifted")
    _require(_coverage(value.get("coverage")) == expected["coverage"],
             "catalog coverage drifted")
    catalog_sha = _sha(value.get("catalog_sha256"), "catalog")
    _require(catalog_sha == _unsigned_identity(value, "catalog_sha256")
             == _sha(expected_catalog_sha256, "expected catalog"),
             "catalog semantic identity drifted")
    expected_document = {**copy.deepcopy(expected), "catalog_sha256": catalog_sha}
    _require(value == expected_document, "catalog normalization drifted")


def build_backend_runtime_qualification_v4_catalog(
    *, q4_input_ref: Mapping[str, Any],
    q4_validator_authority_ref: Mapping[str, Any],
    runner_authority_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    records_v2_global_index: Mapping[str, Any],
    records_v2_global_index_ref: Mapping[str, Any],
    system_context_refs: Sequence[Mapping[str, Any]],
    system_shard_refs: Sequence[Mapping[str, Any]],
    validation_request_refs: Sequence[Mapping[str, Any]],
    validation_record_refs: Sequence[Mapping[str, Any]],
    expected_q4_input_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_records_v2_global_index_sha256: str,
    expected_system_context_set_sha256: str,
    expected_system_shard_set_sha256: str,
    expected_validation_request_global_set_sha256: str,
    expected_validation_record_global_set_sha256: str,
    expected_catalog_semantic_sha256: str,
) -> dict[str, Any]:
    expected_catalog_sha = _sha(
        expected_catalog_semantic_sha256, "expected catalog"
    )
    material = _catalog_material(
        q4_input_ref=q4_input_ref,
        q4_validator_authority_ref=q4_validator_authority_ref,
        runner_authority_ref=runner_authority_ref,
        publication_launcher_invocation_v3_ref=(
            publication_launcher_invocation_v3_ref
        ),
        records_v2_global_index=records_v2_global_index,
        records_v2_global_index_ref=records_v2_global_index_ref,
        system_context_refs=system_context_refs,
        system_shard_refs=system_shard_refs,
        validation_request_refs=validation_request_refs,
        validation_record_refs=validation_record_refs,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
        expected_records_v2_global_index_sha256=(
            expected_records_v2_global_index_sha256
        ),
        expected_system_context_set_sha256=(
            expected_system_context_set_sha256
        ),
        expected_system_shard_set_sha256=expected_system_shard_set_sha256,
        expected_validation_request_global_set_sha256=(
            expected_validation_request_global_set_sha256
        ),
        expected_validation_record_global_set_sha256=(
            expected_validation_record_global_set_sha256
        ),
    )
    catalog_sha = canonical_identity(material)
    _assert_catalog_identity_namespace(material, catalog_sha256=catalog_sha)
    _require(catalog_sha == expected_catalog_sha,
             "catalog external semantic pin drifted")
    value = {**material, "catalog_sha256": catalog_sha}
    _validate_catalog_shape(value, material, expected_catalog_sha)
    return copy.deepcopy(value)


def validate_backend_runtime_qualification_v4_catalog(
    value: Any, *, q4_input_ref: Mapping[str, Any],
    q4_validator_authority_ref: Mapping[str, Any],
    runner_authority_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    records_v2_global_index: Mapping[str, Any],
    records_v2_global_index_ref: Mapping[str, Any],
    system_context_refs: Sequence[Mapping[str, Any]],
    system_shard_refs: Sequence[Mapping[str, Any]],
    validation_request_refs: Sequence[Mapping[str, Any]],
    validation_record_refs: Sequence[Mapping[str, Any]],
    expected_q4_input_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_records_v2_global_index_sha256: str,
    expected_system_context_set_sha256: str,
    expected_system_shard_set_sha256: str,
    expected_validation_request_global_set_sha256: str,
    expected_validation_record_global_set_sha256: str,
    expected_catalog_semantic_sha256: str,
) -> dict[str, Any]:
    expected_catalog_sha = _sha(
        expected_catalog_semantic_sha256, "expected catalog"
    )
    material = _catalog_material(
        q4_input_ref=q4_input_ref,
        q4_validator_authority_ref=q4_validator_authority_ref,
        runner_authority_ref=runner_authority_ref,
        publication_launcher_invocation_v3_ref=(
            publication_launcher_invocation_v3_ref
        ),
        records_v2_global_index=records_v2_global_index,
        records_v2_global_index_ref=records_v2_global_index_ref,
        system_context_refs=system_context_refs,
        system_shard_refs=system_shard_refs,
        validation_request_refs=validation_request_refs,
        validation_record_refs=validation_record_refs,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
        expected_records_v2_global_index_sha256=(
            expected_records_v2_global_index_sha256
        ),
        expected_system_context_set_sha256=(
            expected_system_context_set_sha256
        ),
        expected_system_shard_set_sha256=expected_system_shard_set_sha256,
        expected_validation_request_global_set_sha256=(
            expected_validation_request_global_set_sha256
        ),
        expected_validation_record_global_set_sha256=(
            expected_validation_record_global_set_sha256
        ),
    )
    _assert_catalog_identity_namespace(
        material, catalog_sha256=expected_catalog_sha,
    )
    _validate_catalog_shape(value, material, expected_catalog_sha)
    return copy.deepcopy(value)


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND", "STATUS", "SYSTEMS", "CODECS",
    "TOPOLOGIES", "POLICIES", "DEADLINES_MS", "COORDINATE_FIELDS",
    "Q4_INPUT_SCHEMA_VERSION", "Q4_INPUT_KIND",
    "Q4_VALIDATOR_SCHEMA_VERSION", "Q4_VALIDATOR_KIND",
    "RUNNER_AUTHORITY_SCHEMA_VERSION", "RUNNER_AUTHORITY_KIND",
    "ABI_V3_SCHEMA_VERSION", "ABI_V3_KIND", "RECORDS_V2_SCHEMA_VERSION",
    "RECORDS_V2_CONTEXT_KIND", "RECORDS_V2_REQUEST_KIND",
    "RECORDS_V2_RECORD_KIND", "RECORDS_V2_SHARD_KIND",
    "RECORDS_V2_INDEX_KIND", "BackendRuntimeQualificationV4CatalogError",
    "canonical_identity", "build_backend_runtime_qualification_v4_catalog",
    "validate_backend_runtime_qualification_v4_catalog",
]
