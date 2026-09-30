#!/usr/bin/env python3
"""Prepare one selected native resource pair using current physical inputs.

This host materializer validates original model evidence without rebinding its
aggregate patch, then verifies the unchanged workers and the selected runtime.
It writes neither qualification inputs nor a publication/parity grant.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from statistics import median

from analytics_execution_bindings import build_worker_bindings
from analytics_execution_protocol import canonical_json_bytes, canonical_sha256
from checkpoint_gstreamer_runtime import build_publication_pair_plans
from publication_gstreamer_component_authority_v1 import (
    KIND, SCOPE, SYSTEM, BRANCHES, RESOURCES, ComponentPinsV1, _load, _require,
    held_component_authority_v1,
)
from publication_operational_request_domain_v1 import payload_with_sha256_v1
from publication_physical_io_v1 import PhysicalRootCustodyV1
import publication_policy_qualification_runtime_inputs_v2 as stock
import publication_qualification_image_refreeze_v1 as refreeze
import publication_image_build_v1 as image_build
from publication_policy_qualification_bootstrap_v2 import _accepted_calibration_material
from publication_policy_qualification_execution_code_closure_v1 import load_execution_code_closure_v1


@dataclass(frozen=True)
class SelectedComponentInventoryV1:
    """Actual selected material, deliberately not a QualificationInputs object."""
    root: Path
    dataset_pin: stock._FilePin
    parity_pin: stock._FilePin
    datasets: dict
    parity: dict
    capability: dict
    analytics_execution_pin: stock._FilePin
    analytics_bindings: dict
    analytics_binding_pins: dict
    runtime_probes: dict
    runtime_probe_pins: dict
    model_pins: tuple
    support_pins: tuple
    nvidia: dict
    preprocessing_sha256: str


@dataclass(frozen=True)
class ComponentInputDependenciesV1:
    model_validator: object = _accepted_calibration_material
    code_closure_loader: object = load_execution_code_closure_v1
    inspect_image: object = stock._default_inspect_image
    probe_openvino_device: object = stock._default_probe_openvino_device


DEFAULT_DEPENDENCIES = ComponentInputDependenciesV1()


def _ref(pin):
    return {"path": pin.relative, "size_bytes": pin.size, "sha256": pin.sha256}


def _pin(root, path):
    return stock._project_pin(root, path, label="selected component original input")


def _file(root, descriptor):
    return stock._descriptor_pin(root, descriptor, label="selected component original descriptor")


def _mount(pin):
    return stock._descriptor(pin, container_path=stock._project_container_path(pin.relative))


def _proxy_pins(root):
    manifest = _pin(root, stock.OPENVINO_MODEL_MANIFEST_PATH)
    value = stock._load_yaml(manifest.path, label="selected canonical proxy manifest")
    _require(value.get("schema_version") == 2 and value.get("artifact_kind") == "checkpoint_analytics_model_bindings"
             and set(value.get("branches", {})) == set(BRANCHES), "selected canonical proxy manifest drifted")
    pins = []
    for branch in BRANCHES:
        binding = value["branches"][branch]
        _require(binding.get("semantic_claim") == "topology_load_proxy_only" and binding.get("device") == "CPU",
                 "selected proxy semantics/device drifted")
        for role in ("model", "weights"):
            path = stock._normalized_manifest_model_path(binding[role + "_path"])
            pins.append(stock._project_pin(root, path, label="selected " + branch + " proxy " + role,
                                           expected_sha256=binding[role + "_sha256"]))
    _require(len(pins) == 8 and len({pin.relative for pin in pins}) == 8, "selected proxy closure is not exact eight")
    return manifest, tuple(pins)


def _calibration(candidate, candidate_descriptor, calibration, material):
    """Use the original physical service/transfer medians, selected eight only."""
    expected = {}
    for branch in BRANCHES:
        expected[branch] = {}
        for resource in RESOURCES:
            service = dict(material["services"][(branch, resource)])
            transfer = dict(material["transfers"][(branch, resource)])
            _require(len(service) >= 30 and set(service) == set(transfer), "selected calibration physical sample coverage drifted")
            expected[branch][resource] = {
                "implementation_id": candidate["systems"][SYSTEM]["branches"][branch][resource]["implementation_id"],
                "samples": len(service), "service_ms": float(median(service.values())),
                "transfer_ms": float(median(transfer.values())),
            }
    _require(calibration.get("costs") == expected
        and calibration.get("source_candidate_manifest_sha256") == candidate_descriptor["sha256"]
        and calibration.get("source_model_parity_acceptance_binding_sha256") == material["acceptance_binding_sha256"]
        and calibration.get("source_physical_response_evidence_sha256") == material["physical_response_evidence_sha256"],
        "selected calibration is not derived from exact original model responses")


def _current_workers(root, projection, receipt_path, inspections=None):
    receipt = image_build.load_publication_image_freeze_receipt(receipt_path)
    plan = image_build.publication_image_build_plan(project_root=root, registry_path=root / image_build.REGISTRY_RELATIVE_PATH)
    _require(receipt.get("group") == "analytics_worker" and receipt.get("registry_sha256") == plan["registry_sha256"],
             "selected original worker freeze registry drifted")
    names = {"cpu": "analytics_worker_openvino", "gpu": "analytics_worker_tensorrt"}
    rows = {row["name"]: row for row in receipt["images"]}
    current = {row["name"]: row for row in plan["images"]}
    for resource in RESOURCES:
        row, authority = rows[names[resource]], projection["workers"][resource]
        _require(row["image_id"] == authority["image_id"] and row["target_reference"] == authority["image"]
             and row["source_set_sha256"] == authority["source_set_sha256"]
             and receipt["receipt_sha256"] == authority["receipt_sha256"], "selected original worker freeze does not match model evidence")
        _require(all(row[key] == current[names[resource]][key] for key in
            ("source_set_sha256", "dependency_set_sha256", "build_context_sha256")), "current worker source closure changed; new model evidence is required")
        if inspections is not None:
            observed = inspections[resource]
            _require(observed.get("Id") == row["image_id"]
                and hashlib.sha256(image_build._canonical_json(image_build._inspect_projection(observed))).hexdigest()
                    == row["image_inspect_sha256"], "selected current worker image inspect differs from original freeze")
    return receipt


def _current_runtime(root, receipt_path, inspection=None):
    registry = refreeze.load_refreeze_registry(project_root=root, registry_path=root / refreeze.REGISTRY_RELATIVE_PATH)
    system = next(row for row in registry["systems"] if row["system"] == SYSTEM)
    receipt = refreeze.load_runtime_image_receipt(receipt_path)
    _require(receipt["system"] == SYSTEM and receipt["candidate_binding_eligible"] is True and receipt["blockers"] == []
        and receipt["refreeze_registry_sha256"] == registry["registry_sha256"]
        and receipt["build_registry_sha256"] == registry["build_registry_sha256"]
        and receipt["physical_identity"]["source_identity"] == refreeze._source_identity(root, system),
        "selected runtime receipt is not current source-bound material")
    physical = receipt["physical_identity"]
    image = {"image_id": physical["image_id"], "repository_digest": physical["canonical_repository_digest"],
             "inspect_projection_sha256": physical["inspect_projection_sha256"], "base_image_id": physical["base"]["image_id"]}
    if inspection is not None:
        _require(inspection.get("Id") == image["image_id"] and image["repository_digest"] in (inspection.get("RepoDigests") or [])
            and canonical_sha256(refreeze._image_projection(system, inspection)) == image["inspect_projection_sha256"]
            and inspection.get("Config", {}).get("Labels") is not None
            and all(inspection["Config"]["Labels"].get(key) == item for key, item in physical["labels"].items()),
            "selected live runtime differs from exact original current image receipt")
    return receipt, image, system


def _proof_inputs(root, material, runtime_system):
    # Original acceptance keeps its aggregate association. These physical input
    # descriptors extend custody; none are rebound to the component image.
    references = [*material["acceptance_binding"]["files"], *material["physical_response_evidence"],
                  material["accepted_manifest"], material["accepted_assessment"], material["accepted_receipt"],
                  material["transaction_index"]]
    binding_path = stock._load_json_pin(_file(root, material["accepted_receipt"]), label="original model receipt")["acceptance_binding_path"]
    references.append(_ref(_pin(root, binding_path)))
    paths = {str(row["path"]): {key: row[key] for key in ("path", "size_bytes", "sha256")} for row in references}
    for relative in (image_build.REGISTRY_RELATIVE_PATH, refreeze.REGISTRY_RELATIVE_PATH,
                     runtime_system["source_allowlist"], runtime_system["dependency_allowlist"]):
        pin = _pin(root, relative)
        paths[relative] = _ref(pin)
    groups = [runtime_system["source_allowlist"], runtime_system["dependency_allowlist"]]
    build_registry = image_build.load_publication_image_registry(project_root=root, registry_path=root / image_build.REGISTRY_RELATIVE_PATH)
    groups.extend(row[field] for row in build_registry["images"] if row["group"] == "analytics_worker"
                  for field in ("source_allowlist", "dependency_allowlist"))
    for allowlist in groups:
        paths[allowlist] = _ref(_pin(root, allowlist))
        for relative in image_build._read_allowlist(root, allowlist):
            paths[relative] = _ref(_pin(root, relative))
    return [paths[path] for path in sorted(paths)]


def _model_material(root, receipt_path, dependencies, *, engine, engine_socket):
    receipt = stock._load_json_pin(_pin(root, receipt_path), label="original accepted model receipt")
    from checkpoint_model_parity_acceptance_v4 import load_verified_model_parity_acceptance_v4
    def runner(command):
        _require(type(command) is list and len(command) == 6
            and command[:5] == ["docker", "image", "inspect", "--format", "{{json .}}"]
            and type(command[5]) is str and bool(command[5]), "selected model assessor may only inspect an original image")
        stock._require_file_pin_unchanged(engine, label="selected model image observer engine")
        _require(stock._socket_record(Path(engine_socket["path"]), label="selected model image observer socket") == engine_socket,
                 "selected model observer socket drifted")
        value = stock._run_json((str(engine.path), "--host=unix://" + engine_socket["path"], *command[1:]),
                               timeout=60.0, label="selected original model image inspect")
        stock._require_file_pin_unchanged(engine, label="selected model image observer engine after inspect")
        _require(stock._socket_record(Path(engine_socket["path"]), label="selected model observer socket after inspect") == engine_socket,
                 "selected model observer socket changed during inspect")
        _require(type(value) is dict, "selected formatted model image inspect must return one JSON object")
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    def acceptance_loader(**arguments):
        return load_verified_model_parity_acceptance_v4(command_runner=runner, **arguments)
    return dependencies.model_validator(root=root, accepted_manifest_path=receipt["accepted_manifest"]["path"],
        accepted_assessment_path=receipt["accepted_assessment"]["path"], accepted_receipt_path=receipt_path,
        acceptance_loader=acceptance_loader)


def _inventory(root, loaded):
    value, environment, projection = loaded["document"], loaded["environment"], loaded["worker_projection"]
    model_receipt = stock._load_json_pin(_file(root, value["model_authority"]), label="original selected model receipt")
    parity_pin = _file(root, model_receipt["accepted_manifest"])
    parity = stock._load_yaml(parity_pin.path, label="original accepted parity manifest")
    execution = _file(root, projection["execution_config"])
    binding_pins = {(branch, resource): _file(root, projection["binding_set"]["bindings"][branch + ":" + resource])
                    for branch in BRANCHES for resource in RESOURCES}
    probes = {resource: _file(root, projection["runtime_probes"][resource]) for resource in RESOURCES}
    dataset_pin = _file(root, environment["datasets_config"])
    datasets = stock._load_yaml(dataset_pin.path, label="selected original dataset config")["datasets"]
    model_pins = tuple(_file(root, descriptor) for descriptor in value["model_descriptors"])
    support = (_file(root, projection["binding_set"]["index"]), *binding_pins.values(), *probes.values())
    return SelectedComponentInventoryV1(root=root, dataset_pin=dataset_pin, parity_pin=parity_pin, datasets=datasets,
        parity=parity, capability=loaded["capability_manifest"], analytics_execution_pin=execution,
        analytics_bindings=loaded["bindings"], analytics_binding_pins=binding_pins,
        runtime_probes=loaded["runtime_probes"], runtime_probe_pins=probes, model_pins=model_pins,
        support_pins=support, nvidia=environment["nvidia"], preprocessing_sha256=canonical_sha256(loaded["preprocessing_contract"]))


def materialize_component_authority_v1(*, project_root, capability_manifest_path, calibration_path,
        model_parity_receipt_path, runtime_image_receipt_path, worker_freeze_receipt_path,
        execution_code_closure_path, resource, output_dir, container_engine=stock.DEFAULT_CONTAINER_ENGINE,
        container_engine_socket=stock.DEFAULT_CONTAINER_ENGINE_SOCKET, dependencies=DEFAULT_DEPENDENCIES):
    """Perform the actual selected preflight and commit the source document last."""
    _require(resource in RESOURCES, "component requires one explicit CPU/GPU pair")
    with PhysicalRootCustodyV1.open(project_root, label="selected component materialization") as custody:
        root = custody.root
        output = Path(output_dir)
        if not output.is_absolute():
            output = root / output
        _require(output.is_relative_to(root) and output != root and not os.path.lexists(output), "component output is occupied or outside project")
        candidate_pin, calibration_pin = _pin(root, capability_manifest_path), _pin(root, calibration_path)
        candidate = stock._load_json_pin(candidate_pin, label="historical complete capability declaration")
        calibration = stock._load_json_pin(calibration_pin, label="selected actual calibration")
        engine = stock._external_executable_pin(Path(container_engine), label="selected original engine")
        socket_pin = stock._socket_record(Path(container_engine_socket), label="selected original engine socket")
        material = _model_material(root, model_parity_receipt_path, dependencies, engine=engine, engine_socket=socket_pin)
        _calibration(candidate, _ref(candidate_pin), calibration, material)
        projection = {key: material["model_parity_refresh_authority"][key] for key in
                      ("execution_config", "binding_set", "workers", "runtime_probes")}
        runtime_receipt, image, system = _current_runtime(root, root / runtime_image_receipt_path)
        inspections = {resource: dependencies.inspect_image(engine.path, Path(container_engine_socket), projection["workers"][resource]["image_id"])
                       for resource in RESOURCES}
        _current_workers(root, projection, root / worker_freeze_receipt_path, inspections)
        runtime_inspection = dependencies.inspect_image(engine.path, Path(container_engine_socket), image["image_id"])
        _current_runtime(root, root / runtime_image_receipt_path, runtime_inspection)
        probe_value = dependencies.probe_openvino_device(engine.path, Path(container_engine_socket), root, image["image_id"], SYSTEM)
        _require(probe_value.get("schema_version") == 1 and probe_value.get("artifact_kind") == "vast_openvino_checkpoint_device_probe"
            and type(probe_value.get("openvino_version")) is str and bool(probe_value["openvino_version"])
            and any(row.get("device_id") == "CPU" for row in probe_value.get("available_devices", []))
            and all(probe_value.get("gstreamer_elements", {}).get(name, {}).get("available") is True
                    for name in stock.gstreamer_runtime.REQUIRED_GSTREAMER_ELEMENTS), "selected current native probe is incomplete")
        closure = dependencies.code_closure_loader(project_root=root, receipt_path=execution_code_closure_path)
        original_receipt_pin = _pin(root, model_parity_receipt_path)
        model_receipt = stock._load_json_pin(original_receipt_pin, label="original model receipt")
        parity_pin = _file(root, model_receipt["accepted_manifest"])
        parity = stock._load_yaml(parity_pin.path, label="original parity manifest")
        config = stock._load_yaml(root / stock.EXPERIMENTS_PATH, label="selected frozen experiments")
        datasets = stock._load_yaml(root / stock.DATASETS_PATH, label="selected frozen datasets")["datasets"]
        plans = build_publication_pair_plans(config=config, datasets=datasets, system=SYSTEM, codec="h264")
        cells = [cell.__dict__ for cell in stock.qualification_pilot_cells_v2()
                 if cell.system == SYSTEM and cell.resource == resource and cell.codec == "h264"]
        proxy_manifest, proxy_pins = _proxy_pins(root)
        models = stock._parity_model_inventory(root, parity)
        gpu = parity["toolchain_registry"]["tensorrt_cuda"]
        environment = {"nvidia": {"uuid": gpu["gpu_uuid"], "name": gpu["gpu_name"], "driver_version": gpu["driver_version"]},
            "probe": {"value": probe_value, "sha256": canonical_sha256(probe_value)},
            "engine": {"path": str(engine.path), "size_bytes": engine.size, "sha256": engine.sha256},
            "engine_socket": socket_pin, "worker_freeze_receipt": _ref(_pin(root, worker_freeze_receipt_path)),
            "runtime_inspection": runtime_inspection, "worker_inspections": inspections,
            "datasets_config": _ref(_pin(root, stock.DATASETS_PATH)), "experiments_config": _ref(_pin(root, stock.EXPERIMENTS_PATH)),
            "proxy_manifest": _ref(proxy_manifest), "proof_inputs": _proof_inputs(root, material, system)}
        # A distinct factual inventory is sufficient for the original dataset
        # helper; no synthetic qualification/candidate/transaction object.
        class DatasetInputs:
            pass
        dataset_inputs = DatasetInputs()
        dataset_inputs.root, dataset_inputs.datasets = root, datasets
        _, source_pins = stock._dataset_material(dataset_inputs, "h264")
        unsigned = {"schema_version": 1, "artifact_kind": KIND, "scope": SCOPE, "accepted": False,
            "publication_ready": False, "qualification_ready": False, "policy_contract_sha256": candidate["policy_contract_sha256"],
            "resource": resource, "capability_manifest": _ref(candidate_pin), "calibration": _ref(calibration_pin),
            "model_authority": _ref(original_receipt_pin), "worker_projection": projection,
            "image_authority": {"receipt": _ref(_pin(root, runtime_image_receipt_path)), "contract": image},
            "environment": environment, "planned_cells": cells, "source_descriptors": [_mount(pin) for pin in source_pins],
            "model_descriptors": [_mount(pin) for pin in models], "proxy_model_descriptors": [_mount(pin) for pin in proxy_pins],
            "execution_code_closure": closure["receipt_descriptor"]}
        custody.ensure_directory_owned(output, label="new selected component input namespace")
        unsigned["source_plans"] = {key: custody.write_exclusive(output / (key + ".source-plan.json"),
                canonical_json_bytes(plan) + b"\n", label="actual selected stock source plan") for key, plan in plans.items()}
        document = payload_with_sha256_v1(unsigned)
        destination = output / "gstreamer-component-authority.v1.json"
        payload = canonical_json_bytes(document) + b"\n"
        descriptor = {"path": destination.relative_to(root).as_posix(), "size_bytes": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()}
        # Validate the proposed document against held original inputs before
        # the sole final file exists. Failed source-plan prefixes remain facts.
        pins = ComponentPinsV1(custody)
        try:
            loaded = _load(pins, descriptor, document=document)
            _verify_host_material(root, loaded, dependencies)
            pins.verify()
            stock._require_file_pin_unchanged(engine, label="selected original engine after preflight")
            _require(stock._socket_record(Path(container_engine_socket), label="selected engine socket") == socket_pin, "selected engine socket changed")
            actual = custody.write_exclusive(destination, payload, label="component source authority last")
            _require(actual == descriptor, "committed component authority physical identity drifted")
            pins.verify()
        finally:
            pins.close()
        return {"authority_path": destination, "descriptor": descriptor, "document": document}


def _verify_host_material(root, loaded, dependencies):
    value, environment = loaded["document"], loaded["environment"]
    engine = stock._external_executable_pin(Path(environment["engine"]["path"]), label="selected model validation engine")
    socket_pin = stock._socket_record(Path(environment["engine_socket"]["path"]), label="selected model validation socket")
    _require({"path": str(engine.path), "size_bytes": engine.size, "sha256": engine.sha256} == environment["engine"]
         and socket_pin == environment["engine_socket"], "selected model validation engine/socket changed")
    material = _model_material(root, value["model_authority"]["path"], dependencies, engine=engine, engine_socket=socket_pin)
    _calibration(loaded["capability_manifest"], value["capability_manifest"], loaded["calibration"], material)
    _require(loaded["worker_projection"] == {key: material["model_parity_refresh_authority"][key]
        for key in ("execution_config", "binding_set", "workers", "runtime_probes")}, "selected worker/model provenance changed")
    _current_workers(root, loaded["worker_projection"], root / environment["worker_freeze_receipt"]["path"], environment["worker_inspections"])
    _current_runtime(root, root / value["image_authority"]["receipt"]["path"], environment["runtime_inspection"])
    closure = dependencies.code_closure_loader(project_root=root, receipt_path=value["execution_code_closure"]["path"])
    _require(closure["receipt_descriptor"] == value["execution_code_closure"], "selected execution closure drifted")
    current = build_worker_bindings(loaded["parity"], loaded["execution_config"], project_root=root,
                worker_project_root=loaded["binding_index"]["worker_project_root"])
    _require(all(current[branch][stock.ENGINE_BY_RESOURCE[resource]] == loaded["bindings"][(branch, resource)]
                 for branch in BRANCHES for resource in RESOURCES), "selected model bindings differ from original physical models")
    _require([_mount(pin) for pin in stock._parity_model_inventory(root, loaded["parity"])] == loaded["model_descriptors"],
             "selected mounted terminal models differ from original physical parity models")
    proxy_manifest, proxy_pins = _proxy_pins(root)
    _require(_ref(proxy_manifest) == environment["proxy_manifest"]
         and [_mount(pin) for pin in proxy_pins] == loaded["proxy_model_descriptors"],
         "selected mounted proxy models differ from canonical physical model manifest")
    inventory = _inventory(root, loaded)
    _, media_pins = stock._dataset_material(inventory, "h264")
    _require([_mount(pin) for pin in media_pins] == loaded["source_descriptors"],
             "selected mounted source media differ from original frozen dataset")


@contextmanager
def held_selected_component_inputs_v1(*, project_root, component_authority_path, expected_descriptor=None,
                                      dependencies=DEFAULT_DEPENDENCIES):
    with held_component_authority_v1(project_root=project_root, component_authority_path=component_authority_path,
                                    expected_descriptor=expected_descriptor) as loaded:
        root = loaded["root"]
        _verify_host_material(root, loaded, dependencies)
        inventory = _inventory(root, loaded)
        fixed = {role: _pin(root, relative) for role, relative in {
            "experiments_config": stock.EXPERIMENTS_PATH, "analytics_model_manifest": stock.OPENVINO_MODEL_MANIFEST_PATH,
            "device_probe": stock.DEVICE_PROBE_PATH}.items()}
        environment = loaded["environment"]
        engine = stock._external_executable_pin(Path(environment["engine"]["path"]), label="selected original held engine")
        _require({"path": str(engine.path), "size_bytes": engine.size, "sha256": engine.sha256} == environment["engine"], "selected held engine changed")
        socket_pin = stock._socket_record(Path(environment["engine_socket"]["path"]), label="selected held engine socket")
        _require(socket_pin == environment["engine_socket"], "selected held engine socket changed")
        original_barrier = loaded["verify_barrier"]
        def verify():
            original_barrier()
            stock._require_file_pin_unchanged(engine, label="selected original held engine")
            _require(stock._socket_record(Path(socket_pin["path"]), label="selected held engine socket") == socket_pin,
                     "selected held engine socket drifted")
        loaded.update(resource=loaded["document"]["resource"], inventory=inventory,
            candidate_pin=_file(root, loaded["capability_manifest_descriptor"]),
            calib_pin=_file(root, loaded["calibration_descriptor"]), fixed=fixed,
            engine_pin=engine, engine_socket=socket_pin, adapter_descriptor=None,
            capability_hashes=stock._analytics_capability_hashes(inventory), probe=environment["probe"],
            dataset=stock._dataset_material(inventory, "h264")[0],
            support_descriptors=stock._support_descriptors(inventory, system=SYSTEM), verify_barrier=verify)
        verify()
        yield loaded
        verify()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project-root", "capability-manifest-path", "calibration-path", "model-parity-receipt-path",
        "runtime-image-receipt-path", "worker-freeze-receipt-path", "execution-code-closure-path", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--resource", choices=RESOURCES, required=True)
    parser.add_argument("--container-engine", type=Path, default=stock.DEFAULT_CONTAINER_ENGINE)
    parser.add_argument("--container-engine-socket", type=Path, default=stock.DEFAULT_CONTAINER_ENGINE_SOCKET)
    arguments = vars(parser.parse_args(argv))
    try:
        result = materialize_component_authority_v1(**arguments)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(78, "selected component input preparation failed: " + str(error) + "\n")
    print(json.dumps(result["descriptor"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
