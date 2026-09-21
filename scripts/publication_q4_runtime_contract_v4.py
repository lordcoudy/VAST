#!/usr/bin/env python3
"""Pure arbitrary-Q4 runtime ABI over physically prepared v3 inputs.

The builder deliberately does not inspect files, launch a process, qualify
evidence, or authorize execution.  It binds one of the exact frozen 560 Q4
coordinates to an externally self-hashed runtime-authority snapshot, the
matching frozen six-stream KPP codec corpus, and one caller-owned run identity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

import checkpoint_deepstream_publication_runtime_v3 as deepstream_runtime
import checkpoint_gstreamer_publication_runtime_v3 as gstreamer_runtime
import checkpoint_openvino_gva_publication_runtime_v3 as openvino_runtime
import checkpoint_savant_publication_runtime_v3 as savant_runtime
from backend_publication_launcher_invocation_v3 import (
    ARTIFACT_KIND as PUBLICATION_LAUNCHER_INVOCATION_KIND,
    SCHEMA_VERSION as PUBLICATION_LAUNCHER_INVOCATION_SCHEMA_VERSION,
    validate_publication_launcher_invocation_v3,
)
from publication_acceptance_evidence import (
    pre_finalization_acceptance_evidence_files,
)


SCHEMA_VERSION = 4
ARTIFACT_KIND = "vast_publication_runtime_contract_v4"
AUTHORITY_SNAPSHOT_KIND = "vast_publication_runtime_authority_snapshot_v4"
DATASET_BINDING_KIND = "vast_frozen_publication_dataset_binding_v4"
NATIVE_GRAPH_KIND = "vast_publication_native_runtime_graph_contract_v4"
RUNTIME_CANDIDATE_REGISTRY_KIND = (
    "vast_publication_q4_runtime_candidate_registry_v4"
)

SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only",
    "gpu_only",
    "static_hybrid",
    "heft",
    "deadline_aware_heft",
    "queue_aware_edf",
    "adaptive_weights",
)
DEADLINES_MS: tuple[int | float, ...] = (16.7, 33.3, 50, 100, 500)
UPSTREAM_IDENTITY_FIELDS = (
    "dataset_manifest_sha256",
    "policy_contract_sha256",
    "policy_qualification_receipt_sha256",
    "resource_contract_identity_sha256",
    "resource_qualification_receipt_sha256",
    "analytics_execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "model_parity_acceptance_binding_sha256",
)

WARMUP_S = 30
DURATION_S = 180
STREAMS = 6
SEED = 20260323
CELL_COUNT = 560
AUTHORITY_COUNT = 112

SCENARIO_BY_TOPOLOGY = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}
RUNTIME_MODULE_BY_SYSTEM = {
    "deepstream": deepstream_runtime,
    "savant": savant_runtime,
    "openvino_gva": openvino_runtime,
    "gstreamer_custom": gstreamer_runtime,
}
RUNTIME_INPUT_KEY_BY_SYSTEM = {
    system: module.RUNTIME_INPUT_KEY
    for system, module in RUNTIME_MODULE_BY_SYSTEM.items()
}
RUNTIME_INPUT_KIND_BY_SYSTEM = {
    system: module.RUNTIME_INPUT_KIND
    for system, module in RUNTIME_MODULE_BY_SYSTEM.items()
}

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_TYPED_REF_FIELDS = frozenset(
    {
        "artifact_schema_version",
        "artifact_kind",
        "descriptor",
        "content_identity_sha256",
    }
)
_AUTHORITY_COORDINATE_FIELDS = frozenset(
    {"system", "codec", "topology_kind", "policy"}
)
_CELL_COORDINATE_FIELDS = frozenset(
    {*_AUTHORITY_COORDINATE_FIELDS, "deadline_ms", "cell_index"}
)
_DATASET_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "codec_variant",
        "dataset",
        "dataset_binding_sha256",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "coordinate",
        "dataset_binding_sha256",
        "upstream_identities",
        "runtime_authority_ref",
        "runtime_authority_sha256",
        "runtime_authority_set_sha256",
        "runtime_binding_identity_v4_sha256",
        "launcher_runtime_authority_ref",
        "launcher_runtime_authority_sha256",
        "publication_launcher_invocation_v3_ref",
        "publication_launcher_invocation_v3",
        "q4_validator_authority_ref",
        "q4_validator_authority_sha256",
        "runner_authority_ref",
        "runner_authority_sha256",
        "runner_invocation_identity_sha256",
        "runtime_input_template",
        "authority_snapshot_sha256",
    }
)
_GRAPH_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "coordinate",
        "run_id",
        "duration_s",
        "authority_snapshot_sha256",
        "dataset_binding_sha256",
        "upstream_identities",
        "runtime_authority_ref",
        "runtime_authority_sha256",
        "runtime_authority_set_sha256",
        "runtime_binding_identity_v4_sha256",
        "launcher_runtime_authority_ref",
        "launcher_runtime_authority_sha256",
        "publication_launcher_invocation_v3_ref",
        "publication_launcher_invocation_v3_sha256",
        "q4_validator_authority_ref",
        "q4_validator_authority_sha256",
        "runner_authority_ref",
        "runner_authority_sha256",
        "runner_invocation_identity_sha256",
        "runtime_inputs_sha256",
        "launcher_evidence_files",
        "graph_contract_sha256",
    }
)
_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "coordinate",
        "run_id",
        "duration_s",
        "authority_snapshot_sha256",
        "dataset_binding_sha256",
        "runtime_inputs",
        "native_graph_contract",
        "contract_sha256",
    }
)
_REGISTRY_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "accepted_as_input",
        "authorization_eligible",
        "execution_authorized",
        "dataset_bindings",
        "authority_snapshots",
        "registry_sha256",
    }
)
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class PublicationQ4RuntimeContractV4Error(ValueError):
    """The arbitrary-Q4 runtime material is ambiguous or cross-bound wrongly."""


def _fail(message: str) -> None:
    raise PublicationQ4RuntimeContractV4Error(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _strict_json(
    value: Any, *, active: set[int] | None = None, depth: int = 0
) -> None:
    _require(depth <= 64, "runtime v4 JSON nesting is excessive")
    if active is None:
        active = set()
    value_type = type(value)
    if value is None or value_type in {str, bool, int}:
        return
    if value_type is float:
        _require(math.isfinite(value), "runtime v4 JSON contains non-finite number")
        return
    _require(value_type in {dict, list}, "runtime v4 contains a non-JSON type")
    identity = id(value)
    _require(identity not in active, "runtime v4 JSON contains a cycle")
    active.add(identity)
    try:
        if value_type is dict:
            _require(
                all(type(key) is str for key in value),
                "runtime v4 JSON object has a non-string key",
            )
            for item in value.values():
                _strict_json(item, active=active, depth=depth + 1)
        else:
            for item in value:
                _strict_json(item, active=active, depth=depth + 1)
    finally:
        active.remove(identity)


def _canonical_bytes(value: Any) -> bytes:
    _strict_json(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise PublicationQ4RuntimeContractV4Error(
            "runtime v4 material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and _SHA_RE.fullmatch(value) is not None,
        f"{label} is not a SHA-256 identity",
    )
    return value


def _relative_path(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} path is invalid")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and not posix.is_absolute()
        and not windows.is_absolute()
        and posix.as_posix() == value
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


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    size = value.get("size_bytes")
    _require(
        type(size) is int and 0 < size <= 8 * 1024 * 1024 * 1024,
        f"{label} descriptor size is invalid",
    )
    return {
        "path": _relative_path(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _typed_ref(
    value: Any,
    label: str,
    *,
    schema_version: int,
    artifact_kind: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _TYPED_REF_FIELDS,
        f"{label} typed-reference fields drifted",
    )
    _require(
        type(value.get("artifact_schema_version")) is int
        and value.get("artifact_schema_version") == schema_version
        and type(value.get("artifact_kind")) is str
        and value.get("artifact_kind") == artifact_kind,
        f"{label} typed-reference identity drifted",
    )
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": _descriptor(value.get("descriptor"), label),
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} semantic"
        ),
    }


def _deadline(value: Any) -> int | float:
    _require(type(value) in {int, float}, "Q4 deadline type drifted")
    matches = [
        candidate
        for candidate in DEADLINES_MS
        if type(value) is type(candidate) and value == candidate
    ]
    _require(len(matches) == 1, "Q4 deadline value/type drifted")
    return matches[0]


def coordinate_for_q4_cell_index_v4(cell_index: int) -> dict[str, Any]:
    """Return the sole canonical Q4 coordinate for ordinal 0..559."""

    _require(
        type(cell_index) is int and 0 <= cell_index < CELL_COUNT,
        "Q4 cell_index is outside the frozen matrix",
    )
    remaining, deadline_position = divmod(cell_index, len(DEADLINES_MS))
    remaining, policy_position = divmod(remaining, len(POLICIES))
    remaining, topology_position = divmod(remaining, len(TOPOLOGIES))
    system_codec_position, codec_position = divmod(remaining, len(CODECS))
    system_position = system_codec_position
    return {
        "system": SYSTEMS[system_position],
        "codec": CODECS[codec_position],
        "topology_kind": TOPOLOGIES[topology_position],
        "policy": POLICIES[policy_position],
        "deadline_ms": DEADLINES_MS[deadline_position],
        "cell_index": cell_index,
    }


def _cell_coordinate(value: Any) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _CELL_COORDINATE_FIELDS,
        "Q4 coordinate fields drifted",
    )
    system = value.get("system")
    codec = value.get("codec")
    topology = value.get("topology_kind")
    policy = value.get("policy")
    deadline = _deadline(value.get("deadline_ms"))
    index = value.get("cell_index")
    _require(
        type(system) is str
        and system in SYSTEMS
        and type(codec) is str
        and codec in CODECS
        and type(topology) is str
        and topology in TOPOLOGIES
        and type(policy) is str
        and policy in POLICIES
        and type(index) is int,
        "Q4 coordinate value drifted",
    )
    normalized = {
        "system": system,
        "codec": codec,
        "topology_kind": topology,
        "policy": policy,
        "deadline_ms": deadline,
        "cell_index": index,
    }
    _require(
        coordinate_for_q4_cell_index_v4(index) == normalized,
        "Q4 coordinate does not match its global ordinal",
    )
    return normalized


def _authority_coordinate(value: Any) -> dict[str, str]:
    _require(
        type(value) is dict and set(value) == _AUTHORITY_COORDINATE_FIELDS,
        "runtime authority coordinate fields drifted",
    )
    result = {key: value.get(key) for key in _AUTHORITY_COORDINATE_FIELDS}
    _require(
        result["system"] in SYSTEMS
        and result["codec"] in CODECS
        and result["topology_kind"] in TOPOLOGIES
        and result["policy"] in POLICIES
        and all(type(item) is str for item in result.values()),
        "runtime authority coordinate drifted",
    )
    return {
        key: str(value[key])
        for key in ("system", "codec", "topology_kind", "policy")
    }


def qualification_launcher_evidence_files_v4(policy: str) -> tuple[str, ...]:
    """Return the policy-aware direct-child evidence namespace for Q4."""

    _require(
        type(policy) is str and policy in POLICIES,
        "Q4 evidence policy is invalid",
    )
    values = (
        *pre_finalization_acceptance_evidence_files(policy),
        "resource_intervals.csv",
        "fanout_work_counters.csv",
        "checkpoint_publication_candidate.json",
    )
    _require(len(values) == len(set(values)), "Q4 evidence namespace aliases")
    return values


def _dataset_binding(value: Any) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DATASET_FIELDS,
        "dataset binding fields drifted",
    )
    codec = value.get("codec_variant")
    dataset = value.get("dataset")
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == DATASET_BINDING_KIND
        and value.get("status") == "frozen_publication_codec_corpus"
        and type(codec) is str
        and codec in CODECS
        and type(dataset) is dict
        and set(dataset)
        == {"name", "codec_variant", "logical_stream_instances", "streams"}
        and dataset.get("name") == f"kpp_iss_publication_v3_{codec}"
        and dataset.get("codec_variant") == codec
        and dataset.get("logical_stream_instances") == STREAMS,
        "dataset binding identity drifted",
    )
    streams = dataset.get("streams")
    _require(type(streams) is list and len(streams) == STREAMS, "dataset streams drifted")
    checked: list[dict[str, Any]] = []
    for index, stream in enumerate(streams):
        _require(
            type(stream) is dict
            and set(stream) == {"stream_id", "codec_name", "sha256"}
            and stream.get("stream_id") == index
            and stream.get("codec_name") == codec,
            f"dataset stream {index} coordinate drifted",
        )
        checked.append(
            {
                "stream_id": index,
                "codec_name": codec,
                "sha256": _sha(stream.get("sha256"), f"dataset stream {index}"),
            }
        )
    _require(
        len({item["sha256"] for item in checked}) == 2
        and all(checked[index]["sha256"] == checked[0]["sha256"] for index in range(5))
        and checked[5]["sha256"] != checked[0]["sha256"],
        "dataset stream/source topology drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "dataset_binding_sha256"}
    identity = _sha(value.get("dataset_binding_sha256"), "dataset binding")
    _require(identity == _canonical_sha(unsigned), "dataset binding self-hash drifted")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": DATASET_BINDING_KIND,
        "status": "frozen_publication_codec_corpus",
        "codec_variant": codec,
        "dataset": {
            "name": dataset["name"],
            "codec_variant": codec,
            "logical_stream_instances": STREAMS,
            "streams": checked,
        },
        "dataset_binding_sha256": identity,
    }


def build_publication_q4_dataset_binding_v4(
    *, codec_variant: str, front_gate_sha256: str, underbody_sha256: str
) -> dict[str, Any]:
    """Build the exact five-front/one-underbody frozen codec binding."""

    _require(
        type(codec_variant) is str and codec_variant in CODECS,
        "Q4 dataset codec variant is invalid",
    )
    front = _sha(front_gate_sha256, "front-gate source")
    underbody = _sha(underbody_sha256, "underbody source")
    _require(front != underbody, "Q4 front/underbody source identities alias")
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": DATASET_BINDING_KIND,
        "status": "frozen_publication_codec_corpus",
        "codec_variant": codec_variant,
        "dataset": {
            "name": f"kpp_iss_publication_v3_{codec_variant}",
            "codec_variant": codec_variant,
            "logical_stream_instances": STREAMS,
            "streams": [
                {
                    "stream_id": index,
                    "codec_name": codec_variant,
                    "sha256": front if index < STREAMS - 1 else underbody,
                }
                for index in range(STREAMS)
            ],
        },
    }
    return _dataset_binding(
        {**unsigned, "dataset_binding_sha256": _canonical_sha(unsigned)}
    )


def _runtime_template(
    value: Any, *, system: str, policy: str, dataset: Mapping[str, Any]
) -> dict[str, Any]:
    module = RUNTIME_MODULE_BY_SYSTEM[system]
    _require(
        type(value) is dict and set(value) == set(module.RUNTIME_FIELDS),
        f"{system} v3 runtime-input template fields drifted",
    )
    checked = copy.deepcopy(value)
    _require(
        checked.get("schema_version") == 3
        and checked.get("artifact_kind") == module.RUNTIME_INPUT_KIND,
        f"{system} v3 runtime-input template identity drifted",
    )
    _require(
        checked.get("defer_full_resource_acceptance") is True,
        f"{system} runtime must defer acceptance to physical Q4 replay",
    )
    evidence = checked.get("evidence_mapping")
    expected_evidence = qualification_launcher_evidence_files_v4(policy)
    _require(
        type(evidence) is dict
        and set(evidence) == set(expected_evidence)
        and len(set(evidence.values())) == len(evidence)
        and all(
            type(item) is str
            and PurePosixPath(item).name == item
            and item not in {
                "backend_publication_arm_contract.json",
                "backend_publication_launch_fence_v3.json",
                "backend_publication_output_receipt_v3.json",
            }
            for item in evidence.values()
        ),
        f"{system} v3 runtime evidence mapping drifted",
    )
    static_map = checked.get("static_hybrid_map")
    _require(
        (policy == "static_hybrid") == (type(static_map) is dict),
        f"{system} static-hybrid runtime binding drifted",
    )
    sources = checked.get("source_files")
    _require(
        type(sources) is list and len(sources) == 2,
        f"{system} runtime source descriptor coverage drifted",
    )
    source_hashes: set[str] = set()
    for position, source in enumerate(sources):
        _require(
            type(source) is dict
            and frozenset(source) in {
                frozenset({"path", "size_bytes", "sha256"}),
                frozenset(
                    {"path", "container_path", "size_bytes", "sha256"}
                ),
            },
            f"{system} runtime source descriptor[{position}] fields drifted",
        )
        _relative_path(source.get("path"), f"{system} runtime source[{position}]")
        size = source.get("size_bytes")
        _require(
            type(size) is int and size > 0,
            f"{system} runtime source descriptor[{position}] size drifted",
        )
        source_hashes.add(_sha(source.get("sha256"), f"{system} runtime source"))
    stream_hashes = {item["sha256"] for item in dataset["dataset"]["streams"]}
    _require(
        len(source_hashes) == 2 and source_hashes == stream_hashes,
        f"{system} runtime source/dataset binding drifted",
    )
    return checked


def _upstream(value: Any) -> dict[str, str]:
    _require(
        type(value) is dict and set(value) == set(UPSTREAM_IDENTITY_FIELDS),
        "runtime snapshot upstream identity fields drifted",
    )
    return {field: _sha(value[field], field) for field in UPSTREAM_IDENTITY_FIELDS}


def _authority_snapshot(
    value: Any, *, dataset: Mapping[str, Any]
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _SNAPSHOT_FIELDS,
        "runtime authority snapshot fields drifted",
    )
    coordinate = _authority_coordinate(value.get("coordinate"))
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == AUTHORITY_SNAPSHOT_KIND
        and value.get("status") == "physically_prepared_non_authorizing_runtime"
        and value.get("dataset_binding_sha256")
        == dataset["dataset_binding_sha256"]
        and coordinate["codec"] == dataset["codec_variant"],
        "runtime authority snapshot header/dataset binding drifted",
    )
    runtime_ref = _typed_ref(
        value.get("runtime_authority_ref"),
        "runtime authority",
        schema_version=2,
        artifact_kind="vast_backend_publication_runtime_authority_v2",
    )
    runtime_sha = _sha(value.get("runtime_authority_sha256"), "runtime authority")
    _require(
        runtime_ref["content_identity_sha256"] == runtime_sha,
        "runtime authority semantic reference drifted",
    )
    launcher_ref = _typed_ref(
        value.get("launcher_runtime_authority_ref"),
        "launcher runtime authority",
        schema_version=1,
        artifact_kind="vast_backend_publication_launcher_runtime_authority",
    )
    launcher_sha = _sha(
        value.get("launcher_runtime_authority_sha256"),
        "launcher runtime authority",
    )
    _require(
        launcher_ref["content_identity_sha256"] == launcher_sha,
        "launcher runtime authority semantic reference drifted",
    )
    try:
        invocation = validate_publication_launcher_invocation_v3(
            value.get("publication_launcher_invocation_v3")
        )
    except Exception as error:
        raise PublicationQ4RuntimeContractV4Error(
            f"publication launcher invocation v3 drifted: {error}"
        ) from error
    invocation_ref = _typed_ref(
        value.get("publication_launcher_invocation_v3_ref"),
        "publication launcher invocation v3",
        schema_version=PUBLICATION_LAUNCHER_INVOCATION_SCHEMA_VERSION,
        artifact_kind=PUBLICATION_LAUNCHER_INVOCATION_KIND,
    )
    _require(
        invocation_ref["content_identity_sha256"] == invocation["invocation_sha256"],
        "publication launcher invocation v3 reference drifted",
    )
    validator_ref = _typed_ref(
        value.get("q4_validator_authority_ref"),
        "Q4 validator authority",
        schema_version=1,
        artifact_kind="vast_backend_runtime_validator_authority_q4",
    )
    validator_sha = _sha(
        value.get("q4_validator_authority_sha256"), "Q4 validator authority"
    )
    _require(
        validator_ref["content_identity_sha256"] == validator_sha,
        "Q4 validator authority semantic reference drifted",
    )
    runner_ref = _typed_ref(
        value.get("runner_authority_ref"),
        "Q4 validation runner authority",
        schema_version=1,
        artifact_kind="vast_backend_runtime_validation_runner_authority",
    )
    runner_sha = _sha(value.get("runner_authority_sha256"), "Q4 runner authority")
    _require(
        runner_ref["content_identity_sha256"] == runner_sha,
        "Q4 runner authority semantic reference drifted",
    )
    template = _runtime_template(
        value.get("runtime_input_template"),
        system=coordinate["system"],
        policy=coordinate["policy"],
        dataset=dataset,
    )
    unsigned = {
        key: item for key, item in value.items() if key != "authority_snapshot_sha256"
    }
    snapshot_sha = _sha(
        value.get("authority_snapshot_sha256"), "runtime authority snapshot"
    )
    _require(
        snapshot_sha == _canonical_sha(unsigned),
        "runtime authority snapshot self-hash drifted",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": AUTHORITY_SNAPSHOT_KIND,
        "status": "physically_prepared_non_authorizing_runtime",
        "coordinate": coordinate,
        "dataset_binding_sha256": dataset["dataset_binding_sha256"],
        "upstream_identities": _upstream(value.get("upstream_identities")),
        "runtime_authority_ref": runtime_ref,
        "runtime_authority_sha256": runtime_sha,
        "runtime_authority_set_sha256": _sha(
            value.get("runtime_authority_set_sha256"), "runtime authority set"
        ),
        "runtime_binding_identity_v4_sha256": _sha(
            value.get("runtime_binding_identity_v4_sha256"),
            "runtime binding identity v4",
        ),
        "launcher_runtime_authority_ref": launcher_ref,
        "launcher_runtime_authority_sha256": launcher_sha,
        "publication_launcher_invocation_v3_ref": invocation_ref,
        "publication_launcher_invocation_v3": invocation,
        "q4_validator_authority_ref": validator_ref,
        "q4_validator_authority_sha256": validator_sha,
        "runner_authority_ref": runner_ref,
        "runner_authority_sha256": runner_sha,
        "runner_invocation_identity_sha256": _sha(
            value.get("runner_invocation_identity_sha256"),
            "runner invocation identity",
        ),
        "runtime_input_template": template,
        "authority_snapshot_sha256": snapshot_sha,
    }


def _run_id(value: Any) -> str:
    _require(
        type(value) is str and _RUN_ID_RE.fullmatch(value) is not None,
        "runtime v4 run_id is invalid",
    )
    return value


def _duration(value: Any) -> int:
    _require(
        type(value) is int and value == DURATION_S,
        "runtime v4 duration must equal the frozen 180 seconds",
    )
    return value


def _material(
    *,
    coordinate: Mapping[str, Any],
    authority_snapshot: Mapping[str, Any],
    dataset_binding: Mapping[str, Any],
    run_id: str,
    duration_s: int,
) -> dict[str, Any]:
    cell = _cell_coordinate(copy.deepcopy(dict(coordinate)))
    dataset = _dataset_binding(copy.deepcopy(dict(dataset_binding)))
    snapshot = _authority_snapshot(
        copy.deepcopy(dict(authority_snapshot)), dataset=dataset
    )
    authority_coordinate = {
        key: cell[key] for key in ("system", "codec", "topology_kind", "policy")
    }
    _require(
        snapshot["coordinate"] == authority_coordinate,
        "runtime authority snapshot coordinate drifted from Q4 cell",
    )
    checked_run_id = _run_id(run_id)
    checked_duration = _duration(duration_s)
    runtime_dataset = copy.deepcopy(dataset["dataset"])
    runtime_dataset[RUNTIME_INPUT_KEY_BY_SYSTEM[cell["system"]]] = copy.deepcopy(
        snapshot["runtime_input_template"]
    )
    runtime_inputs = {
        "system": cell["system"],
        "scenario": SCENARIO_BY_TOPOLOGY[cell["topology_kind"]],
        "topology_kind": cell["topology_kind"],
        "codec": cell["codec"],
        "policy": cell["policy"],
        "deadline_ms": cell["deadline_ms"],
        "duration_s": checked_duration,
        "warmup_s": WARMUP_S,
        "streams": STREAMS,
        "base_seed": SEED,
        "run_id": checked_run_id,
        "dataset": runtime_dataset,
    }
    graph_unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": NATIVE_GRAPH_KIND,
        "status": "bound_non_authorizing_native_runtime_graph",
        "authorization_eligible": False,
        "execution_authorized": False,
        "coordinate": copy.deepcopy(cell),
        "run_id": checked_run_id,
        "duration_s": checked_duration,
        "authority_snapshot_sha256": snapshot["authority_snapshot_sha256"],
        "dataset_binding_sha256": dataset["dataset_binding_sha256"],
        "upstream_identities": copy.deepcopy(snapshot["upstream_identities"]),
        "runtime_authority_ref": copy.deepcopy(snapshot["runtime_authority_ref"]),
        "runtime_authority_sha256": snapshot["runtime_authority_sha256"],
        "runtime_authority_set_sha256": snapshot[
            "runtime_authority_set_sha256"
        ],
        "runtime_binding_identity_v4_sha256": snapshot[
            "runtime_binding_identity_v4_sha256"
        ],
        "launcher_runtime_authority_ref": copy.deepcopy(
            snapshot["launcher_runtime_authority_ref"]
        ),
        "launcher_runtime_authority_sha256": snapshot[
            "launcher_runtime_authority_sha256"
        ],
        "publication_launcher_invocation_v3_ref": copy.deepcopy(
            snapshot["publication_launcher_invocation_v3_ref"]
        ),
        "publication_launcher_invocation_v3_sha256": snapshot[
            "publication_launcher_invocation_v3"
        ]["invocation_sha256"],
        "q4_validator_authority_ref": copy.deepcopy(
            snapshot["q4_validator_authority_ref"]
        ),
        "q4_validator_authority_sha256": snapshot[
            "q4_validator_authority_sha256"
        ],
        "runner_authority_ref": copy.deepcopy(snapshot["runner_authority_ref"]),
        "runner_authority_sha256": snapshot["runner_authority_sha256"],
        "runner_invocation_identity_sha256": snapshot[
            "runner_invocation_identity_sha256"
        ],
        "runtime_inputs_sha256": _canonical_sha(runtime_inputs),
        "launcher_evidence_files": list(
            qualification_launcher_evidence_files_v4(cell["policy"])
        ),
    }
    graph = {
        **graph_unsigned,
        "graph_contract_sha256": _canonical_sha(graph_unsigned),
    }
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": "bound_non_authorizing_arbitrary_q4_runtime",
        "authorization_eligible": False,
        "execution_authorized": False,
        "coordinate": copy.deepcopy(cell),
        "run_id": checked_run_id,
        "duration_s": checked_duration,
        "authority_snapshot_sha256": snapshot["authority_snapshot_sha256"],
        "dataset_binding_sha256": dataset["dataset_binding_sha256"],
        "runtime_inputs": runtime_inputs,
        "native_graph_contract": graph,
    }
    return {**unsigned, "contract_sha256": _canonical_sha(unsigned)}


def build_publication_runtime_contract_v4(
    *,
    coordinate: Mapping[str, Any],
    authority_snapshot: Mapping[str, Any],
    dataset_binding: Mapping[str, Any],
    run_id: str,
    duration_s: int,
) -> dict[str, Any]:
    """Build one deterministic, non-authorizing arbitrary-Q4 runtime contract."""

    _require(isinstance(coordinate, Mapping), "Q4 coordinate must be a mapping")
    _require(
        isinstance(authority_snapshot, Mapping),
        "runtime authority snapshot must be a mapping",
    )
    _require(
        isinstance(dataset_binding, Mapping), "dataset binding must be a mapping"
    )
    return _material(
        coordinate=coordinate,
        authority_snapshot=authority_snapshot,
        dataset_binding=dataset_binding,
        run_id=run_id,
        duration_s=duration_s,
    )


def validate_publication_runtime_contract_v4(
    value: Any,
    *,
    coordinate: Mapping[str, Any],
    authority_snapshot: Mapping[str, Any],
    dataset_binding: Mapping[str, Any],
    run_id: str,
    duration_s: int,
) -> dict[str, Any]:
    """Validate candidate bytes against every external runtime/dataset/run pin."""

    _require(
        type(value) is dict and set(value) == _TOP_FIELDS,
        "runtime contract v4 fields drifted",
    )
    graph = value.get("native_graph_contract")
    _require(
        type(graph) is dict and set(graph) == _GRAPH_FIELDS,
        "native graph contract v4 fields drifted",
    )
    expected = _material(
        coordinate=coordinate,
        authority_snapshot=authority_snapshot,
        dataset_binding=dataset_binding,
        run_id=run_id,
        duration_s=duration_s,
    )
    _require(value == expected, "runtime contract v4 external binding drifted")
    return copy.deepcopy(expected)


def build_publication_q4_runtime_candidate_registry_v4(
    *,
    dataset_bindings: Sequence[Mapping[str, Any]],
    authority_snapshots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the sole deterministic two-dataset/112-authority registry."""

    _require(
        not isinstance(dataset_bindings, (str, bytes))
        and isinstance(dataset_bindings, Sequence),
        "Q4 runtime candidate dataset bindings must be a sequence",
    )
    _require(
        not isinstance(authority_snapshots, (str, bytes))
        and isinstance(authority_snapshots, Sequence),
        "Q4 runtime authority snapshots must be a sequence",
    )
    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RUNTIME_CANDIDATE_REGISTRY_KIND,
        "status": "physically_prepared_runtime_candidates",
        "accepted_as_input": True,
        "authorization_eligible": False,
        "execution_authorized": False,
        "dataset_bindings": copy.deepcopy(list(dataset_bindings)),
        "authority_snapshots": copy.deepcopy(list(authority_snapshots)),
    }
    return validate_publication_q4_runtime_candidate_registry_v4(
        {**unsigned, "registry_sha256": _canonical_sha(unsigned)}
    )


def validate_publication_q4_runtime_candidate_registry_v4(
    value: Any,
) -> dict[str, Any]:
    """Validate exact two-dataset/112-authority input coverage for all 560 cells."""

    _require(
        type(value) is dict and set(value) == _REGISTRY_FIELDS,
        "Q4 runtime candidate registry fields drifted",
    )
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == RUNTIME_CANDIDATE_REGISTRY_KIND
        and value.get("status") == "physically_prepared_runtime_candidates"
        and value.get("accepted_as_input") is True
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 runtime candidate registry header drifted",
    )
    raw_datasets = value.get("dataset_bindings")
    _require(
        type(raw_datasets) is list and len(raw_datasets) == len(CODECS),
        "Q4 runtime candidate dataset coverage drifted",
    )
    datasets = [_dataset_binding(item) for item in raw_datasets]
    _require(
        [item["codec_variant"] for item in datasets] == list(CODECS),
        "Q4 runtime candidate dataset order drifted",
    )
    by_codec = {item["codec_variant"]: item for item in datasets}
    raw_snapshots = value.get("authority_snapshots")
    _require(
        type(raw_snapshots) is list and len(raw_snapshots) == AUTHORITY_COUNT,
        "Q4 runtime authority snapshot coverage drifted",
    )
    expected_coordinates = [
        {
            "system": system,
            "codec": codec,
            "topology_kind": topology,
            "policy": policy,
        }
        for system in SYSTEMS
        for codec in CODECS
        for topology in TOPOLOGIES
        for policy in POLICIES
    ]
    snapshots: list[dict[str, Any]] = []
    for position, (raw, expected_coordinate) in enumerate(
        zip(raw_snapshots, expected_coordinates)
    ):
        codec = expected_coordinate["codec"]
        checked = _authority_snapshot(raw, dataset=by_codec[codec])
        _require(
            checked["coordinate"] == expected_coordinate,
            f"Q4 runtime authority snapshot[{position}] order drifted",
        )
        snapshots.append(checked)
    _require(
        len({item["authority_snapshot_sha256"] for item in snapshots})
        == AUTHORITY_COUNT,
        "Q4 runtime authority snapshot identities alias",
    )
    first = snapshots[0]
    global_fields = (
        "upstream_identities",
        "publication_launcher_invocation_v3_ref",
        "publication_launcher_invocation_v3",
        "q4_validator_authority_ref",
        "q4_validator_authority_sha256",
        "runner_authority_ref",
        "runner_authority_sha256",
        "runner_invocation_identity_sha256",
    )
    _require(
        all(
            all(item[field] == first[field] for field in global_fields)
            for item in snapshots
        ),
        "Q4 runtime candidate global trust domain drifted",
    )
    for system in SYSTEMS:
        system_items = [
            item for item in snapshots if item["coordinate"]["system"] == system
        ]
        _require(
            len(system_items) == AUTHORITY_COUNT // len(SYSTEMS),
            f"Q4 {system} runtime candidate coverage drifted",
        )
        system_fields = (
            "runtime_authority_set_sha256",
            "runtime_binding_identity_v4_sha256",
            "launcher_runtime_authority_ref",
            "launcher_runtime_authority_sha256",
        )
        _require(
            all(
                all(item[field] == system_items[0][field] for field in system_fields)
                for item in system_items
            ),
            f"Q4 {system} runtime candidate trust pins drifted",
        )
    _require(
        len({item["runtime_authority_sha256"] for item in snapshots})
        == AUTHORITY_COUNT,
        "Q4 runtime authority semantic identities alias",
    )
    unsigned = {key: item for key, item in value.items() if key != "registry_sha256"}
    registry_sha = _sha(value.get("registry_sha256"), "Q4 runtime candidate registry")
    _require(
        registry_sha == _canonical_sha(unsigned),
        "Q4 runtime candidate registry self-hash drifted",
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RUNTIME_CANDIDATE_REGISTRY_KIND,
        "status": "physically_prepared_runtime_candidates",
        "accepted_as_input": True,
        "authorization_eligible": False,
        "execution_authorized": False,
        "dataset_bindings": datasets,
        "authority_snapshots": snapshots,
        "registry_sha256": registry_sha,
    }


def select_publication_q4_runtime_material_v4(
    registry: Mapping[str, Any], *, coordinate: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select the sole authority snapshot and dataset for a frozen Q4 cell."""

    checked = validate_publication_q4_runtime_candidate_registry_v4(registry)
    cell = _cell_coordinate(copy.deepcopy(dict(coordinate)))
    authority_position = cell["cell_index"] // len(DEADLINES_MS)
    snapshot = checked["authority_snapshots"][authority_position]
    expected = {
        key: cell[key] for key in ("system", "codec", "topology_kind", "policy")
    }
    _require(
        snapshot["coordinate"] == expected,
        "selected runtime authority snapshot coordinate drifted",
    )
    dataset = checked["dataset_bindings"][CODECS.index(cell["codec"])]
    return copy.deepcopy(snapshot), copy.deepcopy(dataset)


__all__ = [
    "ARTIFACT_KIND",
    "AUTHORITY_SNAPSHOT_KIND",
    "CELL_COUNT",
    "CODECS",
    "DATASET_BINDING_KIND",
    "DEADLINES_MS",
    "DURATION_S",
    "NATIVE_GRAPH_KIND",
    "POLICIES",
    "PublicationQ4RuntimeContractV4Error",
    "RUNTIME_CANDIDATE_REGISTRY_KIND",
    "RUNTIME_INPUT_KEY_BY_SYSTEM",
    "RUNTIME_INPUT_KIND_BY_SYSTEM",
    "SCHEMA_VERSION",
    "SYSTEMS",
    "TOPOLOGIES",
    "UPSTREAM_IDENTITY_FIELDS",
    "build_publication_q4_dataset_binding_v4",
    "build_publication_q4_runtime_candidate_registry_v4",
    "build_publication_runtime_contract_v4",
    "coordinate_for_q4_cell_index_v4",
    "qualification_launcher_evidence_files_v4",
    "select_publication_q4_runtime_material_v4",
    "validate_publication_q4_runtime_candidate_registry_v4",
    "validate_publication_runtime_contract_v4",
]
