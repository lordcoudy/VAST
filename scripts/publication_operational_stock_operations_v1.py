"""Thin prelaunch capture planning from the existing publication-v3 authorities.

No measurement or inference is launched here. Stock transaction/parity/image
validators and stock source-plan constructors remain the authority; the output
only reserves original operations and their separate evidence namespaces.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import os
from contextlib import closing, contextmanager
from pathlib import Path

from analytics_execution_endpoint import expected_capability_from_binding_and_probe
from checkpoint_gstreamer_runtime import build_publication_pair_plans
from checkpoint_runtime_plan import validate_checkpoint_runtime_plan
from publication_operational_capture_plan_v1 import build_operational_capture_plan_v1
from publication_operational_request_domain_v1 import (
    BRANCHES, NATIVE_OPERATIONAL_JSONL, canonical_json_v1, payload_with_sha256_v1,
)
from publication_physical_io_v1 import PhysicalRootCustodyV1

QUALIFICATION_MODE = "complete_qualification_operational_identity_v1"
DIAGNOSTIC_MODE = "bounded_native_diagnostic_operational_v1"
# Held single originals: the bounded native pair, or the reviewed
# qualification prechecks and Savant original that reuse their cell bundle.
HELD_OPERATIONS = {(DIAGNOSTIC_MODE, "diagnostic"): frozenset({"gstreamer_custom"}),
    (QUALIFICATION_MODE, "native_precheck"): frozenset({"gstreamer_custom", "openvino_gva"}),
    (QUALIFICATION_MODE, "savant_original"): frozenset({"savant"})}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def front_workers_from_stock_plan_v1(plan, capabilities):
    """Use the unchanged native process IDs or SDK front capability worker ID."""
    try:
        validate_checkpoint_runtime_plan(plan)
        _require(plan["system"] in {"gstreamer_custom", "openvino_gva", "deepstream", "savant"}
            and len(plan["streams"]) == 6 and plan["required_branches"] == list(BRANCHES)
            and [row["stream_id"] for row in plan["streams"]] == list(range(6)),
            "stock operational source must preserve six streams and four branches")
        result = {}
        for branch in BRANCHES:
            for resource in ("cpu", "gpu"):
                rows = []
                for stream in plan["streams"]:
                    if plan["system"] in {"deepstream", "savant"}:
                        identity = capabilities[(branch, resource)]["worker_id"]
                    elif plan["topology_kind"] == "shared_video_dag":
                        identity = stream["graph_process"]["process_id"]
                    else:
                        workers = [row for row in stream["workers"] if row["branch_id"] == branch]
                        _require(len(workers) == 1, "stock native branch worker is missing or duplicated")
                        identity = workers[0]["process_id"]
                    _require(type(identity) is str and 0 < len(identity) <= 128 and identity.isascii(),
                             "stock front worker identity is invalid")
                    rows.append({"worker_id": identity, "stream_id": stream["stream_id"]})
                result[branch + ":" + resource] = rows
        return result
    except ValueError:
        raise
    except (KeyError, TypeError, RuntimeError) as error:
        raise ValueError("stock operational source is invalid: " + str(error)) from error


def _absolute(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    _require(str(path) == os.path.normpath(str(path)) and path.is_relative_to(root)
             and path != root, "original operational path escaped project_root")
    return path


def _abs_descriptor(root, value):
    result = {key: value[key] for key in ("path", "size_bytes", "sha256")}
    result["path"] = str(_absolute(root, result["path"]))
    return result


def _json_write(custody, path, value):
    raw = canonical_json_v1(value) + b"\n"
    _require(len(raw) <= 1024 * 1024, "original operation source document exceeds bound")
    descriptor = custody.write_exclusive(path, raw, label="original stock operational source", mode=0o444)
    descriptor["path"] = str(path)
    return descriptor


def prepare_stock_operational_capture_plan_v1(*, project_root, output_dir, mode,
        candidate_index_path, candidate_manifest_path, candidate_receipt_path,
        bootstrap_mapping_path, bootstrap_receipt_path, bootstrap_dir, transaction_receipt_path,
        preprocessing_contract_path, preprocessing_receipt_path, execution_code_closure_path,
        pilot_root, guardian_output_dir, diagnostic_resource=None,
        container_engine_path=Path("/usr/bin/docker"),
        container_engine_socket_path=Path("/var/run/docker.sock")):
    """Build exactly the reviewed 37 originals or one nonpromoting native pair."""
    import publication_policy_qualification_runtime_inputs_v2 as stock
    from publication_policy_qualification_pilot_executor_v2 import _pilot_path
    from publication_guardian_preprocessing_contract_v1 import load_guardian_preprocessing_contract_v1
    from publication_policy_qualification_execution_code_closure_v1 import load_execution_code_closure_v1

    _require(mode in {QUALIFICATION_MODE, DIAGNOSTIC_MODE}, "unsupported original capture mode")
    _require((mode == DIAGNOSTIC_MODE and diagnostic_resource in {"cpu", "gpu"}) or
             (mode == QUALIFICATION_MODE and diagnostic_resource is None), "original diagnostic resource/mode drifted")
    inputs = stock._load_qualification_inputs(project_root=project_root,
        candidate_index_path=candidate_index_path, candidate_manifest_path=candidate_manifest_path,
        candidate_receipt_path=candidate_receipt_path, bootstrap_mapping_path=bootstrap_mapping_path,
        bootstrap_receipt_path=bootstrap_receipt_path, bootstrap_dir=bootstrap_dir,
        transaction_receipt_path=transaction_receipt_path)
    root = inputs.root
    output = _absolute(root, output_dir)
    pilots = _absolute(root, pilot_root)
    guardian_output = _absolute(root, guardian_output_dir)
    _require(not os.path.lexists(output) and not os.path.lexists(guardian_output),
             "original capture planning must use a fresh namespace")
    preprocessing = load_guardian_preprocessing_contract_v1(project_root=root,
        preprocessing_contract_path=preprocessing_contract_path, materialization_receipt_path=preprocessing_receipt_path,
        candidate_manifest_path=inputs.candidate_manifest.path)
    closure = load_execution_code_closure_v1(project_root=root, receipt_path=execution_code_closure_path)
    inventory = stock._load_source_inventory(inputs)
    stock._preflight_reachable_runtime_contracts(inventory)
    inventory_identity = stock._inventory_identity(inventory)
    fixed = stock._fixed_project_pins(inventory)
    config = stock._load_yaml(fixed["experiments_config"].path, label="stock experiment configuration")
    engine = Path(container_engine_path)
    engine_socket = Path(container_engine_socket_path)
    engine_pin = stock._external_executable_pin(engine, label="original stock container engine")
    socket_pin = stock._socket_record(engine_socket, label="original stock engine socket")
    stock._require_socket_transport(socket_pin, expected_type="0001", label="original stock engine socket")
    images = stock._inspect_runtime_images(inventory, engine=engine, engine_socket=engine_socket,
                                          dependencies=stock.DEFAULT_DEPENDENCIES)
    refresh = preprocessing["receipt"]["model_parity_refresh_authority"]
    capabilities = {(branch, resource): expected_capability_from_binding_and_probe(
        binding=inventory.analytics_bindings[(branch, resource)],
        runtime_probe=inventory.runtime_probes[resource], resource=resource)
        for branch in BRANCHES for resource in ("cpu", "gpu")}
    cells = stock.qualification_pilot_cells_v2()
    if mode == DIAGNOSTIC_MODE:
        selected = [("diagnostic", cell) for cell in cells if cell.system == "gstreamer_custom"
                    and cell.resource == diagnostic_resource and cell.codec == "h264"]
        _require(len(selected) == 2, "stock diagnostic selection must contain the original native pair")
    else:
        selected = [("native_precheck", cell) for cell in cells if cell.system in {"openvino_gva", "gstreamer_custom"}
                    and cell.codec == "h264" and cell.topology_kind == "independent_processes"]
        selected += [("savant_original", cell) for cell in cells if cell.system == "savant"
                     and cell.resource == "cpu" and cell.codec == "h264" and cell.topology_kind == "independent_processes"]
        selected += [("qualification_cell", cell) for cell in cells]
        _require(len(selected) == 37, "stock qualification selection must contain exactly 37 originals")
    plans = {(system, codec): build_publication_pair_plans(config=config, datasets=inventory.datasets,
                system=system, codec=codec) for system, codec in {(cell.system, cell.codec) for _, cell in selected}}
    with PhysicalRootCustodyV1.open(root, label="stock operational prelaunch custody") as custody:
        custody.ensure_directory_owned(output, label="fresh original operation sources")
        source_dir = output / "original-operations"
        custody.ensure_directory_owned(source_dir, label="original operation documents")
        def pin(path):
            descriptor, _ = custody.read_descriptor(path, label="original operational stock source", maximum=16 * 1024 * 1024)
            descriptor["path"] = str(root / descriptor["path"])
            return descriptor
        closure_ref = _abs_descriptor(root, closure["receipt_descriptor"])
        common = {"capability_manifest": pin(inputs.candidate_manifest.path),
            "model_authority": _abs_descriptor(root, refresh["binding_set"]["index"]),
            "execution_code_closure": closure_ref}
        guardian = {**common, "execution_config": pin(inventory.analytics_execution_pin.path),
            "native_protocol_source": pin(root / "deploy/native_gst_probe/vast_native_gst_probe.cpp"),
            "proxy_protocol_source": pin(root / "scripts/checkpoint_deepstream_protocol_bridge.py")}
        rows, originals = [], {}
        for phase, cell in selected:
            identity = phase.replace("_", "-") + "-" + cell.arm_id.removeprefix("qualification-arm-v2-")
            _require(len(identity) <= 96, "original operation identity exceeds bound")
            plan = plans[(cell.system, cell.codec)]["shared" if cell.topology_kind == "shared_video_dag" else "baseline"]
            source_ref = _json_write(custody, source_dir / (identity + ".source-plan.json"), plan)
            native = cell.system in {"gstreamer_custom", "openvino_gva"}
            descriptors = {**common, "source_plan": source_ref, "calibration": pin(inputs.calibrations[cell.system].path),
                "policy_request_source": guardian["native_protocol_source"] if native else guardian["proxy_protocol_source"],
                "policy_coordinator_source": pin(root / "scripts/checkpoint_native_policy_runtime.py")}
            row = {"operation_id": identity, "phase": phase, "arm_id": cell.arm_id, "run_id": cell.run_id,
                "system": cell.system, "scenario": cell.scenario, "codec": cell.codec, "policy": cell.policy,
                "deadline_ms": cell.deadline_ms, "warmup_s": 30.0, "measurement_s": 180.0, "drain_timeout_s": 10.0,
                "streams": 6, "branches": 4, "descriptors": descriptors,
                "front_workers_by_route": front_workers_from_stock_plan_v1(plan, capabilities)}
            directory = (_pilot_path(pilots, cell) if phase == "qualification_cell" else output / "diagnostics" / identity / "evidence")
            process_dir = output / "process-captures" / identity
            reserved = {"measurement_dir": str(directory),
                "native_domain": str(Path(str(directory) + ".operational") / NATIVE_OPERATIONAL_JSONL),
                "process_receipt": str(process_dir / "original_engine_process_capture.v1.json"),
                "container_receipt": str(process_dir / "container-custody/original_container_custody.v1.json")}
            _require(all(not os.path.lexists(path) for path in reserved.values()), "original output reservation is occupied")
            original = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": "vast_original_native_operation_input_v1",
                "operation": copy.deepcopy(row), "container_image": images[cell.system]["contract"], "outputs": reserved})
            row["original_operation"] = _json_write(custody, source_dir / (identity + ".original.json"), original)
            rows.append(row)
            originals[identity] = original
        def original_validator(row, assets):
            for fixed_pin in fixed.values():
                stock._require_file_pin_unchanged(fixed_pin, label="original stock fixed source before plan sealing")
            for authority_pin in inputs.pins:
                stock._assert_pin_unchanged(authority_pin, label="original stock authority before plan sealing")
            document = json.loads(assets[row["original_operation"]["path"]])
            _require(document == originals[row["operation_id"]] and document["operation"] ==
                {key: value for key, value in row.items() if key != "original_operation"}, "original stock operation document drifted")
            original_plan = json.loads(assets[row["descriptors"]["source_plan"]["path"]])
            expected = plans[(row["system"], row["codec"])]["shared" if row["scenario"] == "checkpoint_video_dag_shared" else "baseline"]
            _require(original_plan == expected and row["front_workers_by_route"] ==
                front_workers_from_stock_plan_v1(expected, capabilities), "original stock source/worker equations drifted")
        result = build_operational_capture_plan_v1(project_root=root, output_dir=output / "capture-plan", mode=mode,
            operations=rows, guardian_descriptors=guardian, guardian_output_dir=guardian_output,
            original_operation_validator=original_validator)
        _require(stock._inventory_identity(stock._load_source_inventory(inputs)) == inventory_identity,
                 "original stock source inventory changed during capture planning")
        stock._require_file_pin_unchanged(engine_pin, label="original stock container engine")
        _require(stock._socket_record(engine_socket, label="original stock engine socket") == socket_pin,
                 "original stock engine socket changed during planning")
        for pin_value in fixed.values():
            stock._require_file_pin_unchanged(pin_value, label="original stock fixed source")
        for pin_value in inputs.pins:
            stock._assert_pin_unchanged(pin_value, label="original stock qualification authority")
        load_execution_code_closure_v1(project_root=root, receipt_path=execution_code_closure_path)
        custody.verify()
        return result


def held_operation_runtime_inputs_v1(*, root, runtime_inputs, runtime_key, system, cell_context, own_context):
    """Bind a held qualification original to its own planned native context.

The stock 32-bundle activates its qualification cell context. A precheck or
the Savant original reuses that exact bundle; only the pinned context file is
replaced, so its process capture proves its own distinct original operation.
"""
    from publication_operational_runtime_context_v1 import CAPTURE_KEY, CAPTURE_ROLE, OUTPUT_PATH_RULE
    result = copy.deepcopy(runtime_inputs)
    contract = result["dataset"][runtime_key]
    declared = contract["files"][CAPTURE_ROLE]
    _require(type(declared) is dict and _abs_descriptor(root, declared) == cell_context and
        contract.get(CAPTURE_KEY) == {"mode": QUALIFICATION_MODE, "output_dir": OUTPUT_PATH_RULE},
        "stock qualification bundle did not activate its exact cell capture context")
    _require(own_context != cell_context, "held original cannot reuse the qualification cell context")
    relative = _absolute(root, own_context["path"]).relative_to(root).as_posix()
    if system in {"deepstream", "savant"}:
        container = declared["container_path"]
    else:
        _require(declared["container_path"] == "/workspace/project/" + declared["path"],
                 "stock native context mount differs from its project path")
        container = "/workspace/project/" + relative
    contract["files"][CAPTURE_ROLE] = {**declared, "path": relative, "size_bytes": own_context["size_bytes"],
        "sha256": own_context["sha256"], "container_path": container}
    return result


@contextmanager
def held_stock_operational_request_v1(*, project_root, capture_plan_path, operation_id,
        runtime_bundle_path, candidate_index_path, preprocessing_contract_path, preprocessing_receipt_path,
        runtime_materialization_receipt_path, guardian_authority_path, transaction_receipt_path,
        bootstrap_mapping_path, bootstrap_receipt_path):
    """Select one original diagnostic using the stock 32-bundle authority spine.

The bounded adapter receives a real v3 request and the exact existing host
finalizer arguments. It gets no replacement transaction or publication grant.
"""
    import publication_policy_qualification_pilot_executor_v2 as pilot
    from publication_operational_capture_plan_v1 import held_operational_capture_plan_v1
    from publication_operational_runtime_context_v1 import CAPTURE_KEY, CAPTURE_ROLE, OUTPUT_PATH_RULE
    from publication_operational_request_reconciliation_v1 import _PinnedFile
    from publication_policy_qualification_execution_closure_v1 import _held_operational_object, _physical_file
    root = pilot._physical_root(project_root)
    _require(pilot._ACTIVE_PHYSICAL_CUSTODY.get() is None, "original diagnostic custody cannot overlap")
    with PhysicalRootCustodyV1.open(root, label="original stock diagnostic request custody") as custody:
        token = pilot._ACTIVE_PHYSICAL_CUSTODY.set(custody)
        try:
            with held_operational_capture_plan_v1(project_root=root, index_path=_absolute(root, capture_plan_path)) as plan:
                mode = plan["index"]["mode"]
                _require(mode in {DIAGNOSTIC_MODE, QUALIFICATION_MODE} and operation_id in plan["operations_by_id"],
                         "original bounded diagnostic mode/operation differs from plan")
                operation = plan["operations_by_id"][operation_id]
                _require(operation["system"] in HELD_OPERATIONS.get((mode, operation["phase"]), ())
                    and operation["codec"] == "h264" and operation["policy"] in {"cpu_only", "gpu_only"},
                    "original adapter requires the authorized forced native pair")
                original = _held_operational_object(custody, root, operation["original_operation"])
                _require(original["artifact_kind"] == "vast_original_native_operation_input_v1" and original["schema_version"] == 1
                    and original["operation"] == {key: value for key, value in operation.items() if key != "original_operation"},
                    "original diagnostic source differs from capture manifest")
                preprocessing = pilot._pin_json(root, preprocessing_receipt_path, label="original preprocessing receipt")
                candidate_ref = operation["descriptors"]["capability_manifest"]
                _require(candidate_ref == _abs_descriptor(root, preprocessing.value["candidate_manifest"]),
                         "original diagnostic candidate differs from preprocessing authority")
                bootstrap_dir = _absolute(root, bootstrap_mapping_path).parent
                inputs = pilot._load_qualification_inputs(project_root=root,
                    candidate_index_path=candidate_index_path, candidate_manifest_path=candidate_ref["path"],
                    candidate_receipt_path=preprocessing.value["candidate_receipt"]["path"],
                    bootstrap_mapping_path=bootstrap_mapping_path, bootstrap_receipt_path=bootstrap_receipt_path,
                    bootstrap_dir=bootstrap_dir, transaction_receipt_path=transaction_receipt_path)
                cells = pilot.qualification_pilot_cells_v2()
                cell = next(cell for cell in cells if cell.arm_id == operation["arm_id"])
                _require(all(getattr(cell, name) == operation[name] for name in
                    ("run_id", "system", "scenario", "codec", "policy", "deadline_ms")),
                    "original diagnostic differs from stock native coordinates")
                operational = pilot._load_operational_inputs(inputs=inputs, bootstrap_dir=bootstrap_dir, cells=cells,
                    runtime_input_materialization_receipt_path=runtime_materialization_receipt_path,
                    guardian_service_authority_path=guardian_authority_path,
                    preprocessing_contract_path=preprocessing_contract_path,
                    preprocessing_contract_receipt_path=preprocessing_receipt_path,
                    service_authority_validator=pilot._default_service_authority_validator,
                    preprocessing_contract_loader=pilot._default_preprocessing_contract_loader,
                    runtime_expectations_loader=pilot._default_runtime_expectations_loader)
                _require(_absolute(root, runtime_bundle_path) == operational.runtime_bundles[cell.arm_id].path,
                         "original diagnostic runtime bundle is detached from stock materialization")
                directory = _absolute(root, original["outputs"]["measurement_dir"])
                _require(not os.path.lexists(directory) and not os.path.lexists(Path(str(directory) + ".operational"))
                    and not os.path.lexists(Path(original["outputs"]["process_receipt"]).parent),
                    "original diagnostic output is occupied; a new invocation is forbidden")
                request = pilot._request_from_bootstrap_bundle(inputs=inputs, bootstrap_dir=bootstrap_dir,
                    cell=cell, output_dir=directory, evidence_names=pilot.CHILD_EVIDENCE_FILES,
                    bundle_pins=operational.runtime_bundles)
                contract = pilot._validate_request(request, inputs=inputs, cell=cell, output_dir=directory)
                context_ref = next(row["descriptor"] for row in plan["index"]["native_contexts"]
                                   if row["operation_id"] == operation_id)
                if mode == QUALIFICATION_MODE:
                    request = dataclasses.replace(request, runtime_inputs=held_operation_runtime_inputs_v1(
                        root=root, runtime_inputs=request.runtime_inputs,
                        runtime_key=pilot.RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system], system=cell.system,
                        cell_context=plan["qualification_contexts_by_arm"][cell.arm_id]["descriptor"],
                        own_context=context_ref))
                    contract = pilot._validate_request(request, inputs=inputs, cell=cell, output_dir=directory)
                declared = contract["files"].get(CAPTURE_ROLE)
                _require(type(declared) is dict and _abs_descriptor(root, declared) == context_ref and
                    contract.get(CAPTURE_KEY) == {"mode": mode, "output_dir": OUTPUT_PATH_RULE},
                    "stock original diagnostic bundle did not activate the exact capture context")
                _require(contract["container_image"] == original["container_image"],
                         "original diagnostic image differs from stock runtime")
                engine_descriptor = {field: contract["files"]["container_engine"][field]
                    for field in ("path", "size_bytes", "sha256")}
                engine_path = Path(engine_descriptor["path"])
                engine_descriptor["path"] = str(_physical_file(root,
                    engine_path if engine_path.is_absolute() else root / engine_path,
                    label="original stock diagnostic engine", external=True))
                closure = pilot._load_execution_code_closure(root=root,
                    receipt_path=operation["descriptors"]["execution_code_closure"]["path"])
                pins = (*inputs.pins, *operational.pins, *closure.pins)
                with closing(_PinnedFile(Path(engine_descriptor["path"]), engine_descriptor,
                        limit=256 * 1024 * 1024)) as engine_pin:
                    def barrier():
                        pilot._assert_execution_barrier(root=root, pins=pins, code_closure=closure)
                        engine_pin.check()
                        for descriptor in (operation["original_operation"], context_ref):
                            actual, _ = custody.read_descriptor(descriptor["path"],
                                label="original diagnostic context barrier", maximum=1024 * 1024)
                            _require(_abs_descriptor(root, actual) == descriptor, "original diagnostic context changed")
                        custody.verify()
                    barrier()
                    yield {"request": request, "cell": cell, "inputs": inputs, "operational": operational,
                        "operation": operation, "original": original,
                        "original_operation_descriptor": operation["original_operation"],
                        "native_context_descriptor": context_ref, "container_image": original["container_image"],
                        "engine_descriptor": engine_descriptor,
                        "finalizer_kwargs": pilot._qualification_finalizer_kwargs_v1(
                            inputs=inputs, operational=operational, cell=cell, output_dir=directory),
                        "execution_barrier": barrier}
                    barrier()
        finally:
            pilot._ACTIVE_PHYSICAL_CUSTODY.reset(token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project-root", "output-dir", "candidate-index-path", "candidate-manifest-path", "candidate-receipt-path",
        "bootstrap-mapping-path", "bootstrap-receipt-path", "bootstrap-dir", "transaction-receipt-path",
        "preprocessing-contract-path", "preprocessing-receipt-path", "execution-code-closure-path", "pilot-root", "guardian-output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--mode", choices=(QUALIFICATION_MODE, DIAGNOSTIC_MODE), required=True)
    parser.add_argument("--diagnostic-resource", choices=("cpu", "gpu"))
    args = vars(parser.parse_args(argv))
    try:
        result = prepare_stock_operational_capture_plan_v1(**args)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(78, "original operational planning failed: " + str(error) + "\n")
    print(json.dumps(result["descriptor"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
