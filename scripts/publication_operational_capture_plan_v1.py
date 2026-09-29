"""Freeze prelaunch constants for existing original runtime launchers.

The mandatory caller validator supplies stock operation/source/worker authority.
This module pins that material and creates no ingress, request, process, socket,
execution, qualification, or publication authority.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
from types import MappingProxyType

from publication_operational_request_domain_v1 import (
    NATIVE_COUNT_FIELDS_V1, NATIVE_DESCRIPTOR_ROLES_V1, NATIVE_DOMAIN_KIND_V1,
    POLICIES, canonical_json_v1, payload_with_sha256_v1, strict_json_object_v1,
    validate_descriptor_v1, validate_native_header_v1,
)
from publication_guardian_operational_recorder_v1 import BRANCHES, COUNTS, DEFAULT_BUDGETS, HEADER_KIND
from publication_physical_io_v1 import PhysicalRootCustodyV1, PublicationPhysicalIoV1Error

QUALIFICATION_MODE = "complete_qualification_operational_identity_v1"
DIAGNOSTIC_MODE = "bounded_native_diagnostic_operational_v1"
MODES = {QUALIFICATION_MODE, DIAGNOSTIC_MODE}
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
NATIVE_SYSTEMS = {"gstreamer_custom", "openvino_gva"}
BASELINE = "checkpoint_independent_processes_baseline"
SHARED = "checkpoint_video_dag_shared"
ROUTES = tuple(f"{branch}:{resource}" for branch in BRANCHES for resource in ("cpu", "gpu"))
GUARDIAN_INPUT_ROLES = {"capability_manifest", "execution_config", "execution_code_closure",
                       "model_authority", "native_protocol_source", "proxy_protocol_source"}
ROW_FIELDS = {"operation_id", "phase", "arm_id", "run_id", "system", "scenario", "codec", "policy",
    "deadline_ms", "warmup_s", "measurement_s", "drain_timeout_s", "streams", "branches",
    "original_operation", "descriptors", "front_workers_by_route"}
INDEX_KIND = "vast_operational_capture_plan_index_v1"
MANIFEST_KIND = "vast_original_operational_capture_manifest_v1"
INVENTORY_KIND = "vast_operational_source_plan_inventory_v1"
COMMON_FIELDS = {"schema_version", "artifact_kind", "mode", "accepted", "publication_ready", "sha256"}
INDEX_FIELDS = COMMON_FIELDS | {"operation_manifest", "source_plan_inventory", "guardian_context", "native_contexts"}
NATIVE_CONTEXT_FIELDS = {"schema_version", "artifact_kind", "mode", "native_header", "admission_limits", "sha256"}
GUARDIAN_CONTEXT_FIELDS = {"schema_version", "artifact_kind", "mode", "headers_by_route", "output_dir", "sha256"}
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
# Reviewed worker capability <=6136 bytes, escaped ASCII descriptor <=1189,
# actual uint64 owner fields and 32-byte lifecycle <=164, less four nulls.
# Actual recorder still validates the final ordinary JSON header before threads.
MAX_STARTUP_REPLACEMENT_BYTES = 7500


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _text(value, maximum, label):
    _require(type(value) is str and 0 < len(value) <= maximum and value.isascii()
        and all(0x21 <= ord(c) < 0x7f and c not in {'"', '\\'} for c in value),
        label + " is outside the frozen constructor domain")


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and str(path) == os.path.normpath(str(path)), "capture path must be canonical absolute")
    return path


def _epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _Pins:
    """Hold original regular-file handles and stock parent custody."""
    def __init__(self, custody):
        self.custody, self.files, self.total = custody, {}, 0

    def read(self, descriptor, maximum=MAX_ASSET_BYTES, *, capture=True):
        validate_descriptor_v1(descriptor)
        path = _path(descriptor["path"])
        _require(descriptor["size_bytes"] <= maximum, "capture asset exceeds byte bound")
        if str(path) in self.files:
            old = self.files[str(path)]
            _require(old[0] == descriptor, "one path has conflicting capture descriptors")
            _require(not capture or old[1] is not None, "released input payload cannot be reused as authority")
            return old[1] if capture else None
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "capture input is not one original regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            observed, raw = self.custody.read_descriptor(path, label="capture original input", maximum=maximum, capture=capture)
            observed["path"] = str(path)
            _require(observed == descriptor and _epoch(before) == _epoch(os.fstat(fd)) == _epoch(path.lstat()),
                     "capture input physical descriptor drifted")
            self.total += observed["size_bytes"]
            _require(self.total <= MAX_INPUT_BYTES, "capture input inventory exceeds aggregate byte bound")
            self.files[str(path)] = (copy.deepcopy(descriptor), raw, fd, _epoch(before))
            return raw
        except BaseException:
            os.close(fd)
            raise

    def verify(self):
        self.custody.verify()
        for name, (descriptor, raw, fd, epoch) in self.files.items():
            _require(_epoch(os.fstat(fd)) == epoch == _epoch(Path(name).lstat()), "held capture input changed")
            observed, _ = self.custody.read_descriptor(name, label="held capture input", maximum=MAX_ASSET_BYTES, capture=False)
            observed["path"] = name
            _require(observed == descriptor, "held capture input bytes changed")

    def release_payloads(self):
        """Decoded documents retain meaning; pinned source payloads retain no cache."""
        self.files = {name: (row[0], None, row[2], row[3]) for name, row in self.files.items()}

    def close(self):
        for row in self.files.values():
            os.close(row[2])


@contextmanager
def _custody(project_root):
    try:
        with PhysicalRootCustodyV1.open(project_root, label="operational capture plan root") as custody:
            pins = _Pins(custody)
            try:
                yield custody, pins
            finally:
                pins.close()
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise ValueError("operational capture plan custody failed: " + str(error)) from error


def _document(raw, fields, kind, mode):
    value = strict_json_object_v1(raw, max_bytes=MAX_DOCUMENT_BYTES)
    _require(set(value) == fields and canonical_json_v1(value) + b"\n" == raw,
             "capture document fields or canonical bytes drifted")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
        and value["artifact_kind"] == kind and value["mode"] == mode, "capture document version/kind/mode drifted")
    _require(payload_with_sha256_v1(value)["sha256"] == value["sha256"], "capture semantic seal drifted")
    if "accepted" in value:
        _require(value["accepted"] is False and value["publication_ready"] is False, "capture plan cannot authorize acceptance")
    return value


def _rows(mode, operations):
    _require(type(mode) is str and mode in MODES and type(operations) in {list, tuple}, "unsupported explicit capture mode")
    _require(len(operations) == (37 if mode == QUALIFICATION_MODE else 2), "capture mode original cardinality drifted")
    rows, ids = copy.deepcopy(list(operations)), set()
    for row in rows:
        _require(type(row) is dict and set(row) == ROW_FIELDS, "original operation fields drifted")
        for key, maximum in (("operation_id", 128), ("run_id", 64), ("arm_id", 68)):
            _text(row[key], maximum, key)
        _require(row["operation_id"] not in ids, "duplicate physical original operation ID")
        ids.add(row["operation_id"])
        _require(row["system"] in SYSTEMS and row["scenario"] in {BASELINE, SHARED}
            and row["codec"] in {"h264", "h265"} and row["policy"] in POLICIES, "original operation unsupported coordinates")
        for key, expected in (("deadline_ms", 100.0), ("warmup_s", 30.0), ("measurement_s", 180.0), ("drain_timeout_s", 10.0)):
            _require(type(row[key]) in {int, float} and row[key] == expected, "original operation window/deadline outside proof")
        _require(type(row["streams"]) is int and row["streams"] == 6 and type(row["branches"]) is int and row["branches"] == 4,
                 "original operation topology cardinality outside proof")
        validate_descriptor_v1(row["original_operation"])
        _require(type(row["descriptors"]) is dict and set(row["descriptors"]) == NATIVE_DESCRIPTOR_ROLES_V1,
                 "original operation native descriptor roles drifted")
        for descriptor in row["descriptors"].values():
            validate_descriptor_v1(descriptor)
        workers = row["front_workers_by_route"]
        _require(type(workers) is dict and set(workers) == set(ROUTES), "original front route set drifted")
        for route_rows in workers.values():
            _require(type(route_rows) is list and len(route_rows) == 6, "original front worker stream count drifted")
            streams = set()
            for worker in route_rows:
                _require(type(worker) is dict and set(worker) == {"worker_id", "stream_id"}, "original front worker fields drifted")
                _text(worker["worker_id"], 160, "original front worker ID")
                _require(type(worker["stream_id"]) is int and 0 <= worker["stream_id"] <= 5, "original front stream outside proof")
                streams.add(worker["stream_id"])
            _require(streams == set(range(6)), "original front worker streams are not exact")
    coord = lambda row: (row["system"], row["codec"], row["scenario"], row["policy"])
    if mode == DIAGNOSTIC_MODE:
        _require(all(row["phase"] == "diagnostic" and row["system"] in NATIVE_SYSTEMS for row in rows),
                 "diagnostic capture requires exactly two authorized native originals")
    else:
        cells = [row for row in rows if row["phase"] == "qualification_cell"]
        expected = {(system, codec, scenario, resource + "_only") for system in SYSTEMS for codec in ("h264", "h265")
                    for scenario in (BASELINE, SHARED) for resource in ("cpu", "gpu")}
        _require(len(cells) == 32 and {coord(row) for row in cells} == expected, "qualification capture requires exact 32 stock cells")
        prechecks = [row for row in rows if row["phase"] == "native_precheck"]
        _require(len(prechecks) == 4 and {coord(row) for row in prechecks} ==
            {(system, "h264", BASELINE, resource + "_only") for system in NATIVE_SYSTEMS for resource in ("cpu", "gpu")},
            "qualification capture requires exact four native prechecks")
        originals = [row for row in rows if row["phase"] == "savant_original"]
        _require(len(originals) == 1 and coord(originals[0]) == ("savant", "h264", BASELINE, "cpu_only"),
                 "qualification capture requires one original Savant invocation")
        for row in rows:
            topology = "independent-processes" if row["scenario"] == BASELINE else "shared-video-dag"
            slug = f"{row['system']}-{row['policy'].removesuffix('_only')}-{row['codec']}-{topology}"
            _require(row["run_id"] == "qualification-v2-" + slug and row["arm_id"] == "qualification-arm-v2-" + slug,
                     "qualification original IDs differ from stock constructors")
        _require(sum(row["system"] in NATIVE_SYSTEMS for row in rows) == 20, "qualification native/SDK proof domain drifted")
    selected = [row["arm_id"] for row in rows if row["phase"] in {"diagnostic", "qualification_cell"}]
    _require(len(set(selected)) == len(selected), "duplicate runtime-selected original arm ID")
    return rows


def _native_context(row, mode):
    arm = (f"{row['run_id']}:{row['scenario']}:{row['codec']}:{row['policy']}:{float(row['deadline_ms'])}"
           if row["system"] in NATIVE_SYSTEMS else row["arm_id"])
    header = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": NATIVE_DOMAIN_KIND_V1,
        "record_kind": "header", "digest_algorithm": "sha256", "operation_input": row["original_operation"],
        "run_id": row["run_id"], "context_arm_id": row["arm_id"], "system": row["system"],
        "scenario": row["scenario"], "codec": row["codec"], "policy": row["policy"], "deadline_ms": row["deadline_ms"],
        "protocol": {"schema_version": 1, "decision_request": "decision_request", "path": "path_enter", "terminal": "terminal",
                     "source_descriptor": "policy_request_source"}, "descriptors": row["descriptors"],
        "initial_state": {"arm_id": arm, "weights": {"cpu": 1.0, "gpu": 1.0}, "service_ewma_ms": {}},
        "counts": dict.fromkeys(NATIVE_COUNT_FIELDS_V1, 0), "adaptive_history": None})
    validate_native_header_v1(header)
    return payload_with_sha256_v1({"schema_version": 1, "artifact_kind": "vast_native_operational_capture_context_v1",
        "mode": mode, "native_header": header, "admission_limits": {"max_admissions_per_stream":
        241 if row["system"] in NATIVE_SYSTEMS else 281, "min_schedule_step_ns": 999_999_600}})


def _guardian_context(rows, mode, descriptors, manifest_descriptor, inventory_descriptor, output_dir):
    headers = {}
    for route in ROUTES:
        protocols, contexts, workers, bindings = [], [], [], []
        protocol_ids, context_ids, worker_ids, binding_ids = {}, {}, {}, set()
        for row in rows:
            message = "analytics_execute" if row["system"] in NATIVE_SYSTEMS else "infer_request"
            if message not in protocol_ids:
                protocol_ids[message] = len(protocols)
                protocols.append({"id": len(protocols), "schema_version": 1, "message_type": message,
                    "transport": "unix_seqpacket_scm_rights_sealed_memfd", "source_descriptor":
                    "native_protocol_source" if message == "analytics_execute" else "proxy_protocol_source"})
            arm = hashlib.sha256(("analytics_execution_arm_v1\n" + row["run_id"] + "\n" + row["policy"] + "\n" +
                f"{row['deadline_ms']:.6f}").encode("ascii")).hexdigest() if message == "analytics_execute" else row["arm_id"]
            constant = (protocol_ids[message], row["run_id"], arm, row["system"], row["policy"])
            if constant not in context_ids:
                context_ids[constant] = len(contexts)
                contexts.append(dict(zip(("id", "protocol", "run_id", "arm_id", "system", "policy"), (len(contexts), *constant))))
            for worker in row["front_workers_by_route"][route]:
                key = (worker["worker_id"], worker["stream_id"])
                if key not in worker_ids:
                    worker_ids[key] = len(workers)
                    workers.append({"id": len(workers), **worker})
                pair = (context_ids[constant], worker_ids[key])
                if pair not in binding_ids:
                    binding_ids.add(pair)
                    bindings.append({"id": len(bindings), "context": pair[0], "front_worker": pair[1]})
        _require(len(protocols) <= 2 and len(contexts) <= 37 and len(workers) <= 24 and len(bindings) <= 222,
                 "guardian constant tables exceed frozen proof")
        branch, resource = route.split(":")
        headers[route] = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": HEADER_KIND,
            "record_kind": "header", "digest_algorithm": "sha256", "descriptors": {**descriptors,
                "accounting_input": manifest_descriptor, "source_plan": inventory_descriptor, "service_authority": None},
            "lifecycle_id": None, "owner": None, "route": {"branch": branch, "resource": resource},
            "protocols": protocols, "contexts": contexts, "front_workers": workers, "bindings": bindings,
            "worker_capability": None, "initial_counters": dict.fromkeys(COUNTS, 0), "budgets": dict(DEFAULT_BUDGETS)})
        _require(len(canonical_json_v1(headers[route])) + 1 + MAX_STARTUP_REPLACEMENT_BYTES <= 65536,
                 "guardian template lacks reviewed actual-startup header capacity")
    return payload_with_sha256_v1({"schema_version": 1, "artifact_kind": "vast_guardian_operational_capture_context_v1",
        "mode": mode, "headers_by_route": headers, "output_dir": str(output_dir)})


def _write(custody, path, value):
    raw = canonical_json_v1(value) + b"\n"
    _require(len(raw) <= MAX_DOCUMENT_BYTES, "capture plan document exceeds byte bound")
    descriptor = custody.write_exclusive(path, raw, label="immutable operational capture document", mode=0o444)
    descriptor["path"] = str(path)
    validate_descriptor_v1(descriptor)
    return descriptor


def build_operational_capture_plan_v1(*, project_root, output_dir, mode, operations,
        guardian_descriptors, guardian_output_dir, original_operation_validator):
    """Return {value: sealed nonauthorizing index, descriptor: physical index pin}."""
    rows = _rows(mode, operations)
    _require(callable(original_operation_validator), "original operation authority validator is mandatory")
    _require(type(guardian_descriptors) is dict and set(guardian_descriptors) == GUARDIAN_INPUT_ROLES,
             "guardian input descriptor roles drifted")
    guardian_descriptors = copy.deepcopy(guardian_descriptors)
    output_dir, guardian_output_dir = _path(output_dir), _path(guardian_output_dir)
    _require(not os.path.lexists(output_dir) and not os.path.lexists(guardian_output_dir), "capture destination already exists")
    with _custody(project_root) as (custody, pins):
        custody.stat_directory_identity(guardian_output_dir.parent, label="future guardian output parent")
        _require(not guardian_output_dir.is_relative_to(output_dir) and not output_dir.is_relative_to(guardian_output_dir),
                 "guardian and immutable plan output domains overlap")
        for descriptor in guardian_descriptors.values():
            pins.read(descriptor)
        for row in rows:
            for descriptor in [row["original_operation"], *row["descriptors"].values()]:
                pins.read(descriptor)
        token = custody.capture_read_namespace(tuple(pins.files), label="original capture input namespace")
        assets = MappingProxyType({name: value[1] for name, value in pins.files.items()})
        for row in rows:
            frozen = copy.deepcopy(row)
            result = original_operation_validator(frozen, assets)
            _require(result is None, "original operation validator must raise on refusal and return None on success")
            _require(frozen == row, "original operation validator mutated its frozen input")
        pins.verify()
        custody.verify_read_namespace(token, label="validated original capture inputs")
        _require(not any(Path(name).is_relative_to(output_dir) for name in pins.files), "capture output overlaps original inputs")
        custody.ensure_directory(output_dir, label="separate immutable capture plan")
        # Own directory creation can update a shared ancestor. Held original
        # leaf epochs remain exact; pin parent epochs after our own creation.
        pins.verify()
        token = custody.capture_read_namespace(tuple(pins.files), label="capture input write boundary")
        manifest = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": MANIFEST_KIND, "mode": mode,
            "accepted": False, "publication_ready": False, "operations": rows})
        manifest_descriptor = _write(custody, output_dir / "original_operations.v1.json", manifest)
        inventory = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": INVENTORY_KIND, "mode": mode,
            "accepted": False, "publication_ready": False, "source_plans": [
                {"operation_id": row["operation_id"], "descriptor": row["descriptors"]["source_plan"]} for row in rows]})
        inventory_descriptor = _write(custody, output_dir / "source_plan_inventory.v1.json", inventory)
        native = []
        for ordinal, row in enumerate(rows):
            descriptor = _write(custody, output_dir / f"native_context_{ordinal:02d}.v1.json", _native_context(row, mode))
            native.append({"operation_id": row["operation_id"], "phase": row["phase"], "arm_id": row["arm_id"], "descriptor": descriptor})
        guardian = _guardian_context(rows, mode, guardian_descriptors, manifest_descriptor, inventory_descriptor, guardian_output_dir)
        guardian_descriptor = _write(custody, output_dir / "guardian_capture_context.v1.json", guardian)
        index = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": INDEX_KIND, "mode": mode,
            "accepted": False, "publication_ready": False, "operation_manifest": manifest_descriptor,
            "source_plan_inventory": inventory_descriptor, "guardian_context": guardian_descriptor, "native_contexts": native})
        index_descriptor = _write(custody, output_dir / "capture_plan_index.v1.json", index)
        pins.verify()
        custody.verify_read_namespace(token, label="capture original inputs after write")
    return {"value": index, "descriptor": index_descriptor}


@contextmanager
def held_operational_capture_plan_v1(*, project_root, index_path, expected_descriptor=None):
    """Hold separately pinned contexts and original files throughout caller use."""
    index_path = _path(index_path)
    with _custody(project_root) as (custody, pins):
        if expected_descriptor is None:
            expected_descriptor, _ = custody.read_descriptor(index_path, label="capture index", maximum=MAX_DOCUMENT_BYTES)
            expected_descriptor["path"] = str(index_path)
        _require(expected_descriptor["path"] == str(index_path), "capture index descriptor path differs")
        raw = pins.read(expected_descriptor, MAX_DOCUMENT_BYTES)
        mode = strict_json_object_v1(raw, max_bytes=MAX_DOCUMENT_BYTES).get("mode")
        _require(type(mode) is str and mode in MODES, "unsupported capture index mode")
        index = _document(raw, INDEX_FIELDS, INDEX_KIND, mode)
        manifest = _document(pins.read(index["operation_manifest"], MAX_DOCUMENT_BYTES), COMMON_FIELDS | {"operations"}, MANIFEST_KIND, mode)
        rows = _rows(mode, manifest["operations"])
        inventory = _document(pins.read(index["source_plan_inventory"], MAX_DOCUMENT_BYTES), COMMON_FIELDS | {"source_plans"}, INVENTORY_KIND, mode)
        _require(inventory["source_plans"] == [{"operation_id": row["operation_id"], "descriptor": row["descriptors"]["source_plan"]} for row in rows],
                 "capture source-plan inventory differs from originals")
        for row in rows:
            for descriptor in [row["original_operation"], *row["descriptors"].values()]:
                pins.read(descriptor, capture=False)
        guardian = _document(pins.read(index["guardian_context"], MAX_DOCUMENT_BYTES), GUARDIAN_CONTEXT_FIELDS,
                             "vast_guardian_operational_capture_context_v1", mode)
        _require(type(guardian["headers_by_route"]) is dict and set(guardian["headers_by_route"]) == set(ROUTES), "capture guardian route set drifted")
        first = guardian["headers_by_route"][ROUTES[0]]
        _require(type(first) is dict and type(first.get("descriptors")) is dict, "capture guardian template missing")
        guardian_descriptors = {role: first["descriptors"][role] for role in GUARDIAN_INPUT_ROLES}
        for descriptor in guardian_descriptors.values():
            pins.read(descriptor, capture=False)
        _require(guardian == _guardian_context(rows, mode, guardian_descriptors, index["operation_manifest"],
            index["source_plan_inventory"], _path(guardian["output_dir"])), "guardian constant bindings differ from original plan")
        _require(type(index["native_contexts"]) is list and len(index["native_contexts"]) == len(rows), "capture native context cardinality drifted")
        native_by_id, selected, qualified = {}, {}, {}
        for row, ref in zip(rows, index["native_contexts"]):
            _require(type(ref) is dict and set(ref) == {"operation_id", "phase", "arm_id", "descriptor"}
                and all(ref[key] == row[key] for key in ("operation_id", "phase", "arm_id")), "capture native index original binding drifted")
            context = _document(pins.read(ref["descriptor"], 65536), NATIVE_CONTEXT_FIELDS,
                                "vast_native_operational_capture_context_v1", mode)
            _require(context == _native_context(row, mode), "capture native context differs from original operation")
            native_by_id[row["operation_id"]] = context
            if row["phase"] in {"qualification_cell", "diagnostic"}:
                selected[row["arm_id"]] = {"operation": row, "descriptor": ref["descriptor"], "context": context}
                if row["phase"] == "qualification_cell":
                    qualified[row["arm_id"]] = selected[row["arm_id"]]
        pins.verify()
        pins.release_payloads()
        try:
            yield {"index": index, "operation_manifest": manifest, "source_plan_inventory": inventory,
                "guardian_context": guardian, "operations_by_id": {row["operation_id"]: row for row in rows},
                "native_contexts_by_id": native_by_id, "runtime_contexts_by_arm": selected,
                "qualification_contexts_by_arm": qualified}
        finally:
            # The authority is a fixed, explicitly enumerated input set.
            # Materializing an unrelated output sibling can legitimately alter
            # ancestor mtime. Keep original handles/leaf epochs/bytes and stock
            # physical ancestor identity checks, not whole-parent exclusivity.
            pins.verify()
