"""Physical selected GStreamer inputs, never a qualification/publication grant.

The complete capability declaration is retained verbatim. Only its selected
eight worker rows are joined to current component material. Host preparation
also verifies the original numeric model evidence and live image/probe facts;
this loader holds those exact documents for subsequent guardian construction.
It never imports the host qualification input factory.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from analytics_execution_endpoint import expected_capability_from_binding_and_probe
from analytics_execution_protocol import PROTOCOL_IDENTITY_SHA256, canonical_sha256
from analytics_execution_worker import validate_runtime_probe
from checkpoint_native_policy_runtime import _assess_external_worker_execution_manifest
from checkpoint_runtime_plan import validate_checkpoint_runtime_plan
from publication_policy_contract import policy_contract_identity, select_static_hybrid_map
from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_operational_request_domain_v1 import payload_with_sha256_v1, strict_json_object_v1
from publication_guardian_runtime_expectations_v1 import runtime_expectations_from_worker_projection_v1

KIND = "vast_gstreamer_component_authority_v1"
SCOPE = "selected_gstreamer_forced_resource_pair_only"
SYSTEM = "gstreamer_custom"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
ENGINES = {"cpu": "openvino_cpu", "gpu": "tensorrt_cuda"}
FIELDS = {"schema_version", "artifact_kind", "scope", "accepted", "publication_ready", "qualification_ready",
    "policy_contract_sha256", "resource", "capability_manifest", "calibration", "model_authority",
    "worker_projection", "image_authority", "environment", "planned_cells", "source_plans",
    "source_descriptors", "model_descriptors", "proxy_model_descriptors", "execution_code_closure", "sha256"}
MAX_METADATA = 16 * 1024 * 1024
MAX_BINARY = 4 * 1024 * 1024 * 1024
CELL_FIELDS = {"system", "resource", "codec", "topology_kind", "scenario", "policy", "deadline_ms",
               "duration_s", "run_id", "arm_id"}


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _descriptor(value):
    _require(type(value) is dict and set(value) == {"path", "size_bytes", "sha256"}, "component descriptor fields drifted")
    path = value["path"]
    _require(type(path) is str and path == PurePosixPath(path).as_posix() and not path.startswith("/")
             and "\\" not in path and all(part not in {"", ".", ".."} for part in path.split("/")),
             "component descriptor must remain project relative")
    _require(type(value["size_bytes"]) is int and 0 < value["size_bytes"] <= MAX_BINARY
             and type(value["sha256"]) is str and len(value["sha256"]) == 64
             and all(c in "0123456789abcdef" for c in value["sha256"]), "component descriptor values drifted")
    return value


def _epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class ComponentPinsV1:
    """Finite declared inputs; sibling outputs do not become input authority."""
    def __init__(self, custody):
        self.custody, self.root, self.files = custody, custody.root, {}

    def read(self, descriptor, *, capture=True):
        _descriptor(descriptor)
        name = descriptor["path"]
        path = self.root / name
        if name in self.files:
            previous = self.files[name]
            _require(previous[0] == descriptor, "one component path has conflicting identities")
            _require(_epoch(os.fstat(previous[1])) == previous[3] == _epoch(path.lstat()), "component reread physical input changed")
            if not capture:
                return None
            observed, raw = self.custody.read_descriptor(name, label="component reread", maximum=MAX_METADATA, capture=True)
            _require(observed == descriptor, "component reread bytes drifted")
            return raw
        maximum = MAX_METADATA if capture else MAX_BINARY
        _require(descriptor["size_bytes"] <= maximum, "component metadata exceeds bound")
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "component source is not an original regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            observed, raw, identity = self.custody.read_descriptor_identity(name, label="component original input",
                                                                          maximum=maximum, capture=capture)
            _require(observed == descriptor and identity == (before.st_dev, before.st_ino)
                     and _epoch(before) == _epoch(os.fstat(fd)) == _epoch(path.lstat()), "component physical source drifted")
            _require(all((row[3][0], row[3][1]) != identity for row in self.files.values()), "component source alias is prohibited")
            self.files[name] = (copy.deepcopy(descriptor), fd, maximum, _epoch(before))
            return raw
        except BaseException:
            os.close(fd)
            raise

    def object(self, descriptor):
        raw = self.read(descriptor)
        try:
            value = strict_json_object_v1(raw, max_bytes=MAX_METADATA)
        except ValueError:
            _require(not raw.lstrip().startswith(b"{") and not descriptor["path"].endswith(".json"),
                     "component JSON is invalid or has duplicate fields")
            import yaml
            value = yaml.safe_load(raw)
        _require(type(value) is dict, "component document must be one object")
        return value

    def verify(self):
        self.custody.verify()
        for name, (descriptor, fd, maximum, epoch) in self.files.items():
            _require(_epoch(os.fstat(fd)) == epoch == _epoch((self.root / name).lstat()), "held component input changed")
            observed, _ = self.custody.read_descriptor(name, label="held component input", maximum=maximum)
            _require(observed == descriptor, "held component input bytes changed")

    def witnesses(self):
        return [{"descriptor": copy.deepcopy(row[0]), "epoch": list(row[3])} for row in self.files.values()]

    def close(self):
        for row in self.files.values():
            os.close(row[1])


def _seal(value, field="sha256"):
    unsigned = {key: item for key, item in value.items() if key != field}
    _require(value.get(field) == canonical_sha256(unsigned), "component document semantic identity drifted")


def _mounts(pins, values):
    _require(type(values) is list and bool(values), "component physical asset set is empty")
    result = []
    for value in values:
        _require(type(value) is dict and set(value) == {"path", "size_bytes", "sha256", "container_path"},
                 "component mounted descriptor fields drifted")
        descriptor = {key: value[key] for key in ("path", "size_bytes", "sha256")}
        _require(value["container_path"] == "/workspace/project/" + value["path"], "component asset target drifted")
        pins.read(descriptor, capture=False)
        result.append(copy.deepcopy(value))
    _require(len({row["path"] for row in result}) == len(result), "component asset path is repeated")
    return result


def _worker_material(pins, projection, capability_manifest, preprocessing):
    _require(type(projection) is dict and set(projection) == {"execution_config", "binding_set", "workers", "runtime_probes"},
             "component worker projection fields drifted")
    runtime_expectations_from_worker_projection_v1(execution_config_authority=projection["execution_config"],
        binding_set_authority=projection["binding_set"], worker_authority=projection["workers"],
        policy_contract_sha256=policy_contract_identity()["sha256"],
        preprocessing_contract_content_sha256=canonical_sha256(preprocessing))
    execution = projection["execution_config"]
    config = pins.object({key: execution[key] for key in ("path", "size_bytes", "sha256")})
    # Deferred until imports are complete: this is the existing packaged
    # sidecar's exact config parser, without the host capability assessor.
    from checkpoint_gstreamer_analytics_sidecar import load_execution_config
    checked = load_execution_config(pins.root / execution["path"])
    _require(checked["identity"]["sha256"] == execution["content_identity_sha256"]
             and canonical_sha256(checked["workers"]) == execution["worker_projection_sha256"],
             "component execution config identity drifted")
    binding_set = projection["binding_set"]
    index = pins.object(binding_set["index"])
    _require(index.get("schema_version") == 1 and index.get("artifact_kind") == "vast_analytics_execution_worker_binding_set"
             and index.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256
             and index.get("execution_config_identity_sha256") == checked["identity"]["sha256"]
             and index.get("identity") == {"algorithm": "sha256", "sha256": canonical_sha256({k: v for k, v in index.items() if k != "identity"})}
             and index["identity"]["sha256"] == binding_set["identity_sha256"], "component binding index identity drifted")
    raw_rows = index.get("files")
    _require(type(raw_rows) is list and len(raw_rows) == 8, "component index must bind exact eight workers")
    records = {row.get("path"): row for row in raw_rows if type(row) is dict}
    expected = {branch + "." + ENGINES[resource] + ".json" for branch in BRANCHES for resource in RESOURCES}
    _require(set(records) == expected, "component binding file coordinate coverage drifted")
    probes = {}
    for resource in RESOURCES:
        authority = projection["runtime_probes"][resource]
        probe = pins.object({key: authority[key] for key in ("path", "size_bytes", "sha256")})
        probes[resource] = validate_runtime_probe(probe, engine=ENGINES[resource])
        _require(canonical_sha256(probe) == authority["content_identity_sha256"], "component probe content drifted")
        worker = projection["workers"][resource]
        _require(all(checked["workers"][resource][key] == worker[key] for key in ("image", "image_id", "worker_implementation_sha256"))
                 and probe["worker_implementation_sha256"] == worker["worker_implementation_sha256"],
                 "component worker config/probe identity drifted")
    capabilities, bindings, identities = {}, {}, {}
    for branch in BRANCHES:
        for resource in RESOURCES:
            descriptor = binding_set["bindings"][branch + ":" + resource]
            name = branch + "." + ENGINES[resource] + ".json"
            _require(descriptor == {"path": (PurePosixPath(binding_set["index"]["path"]).parent / name).as_posix(),
                     "size_bytes": records[name].get("bytes"), "sha256": records[name].get("sha256")},
                     "component original worker file differs from index")
            binding = pins.object(descriptor)
            capability = expected_capability_from_binding_and_probe(binding=binding, runtime_probe=probes[resource], resource=resource)
            _require(capability["worker_image_id"] == projection["workers"][resource]["image_id"], "component worker image mismatch")
            bindings[(branch, resource)], capabilities[(branch, resource)] = binding, capability
            identities[name] = canonical_sha256(binding)
    _require(canonical_sha256(identities) == binding_set["bindings_identity_sha256"] == index.get("bindings_identity_sha256"),
             "component binding content inventory drifted")
    manifest = {"schema_version": 1, "artifact_kind": "vast_checkpoint_external_analytics_execution_manifest_v1",
        "system": SYSTEM, "execution_config": {k: execution[k] for k in ("path", "size_bytes", "sha256")},
        "policy_capability_manifest_sha256": canonical_sha256(capability_manifest),
        "branches": {branch: {resource: capabilities[(branch, resource)] for resource in RESOURCES} for branch in BRANCHES}}
    assessment = _assess_external_worker_execution_manifest(manifest, system=SYSTEM, capability_manifest=capability_manifest,
                                                          preprocessing_contract_sha256=canonical_sha256(preprocessing))
    _require(assessment["passed"], "selected current workers differ from capability declaration: " + ";".join(assessment["blockers"]))
    return checked, bindings, probes, capabilities, manifest, index


def _source_identity(pins, environment, physical):
    """Recompute the selected recipe from pinned ordinary source descriptors."""
    records = environment.get("proof_inputs")
    _require(type(records) is list and 0 < len(records) <= 4096, "component original proof input coverage drifted")
    by_path = {}
    for descriptor in records:
        _require(descriptor["path"] not in by_path, "component proof path is repeated")
        pins.read(descriptor, capture=False)
        by_path[descriptor["path"]] = descriptor
    registry = pins.object(by_path["configs/publication_qualification_image_refreeze_v1.json"])
    rows = [row for row in registry.get("systems", []) if row.get("system") == SYSTEM]
    _require(len(rows) == 1, "component selected recipe is absent")
    recipe = rows[0]
    def paths(role):
        descriptor = by_path[recipe[role]]
        raw = pins.read(descriptor)
        _require(raw.endswith(b"\n") and b"\r" not in raw, "component source allowlist is not canonical LF")
        values = raw.decode("ascii").splitlines()
        _require(values and values == sorted(set(values)) and all(value in by_path for value in values),
                 "component recipe input coverage drifted")
        return values
    sources, dependencies = paths("source_allowlist"), paths("dependency_allowlist")
    def aggregate(values):
        return hashlib.sha256(b"".join((by_path[path]["sha256"] + "  " + path + "\n").encode("ascii")
                                      for path in sorted(values))).hexdigest()
    native = [path for path in sources if recipe["native_source_prefix"] is not None
              and path.startswith(recipe["native_source_prefix"])]
    allowlist = by_path[recipe["source_allowlist"]]
    expected = {"runtime_source_sha256": aggregate(sources), "runtime_source_count": len(sources),
        "dependency_set_sha256": aggregate(dependencies), "dependency_count": len(dependencies),
        "source_allowlist_sha256": allowlist["sha256"], "source_allowlist": {
            "path": allowlist["path"], "size": allowlist["size_bytes"], "sha256": allowlist["sha256"]},
        "native_source_sha256": aggregate(native) if native else None, "native_source_count": len(native)}
    _require(expected == physical["source_identity"], "component runtime receipt source is stale")


def _load(pins, descriptor, *, document=None):
    value = pins.object(descriptor) if document is None else document
    from analytics_execution_protocol import canonical_json_bytes
    if document is None:
        _require(pins.read(descriptor) == canonical_json_bytes(value) + b"\n", "component authority bytes are not canonical")
    _require(set(value) == FIELDS and value.get("schema_version") == 1 and value.get("artifact_kind") == KIND
             and value.get("scope") == SCOPE and value.get("resource") in RESOURCES
             and all(value.get(key) is False for key in ("accepted", "publication_ready", "qualification_ready")),
             "component authority scope/kind/flags drifted")
    _seal(value)
    _require(value["policy_contract_sha256"] == policy_contract_identity()["sha256"], "component policy contract drifted")
    candidate, calibration = pins.object(value["capability_manifest"]), pins.object(value["calibration"])
    select_static_hybrid_map(SYSTEM, calibration, candidate)
    receipt = pins.object(value["model_authority"])
    _seal(receipt, "receipt_sha256")
    _require(receipt.get("artifact_kind") == "vast_checkpoint_model_parity_acceptance_receipt_v4"
             and receipt.get("publication_ready") is True and receipt.get("blockers") == [], "original model evidence is not accepted v4")
    parity = pins.object(receipt["accepted_manifest"])
    projection = value["worker_projection"]
    _require(projection == {key: receipt["refresh_authority"][key] for key in
        ("execution_config", "binding_set", "workers", "runtime_probes")}, "component rebinds historical model worker evidence")
    preprocessing = parity.get("preprocessing_contract")
    _require(type(preprocessing) is dict, "original preprocessing contract is absent")
    config, bindings, probes, capabilities, external, binding_index = _worker_material(pins, projection, candidate, preprocessing)
    cells = value["planned_cells"]
    _require(type(cells) is list and len(cells) == 2, "component must contain exactly one original pair")
    for cell, topology, scenario in zip(cells, ("independent_processes", "shared_video_dag"),
            ("checkpoint_independent_processes_baseline", "checkpoint_video_dag_shared"), strict=True):
        _require(type(cell) is dict and set(cell) == CELL_FIELDS and cell["system"] == SYSTEM
            and cell["resource"] == value["resource"] and cell["codec"] == "h264" and cell["policy"] == value["resource"] + "_only"
            and type(cell["deadline_ms"]) in (int, float) and cell["deadline_ms"] == 100
            and type(cell["duration_s"]) is int and cell["duration_s"] == 180 and cell["topology_kind"] == topology
            and cell["scenario"] == scenario, "component original cell coordinates drifted")
        slug = SYSTEM + "-" + value["resource"] + "-h264-" + topology.replace("_", "-")
        _require(cell["run_id"] == "qualification-v2-" + slug and cell["arm_id"] == "qualification-arm-v2-" + slug,
                 "component cell is outside original constructors")
    plans = value["source_plans"]
    _require(type(plans) is dict and set(plans) == {"baseline", "shared"}, "component source plan coverage drifted")
    decoded = {key: pins.object(plans[key]) for key in ("baseline", "shared")}
    for plan, cell in zip(decoded.values(), cells, strict=True):
        validate_checkpoint_runtime_plan(plan)
        _require(plan["system"] == SYSTEM and plan["scenario"] == cell["scenario"] and len(plan["streams"]) == 6
                 and set(plan["required_branches"]) == set(BRANCHES), "component actual source plan differs from original cell")
    sources = _mounts(pins, value["source_descriptors"])
    models = _mounts(pins, value["model_descriptors"])
    proxies = _mounts(pins, value["proxy_model_descriptors"])
    _require(len(sources) == 2 and len(models) == 16 and len(proxies) == 8, "component source/model physical inventory cardinality drifted")
    image_authority = value["image_authority"]
    _require(type(image_authority) is dict and set(image_authority) == {"receipt", "contract"}, "component image authority fields drifted")
    image_receipt = pins.object(image_authority["receipt"])
    from publication_qualification_image_refreeze_v1 import load_runtime_image_receipt
    _require(load_runtime_image_receipt(pins.root / image_authority["receipt"]["path"]) == image_receipt,
             "component image receipt differs from exact original stock schema")
    _seal(image_receipt, "receipt_sha256")
    physical = image_receipt.get("physical_identity", {})
    image = image_authority["contract"]
    _require(image_receipt.get("system") == SYSTEM and image_receipt.get("candidate_binding_eligible") is True
         and image_receipt.get("blockers") == [] and type(image) is dict
         and set(image) == {"image_id", "repository_digest", "inspect_projection_sha256", "base_image_id"}
         and image == {"image_id": physical.get("image_id"), "repository_digest": physical.get("canonical_repository_digest"),
                      "inspect_projection_sha256": physical.get("inspect_projection_sha256"),
                      "base_image_id": physical.get("base", {}).get("image_id")}, "component selected image binding drifted")
    environment = value["environment"]
    _source_identity(pins, environment, physical)
    for key in ("datasets_config", "experiments_config", "proxy_manifest", "worker_freeze_receipt"):
        pins.read(environment[key], capture=False)
    from checkpoint_gstreamer_runtime import build_publication_pair_plans
    expected_plans = build_publication_pair_plans(config=pins.object(environment["experiments_config"]),
        datasets=pins.object(environment["datasets_config"])["datasets"], system=SYSTEM, codec="h264")
    _require(expected_plans == decoded, "component plan differs from actual frozen experiments/source registry")
    closure = pins.object(value["execution_code_closure"])
    _seal(closure, "receipt_sha256")
    _require(closure.get("kind") == "vast_publication_policy_qualification_execution_code_closure_v1"
        and closure.get("status") == "frozen" and type(closure.get("project_sources")) is list
        and 0 < len(closure["project_sources"]) <= 256, "component actual execution closure is absent")
    for row in closure["project_sources"]:
        pins.read({key: row[key] for key in ("path", "size_bytes", "sha256")}, capture=False)
    proof = {row["path"]: row for row in environment["proof_inputs"]}
    request_source = proof["deploy/native_gst_probe/vast_native_gst_probe.cpp"]
    coordinator_source = proof["scripts/checkpoint_native_policy_runtime.py"]
    return {"document": value, "descriptor": copy.deepcopy(descriptor), "capability_manifest": candidate,
        "capability_manifest_descriptor": value["capability_manifest"], "calibration": calibration,
        "calibration_descriptor": value["calibration"], "worker_projection": projection, "worker_capabilities": capabilities,
        "preprocessing_contract": preprocessing, "planned_cells": cells, "source_plans": decoded,
        "source_descriptors": sources, "model_descriptors": models, "proxy_model_descriptors": proxies,
        "image": image, "environment": value["environment"], "execution_config": config,
        "bindings": bindings, "runtime_probes": probes, "external_execution_manifest": external,
        "parity": parity, "binding_index": binding_index,
        "execution_code_closure_descriptor": value["execution_code_closure"],
        "policy_request_source_descriptor": request_source,
        "policy_coordinator_source_descriptor": coordinator_source}


def validate_component_original_native_row_v1(*, source, row, source_plan):
    """Join original native coordinates and all seven input roles to this source."""
    cells = [cell for cell in source["planned_cells"] if cell["arm_id"] == row.get("arm_id")]
    _require(len(cells) == 1 and row.get("phase") == "diagnostic", "component original row is outside its selected pair")
    cell = cells[0]
    _require(all(row.get(key) == cell[key] for key in
        ("arm_id", "run_id", "system", "scenario", "codec", "policy", "deadline_ms"))
        and all(row.get(key) == expected for key, expected in
        (("warmup_s", 30.0), ("measurement_s", 180.0), ("drain_timeout_s", 10.0), ("streams", 6), ("branches", 4))),
        "component original coordinates/windows drifted")
    key = "shared" if cell["topology_kind"] == "shared_video_dag" else "baseline"
    _require(source_plan == source["source_plans"][key], "component original source plan is foreign")
    descriptors = row.get("descriptors")
    _require(type(descriptors) is dict and set(descriptors) == {"capability_manifest", "source_plan", "model_authority",
        "calibration", "policy_request_source", "policy_coordinator_source", "execution_code_closure"},
        "component original native input roles drifted")
    root = source["root"]
    def absolute(descriptor):
        return {**descriptor, "path": str(Path(root) / descriptor["path"])}
    expected = {"capability_manifest": source["capability_manifest_descriptor"],
        "calibration": source["calibration_descriptor"], "model_authority": source["document"]["model_authority"],
        "execution_code_closure": source["execution_code_closure_descriptor"],
        "policy_request_source": source["policy_request_source_descriptor"],
        "policy_coordinator_source": source["policy_coordinator_source_descriptor"]}
    _require(all(descriptors[role] == absolute(descriptor) for role, descriptor in expected.items()),
             "component original native descriptor differs from selected source")
    source_ref = source["document"]["source_plans"][key]
    _require(all(descriptors["source_plan"][field] == source_ref[field] for field in ("size_bytes", "sha256")),
             "component original source-plan copy bytes differ from selected original")
    workers = {}
    for branch in BRANCHES:
        for resource in RESOURCES:
            rows = []
            for stream in source_plan["streams"]:
                if source_plan["topology_kind"] == "shared_video_dag":
                    identity = stream["graph_process"]["process_id"]
                else:
                    matches = [worker for worker in stream["workers"] if worker["branch_id"] == branch]
                    _require(len(matches) == 1, "component native source worker coordinate is ambiguous")
                    identity = matches[0]["process_id"]
                rows.append({"worker_id": identity, "stream_id": stream["stream_id"]})
            workers[branch + ":" + resource] = rows
    _require(row.get("front_workers_by_route") == workers, "component original front workers differ from actual source plan")
    return workers


@contextmanager
def held_component_authority_v1(*, project_root, component_authority_path, expected_descriptor=None):
    with PhysicalRootCustodyV1.open(project_root, label="selected GStreamer component authority") as custody:
        pins = ComponentPinsV1(custody)
        try:
            path = Path(component_authority_path)
            descriptor, _ = custody.read_descriptor(path, label="component source authority", maximum=MAX_METADATA)
            if expected_descriptor is not None:
                _require(descriptor == expected_descriptor, "component expected physical descriptor drifted")
            loaded = _load(pins, descriptor)
            loaded.update(source_pins=pins.witnesses(), verify_barrier=pins.verify, root=custody.root)
            pins.verify()
            yield loaded
            pins.verify()
        finally:
            pins.close()


def load_component_authority_v1(**kwargs):
    with held_component_authority_v1(**kwargs) as loaded:
        return {key: copy.deepcopy(value) for key, value in loaded.items() if key != "verify_barrier"}


__all__ = ["KIND", "SCOPE", "load_component_authority_v1", "held_component_authority_v1",
           "validate_component_original_native_row_v1"]
