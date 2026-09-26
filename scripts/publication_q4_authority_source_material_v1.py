#!/usr/bin/env python3
"""Materialize the unsigned production Q4 authority source material.

The producer consumes one externally raw-file- and semantic-pinned request,
physically rebuilds the complete 112 runtime + 4 launcher authority closure
through the public builders, and commits an unsigned source material followed
by a self-hashed receipt.  It never accepts evidence, issues a grant, or
authorizes execution.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
)
from backend_publication_launcher_runtime_authority import (
    build_backend_publication_launcher_runtime_authority,
)
from backend_publication_runtime_authority_v2 import (
    build_backend_publication_runtime_authority_v2,
)
from backend_runtime_validation_runner_authority import (
    build_backend_runtime_validation_runner_authority,
)
from backend_runtime_validator_authority_v4 import (
    assess_backend_runtime_validator_authority_v4,
    build_backend_runtime_validator_authority_v4,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
    canonical_relative_path_v1,
)
from publication_q4_authority_plan_pipeline_v1 import (
    build_publication_q4_authority_source_spec_v1,
    canonical_sha256,
    load_publication_q4_authority_source_material_v1,
)
from publication_q4_runtime_contract_v4 import (
    CODECS,
    POLICIES,
    SYSTEMS,
    TOPOLOGIES,
)
from publication_q4_runtime_registry_materializer_v4 import (
    validate_publication_q4_runtime_launcher_input_wrapper_v3,
)


SCHEMA_VERSION = 1
REQUEST_KIND = "vast_publication_q4_authority_source_material_request_v1"
RECEIPT_KIND = (
    "vast_publication_q4_authority_source_material_materialization_receipt_v1"
)
MATERIAL_FILENAME = "publication_q4_authority_source_material.v1.json"
RECEIPT_FILENAME = (
    "publication_q4_authority_source_material.materialization.v1.receipt.json"
)
EXIT_REJECTED = 78
MAX_REQUEST_BYTES = 256 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 16 * 1024 * 1024 * 1024

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_COORDINATE_FIELDS = frozenset(
    {"system", "codec", "topology_kind", "policy"}
)
_RUNTIME_INPUT_FIELDS = frozenset(
    {
        "dataset_manifest",
        "dataset_files",
        "source_runtime_artifacts",
        "backend_runtime_artifacts",
        "analytics_authority",
        "policy_authority",
        "cohort_topology_plan",
        "resource_contract",
        "system_specific_launcher_input",
    }
)
_RUNTIME_REQUEST_FIELDS = frozenset({"coordinate", "inputs"})
_LAUNCHER_BUILD_FIELDS = frozenset(
    {
        "system",
        "runtime_closure_manifest_path",
        "python_executable_path",
        "publication_launcher_path",
        "runtime_leaf_paths",
        "expected_authority_sha256",
        "expected_closure_manifest_sha256",
        "expected_runtime_closure_set_sha256",
    }
)
_VALIDATOR_BUILD_FIELDS = frozenset(
    {
        "validator_id",
        "implementation_descriptor",
        "qualification_input_schema_identity_sha256",
        "validation_system_context_schema_identity_sha256",
        "validation_request_schema_identity_sha256",
        "validation_record_schema_identity_sha256",
        "validation_system_shard_schema_identity_sha256",
        "validation_record_set_index_schema_identity_sha256",
        "validation_protocol_identity_sha256",
        "validation_input_schema_identity_sha256",
        "validation_output_schema_identity_sha256",
        "expected_authority_sha256",
    }
)
_RUNNER_BUILD_FIELDS = frozenset(
    {
        "runner_id",
        "runtime_bundle_manifest_path",
        "runtime_leaf_paths",
        "python_executable_path",
        "runner_path",
        "validation_protocol_identity_sha256",
        "input_schema_identity_sha256",
        "output_schema_identity_sha256",
        "expected_runner_authority_sha256",
    }
)
_UPSTREAM_IDENTITY_FIELDS = frozenset(
    {
        "dataset_manifest_sha256",
        "policy_contract_sha256",
        "policy_qualification_receipt_sha256",
        "resource_contract_identity_sha256",
        "resource_qualification_receipt_sha256",
        "analytics_execution_config_identity_sha256",
        "model_parity_manifest_identity_sha256",
        "model_parity_acceptance_binding_sha256",
    }
)
_ACCEPTED_SOURCE_PATH_FIELDS = frozenset(
    {
        "model_parity_acceptance_receipt_path",
        "policy_qualification_receipt_path",
        "policy_capability_manifest_path",
        "policy_calibration_mapping_path",
        "resource_qualification_receipt_path",
        "resource_capability_manifest_path",
        "analytics_service_authority_path",
        "guardian_preprocessing_contract_path",
        "guardian_preprocessing_receipt_path",
    }
)
_DATASET_DESCRIPTOR_FIELDS = frozenset(
    {"codec_variant", "front_gate", "underbody"}
)
_PLANNED_OUTPUT_FIELDS = frozenset(
    {
        "runtime_candidate_registry_path",
        "runtime_materialization_result_path",
        "source_registry_path",
        "source_materialization_result_path",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "accepted_upstream_identities",
        "accepted_source_descriptors",
        "expected_analytics_service_identity_sha256",
        "dataset_source_descriptors",
        "runtime_authority_requests",
        "launcher_runtime_authority_builds",
        "publication_launcher_invocation_v3_sha256",
        "q4_validator_authority_build",
        "runner_authority_build",
        "planned_outputs",
        "request_sha256",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "request",
        "request_sha256",
        "source_material",
        "source_material_sha256",
        "accepted_upstream_identities",
        "planned_outputs",
        "dataset_source_count",
        "runtime_authority_build_count",
        "launcher_runtime_authority_build_count",
        "receipt_sha256",
    }
)


class PublicationQ4AuthoritySourceMaterialV1Error(RuntimeError):
    """The pinned Q4 source-material transaction is not closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationQ4AuthoritySourceMaterialV1Error(message)


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and _SHA_RE.fullmatch(value) is not None,
        f"{label} is not a SHA-256 identity",
    )
    return value


def _strict_json(
    value: Any, *, active: set[int] | None = None, depth: int = 0
) -> None:
    _require(depth <= 96, "Q4 source-material JSON nesting is excessive")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "Q4 source-material JSON is non-finite")
        return
    _require(type(value) in {dict, list}, "Q4 source-material value is not JSON")
    active = set() if active is None else active
    identity = id(value)
    _require(identity not in active, "Q4 source-material JSON contains a cycle")
    active.add(identity)
    try:
        values = value.values() if type(value) is dict else value
        if type(value) is dict:
            _require(
                all(type(key) is str for key in value),
                "Q4 source-material JSON key type drifted",
            )
        for item in values:
            _strict_json(item, active=active, depth=depth + 1)
    finally:
        active.remove(identity)


def _canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    _strict_json(value)
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise PublicationQ4AuthoritySourceMaterialV1Error(
            "Q4 source-material value is not canonical JSON"
        ) from error
    return payload + (b"\n" if newline else b"")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    path = canonical_relative_path_v1(value.get("path"), label=f"{label} path")
    size = value.get("size_bytes")
    _require(
        type(size) is int and 0 < size <= MAX_DESCRIPTOR_BYTES,
        f"{label} descriptor size is invalid",
    )
    return {
        "path": path,
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} descriptor"),
    }


def _coordinate(value: Any, label: str) -> dict[str, str]:
    _require(
        type(value) is dict and set(value) == _COORDINATE_FIELDS,
        f"{label} coordinate fields drifted",
    )
    result = {
        "system": value.get("system"),
        "codec": value.get("codec"),
        "topology_kind": value.get("topology_kind"),
        "policy": value.get("policy"),
    }
    _require(
        result["system"] in SYSTEMS
        and result["codec"] in CODECS
        and result["topology_kind"] in TOPOLOGIES
        and result["policy"] in POLICIES,
        f"{label} coordinate value drifted",
    )
    return {key: str(item) for key, item in result.items()}


def _coordinates() -> list[dict[str, str]]:
    return [
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


def _relative_mapping(value: Any, fields: frozenset[str], label: str) -> dict[str, str]:
    _require(type(value) is dict and set(value) == fields, f"{label} fields drifted")
    result = {
        key: canonical_relative_path_v1(value.get(key), label=f"{label} {key}")
        for key in sorted(fields)
    }
    _require(
        len({item.casefold() for item in result.values()}) == len(result),
        f"{label} paths alias",
    )
    return result


def build_publication_q4_authority_source_material_request_v1(
    *,
    accepted_upstream_identities: Mapping[str, Any],
    accepted_source_descriptors: Mapping[str, Any],
    expected_analytics_service_identity_sha256: str,
    dataset_source_descriptors: Sequence[Mapping[str, Any]],
    runtime_authority_requests: Sequence[Mapping[str, Any]],
    launcher_runtime_authority_builds: Sequence[Mapping[str, Any]],
    publication_launcher_invocation_v3_sha256: str,
    q4_validator_authority_build: Mapping[str, Any],
    runner_authority_build: Mapping[str, Any],
    planned_outputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a non-authorizing, externally pinnable production request."""

    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": REQUEST_KIND,
        "status": "requested_non_authorizing_q4_authority_source_material",
        "authorization_eligible": False,
        "execution_authorized": False,
        "accepted_upstream_identities": copy.deepcopy(
            dict(accepted_upstream_identities)
        ),
        "accepted_source_descriptors": copy.deepcopy(
            dict(accepted_source_descriptors)
        ),
        "expected_analytics_service_identity_sha256": (
            expected_analytics_service_identity_sha256
        ),
        "dataset_source_descriptors": copy.deepcopy(
            list(dataset_source_descriptors)
        ),
        "runtime_authority_requests": copy.deepcopy(
            list(runtime_authority_requests)
        ),
        "launcher_runtime_authority_builds": copy.deepcopy(
            list(launcher_runtime_authority_builds)
        ),
        "publication_launcher_invocation_v3_sha256": (
            publication_launcher_invocation_v3_sha256
        ),
        "q4_validator_authority_build": copy.deepcopy(
            dict(q4_validator_authority_build)
        ),
        "runner_authority_build": copy.deepcopy(dict(runner_authority_build)),
        "planned_outputs": copy.deepcopy(dict(planned_outputs)),
    }
    return validate_publication_q4_authority_source_material_request_v1(
        {**unsigned, "request_sha256": _canonical_sha(unsigned)}
    )


def validate_publication_q4_authority_source_material_request_v1(
    value: Any,
) -> dict[str, Any]:
    """Purely validate exact coverage and all caller-owned trust pins."""

    _require(
        type(value) is dict and set(value) == _REQUEST_FIELDS,
        "Q4 source-material request fields drifted",
    )
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == REQUEST_KIND
        and value.get("status")
        == "requested_non_authorizing_q4_authority_source_material"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 source-material request header/claims drifted",
    )
    upstream = value.get("accepted_upstream_identities")
    _require(
        type(upstream) is dict and set(upstream) == _UPSTREAM_IDENTITY_FIELDS,
        "Q4 source-material upstream identity fields drifted",
    )
    checked_upstream = {
        key: _sha(upstream.get(key), f"accepted upstream {key}")
        for key in sorted(upstream)
    }
    accepted_raw = value.get("accepted_source_descriptors")
    _require(
        type(accepted_raw) is dict
        and set(accepted_raw) == _ACCEPTED_SOURCE_PATH_FIELDS,
        "Q4 accepted source descriptor coverage drifted",
    )
    accepted = {
        key: _descriptor(accepted_raw[key], f"accepted source {key}")
        for key in sorted(accepted_raw)
    }
    _require(
        len({row["path"].casefold() for row in accepted.values()})
        == len(accepted),
        "Q4 accepted source descriptor paths alias",
    )
    service_identity = _sha(
        value.get("expected_analytics_service_identity_sha256"),
        "expected analytics service identity",
    )

    raw_datasets = value.get("dataset_source_descriptors")
    _require(
        type(raw_datasets) is list and len(raw_datasets) == len(CODECS),
        "Q4 dataset source descriptor coverage drifted",
    )
    datasets: list[dict[str, Any]] = []
    for position, (raw, codec) in enumerate(zip(raw_datasets, CODECS, strict=True)):
        _require(
            type(raw) is dict
            and set(raw) == _DATASET_DESCRIPTOR_FIELDS
            and raw.get("codec_variant") == codec,
            f"Q4 dataset descriptor[{position}] fields/order drifted",
        )
        front = _descriptor(raw.get("front_gate"), f"{codec} front-gate")
        underbody = _descriptor(raw.get("underbody"), f"{codec} underbody")
        _require(
            front["path"].casefold() != underbody["path"].casefold(),
            f"Q4 dataset descriptor[{position}] paths alias",
        )
        datasets.append(
            {
                "codec_variant": codec,
                "front_gate": front,
                "underbody": underbody,
            }
        )

    raw_runtime = value.get("runtime_authority_requests")
    expected_coordinates = _coordinates()
    _require(
        type(raw_runtime) is list and len(raw_runtime) == len(expected_coordinates),
        "Q4 runtime authority request coverage drifted",
    )
    runtime: list[dict[str, Any]] = []
    dataset_by_codec = {row["codec_variant"]: row for row in datasets}
    for position, (raw, expected) in enumerate(
        zip(raw_runtime, expected_coordinates, strict=True)
    ):
        _require(
            type(raw) is dict and set(raw) == _RUNTIME_REQUEST_FIELDS,
            f"Q4 runtime authority request[{position}] fields drifted",
        )
        coordinate = _coordinate(raw.get("coordinate"), f"runtime[{position}]")
        _require(
            coordinate == expected,
            f"Q4 runtime authority request[{position}] order drifted",
        )
        inputs = raw.get("inputs")
        _require(
            type(inputs) is dict and set(inputs) == _RUNTIME_INPUT_FIELDS,
            f"Q4 runtime authority request[{position}] input fields drifted",
        )
        manifest = _descriptor(
            inputs.get("dataset_manifest"), f"runtime[{position}] dataset manifest"
        )
        _require(
            manifest["sha256"] == checked_upstream["dataset_manifest_sha256"],
            f"Q4 runtime authority request[{position}] dataset lineage drifted",
        )
        files = inputs.get("dataset_files")
        _require(
            type(files) is list and len(files) == 2,
            f"Q4 runtime authority request[{position}] dataset coverage drifted",
        )
        checked_files = [
            _descriptor(item, f"runtime[{position}] dataset file[{index}]")
            for index, item in enumerate(files)
        ]
        source_row = dataset_by_codec[coordinate["codec"]]
        _require(
            {tuple(sorted(item.items())) for item in checked_files}
            == {
                tuple(sorted(source_row["front_gate"].items())),
                tuple(sorted(source_row["underbody"].items())),
            },
            f"Q4 runtime authority request[{position}] dataset pins drifted",
        )
        launcher_section = inputs.get("system_specific_launcher_input")
        _require(
            type(launcher_section) is dict
            and set(launcher_section) == {"content", "content_identity_sha256"},
            f"Q4 runtime authority request[{position}] launcher section drifted",
        )
        checked_wrapper = validate_publication_q4_runtime_launcher_input_wrapper_v3(
            launcher_section.get("content"),
            expected_system=coordinate["system"],
            expected_policy=coordinate["policy"],
        )
        _require(
            launcher_section.get("content_identity_sha256")
            == canonical_sha256(checked_wrapper),
            f"Q4 runtime authority request[{position}] launcher identity drifted",
        )
        checked_inputs = copy.deepcopy(inputs)
        checked_inputs["dataset_manifest"] = manifest
        checked_inputs["dataset_files"] = checked_files
        checked_inputs["system_specific_launcher_input"] = {
            "content": checked_wrapper,
            "content_identity_sha256": canonical_sha256(checked_wrapper),
        }
        runtime.append({"coordinate": coordinate, "inputs": checked_inputs})

    raw_launchers = value.get("launcher_runtime_authority_builds")
    _require(
        type(raw_launchers) is list and len(raw_launchers) == len(SYSTEMS),
        "Q4 launcher authority build coverage drifted",
    )
    launchers: list[dict[str, Any]] = []
    for position, (raw, system) in enumerate(zip(raw_launchers, SYSTEMS, strict=True)):
        _require(
            type(raw) is dict
            and set(raw) == _LAUNCHER_BUILD_FIELDS
            and raw.get("system") == system,
            f"Q4 launcher authority build[{position}] fields/order drifted",
        )
        checked = copy.deepcopy(raw)
        for key in (
            "runtime_closure_manifest_path",
            "python_executable_path",
            "publication_launcher_path",
        ):
            checked[key] = canonical_relative_path_v1(
                raw.get(key), label=f"launcher[{position}] {key}"
            )
        leaves = raw.get("runtime_leaf_paths")
        _require(
            type(leaves) is list and bool(leaves),
            f"Q4 launcher authority build[{position}] leaves drifted",
        )
        checked["runtime_leaf_paths"] = [
            canonical_relative_path_v1(
                item, label=f"launcher[{position}] runtime leaf"
            )
            for item in leaves
        ]
        _require(
            len(set(checked["runtime_leaf_paths"]))
            == len(checked["runtime_leaf_paths"]),
            f"Q4 launcher authority build[{position}] leaf paths alias",
        )
        for key in (
            "expected_authority_sha256",
            "expected_closure_manifest_sha256",
            "expected_runtime_closure_set_sha256",
        ):
            checked[key] = _sha(raw.get(key), f"launcher[{position}] {key}")
        launchers.append(checked)

    validator = value.get("q4_validator_authority_build")
    _require(
        type(validator) is dict and set(validator) == _VALIDATOR_BUILD_FIELDS,
        "Q4 validator authority build fields drifted",
    )
    checked_validator = copy.deepcopy(validator)
    checked_validator["implementation_descriptor"] = _descriptor(
        validator.get("implementation_descriptor"), "Q4 validator implementation"
    )
    for key in _VALIDATOR_BUILD_FIELDS:
        if key.endswith("_sha256"):
            checked_validator[key] = _sha(validator.get(key), f"Q4 validator {key}")

    runner = value.get("runner_authority_build")
    _require(
        type(runner) is dict and set(runner) == _RUNNER_BUILD_FIELDS,
        "Q4 runner authority build fields drifted",
    )
    checked_runner = copy.deepcopy(runner)
    for key in _RUNNER_BUILD_FIELDS:
        if key.endswith("_sha256"):
            checked_runner[key] = _sha(runner.get(key), f"Q4 runner {key}")
        elif key.endswith("_path"):
            checked_runner[key] = canonical_relative_path_v1(
                runner.get(key), label=f"Q4 runner {key}"
            )
    leaves = runner.get("runtime_leaf_paths")
    _require(
        type(leaves) is list and bool(leaves), "Q4 runner runtime leaves drifted"
    )
    checked_runner["runtime_leaf_paths"] = [
        canonical_relative_path_v1(item, label="Q4 runner runtime leaf")
        for item in leaves
    ]
    _require(
        len(set(checked_runner["runtime_leaf_paths"]))
        == len(checked_runner["runtime_leaf_paths"]),
        "Q4 runner runtime leaf paths alias",
    )

    planned = _relative_mapping(
        value.get("planned_outputs"), _PLANNED_OUTPUT_FIELDS, "Q4 planned output"
    )
    source_paths = set(
        _collect_descriptors(
            {
                "accepted": accepted,
                "datasets": datasets,
                "runtime": runtime,
                "validator": checked_validator,
            },
            label="Q4 request physical sources",
        )
    )
    source_paths.update(
        path
        for build in launchers
        for path in (
            build["runtime_closure_manifest_path"],
            build["python_executable_path"],
            build["publication_launcher_path"],
            *build["runtime_leaf_paths"],
        )
    )
    source_paths.update(
        (
            checked_runner["runtime_bundle_manifest_path"],
            checked_runner["python_executable_path"],
            checked_runner["runner_path"],
            *checked_runner["runtime_leaf_paths"],
        )
    )
    _require(
        not ({path.casefold() for path in planned.values()}
             & {path.casefold() for path in source_paths}),
        "Q4 planned output aliases a physical source",
    )
    invocation_sha = _sha(
        value.get("publication_launcher_invocation_v3_sha256"),
        "publication launcher invocation v3",
    )
    _require(
        invocation_sha
        == publication_launcher_invocation_v3_contract()["invocation_sha256"],
        "publication launcher invocation v3 pin drifted",
    )
    unsigned = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key != "request_sha256"
    }
    identity = _sha(value.get("request_sha256"), "Q4 source-material request")
    _require(
        identity == _canonical_sha(unsigned),
        "Q4 source-material request self-hash drifted",
    )
    return {
        **unsigned,
        "accepted_upstream_identities": checked_upstream,
        "accepted_source_descriptors": accepted,
        "expected_analytics_service_identity_sha256": service_identity,
        "dataset_source_descriptors": datasets,
        "runtime_authority_requests": runtime,
        "launcher_runtime_authority_builds": launchers,
        "publication_launcher_invocation_v3_sha256": invocation_sha,
        "q4_validator_authority_build": checked_validator,
        "runner_authority_build": checked_runner,
        "planned_outputs": planned,
        "request_sha256": identity,
    }


def _collect_descriptors(
    value: Any,
    *,
    label: str,
    result: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    descriptors = {} if result is None else result
    if type(value) is dict and set(value) == _DESCRIPTOR_FIELDS:
        descriptor = _descriptor(value, label)
        previous = descriptors.get(descriptor["path"])
        _require(
            previous is None or previous == descriptor,
            f"{label} reuses one path with conflicting descriptor pins",
        )
        descriptors[descriptor["path"]] = descriptor
        return descriptors
    if type(value) is dict:
        for key, item in value.items():
            _collect_descriptors(
                item, label=f"{label}.{key}", result=descriptors
            )
    elif type(value) is list:
        for index, item in enumerate(value):
            _collect_descriptors(
                item, label=f"{label}[{index}]", result=descriptors
            )
    return descriptors


def _verify_descriptors(
    custody: PhysicalRootCustodyV1,
    descriptors: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> None:
    for position, path in enumerate(sorted(descriptors, key=lambda item: (item.casefold(), item))):
        expected = descriptors[path]
        observed, _payload = custody.read_descriptor(
            path,
            label=f"{label} descriptor[{position}]",
            maximum=int(expected["size_bytes"]),
            capture=False,
        )
        _require(observed == expected, f"{label} descriptor[{position}] drifted")


def _policy_outputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    policy = inputs.get("policy_authority")
    _require(
        type(policy) is dict
        and set(policy) == {"capability", "calibration", "static_map"},
        "runtime policy authority fields drifted",
    )
    result: dict[str, Any] = {}
    for key in ("capability", "calibration", "static_map"):
        item = policy.get(key)
        if item is None:
            result[key] = None
        else:
            _require(
                type(item) is dict and type(item.get("descriptor")) is dict,
                f"runtime policy {key} artifact drifted",
            )
            result[key] = copy.deepcopy(item["descriptor"])
    return result


def _accepted_sources(request: Mapping[str, Any]) -> dict[str, str]:
    result = {
        key: request["accepted_source_descriptors"][key]["path"]
        for key in sorted(_ACCEPTED_SOURCE_PATH_FIELDS)
    }
    result["expected_analytics_service_identity_sha256"] = request[
        "expected_analytics_service_identity_sha256"
    ]
    return result


def _dataset_sources(request: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "codec_variant": row["codec_variant"],
            "front_gate_path": row["front_gate"]["path"],
            "underbody_path": row["underbody"]["path"],
        }
        for row in request["dataset_source_descriptors"]
    ]


def build_publication_q4_authority_source_material_v1(
    *, project_root: Path | str, request: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    """Physically build and close the complete unsigned source material."""

    root = Path(project_root)
    checked = validate_publication_q4_authority_source_material_request_v1(request)
    with PhysicalRootCustodyV1.open(root, label="Q4 source-material project_root") as custody:
        request_descriptors = _collect_descriptors(
            checked, label="Q4 source-material request"
        )
        _verify_descriptors(custody, request_descriptors, label="Q4 source-material input")

        validator_arguments = copy.deepcopy(checked["q4_validator_authority_build"])
        validator = build_backend_runtime_validator_authority_v4(
            **validator_arguments
        )
        validator_assessment = assess_backend_runtime_validator_authority_v4(
            validator,
            project_root=root,
            expected_authority_sha256=validator_arguments[
                "expected_authority_sha256"
            ],
        )
        _require(
            validator_assessment.get("status") == "physically_valid",
            "Q4 validator authority physical build failed",
        )

        runner_arguments = copy.deepcopy(checked["runner_authority_build"])
        expected_runner = runner_arguments.pop("expected_runner_authority_sha256")
        runner = build_backend_runtime_validation_runner_authority(
            project_root=root, **runner_arguments
        )
        _require(
            runner["runner_authority_sha256"] == expected_runner,
            "Q4 runner external authority pin drifted",
        )
        _require(
            runner["validation_protocol_identity_sha256"]
            == validator["validation_protocol_identity_sha256"]
            and runner["input_schema_identity_sha256"]
            == validator["validation_input_schema_identity_sha256"]
            and runner["output_schema_identity_sha256"]
            == validator["validation_output_schema_identity_sha256"],
            "Q4 validator/runner protocol trust domain drifted",
        )

        launcher_values: list[dict[str, Any]] = []
        for position, build in enumerate(
            checked["launcher_runtime_authority_builds"]
        ):
            try:
                authority = build_backend_publication_launcher_runtime_authority(
                    project_root=root,
                    system=build["system"],
                    runtime_closure_manifest_path=build[
                        "runtime_closure_manifest_path"
                    ],
                    python_executable_path=build["python_executable_path"],
                    publication_launcher_path=build["publication_launcher_path"],
                    runtime_leaf_paths=build["runtime_leaf_paths"],
                    expected_authority_sha256=build[
                        "expected_authority_sha256"
                    ],
                    expected_system=build["system"],
                    expected_publication_launcher_invocation_v3_sha256=checked[
                        "publication_launcher_invocation_v3_sha256"
                    ],
                    expected_closure_manifest_sha256=build[
                        "expected_closure_manifest_sha256"
                    ],
                    expected_runtime_closure_set_sha256=build[
                        "expected_runtime_closure_set_sha256"
                    ],
                )
            except Exception as error:
                raise PublicationQ4AuthoritySourceMaterialV1Error(
                    f"Q4 launcher authority build[{position}] rejected: {error}"
                ) from error
            launcher_values.append(authority)

        runtime_builds: list[dict[str, Any]] = []
        runtime_values: list[dict[str, Any]] = []
        for position, build in enumerate(checked["runtime_authority_requests"]):
            coordinate = copy.deepcopy(build["coordinate"])
            inputs = copy.deepcopy(build["inputs"])
            try:
                authority = build_backend_publication_runtime_authority_v2(
                    project_root=root,
                    **coordinate,
                    **inputs,
                    upstream_identities=checked["accepted_upstream_identities"],
                    expected_upstream_identities=checked[
                        "accepted_upstream_identities"
                    ],
                    expected_policy_outputs=_policy_outputs(inputs),
                )
            except Exception as error:
                raise PublicationQ4AuthoritySourceMaterialV1Error(
                    f"Q4 runtime authority build[{position}] rejected: {error}"
                ) from error
            runtime_values.append(authority)
            runtime_builds.append(
                {
                    "coordinate": coordinate,
                    "expected_authority_sha256": authority["authority_sha256"],
                    "inputs": inputs,
                }
            )

        closure_descriptors = dict(request_descriptors)
        for label, material in (
            ("validator", validator),
            ("runner", runner),
            ("launchers", launcher_values),
            ("runtimes", runtime_values),
        ):
            _collect_descriptors(
                material, label=f"built Q4 {label}", result=closure_descriptors
            )
        _verify_descriptors(
            custody, closure_descriptors, label="built Q4 authority closure"
        )

        spec = build_publication_q4_authority_source_spec_v1(
            accepted_upstream_identities=checked["accepted_upstream_identities"],
            accepted_sources=_accepted_sources(checked),
            dataset_sources=_dataset_sources(checked),
            runtime_authority_builds=runtime_builds,
            launcher_runtime_authority_builds=checked[
                "launcher_runtime_authority_builds"
            ],
            publication_launcher_invocation_v3_sha256=checked[
                "publication_launcher_invocation_v3_sha256"
            ],
            q4_validator_authority_build=checked[
                "q4_validator_authority_build"
            ],
            runner_authority_build=checked["runner_authority_build"],
            planned_outputs=checked["planned_outputs"],
        )
        material = {
            key: copy.deepcopy(item)
            for key, item in spec.items()
            if key != "source_spec_sha256"
        }
        _require(
            _canonical_sha(material) == spec["source_spec_sha256"],
            "Q4 unsigned source material semantic identity drifted",
        )
        return material, spec["source_spec_sha256"]


def _read_canonical_json(
    custody: PhysicalRootCustodyV1,
    path: Path | str,
    *,
    label: str,
    maximum: int,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    descriptor, payload = custody.read_descriptor(
        path, label=label, maximum=maximum, capture=True
    )
    assert payload is not None
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PublicationQ4AuthoritySourceMaterialV1Error(
            f"{label} is not canonical JSON"
        ) from error
    _require(type(value) is dict, f"{label} is not a JSON object")
    _require(
        payload == _canonical_bytes(value, newline=True),
        f"{label} bytes are not canonical JSON",
    )
    return descriptor, value, payload


def validate_publication_q4_authority_source_material_receipt_v1(
    value: Any,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _RECEIPT_FIELDS,
        "Q4 source-material receipt fields drifted",
    )
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == RECEIPT_KIND
        and value.get("status")
        == "materialized_non_authorizing_q4_authority_source_material"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 source-material receipt header/claims drifted",
    )
    request_descriptor = _descriptor(value.get("request"), "Q4 request receipt")
    material_descriptor = _descriptor(
        value.get("source_material"), "Q4 source material receipt"
    )
    request_sha = _sha(value.get("request_sha256"), "Q4 request receipt")
    material_sha = _sha(
        value.get("source_material_sha256"), "Q4 source material receipt"
    )
    upstream = value.get("accepted_upstream_identities")
    _require(
        type(upstream) is dict and set(upstream) == _UPSTREAM_IDENTITY_FIELDS,
        "Q4 source-material receipt upstream fields drifted",
    )
    checked_upstream = {
        key: _sha(upstream.get(key), f"receipt upstream {key}")
        for key in sorted(upstream)
    }
    planned = _relative_mapping(
        value.get("planned_outputs"), _PLANNED_OUTPUT_FIELDS, "receipt planned output"
    )
    _require(
        value.get("dataset_source_count") == len(CODECS)
        and value.get("runtime_authority_build_count") == len(_coordinates())
        and value.get("launcher_runtime_authority_build_count") == len(SYSTEMS),
        "Q4 source-material receipt coverage drifted",
    )
    unsigned = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key != "receipt_sha256"
    }
    receipt_sha = _sha(value.get("receipt_sha256"), "Q4 source-material receipt")
    _require(
        receipt_sha == _canonical_sha(unsigned),
        "Q4 source-material receipt self-hash drifted",
    )
    return {
        **unsigned,
        "request": request_descriptor,
        "request_sha256": request_sha,
        "source_material": material_descriptor,
        "source_material_sha256": material_sha,
        "accepted_upstream_identities": checked_upstream,
        "planned_outputs": planned,
        "receipt_sha256": receipt_sha,
    }


def load_publication_q4_authority_source_material_receipt_v1(
    *,
    project_root: Path | str,
    receipt_path: Path | str,
    expected_receipt_file_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str, Any]:
    """Cold-load the receipt and both exact causally preceding artifacts."""

    with PhysicalRootCustodyV1.open(
        project_root, label="Q4 source-material receipt project_root"
    ) as custody:
        receipt_descriptor, raw, _payload = _read_canonical_json(
            custody,
            receipt_path,
            label="Q4 source-material receipt",
            maximum=MAX_REQUEST_BYTES,
        )
        _require(
            receipt_descriptor["sha256"]
            == _sha(expected_receipt_file_sha256, "expected receipt raw file"),
            "Q4 source-material receipt raw-file pin drifted",
        )
        receipt = validate_publication_q4_authority_source_material_receipt_v1(raw)
        _require(
            receipt["receipt_sha256"]
            == _sha(expected_receipt_sha256, "expected receipt semantic"),
            "Q4 source-material receipt semantic pin drifted",
        )
        request_descriptor, request_raw, _request_payload = _read_canonical_json(
            custody,
            receipt["request"]["path"],
            label="Q4 source-material request",
            maximum=MAX_REQUEST_BYTES,
        )
        _require(
            request_descriptor == receipt["request"],
            "Q4 source-material receipt/request descriptor drifted",
        )
        request = validate_publication_q4_authority_source_material_request_v1(
            request_raw
        )
        _require(
            request["request_sha256"] == receipt["request_sha256"]
            and request["accepted_upstream_identities"]
            == receipt["accepted_upstream_identities"]
            and request["planned_outputs"] == receipt["planned_outputs"],
            "Q4 source-material receipt/request binding drifted",
        )
        material_descriptor, source_spec = (
            load_publication_q4_authority_source_material_v1(
                project_root=project_root,
                source_material_path=receipt["source_material"]["path"],
                expected_source_material_file_sha256=receipt[
                    "source_material"
                ]["sha256"],
                expected_source_material_sha256=receipt[
                    "source_material_sha256"
                ],
            )
        )
        _require(
            material_descriptor == receipt["source_material"]
            and source_spec["source_spec_sha256"]
            == receipt["source_material_sha256"]
            and source_spec["accepted_upstream_identities"]
            == receipt["accepted_upstream_identities"]
            and source_spec["planned_outputs"] == receipt["planned_outputs"]
            and len(source_spec["dataset_sources"])
            == receipt["dataset_source_count"]
            and len(source_spec["runtime_authority_builds"])
            == receipt["runtime_authority_build_count"]
            and len(source_spec["launcher_runtime_authority_builds"])
            == receipt["launcher_runtime_authority_build_count"],
            "Q4 source-material receipt/material binding drifted",
        )
        output_dir = PurePosixPath(receipt["source_material"]["path"]).parent.as_posix()
        _require(
            custody.list_directory_names(
                output_dir, label="Q4 source-material output namespace"
            )
            == tuple(sorted((MATERIAL_FILENAME, RECEIPT_FILENAME))),
            "Q4 source-material output namespace drifted",
        )
        return receipt


def _transaction_descriptor(path: str, payload: bytes) -> dict[str, Any]:
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _read_exact_transaction_leaf(
    custody: PhysicalRootCustodyV1,
    *,
    path: str,
    payload: bytes,
    label: str,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], tuple[int, int]]:
    """Cold-adopt only an exact immutable leaf and retain its inode identity."""

    observed, identity = custody.adopt_exact_durable_identity(
        path,
        payload,
        label=label,
        mode=0o444,
        expected_identity=expected_identity,
    )
    _require(
        observed == _transaction_descriptor(path, payload),
        f"{label} resumable artifact drifted",
    )
    return observed, identity


def _after_artifact_commit(
    callback: Callable[[str], None] | None,
    boundary: str,
    *,
    custody: PhysicalRootCustodyV1,
    watch_path: str,
) -> None:
    if callback is not None:
        epochs = custody.capture_pinned_directory_epochs(
            label=f"Q4 source-material {boundary} fault boundary"
        )
        mutation_watch = custody.begin_read_namespace_mutation_watch(
            [watch_path],
            label=f"Q4 source-material {boundary} fault boundary",
        )
        try:
            callback(boundary)
        except BaseException:
            if mutation_watch is not None:
                mutation_watch.close()
            raise
        custody.verify_pinned_directory_mutation_watch(
            mutation_watch,
            label=f"Q4 source-material {boundary} fault boundary",
        )
        custody.verify_pinned_directory_epochs(
            epochs,
            label=f"Q4 source-material {boundary} fault boundary",
        )


def materialize_publication_q4_authority_source_material_v1(
    *,
    project_root: Path | str,
    request_path: Path | str,
    expected_request_file_sha256: str,
    expected_request_sha256: str,
    output_dir: Path | str,
    after_artifact_commit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Commit or exactly resume material first and its completion receipt last."""

    with PhysicalRootCustodyV1.open(
        project_root, label="Q4 source-material project_root"
    ) as custody:
        request_descriptor, raw, request_payload = _read_canonical_json(
            custody,
            request_path,
            label="Q4 source-material request",
            maximum=MAX_REQUEST_BYTES,
        )
        _require(
            request_descriptor["sha256"]
            == _sha(expected_request_file_sha256, "expected request raw file"),
            "Q4 source-material request raw-file pin drifted",
        )
        request = validate_publication_q4_authority_source_material_request_v1(raw)
        _require(
            request["request_sha256"]
            == _sha(expected_request_sha256, "expected request semantic"),
            "Q4 source-material request semantic pin drifted",
        )
        output_relative = canonical_relative_path_v1(
            output_dir, label="Q4 source-material output directory"
        )
        custody.ensure_directory(
            output_relative, label="Q4 source-material output directory"
        )
        # Pin the directory before exposing the first crash boundary.  A
        # replacement that occurs while this invocation is alive is rejected
        # by every subsequent dirfd-custodied operation.
        custody.stat_directory_identity(
            output_relative, label="Q4 source-material output directory"
        )
        _after_artifact_commit(
            after_artifact_commit,
            "output_directory",
            custody=custody,
            watch_path=f"{output_relative}/.publication-q4-fault-boundary",
        )
        material_path = f"{output_relative}/{MATERIAL_FILENAME}"
        receipt_path = f"{output_relative}/{RECEIPT_FILENAME}"
        planned_paths = set(request["planned_outputs"].values())
        _require(
            material_path not in planned_paths
            and receipt_path not in planned_paths
            and request_descriptor["path"] not in planned_paths,
            "Q4 source-material transaction aliases a planned output",
        )

        material, material_sha = build_publication_q4_authority_source_material_v1(
            project_root=project_root, request=request
        )
        material_payload = _canonical_bytes(material, newline=True)
        material_descriptor = _transaction_descriptor(
            material_path, material_payload
        )
        observed_request, observed_payload = custody.read_descriptor(
            request_descriptor["path"],
            label="Q4 source-material request post-build",
            maximum=len(request_payload),
            capture=True,
        )
        _require(
            observed_request == request_descriptor
            and observed_payload == request_payload,
            "Q4 source-material request changed during authority build",
        )
        receipt_unsigned: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": RECEIPT_KIND,
            "status": "materialized_non_authorizing_q4_authority_source_material",
            "authorization_eligible": False,
            "execution_authorized": False,
            "request": request_descriptor,
            "request_sha256": request["request_sha256"],
            "source_material": material_descriptor,
            "source_material_sha256": material_sha,
            "accepted_upstream_identities": copy.deepcopy(
                request["accepted_upstream_identities"]
            ),
            "planned_outputs": copy.deepcopy(request["planned_outputs"]),
            "dataset_source_count": len(CODECS),
            "runtime_authority_build_count": len(_coordinates()),
            "launcher_runtime_authority_build_count": len(SYSTEMS),
        }
        receipt = validate_publication_q4_authority_source_material_receipt_v1(
            {
                **receipt_unsigned,
                "receipt_sha256": _canonical_sha(receipt_unsigned),
            }
        )
        receipt_payload = _canonical_bytes(receipt, newline=True)
        receipt_descriptor = _transaction_descriptor(
            receipt_path, receipt_payload
        )

        observed_names = custody.list_directory_names(
            output_relative, label="Q4 source-material resumable preflight"
        )
        allowed_states = {
            (),
            (MATERIAL_FILENAME,),
            tuple(sorted((MATERIAL_FILENAME, RECEIPT_FILENAME))),
        }
        _require(
            observed_names in allowed_states,
            "Q4 source-material output directory is not empty with an exact "
            "resumable prefix; overwrite refused",
        )
        _require(
            RECEIPT_FILENAME not in observed_names
            or MATERIAL_FILENAME in observed_names,
            "Q4 source-material receipt exists without its causal material",
        )

        identities: dict[str, tuple[int, int]] = {}

        def material_fault_step(step: str) -> None:
            _after_artifact_commit(
                after_artifact_commit,
                f"{MATERIAL_FILENAME}:{step}",
                custody=custody,
                watch_path=f"{output_relative}/.publication-q4-fault-boundary",
            )

        observed, identities[MATERIAL_FILENAME], material_disposition = (
            custody.commit_or_adopt_exact_identity(
                material_path,
                material_payload,
                label="Q4 unsigned authority source material",
                mode=0o444,
                create_parents=False,
                after_publish_step=(
                    material_fault_step
                    if after_artifact_commit is not None
                    else None
                ),
            )
        )
        _require(
            observed == material_descriptor,
            "committed/adopted Q4 source-material descriptor drifted",
        )
        if material_disposition == "published":
            _after_artifact_commit(
                after_artifact_commit,
                MATERIAL_FILENAME,
                custody=custody,
                watch_path=f"{output_relative}/.publication-q4-fault-boundary",
            )

        # The material must still name the exact adopted/created inode before
        # the receipt can make the transaction complete.
        _read_exact_transaction_leaf(
            custody,
            path=material_path,
            payload=material_payload,
            label="pre-receipt Q4 unsigned authority source material",
            expected_identity=identities[MATERIAL_FILENAME],
        )
        loaded_material_descriptor, loaded_spec = (
            load_publication_q4_authority_source_material_v1(
                project_root=project_root,
                source_material_path=material_path,
                expected_source_material_file_sha256=material_descriptor["sha256"],
                expected_source_material_sha256=material_sha,
            )
        )
        _require(
            loaded_material_descriptor == material_descriptor
            and loaded_spec["source_spec_sha256"] == material_sha,
            "Q4 unsigned source material changed across pipeline cold-load",
        )

        def receipt_fault_step(step: str) -> None:
            _after_artifact_commit(
                after_artifact_commit,
                f"{RECEIPT_FILENAME}:{step}",
                custody=custody,
                watch_path=f"{output_relative}/.publication-q4-fault-boundary",
            )

        observed, identities[RECEIPT_FILENAME], receipt_disposition = (
            custody.commit_or_adopt_exact_identity(
                receipt_path,
                receipt_payload,
                label="Q4 source-material receipt-last commit",
                mode=0o444,
                create_parents=False,
                after_publish_step=(
                    receipt_fault_step
                    if after_artifact_commit is not None
                    else None
                ),
            )
        )
        _require(
            observed == receipt_descriptor,
            "committed/adopted Q4 source-material receipt descriptor drifted",
        )
        if receipt_disposition == "published":
            _after_artifact_commit(
                after_artifact_commit,
                RECEIPT_FILENAME,
                custody=custody,
                watch_path=f"{output_relative}/.publication-q4-fault-boundary",
            )

        _require(
            custody.list_directory_names(
                output_relative, label="Q4 source-material committed namespace"
            )
            == tuple(sorted((MATERIAL_FILENAME, RECEIPT_FILENAME))),
            "Q4 source-material committed namespace drifted",
        )
        _read_exact_transaction_leaf(
            custody,
            path=material_path,
            payload=material_payload,
            label="committed Q4 unsigned authority source material",
            expected_identity=identities[MATERIAL_FILENAME],
        )
        _read_exact_transaction_leaf(
            custody,
            path=receipt_path,
            payload=receipt_payload,
            label="committed Q4 source-material receipt",
            expected_identity=identities[RECEIPT_FILENAME],
        )

    return load_publication_q4_authority_source_material_receipt_v1(
        project_root=project_root,
        receipt_path=receipt_path,
        expected_receipt_file_sha256=receipt_descriptor["sha256"],
        expected_receipt_sha256=receipt["receipt_sha256"],
    )


def run_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the unsigned production Q4 authority source material."
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--request-file-sha256", required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    try:
        arguments = parser.parse_args(list(argv))
        receipt = materialize_publication_q4_authority_source_material_v1(
            project_root=arguments.project_root,
            request_path=arguments.request,
            expected_request_file_sha256=arguments.request_file_sha256,
            expected_request_sha256=arguments.request_sha256,
            output_dir=arguments.output_dir,
        )
        sys.stdout.buffer.write(_canonical_bytes(receipt, newline=True))
        sys.stdout.buffer.flush()
        return 0
    except SystemExit as error:
        return int(error.code)
    except Exception as error:
        sys.stderr.write(f"Q4 authority source-material producer rejected: {error}\n"[:4096])
        sys.stderr.flush()
        return EXIT_REJECTED


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_REJECTED",
    "MATERIAL_FILENAME",
    "RECEIPT_FILENAME",
    "RECEIPT_KIND",
    "REQUEST_KIND",
    "PublicationQ4AuthoritySourceMaterialV1Error",
    "build_publication_q4_authority_source_material_request_v1",
    "build_publication_q4_authority_source_material_v1",
    "load_publication_q4_authority_source_material_receipt_v1",
    "main",
    "materialize_publication_q4_authority_source_material_v1",
    "run_cli",
    "validate_publication_q4_authority_source_material_receipt_v1",
    "validate_publication_q4_authority_source_material_request_v1",
]
