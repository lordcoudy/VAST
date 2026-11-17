#!/usr/bin/env python3
"""Stock host owner of the reviewed original operations under one guardian.

The sealed capture plan is the only operation authority. ``execute`` runs the
held originals (four native prechecks and one Savant original, or the bounded
diagnostic pair) through the existing single-operation diagnostic runner, then
the 32 stock cells through ``execute_qualification_pilots_v2`` whose exact
four-system ``runtime_registry`` opens one ``capture_original_engine_processes_v1``
per planned cell. After the authenticated guardian stop, ``bind`` cold-validates
every original process/container receipt and writes the existing
``vast_original_operational_execution_binding_v1``. No new format, limit or
publication authority is created; a missing, extra, duplicated or foreign
operation fails closed and nothing is retried.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import MappingProxyType

from checkpoint_publication_launcher_adapter_v3 import NativePublicationRequestV3
from publication_operational_capture_plan_v1 import (
    DIAGNOSTIC_MODE, QUALIFICATION_MODE, held_operational_capture_plan_v1,
)
from publication_operational_container_custody_v1 import original_container_validator_v1
from publication_operational_process_custody_v1 import (
    capture_original_engine_processes_v1, original_process_validator_v1,
)
from publication_operational_request_domain_v1 import (
    canonical_json_v1, payload_with_sha256_v1, strict_json_object_v1, validate_descriptor_v1,
)
from publication_physical_io_v1 import PhysicalRootCustodyV1
import publication_policy_qualification_pilot_executor_v2 as pilot

BINDING_KIND = "vast_original_operational_execution_binding_v1"
BINDING_FIELDS = {"schema_version", "artifact_kind", "mode", "capture_plan",
    "guardian_companion", "operation_outputs", "sha256"}
OUTPUT_FIELDS = {"operation_id", "native_domain", "measurement_decisions",
    "accepted_ingress", "process_receipt", "container_receipt"}
OPERATION_COUNTS = {QUALIFICATION_MODE: 37, DIAGNOSTIC_MODE: 2}
HELD_PHASES = {QUALIFICATION_MODE: ("native_precheck", "savant_original"), DIAGNOSTIC_MODE: ("diagnostic",)}
HELD_COUNTS = {QUALIFICATION_MODE: 5, DIAGNOSTIC_MODE: 2}
CELL_PHASE = "qualification_cell"
GUARDIAN_GROUP_FILENAME = "operational_group.v1.json"
MAX_BINDING_BYTES = 1024 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
# The exact keyword set of the stock pilot executor; held runners take a subset.
STOCK_ARGUMENTS = ("candidate_index_path", "candidate_manifest_path", "candidate_receipt_path",
    "bootstrap_mapping_path", "bootstrap_receipt_path", "bootstrap_dir", "transaction_receipt_path",
    "runtime_input_materialization_receipt_path", "guardian_service_authority_path",
    "preprocessing_contract_path", "preprocessing_contract_receipt_path",
    "execution_code_closure_receipt_path", "pilot_root", "checkpoint_path")


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _root(project_root):
    root = Path(os.path.abspath(os.fspath(project_root)))
    _require(root.resolve(strict=True) == root and root.is_dir(),
             "original owner project_root is not one physical canonical directory")
    return root


def _absolute(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    _require(str(path) == os.path.normpath(str(path)) and path.is_relative_to(root) and path != root,
             "original owner path escaped project_root")
    return path


def _load_original(root, operation):
    """Read the sealed original operation document named by the plan."""
    descriptor = operation["original_operation"]
    with PhysicalRootCustodyV1.open(root, label="original owner operation document") as custody:
        observed, raw = custody.read_descriptor(descriptor["path"], label="original owner operation document",
            maximum=MAX_BINDING_BYTES, capture=True)
        custody.verify()
    observed["path"] = str(root / observed["path"])
    _require(observed == descriptor, "original operation document physical descriptor drifted")
    value = strict_json_object_v1(raw, max_bytes=MAX_BINDING_BYTES)
    _require(canonical_json_v1(value) + b"\n" == raw and set(value) == {"schema_version", "artifact_kind",
        "operation", "container_image", "outputs", "sha256"} and value["schema_version"] == 1
        and value["artifact_kind"] == "vast_original_native_operation_input_v1"
        and payload_with_sha256_v1(value)["sha256"] == value["sha256"]
        and value["operation"] == {key: item for key, item in operation.items() if key != "original_operation"},
        "original operation document differs from its sealed plan row")
    outputs = value["outputs"]
    _require(type(outputs) is dict and set(outputs) == {"measurement_dir", "native_domain",
        "process_receipt", "container_receipt"}, "original output reservations are incomplete")
    for name in outputs.values():
        _absolute(root, name)
    process_dir = Path(outputs["process_receipt"]).parent
    _require(Path(outputs["process_receipt"]).name == "original_engine_process_capture.v1.json"
        and Path(outputs["container_receipt"]) == process_dir / "container-custody/original_container_custody.v1.json"
        and Path(outputs["native_domain"]).parent == Path(outputs["measurement_dir"] + ".operational"),
        "original output reservations differ from the stock capture layout")
    return value


def _reserved_paths(original):
    outputs = original["outputs"]
    directory = Path(outputs["measurement_dir"])
    return (directory, Path(str(directory) + ".operational"), Path(outputs["process_receipt"]).parent)


@contextmanager
def original_operation_capture_v1(*, project_root, operation, native_context_descriptor, original):
    """Open the one original engine capture reserved for a planned operation."""
    outputs = original["outputs"]
    with capture_original_engine_processes_v1(project_root=project_root,
            output_dir=Path(outputs["process_receipt"]).parent, operation_id=operation["operation_id"],
            original_operation_descriptor=operation["original_operation"],
            native_context_descriptor=native_context_descriptor,
            container_image=original["container_image"]) as capture:
        yield capture
    _require(capture.receipt_descriptor is not None and capture.container_receipt_descriptor is not None
        and capture.receipt_descriptor["path"] == outputs["process_receipt"]
        and capture.container_receipt_descriptor["path"] == outputs["container_receipt"],
        "original process/container receipts are missing or detached from their reservation")


def _operation_output_v1(*, root, operation, native_context_descriptor, original):
    """Cold original validators decide; the owner only names their physical leaves."""
    outputs = original["outputs"]
    _require(os.path.lexists(outputs["process_receipt"]) and os.path.lexists(outputs["container_receipt"]),
             "original process/container receipt is missing: " + operation["operation_id"])
    arguments = dict(project_root=root, operation_id=operation["operation_id"],
        original_operation_descriptor=operation["original_operation"],
        native_context_descriptor=native_context_descriptor, expected_container_image=original["container_image"])
    process = original_process_validator_v1(receipt_path=outputs["process_receipt"], **arguments)
    container = original_container_validator_v1(receipt_path=outputs["container_receipt"],
        process_receipt_path=outputs["process_receipt"], expected_process_descriptor=process["descriptor"], **arguments)
    _require(container["container_quiescence_verified"] is True, "original container terminal is unverified")
    directory = Path(outputs["measurement_dir"])
    with PhysicalRootCustodyV1.open(root, label="original owner operation outputs") as custody:
        def descriptor(path, label):
            value, _ = custody.read_descriptor(path, label=label, maximum=MAX_EVIDENCE_BYTES)
            value["path"] = str(root / value["path"])
            return value
        row = {"operation_id": operation["operation_id"],
            "native_domain": descriptor(outputs["native_domain"], "original native operational domain"),
            "measurement_decisions": descriptor(directory / "publication_policy_decisions.jsonl",
                                                "original measurement decisions"),
            "accepted_ingress": descriptor(directory / "ingress_ledger.csv", "original accepted ingress"),
            "process_receipt": copy.deepcopy(process["descriptor"]),
            "container_receipt": copy.deepcopy(container["descriptor"])}
        custody.verify()
    return row


def _require_exact_capture_namespace(root, originals):
    """Every capture directory beside a reserved one belongs to the plan."""
    expected = {}
    for original in originals.values():
        process_dir = _reserved_paths(original)[2]
        expected.setdefault(process_dir.parent, set()).add(process_dir.name)
    with PhysicalRootCustodyV1.open(root, label="original owner capture namespace") as custody:
        for parent, names in expected.items():
            observed = set(custody.list_directory_names(parent, label="original capture namespace"))
            _require(observed == names, "original capture namespace has missing or extra foreign invocations: "
                + ",".join(sorted(observed ^ names)))
        custody.verify()


class _OperationLedger:
    def __init__(self, expected):
        self.expected, self.started, self.completed = frozenset(expected), set(), set()

    def start(self, identity):
        _require(identity in self.expected, "foreign original operation is not planned")
        _require(identity not in self.started, "duplicate original invocation is forbidden: " + identity)
        self.started.add(identity)

    def complete(self, identity):
        _require(identity in self.started and identity not in self.completed,
                 "original operation completion is detached")
        self.completed.add(identity)

    def require_complete(self, label):
        missing = sorted(self.expected - self.completed)
        _require(not missing and self.started == self.completed == self.expected,
                 label + " missing or incomplete original operations: " + ",".join(missing))


def operational_runtime_registry_v1(*, project_root, cells_by_arm, contexts, originals, base_registry, ledger):
    """Wrap the four stock runners; one planned capture per original cell."""
    root = _root(project_root)
    _require(set(base_registry) == set(pilot.SYSTEMS) and all(callable(base_registry[name]) for name in pilot.SYSTEMS),
             "stock runtime registry must contain exactly four direct callables")

    def wrap(system, runner):
        def captured(request):
            _require(type(request) is NativePublicationRequestV3 and request.system == system,
                     "original qualification request differs from its stock runtime system")
            operation = cells_by_arm.get(request.arm_id)
            _require(operation is not None, "foreign original qualification runtime request: " + str(request.arm_id))
            topology = "shared_video_dag" if operation["scenario"] == "checkpoint_video_dag_shared" else "independent_processes"
            _require(operation["system"] == request.system and operation["run_id"] == request.run_id
                and operation["scenario"] == request.scenario and request.topology_kind == topology
                and Path(request.project_root) == root,
                "original qualification request differs from the planned original cell")
            identity = operation["operation_id"]
            ledger.start(identity)
            original = originals[identity]
            _require(all(not os.path.lexists(path) for path in _reserved_paths(original)),
                     "original qualification output is occupied; a new invocation is forbidden")
            with original_operation_capture_v1(project_root=root, operation=operation,
                    native_context_descriptor=contexts[identity], original=original):
                outcome = runner(request)
            ledger.complete(identity)
            return outcome
        return captured
    return MappingProxyType({system: wrap(system, base_registry[system]) for system in pilot.SYSTEMS})


def _stock_held_operation_v1(*, project_root, capture_plan_path, operation, stock_arguments):
    """Delegate one held original to the existing single-operation runner."""
    from publication_benchmark_native_diagnostic_v1 import execute_native_diagnostic_operation_v1
    root = _root(project_root)
    mapping = _absolute(root, stock_arguments["bootstrap_mapping_path"])
    _require(_absolute(root, stock_arguments["bootstrap_dir"]) == mapping.parent,
             "held original bootstrap mapping is detached from bootstrap_dir")
    cell = next((cell for cell in pilot.qualification_pilot_cells_v2() if cell.arm_id == operation["arm_id"]), None)
    _require(cell is not None, "held original has no stock runtime bundle")
    return execute_native_diagnostic_operation_v1(project_root=root, capture_plan_path=capture_plan_path,
        operation_id=operation["operation_id"], runtime_bundle_path=pilot._runtime_bundle_path(mapping.parent, cell),
        candidate_index_path=stock_arguments["candidate_index_path"],
        preprocessing_contract_path=stock_arguments["preprocessing_contract_path"],
        preprocessing_receipt_path=stock_arguments["preprocessing_contract_receipt_path"],
        runtime_materialization_receipt_path=stock_arguments["runtime_input_materialization_receipt_path"],
        guardian_authority_path=stock_arguments["guardian_service_authority_path"],
        transaction_receipt_path=stock_arguments["transaction_receipt_path"],
        bootstrap_mapping_path=stock_arguments["bootstrap_mapping_path"],
        bootstrap_receipt_path=stock_arguments["bootstrap_receipt_path"])


def _held_plan(root, capture_plan_path):
    return held_operational_capture_plan_v1(project_root=root, index_path=_absolute(root, capture_plan_path))


def _plan_rows(plan):
    mode = plan["index"]["mode"]
    _require(mode in OPERATION_COUNTS, "original owner capture mode is unsupported")
    rows = list(plan["operations_by_id"].values())
    _require(len(rows) == OPERATION_COUNTS[mode], "original owner plan cardinality drifted")
    held = [row for row in rows if row["phase"] in HELD_PHASES[mode]]
    cells = [row for row in rows if row["phase"] == CELL_PHASE]
    _require(len(held) == HELD_COUNTS[mode] and len(held) + len(cells) == len(rows)
             and len(cells) == (32 if mode == QUALIFICATION_MODE else 0),
             "original owner plan phases differ from the reviewed operations")
    contexts = {ref["operation_id"]: ref["descriptor"] for ref in plan["index"]["native_contexts"]}
    _require(set(contexts) == set(plan["operations_by_id"]), "original native context set drifted")
    return mode, rows, held, cells, contexts


def execute_qualification_operational_owner_v1(*, project_root, capture_plan_path, stock_arguments,
        held_operation_runner=None, pilot_executor=None, runtime_registry=None):
    """Run each planned original exactly once; return nonauthorizing identities."""
    root = _root(project_root)
    _require(type(stock_arguments) is dict and set(stock_arguments) == set(STOCK_ARGUMENTS),
             "original owner stock arguments differ from the stock pilot executor")
    held_runner = held_operation_runner or _stock_held_operation_v1
    executor = pilot_executor or pilot.execute_qualification_pilots_v2
    base_registry = runtime_registry or pilot.NATIVE_RUNTIME_REGISTRY
    plan_path = _absolute(root, capture_plan_path)
    with _held_plan(root, plan_path) as plan:
        mode, rows, held, cells, contexts = _plan_rows(plan)
        originals = {row["operation_id"]: _load_original(root, row) for row in rows}
        if cells:
            _require(not os.path.lexists(_absolute(root, stock_arguments["checkpoint_path"])),
                     "pilot checkpoint exists; a resumed matrix cannot satisfy one original owner")
            pilot_root = _absolute(root, stock_arguments["pilot_root"])
            stock_cells = {cell.arm_id: cell for cell in pilot.qualification_pilot_cells_v2()}
            _require(set(stock_cells) == {row["arm_id"] for row in cells}, "planned cells differ from stock cells")
            for row in cells:
                _require(originals[row["operation_id"]]["outputs"]["measurement_dir"] ==
                    str(pilot._pilot_path(pilot_root, stock_cells[row["arm_id"]])),
                    "planned cell reservation differs from the stock pilot namespace")
        for original in originals.values():
            _require(all(not os.path.lexists(path) for path in _reserved_paths(original)),
                     "original output is occupied; a new invocation is forbidden")
        held_ledger = _OperationLedger(row["operation_id"] for row in held)
        for row in held:
            identity = row["operation_id"]
            held_ledger.start(identity)
            held_runner(project_root=root, capture_plan_path=plan_path, operation=copy.deepcopy(row),
                        stock_arguments=dict(stock_arguments))
            _operation_output_v1(root=root, operation=row, native_context_descriptor=contexts[identity],
                                 original=originals[identity])
            held_ledger.complete(identity)
        held_ledger.require_complete("held")
        if cells:
            ledger = _OperationLedger(row["operation_id"] for row in cells)
            registry = operational_runtime_registry_v1(project_root=root,
                cells_by_arm={row["arm_id"]: row for row in cells}, contexts=contexts,
                originals=originals, base_registry=base_registry, ledger=ledger)
            executor(project_root=root, runtime_registry=registry, **stock_arguments)
            ledger.require_complete("qualification cells:")
            for row in cells:
                _operation_output_v1(root=root, operation=row, native_context_descriptor=contexts[row["operation_id"]],
                                     original=originals[row["operation_id"]])
        _require_exact_capture_namespace(root, originals)
        return {"mode": mode, "capture_plan": copy.deepcopy(plan["index"]["operation_manifest"]),
            "operation_ids": [row["operation_id"] for row in rows],
            "accepted": False, "publication_ready": False}


def operational_execution_binding_v1(*, mode, capture_plan, guardian_companion, operation_outputs):
    """Seal the existing binding shape; cold closure remains the only reader."""
    _require(mode in OPERATION_COUNTS, "original binding mode is unsupported")
    validate_descriptor_v1(capture_plan)
    validate_descriptor_v1(guardian_companion)
    _require(type(operation_outputs) is list and len(operation_outputs) == OPERATION_COUNTS[mode],
             "original binding has missing or extra producing operations")
    identities = set()
    for row in operation_outputs:
        _require(type(row) is dict and set(row) == OUTPUT_FIELDS and type(row["operation_id"]) is str
                 and 0 < len(row["operation_id"]) <= 128, "original binding output fields drifted")
        _require(row["operation_id"] not in identities, "duplicate original binding operation")
        identities.add(row["operation_id"])
        for name in OUTPUT_FIELDS - {"operation_id"}:
            validate_descriptor_v1(row[name])
            _require(Path(row[name]["path"]).is_absolute(), "original binding descriptor is not absolute")
    return payload_with_sha256_v1({"schema_version": 1, "artifact_kind": BINDING_KIND, "mode": mode,
        "capture_plan": copy.deepcopy(capture_plan), "guardian_companion": copy.deepcopy(guardian_companion),
        "operation_outputs": copy.deepcopy(operation_outputs)})


def write_operational_execution_binding_v1(*, project_root, binding_path, **values):
    """Exclusively commit one immutable binding; never replace an existing one."""
    root = _root(project_root)
    value = operational_execution_binding_v1(**values)
    raw = canonical_json_v1(value) + b"\n"
    _require(len(raw) <= MAX_BINDING_BYTES, "original binding exceeds its byte bound")
    path = _absolute(root, binding_path)
    with PhysicalRootCustodyV1.open(root, label="original operational execution binding") as custody:
        descriptor = custody.write_exclusive(path, raw, label="original operational execution binding", mode=0o444)
        custody.verify()
    descriptor["path"] = str(path)
    return {"descriptor": descriptor, "value": value}


def bind_operational_execution_v1(*, project_root, capture_plan_path, binding_path):
    """After authenticated stop: cold-validate all planned originals, then bind."""
    root = _root(project_root)
    with _held_plan(root, capture_plan_path) as plan:
        mode, rows, _held, _cells, contexts = _plan_rows(plan)
        originals = {row["operation_id"]: _load_original(root, row) for row in rows}
        _require_exact_capture_namespace(root, originals)
        outputs = [_operation_output_v1(root=root, operation=row, native_context_descriptor=contexts[row["operation_id"]],
                   original=originals[row["operation_id"]]) for row in rows]
        group = Path(plan["guardian_context"]["output_dir"]) / GUARDIAN_GROUP_FILENAME
        with PhysicalRootCustodyV1.open(root, label="original guardian operational group") as custody:
            companion, _ = custody.read_descriptor(group, label="original guardian operational group",
                                                   maximum=MAX_BINDING_BYTES)
            custody.verify()
        companion["path"] = str(root / companion["path"])
        _require_exact_capture_namespace(root, originals)
        return write_operational_execution_binding_v1(project_root=root, binding_path=binding_path, mode=mode,
            capture_plan=_capture_plan_descriptor(root, capture_plan_path), guardian_companion=companion,
            operation_outputs=outputs)


def _capture_plan_descriptor(root, capture_plan_path):
    path = _absolute(root, capture_plan_path)
    with PhysicalRootCustodyV1.open(root, label="original capture plan index") as custody:
        descriptor, _ = custody.read_descriptor(path, label="original capture plan index", maximum=MAX_BINDING_BYTES)
        custody.verify()
    descriptor["path"] = str(path)
    return descriptor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("execute", help="run every planned original once under the live guardian")
    bind = commands.add_parser("bind", help="after authenticated guardian stop, write the execution binding")
    for command in (execute, bind):
        command.add_argument("--project-root", type=Path, required=True)
        command.add_argument("--capture-plan", type=Path, required=True)
    for name in STOCK_ARGUMENTS:
        execute.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    bind.add_argument("--binding-path", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "execute":
            result = execute_qualification_operational_owner_v1(project_root=args["project_root"],
                capture_plan_path=args["capture_plan"],
                stock_arguments={name: args[name] for name in STOCK_ARGUMENTS})
        else:
            result = bind_operational_execution_v1(project_root=args["project_root"],
                capture_plan_path=args["capture_plan"], binding_path=args["binding_path"])["descriptor"]
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(78, "original operational owner failed: " + str(error) + "\n")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
