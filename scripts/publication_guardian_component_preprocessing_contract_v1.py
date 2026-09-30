"""Receipt-bound preprocessing for one selected GStreamer resource pair.

This distinct kind cannot authorize full qualification or publication.  The
source authority predates the capture plan; this receipt then binds both.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Mapping

from publication_gstreamer_component_authority_v1 import (
    held_component_authority_v1, validate_component_original_native_row_v1,
)
from publication_guardian_preprocessing_contract_v1 import (
    GuardianPreprocessingContractV1Error, _canonical, _commit_receipt_last_bundle_v1,
    _physical_root, _planned_descriptor, _semantic_sha, _under_root, _valid_sha,
)
from publication_guardian_runtime_expectations_v1 import runtime_expectations_from_worker_projection_v1
from publication_operational_capture_plan_v1 import (
    COMMON_FIELDS, DIAGNOSTIC_MODE, GUARDIAN_CONTEXT_FIELDS, GUARDIAN_INPUT_ROLES,
    INVENTORY_KIND, MANIFEST_KIND, MAX_DOCUMENT_BYTES, ROUTES,
    _custody, _document, _guardian_context, _path, _rows,
)
from publication_operational_request_domain_v1 import canonical_json_v1, strict_json_object_v1

RECEIPT_KIND = "vast_guardian_component_preprocessing_contract_materialization_v1"
AUTHORITY_KIND = "vast_guardian_component_preprocessing_contract_authority_v1"
CONTRACT_FILENAME = "guardian-preprocessing-contract.v1.json"
RECEIPT_FILENAME = "guardian-component-preprocessing-receipt.v1.json"
OPERATION_FIELDS = {"operation_id", "arm_id", "run_id", "system", "scenario", "codec", "policy", "deadline_ms", "wire_arm_id"}
RECEIPT_FIELDS = {"schema_version", "artifact_kind", "scope", "accepted", "publication_ready",
    "authorization_eligible", "component_authority", "capability_manifest", "operational_context",
    "preprocessing_contract", "preprocessing_contract_content_sha256", "policy_contract_sha256",
    "worker_projection", "allowed_operations", "receipt_sha256"}
AUTHORITY_SHA_FIELDS = {"component_authority_file_sha256", "component_authority_identity_sha256",
    "capability_manifest_file_sha256", "operational_context_file_sha256", "operational_context_identity_sha256",
    "preprocessing_contract_content_sha256", "preprocessing_contract_file_sha256",
    "materialization_receipt_identity_sha256", "materialization_receipt_file_sha256", "policy_contract_sha256"}
AUTHORITY_FIELDS = {"schema_version", "artifact_kind", "allowed_operations"} | AUTHORITY_SHA_FIELDS


class ComponentGuardianPreprocessingContractV1Error(GuardianPreprocessingContractV1Error):
    """A selected source, preprocessing input or capture scope drifted."""


def _require(ok: object, message: str) -> None:
    if not ok:
        raise ComponentGuardianPreprocessingContractV1Error(message)


def _descriptor(custody, root: Path, value, *, label: str):
    path = _under_root(root, value, label=label)
    descriptor, raw = custody.read_descriptor(path, label=label, maximum=MAX_DOCUMENT_BYTES)
    return descriptor, raw


def _absolute(root: Path, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {**descriptor, "path": str(_under_root(root, descriptor["path"], label="component descriptor"))}


def _allowed_operations(rows) -> list[dict[str, Any]]:
    return [{**{key: row[key] for key in OPERATION_FIELDS - {"wire_arm_id"}},
        "wire_arm_id": hashlib.sha256(("analytics_execution_arm_v1\n" + row["run_id"] + "\n" +
            row["policy"] + "\n" + f"{row['deadline_ms']:.6f}").encode("ascii")).hexdigest()} for row in rows]


def _validate_operations(value):
    _require(type(value) is list and len(value) == 2, "component scope requires exactly two original operations")
    for row in value:
        _require(type(row) is dict and set(row) == OPERATION_FIELDS and row["system"] == "gstreamer_custom"
            and row["codec"] == "h264" and row["policy"] in {"cpu_only", "gpu_only"}
            and type(row["deadline_ms"]) in {int, float} and row["deadline_ms"] == 100.0
            and _valid_sha(row["wire_arm_id"]), "component operation coordinates drifted")
        for key, maximum in (("operation_id", 128), ("arm_id", 68), ("run_id", 64)):
            _require(type(row[key]) is str and 0 < len(row[key]) <= maximum and row[key].isascii()
                and all(0x21 <= ord(char) < 0x7f and char not in {'"', '\\'} for char in row[key]),
                     "component operation ID exceeds original constructor bounds")
        expected = hashlib.sha256(("analytics_execution_arm_v1\n" + row["run_id"] + "\n" + row["policy"] +
            "\n" + f"{row['deadline_ms']:.6f}").encode("ascii")).hexdigest()
        _require(row["wire_arm_id"] == expected, "component native wire arm identity drifted")
    _require(len({row["arm_id"] for row in value}) == 2 and len({row["operation_id"] for row in value}) == 2
        and len({row["policy"] for row in value}) == 1 and {row["scenario"] for row in value} == {
            "checkpoint_independent_processes_baseline", "checkpoint_video_dag_shared"},
        "component scope is not one forced resource baseline/shared pair")
    return copy.deepcopy(value)


def validate_component_guardian_preprocessing_authority_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == AUTHORITY_FIELDS and type(value.get("schema_version")) is int
        and value.get("schema_version") == 1
        and value.get("artifact_kind") == AUTHORITY_KIND and all(_valid_sha(value.get(key)) for key in AUTHORITY_SHA_FIELDS),
        "component preprocessing authority fields/identities drifted")
    _validate_operations(value["allowed_operations"])
    return copy.deepcopy(value)


def validate_component_operational_context_v1(authority, context) -> None:
    """Bind service activation to the exact prelaunch context bytes."""
    validate_component_guardian_preprocessing_authority_v1(authority)
    _require(type(context) is dict and set(context) == {"headers_by_route", "output_dir"},
        "component guardian requires explicit active operational capture")
    headers = context["headers_by_route"]
    _require(type(headers) is dict and set(headers) == {tuple(route.split(":")) for route in ROUTES},
        "component operational headers must cover the original eight routes")
    unsigned = {"schema_version": 1, "artifact_kind": "vast_guardian_operational_capture_context_v1",
        "mode": DIAGNOSTIC_MODE, "headers_by_route": {":".join(route): header for route, header in headers.items()},
        "output_dir": context["output_dir"]}
    document = {**unsigned, "sha256": _semantic_sha(unsigned)}
    _require(document["sha256"] == authority["operational_context_identity_sha256"]
        and hashlib.sha256(_canonical(document) + b"\n").hexdigest() == authority["operational_context_file_sha256"],
        "component active context differs from preprocessing authority")


def validate_component_front_request_v1(authority, manifest, message, route, protocol_mode) -> None:
    """Reject sibling implementations and foreign forced routes before inference."""
    _require(protocol_mode == "gstreamer" and message.get("message_type") == "analytics_execute",
        "component guardian accepts only its selected native GStreamer requests")
    matches = [operation for operation in authority["allowed_operations"] if operation["run_id"] == message.get("run_id")
        and operation["wire_arm_id"] == message.get("arm_id")]
    _require(len(matches) == 1, "component request is outside its exact two original operations")
    branch, resource = route
    decision = message.get("decision")
    _require(type(decision) is dict and resource == matches[0]["policy"].removesuffix("_only")
        and decision.get("selected_resource") == resource, "component request changed its original forced resource")
    try:
        binding = manifest["systems"]["gstreamer_custom"]["branches"][branch][resource]
        native = binding["native_evidence"]
    except (KeyError, TypeError) as error:
        raise ComponentGuardianPreprocessingContractV1Error("component GStreamer binding is missing") from error
    _require(decision.get("selected_implementation_id") == binding["implementation_id"]
        and decision.get("emitter_id") == native["emitter_id"]
        and decision.get("emitter_sha256") == native["emitter_sha256"],
        "component request changed its selected GStreamer implementation/emitter")


def _scope(root, pins, source, context_descriptor):
    context_raw = pins.read(_absolute(root, context_descriptor), MAX_DOCUMENT_BYTES)
    context = _document(context_raw, GUARDIAN_CONTEXT_FIELDS,
        "vast_guardian_operational_capture_context_v1", DIAGNOSTIC_MODE)
    headers = context["headers_by_route"]
    _require(type(headers) is dict and set(headers) == set(ROUTES), "component capture route coverage drifted")
    first = headers[ROUTES[0]]
    _require(type(first) is dict and type(first.get("descriptors")) is dict, "component capture header missing")
    descriptors = first["descriptors"]
    manifest = _document(pins.read(descriptors["accounting_input"], MAX_DOCUMENT_BYTES),
        COMMON_FIELDS | {"operations"}, MANIFEST_KIND, DIAGNOSTIC_MODE)
    rows = _rows(DIAGNOSTIC_MODE, manifest["operations"])
    cells = source["planned_cells"]
    _require(type(cells) is list and len(cells) == 2, "selected authority does not contain exact two stock cells")
    by_arm = {cell["arm_id"]: cell for cell in cells}
    _require(len(by_arm) == 2 and {row["arm_id"] for row in rows} == set(by_arm), "capture originals differ from selected stock cells")
    for row in rows:
        raw_plan = pins.read(row["descriptors"]["source_plan"])
        plan = strict_json_object_v1(raw_plan, max_bytes=len(raw_plan))
        try:
            validate_component_original_native_row_v1(source=source, row=row, source_plan=plan)
        except ValueError as error:
            raise ComponentGuardianPreprocessingContractV1Error(str(error)) from error
        for descriptor in [row["original_operation"], *row["descriptors"].values()]:
            pins.read(descriptor, capture=False)
    inventory = _document(pins.read(descriptors["source_plan"], MAX_DOCUMENT_BYTES),
        COMMON_FIELDS | {"source_plans"}, INVENTORY_KIND, DIAGNOSTIC_MODE)
    _require(inventory["source_plans"] == [{"operation_id": row["operation_id"], "descriptor": row["descriptors"]["source_plan"]} for row in rows],
        "component source-plan inventory differs from original operations")
    guardian_inputs = {role: descriptors[role] for role in GUARDIAN_INPUT_ROLES}
    for descriptor in guardian_inputs.values():
        pins.read(descriptor, capture=False)
    _require(guardian_inputs["capability_manifest"] == _absolute(root, source["capability_manifest_descriptor"]),
        "component capture capability manifest differs from original capability bytes")
    execution = source["worker_projection"]["execution_config"]
    _require(guardian_inputs["execution_config"] == _absolute(root, {key: execution[key] for key in ("path", "size_bytes", "sha256")}),
        "component capture execution config differs from selected worker authority")
    _require(guardian_inputs["model_authority"] == _absolute(root, source["document"]["model_authority"])
        and guardian_inputs["execution_code_closure"] == _absolute(root, source["document"]["execution_code_closure"]),
        "component capture model/code authority differs from selected source")
    _require(context == _guardian_context(rows, DIAGNOSTIC_MODE, guardian_inputs,
        descriptors["accounting_input"], descriptors["source_plan"], _path(context["output_dir"])),
        "component guardian constants differ from actual original rows")
    return context, _validate_operations(_allowed_operations(rows))


def _receipt(source, context_descriptor, context, operations, contract_descriptor):
    unsigned = {"schema_version": 1, "artifact_kind": RECEIPT_KIND,
        "scope": "selected_gstreamer_forced_resource_pair_only", "accepted": False,
        "publication_ready": False, "authorization_eligible": False,
        "component_authority": source["descriptor"], "capability_manifest": source["capability_manifest_descriptor"],
        "operational_context": context_descriptor, "preprocessing_contract": contract_descriptor,
        "preprocessing_contract_content_sha256": _semantic_sha(source["preprocessing_contract"]),
        "policy_contract_sha256": source["document"]["policy_contract_sha256"],
        "worker_projection": source["worker_projection"], "allowed_operations": operations}
    return {**unsigned, "receipt_sha256": _semantic_sha(unsigned)}


def materialize_component_guardian_preprocessing_contract_v1(*, project_root, component_authority_path,
    operational_context_path, output_dir) -> dict[str, Any]:
    root = _physical_root(project_root)
    output = _under_root(root, output_dir, label="component preprocessing output")
    _require(output != root, "component preprocessing requires a dedicated output directory")
    with held_component_authority_v1(project_root=root, component_authority_path=component_authority_path) as source:
        with _custody(root) as (custody, pins):
            context_descriptor, _ = _descriptor(custody, root, operational_context_path, label="component operational context")
            context, operations = _scope(root, pins, source, context_descriptor)
            contract_payload = _canonical(source["preprocessing_contract"]) + b"\n"
            contract_descriptor = _planned_descriptor(root, output / CONTRACT_FILENAME, contract_payload)
            receipt = _receipt(source, context_descriptor, context, operations, contract_descriptor)
            pins.verify()
            source["verify_barrier"]()
            _commit_receipt_last_bundle_v1(root=root, output=output,
                intent_kind="vast_guardian_component_preprocessing_materialization_intent_v1",
                ordered_payloads=((CONTRACT_FILENAME, contract_payload), (RECEIPT_FILENAME, _canonical(receipt) + b"\n")),
                label="component guardian preprocessing")
            pins.verify()
            source["verify_barrier"]()
    return {"contract_path": output / CONTRACT_FILENAME, "receipt_path": output / RECEIPT_FILENAME,
        "preprocessing_contract_sha256": receipt["preprocessing_contract_content_sha256"]}


def load_component_guardian_preprocessing_contract_v1(*, project_root, preprocessing_contract_path,
    materialization_receipt_path, capability_manifest_path, component_authority_path=None,
    operational_context_path=None) -> dict[str, Any]:
    root = _physical_root(project_root)
    with _custody(root) as (custody, pins):
        receipt_descriptor, _ = _descriptor(custody, root, materialization_receipt_path, label="component preprocessing receipt")
        receipt_path = _under_root(root, materialization_receipt_path, label="component receipt")
        contract_path = _under_root(root, preprocessing_contract_path, label="component contract")
        _require(receipt_path.name == RECEIPT_FILENAME and contract_path.name == CONTRACT_FILENAME
            and receipt_path.parent == contract_path.parent, "component preprocessing contract/receipt namespace drifted")
        raw = pins.read(_absolute(root, receipt_descriptor), MAX_DOCUMENT_BYTES)
        receipt = strict_json_object_v1(raw, max_bytes=MAX_DOCUMENT_BYTES)
        _require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS and receipt["artifact_kind"] == RECEIPT_KIND,
            "component preprocessing receipt fields/kind drifted")
        source_descriptor = receipt["component_authority"]
        context_descriptor = receipt["operational_context"]
        if component_authority_path is not None:
            _require(_under_root(root, component_authority_path, label="component authority") ==
                _under_root(root, source_descriptor["path"], label="component authority"), "explicit component authority path differs")
        if operational_context_path is not None:
            _require(_under_root(root, operational_context_path, label="component context") ==
                _under_root(root, context_descriptor["path"], label="component context"), "explicit component context path differs")
        with held_component_authority_v1(project_root=root, component_authority_path=source_descriptor["path"],
            expected_descriptor=source_descriptor) as source:
            context, operations = _scope(root, pins, source, context_descriptor)
            contract_descriptor, _ = _descriptor(custody, root, preprocessing_contract_path, label="component preprocessing contract")
            contract_raw = pins.read(_absolute(root, contract_descriptor), MAX_DOCUMENT_BYTES)
            contract = strict_json_object_v1(contract_raw, max_bytes=MAX_DOCUMENT_BYTES)
            _require(contract == source["preprocessing_contract"] and contract_raw == _canonical(contract) + b"\n",
                "component preprocessing contract differs from selected original contract")
            capability_descriptor, _ = _descriptor(custody, root, capability_manifest_path, label="component capability manifest")
            _require(capability_descriptor == source["capability_manifest_descriptor"], "component capability path/bytes differ")
            _require(raw == _canonical(receipt) + b"\n" and receipt == _receipt(source, context_descriptor, context, operations, contract_descriptor),
                "component preprocessing receipt differs from physically recomputed inputs")
            runtime_expectations_from_worker_projection_v1(execution_config_authority=source["worker_projection"]["execution_config"],
                binding_set_authority=source["worker_projection"]["binding_set"], worker_authority=source["worker_projection"]["workers"],
                policy_contract_sha256=receipt["policy_contract_sha256"],
                preprocessing_contract_content_sha256=receipt["preprocessing_contract_content_sha256"])
            authority = {"schema_version": 1, "artifact_kind": AUTHORITY_KIND, "allowed_operations": operations,
                "component_authority_file_sha256": source_descriptor["sha256"],
                "component_authority_identity_sha256": source["document"]["sha256"],
                "capability_manifest_file_sha256": capability_descriptor["sha256"],
                "operational_context_file_sha256": context_descriptor["sha256"],
                "operational_context_identity_sha256": context["sha256"],
                "preprocessing_contract_content_sha256": receipt["preprocessing_contract_content_sha256"],
                "preprocessing_contract_file_sha256": contract_descriptor["sha256"],
                "materialization_receipt_identity_sha256": receipt["receipt_sha256"],
                "materialization_receipt_file_sha256": receipt_descriptor["sha256"],
                "policy_contract_sha256": receipt["policy_contract_sha256"]}
            validate_component_guardian_preprocessing_authority_v1(authority)
            pins.verify()
            source["verify_barrier"]()
    return {"preprocessing_contract": contract, "receipt": receipt, "authority": authority}
