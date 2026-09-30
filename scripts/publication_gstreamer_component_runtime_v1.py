#!/usr/bin/env python3
"""Execute and cold-check selected native arms without a campaign grant."""
from __future__ import annotations

import copy
import csv
import io
import json
import math
import os
from pathlib import Path
import time
from contextlib import contextmanager
from functools import partial

from checkpoint_gstreamer_publication_runtime_v3 import run_checkpoint_gstreamer_publication_runtime_v3
from checkpoint_publication_launcher_adapter_v3 import NativePublicationOutcomeV3, NativePublicationRequestV3
from checkpoint_publication_runtime import prepare_checkpoint_publication_acceptance
from collect_metrics import HardwareResourceCollector
from publication_benchmark_native_diagnostic_v1 import _stop_collector
from publication_operational_capture_plan_v1 import DIAGNOSTIC_MODE, build_operational_capture_plan_v1, held_operational_capture_plan_v1
from publication_operational_container_custody_v1 import original_container_validator_v1
from publication_operational_process_custody_v1 import capture_original_engine_processes_v1, original_process_validator_v1
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1, strict_json_object_v1
from publication_operational_stock_operations_v1 import front_workers_from_stock_plan_v1
from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_policy_qualification_execution_closure_v1 import (
    _held_operational_cold_custody_v1, _held_operational_object,
    _operational_absolute_descriptor, _operational_measured_ingress_v1,
    reconcile_guardian_operational_workload_v1,
)
from publication_policy_qualification_execution_code_closure_v1 import load_execution_code_closure_v1
from publication_policy_qualification_pilot_executor_v2 import CHILD_EVIDENCE_FILES, qualification_pilot_cells_v2

ARM_KIND = "vast_gstreamer_component_arm_result_v1"
BUNDLE_KIND = "vast_gstreamer_component_runtime_bundle_v1"
PAIR_KIND = "vast_gstreamer_component_pair_result_v1"
MAX_DOCUMENT_BYTES = 1024 * 1024
RESULT_FILENAME = "component_arm_result.v1.json"


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def selected_cells_v1(resource):
    _require(resource in {"cpu", "gpu"}, "component resource must be cpu or gpu")
    cells = tuple(cell for cell in qualification_pilot_cells_v2()
                  if cell.system == "gstreamer_custom" and cell.codec == "h264" and cell.resource == resource)
    _require(len(cells) == 2 and {cell.topology_kind for cell in cells} ==
             {"independent_processes", "shared_video_dag"}, "original selected pair coordinates drifted")
    return cells


def _authority(root, path):
    from publication_gstreamer_component_authority_v1 import load_component_authority_v1
    return load_component_authority_v1(project_root=root, component_authority_path=path)


def _absolute(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    _require(path.is_relative_to(root) and path != root and str(path) == os.path.normpath(str(path)),
             "component path escaped physical project root")
    return path


def _descriptor(custody, root, path, maximum=MAX_DOCUMENT_BYTES):
    value, _ = custody.read_descriptor(path, label="component physical input/output", maximum=maximum)
    value["path"] = str(root / value["path"])
    return value


def _reference(root, value):
    return _operational_absolute_descriptor(root, {k: value[k] for k in ("path", "size_bytes", "sha256")})


def _write(custody, path, value):
    raw = canonical_json_v1(value) + b"\n"
    _require(len(raw) <= MAX_DOCUMENT_BYTES, "component document exceeds byte bound")
    descriptor = custody.write_exclusive(path, raw, label="component immutable document", mode=0o444)
    descriptor["path"] = str(path)
    return descriptor


def _component_flags():
    return {"qualification_eligible": False, "q4_eligible": False, "publication_ready": False,
            "full_run_eligible": False, "qualification_cells": 0, "q4_runs": 0, "full_arms": 0}


def prepare_component_capture_plan_v1(*, project_root, component_authority_path,
        execution_code_closure_path, output_dir, guardian_output_dir):
    """Reserve the two original operations; this does not start a guardian."""
    root = Path(project_root)
    loaded = _authority(root, component_authority_path)
    closure = load_execution_code_closure_v1(project_root=root, receipt_path=execution_code_closure_path)
    output, guardian_output = _absolute(root, output_dir), _absolute(root, guardian_output_dir)
    _require(not os.path.lexists(output) and not os.path.lexists(guardian_output), "component output is occupied")
    resource = loaded["document"]["resource"]
    cells = selected_cells_v1(resource)
    coordinates = ("arm_id", "run_id", "system", "scenario", "codec", "policy", "deadline_ms")
    _require([{k: getattr(cell, k) for k in coordinates} for cell in cells] ==
             [{k: cell[k] for k in coordinates} for cell in loaded["planned_cells"]],
             "component authority changed the original pair")
    capabilities = loaded["worker_capabilities"]
    plans = loaded["source_plans"]
    with PhysicalRootCustodyV1.open(root, label="component capture preparation") as custody:
        custody.ensure_directory_owned(output, label="fresh component source documents")
        sources = output / "original-operations"
        custody.ensure_directory_owned(sources, label="original component operations")
        common = {"capability_manifest": _reference(root, loaded["capability_manifest_descriptor"]),
                  "model_authority": _reference(root, loaded["document"]["model_authority"]),
                  "execution_code_closure": _descriptor(custody, root, execution_code_closure_path)}
        _require(common["execution_code_closure"] == _reference(root, loaded["execution_code_closure_descriptor"]),
                 "component capture changed its selected host closure")
        guardian = {**common,
            "execution_config": _reference(root, loaded["worker_projection"]["execution_config"]),
            "native_protocol_source": _descriptor(custody, root, root / "deploy/native_gst_probe/vast_native_gst_probe.cpp", 16 * 1024 * 1024),
            "proxy_protocol_source": _descriptor(custody, root, root / "scripts/checkpoint_deepstream_protocol_bridge.py", 16 * 1024 * 1024)}
        rows, originals = [], {}
        for cell in cells:
            identity = "component-" + cell.arm_id.removeprefix("qualification-arm-v2-")
            plan = plans["shared" if cell.topology_kind == "shared_video_dag" else "baseline"]
            plan_ref = _write(custody, sources / (identity + ".source-plan.json"), plan)
            descriptors = {**common, "source_plan": plan_ref,
                "calibration": _reference(root, loaded["calibration_descriptor"]),
                "policy_request_source": guardian["native_protocol_source"],
                "policy_coordinator_source": _descriptor(custody, root, root / "scripts/checkpoint_native_policy_runtime.py", 16 * 1024 * 1024)}
            row = {"operation_id": identity, "phase": "diagnostic", **{k: getattr(cell, k) for k in coordinates},
                "warmup_s": 30.0, "measurement_s": 180.0, "drain_timeout_s": 10.0,
                "streams": 6, "branches": 4, "descriptors": descriptors,
                "front_workers_by_route": front_workers_from_stock_plan_v1(plan, capabilities)}
            directory = output / "arms" / identity / "evidence"
            process_dir = output / "process-captures" / identity
            outputs = {"measurement_dir": str(directory), "native_domain": str(directory) + ".operational/native_operational_requests.v1.jsonl",
                "process_receipt": str(process_dir / "original_engine_process_capture.v1.json"),
                "container_receipt": str(process_dir / "container-custody/original_container_custody.v1.json")}
            original = payload_with_sha256_v1({"schema_version": 1,
                "artifact_kind": "vast_original_native_operation_input_v1", "operation": copy.deepcopy(row),
                "container_image": loaded["image"], "outputs": outputs})
            row["original_operation"] = _write(custody, sources / (identity + ".original.json"), original)
            rows.append(row)
            originals[identity] = original
        def validate_original(row, assets):
            from publication_gstreamer_component_authority_v1 import validate_component_original_native_row_v1
            current = _authority(root, component_authority_path)
            _require(current["document"] == loaded["document"], "component inputs changed during capture planning")
            _require(json.loads(assets[row["original_operation"]["path"]]) == originals[row["operation_id"]],
                     "original component operation drifted")
            plan = plans["shared" if row["scenario"] == "checkpoint_video_dag_shared" else "baseline"]
            _require(json.loads(assets[row["descriptors"]["source_plan"]["path"]]) == plan and
                     row["front_workers_by_route"] == front_workers_from_stock_plan_v1(plan, capabilities),
                     "component source/worker equations drifted")
            validate_component_original_native_row_v1(source=current, row=row, source_plan=plan)
            _require(load_execution_code_closure_v1(project_root=root, receipt_path=execution_code_closure_path) == closure,
                     "component execution source closure drifted")
        result = build_operational_capture_plan_v1(project_root=root, output_dir=output / "capture-plan",
            mode=DIAGNOSTIC_MODE, operations=rows, guardian_descriptors=guardian,
            guardian_output_dir=guardian_output, original_operation_validator=validate_original)
        custody.verify()
        return result


def _sealed_object(custody, root, path, *, kind):
    descriptor, raw = custody.read_descriptor(path, label="component sealed input", maximum=MAX_DOCUMENT_BYTES, capture=True)
    descriptor["path"] = str(root / descriptor["path"])
    value = strict_json_object_v1(raw, max_bytes=MAX_DOCUMENT_BYTES)
    _require(type(value.get("schema_version")) is int and value["schema_version"] == 1 and value.get("artifact_kind") == kind and
             canonical_json_v1(value) + b"\n" == raw and
             payload_with_sha256_v1(value)["sha256"] == value.get("sha256"),
             "component input kind, canonical bytes or semantic seal drifted")
    return value, descriptor


def _selected_guardian_v1(custody, root, path, *, preprocessing, analytics_socket_path, live):
    from checkpoint_gstreamer_analytics_sidecar import (
        assert_publication_sidecar_service_authority_identity_v1,
        assert_publication_sidecar_service_authority_v1,
    )
    from publication_guardian_runtime_expectations_v1 import runtime_expectations_from_preprocessing_receipt_v1
    ref, raw = custody.read_descriptor(path, label="component original guardian authority",
                                      maximum=MAX_DOCUMENT_BYTES, capture=True)
    ref = _reference(root, ref)
    authority = strict_json_object_v1(raw, max_bytes=MAX_DOCUMENT_BYTES)
    expected = runtime_expectations_from_preprocessing_receipt_v1(preprocessing["receipt"])
    validator = (assert_publication_sidecar_service_authority_v1 if live else
                 assert_publication_sidecar_service_authority_identity_v1)
    checked = validator(authority, expected_front_socket=analytics_socket_path,
        expected_execution_config_identity_sha256=expected["execution_config_identity_sha256"],
        expected_binding_set_identity_sha256=expected["binding_set_identity_sha256"],
        expected_worker_image_ids=expected["worker_image_ids"],
        expected_preprocessing_contract_authority=preprocessing["authority"],
        expected_service_identity_sha256=authority["service_identity_sha256"],
        expected_policy_contract_sha256=expected["policy_contract_sha256"])
    _require(checked == authority and authority["readiness_artifact_path"] == ref["path"],
             "component guardian authority escaped its original readiness reservation")
    return authority, ref


def _expected_runtime_inputs_v1(*, custody, selected, cell, preprocessing, context_ref,
        bundle_directory, analytics, scratch_root):
    """Reconstruct every ABI input from selected pins and explicit reservations."""
    import publication_policy_qualification_runtime_inputs_v2 as factory
    from publication_operational_runtime_context_v1 import CAPTURE_KEY, CAPTURE_ROLE, OUTPUT_PATH_RULE
    root, inventory = selected["root"], selected["inventory"]
    engine_target = bundle_directory / "container-engine" / "docker"
    engine = _descriptor(custody, root, engine_target, 256 * 1024 * 1024)
    _require(engine["size_bytes"] == selected["engine_pin"].size and
             engine["sha256"] == selected["engine_pin"].sha256,
             "component copied engine differs from held selected executable")
    adapter_path, adapter_bytes, adapter_descriptor = factory._adapter_asset(
        inventory, system="gstreamer_custom", final_root=bundle_directory)
    actual, raw = custody.read_descriptor(adapter_path, label="component original execution manifest",
                                         maximum=MAX_DOCUMENT_BYTES, capture=True)
    _require(raw == adapter_bytes and _reference(root, actual) == _reference(root, adapter_descriptor),
             "component execution manifest differs from selected original constructor")
    files = factory._system_file_descriptors_from_pins_v1(root=root,
        dataset_pin=inventory.dataset_pin, parity_pin=inventory.parity_pin,
        candidate_pin=selected["candidate_pin"], calibration_pin=selected["calib_pin"],
        system="gstreamer_custom", fixed=selected["fixed"], engine_asset_path=engine_target,
        engine_pin=selected["engine_pin"], adapter_descriptor=adapter_descriptor)
    contract = factory._runtime_contract_from_material_v1(cell, nvidia=inventory.nvidia,
        preprocessing_sha256=preprocessing["receipt"]["preprocessing_contract_content_sha256"],
        files=files, source_files=selected["source_descriptors"],
        model_files=[*selected["model_descriptors"], *selected["proxy_model_descriptors"]],
        support_files=selected["support_descriptors"], image=selected["image"],
        engine_socket=selected["engine_socket"], analytics_socket=analytics,
        scratch_root=factory._external_directory(Path(scratch_root), label="component original scratch reservation"),
        probe=selected["probe"], capability_hashes=selected["capability_hashes"])
    relative = Path(context_ref["path"]).relative_to(root).as_posix()
    contract["files"][CAPTURE_ROLE] = {**context_ref, "path": relative,
                                      "container_path": factory._project_container_path(relative)}
    contract[CAPTURE_KEY] = {"mode": DIAGNOSTIC_MODE, "output_dir": OUTPUT_PATH_RULE}
    return factory._runtime_inputs_for_cell(cell, dataset=selected["dataset"], contract=contract), engine


def _commit_hardware_v1(custody, root, source, destination):
    from publication_owned_staging_cleanup_v1 import OwnedStagingFileV1, _snapshot
    _require(os.name == "posix", "component native hardware transfer requires its POSIX owner")
    anchor = OwnedStagingFileV1.capture(source, label="component original stopped collector file",
                                       maximum_bytes=64 * 1024 * 1024)
    try:
        descriptor, raw = custody.read_descriptor(source, label="component stopped hardware evidence",
                                                 maximum=64 * 1024 * 1024, capture=True)
        _require(descriptor["size_bytes"] > 0, "component original hardware evidence is empty")
        _require(descriptor["sha256"] == anchor.sha256 and
                 _snapshot(source.lstat()) == anchor.snapshot == _snapshot(os.fstat(anchor._file_fd)),
                 "component original hardware file was rebound during transfer")
        custody.verify()
        committed, _identity, disposition = custody.commit_or_adopt_exact_identity(
            destination, raw, label="component original hardware evidence", mode=0o444)
        _require(disposition == "published" and committed["size_bytes"] == descriptor["size_bytes"] and
                 committed["sha256"] == descriptor["sha256"], "component hardware transfer was not fresh and exact")
        anchor.unlink_owned(final_target=source.with_name("." + source.name + ".published-source-sentinel"))
        return _reference(root, committed)
    finally:
        anchor.close()


def _hold_acceptance_inputs_v1(custody, directory):
    """Keep every existing physical acceptance leaf through receipt creation."""
    for name in (*CHILD_EVIDENCE_FILES, "hardware_resource_samples.csv"):
        custody.read_descriptor(directory / name, label="component full physical acceptance leaf",
                                maximum=64 * 1024 * 1024)


def _pair_schedule_v1(arms):
    # Original cohorts contain their run ID and observed absolute window.
    # The stock pair gate compares schedule fingerprints, excluding both.
    _require(len(arms) == 2 and arms[0]["schedule_sha256"] == arms[1]["schedule_sha256"],
             "component paired measurement schedules differ")
    return arms[0]["schedule_sha256"]


def _hold_guardian_journal_v1(custody, root, journal):
    expected = {key: journal[key] for key in ("path", "size_bytes", "sha256")}
    observed, _ = custody.read_descriptor(journal["path"], label="component whole-pair guardian journal",
                                         maximum=64 * 1024 * 1024)
    _require(_reference(root, observed) == expected, "component guardian journal physical descriptor drifted")
    return {"path": journal["path"], "descriptor": expected}


def _descriptive_arm_metrics_v1(directory, *, operation, admitted):
    from benchmark_contract import summarize_frames
    import pandas as pd
    metrics = summarize_frames(directory / "frames.csv", deadline_ms=operation["deadline_ms"],
                               measurement_s=operation["measurement_s"])
    frames = pd.read_csv(directory / "frames.csv")
    _require(type(admitted) is int and 0 < metrics["frames"] <= admitted,
             "component completed frames exceed validated measurement ingress")
    metrics.update(completed_deadline_misses=int((frames["e2e_latency_ms"] > operation["deadline_ms"]).sum()),
        measurement_admitted=admitted, measurement_dropped=admitted - metrics["frames"],
        measurement_censored=0, completion_coverage=metrics["frames"] / admitted,
        latency_population="completed_measurement_frames")
    return metrics


def _descriptive_comparison_v1(arms):
    result = {}
    for metric in ("latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "latency_max_ms",
                   "throughput_fps", "completed_deadline_misses", "measurement_dropped", "completion_coverage"):
        baseline, shared = (arm["descriptive_metrics"][metric] for arm in arms)
        _require(type(baseline) in {int, float} and type(shared) in {int, float}
                 and math.isfinite(baseline) and math.isfinite(shared), "component descriptive metric is not finite")
        ratio = shared / baseline if baseline > 0 else None
        result[metric] = {"baseline": baseline, "shared": shared, "shared_minus_baseline": shared - baseline,
            "shared_over_baseline": ratio, "ratio_reason": None if ratio is not None else "baseline_is_not_positive"}
    return result


def _write_descriptive_artifacts_v1(output, destination, arms, directories, *, resource, deadline_ms):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    buffer = io.StringIO(newline="")
    fields = ["operation_id", "scenario", "measurement_admitted", "frames", "measurement_dropped",
        "measurement_censored", "completed_deadline_misses", "completion_coverage", "latency_p50_ms",
        "latency_p95_ms", "latency_p99_ms", "latency_max_ms", "throughput_fps", "latency_population"]
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for arm in arms:
        row = {**arm["descriptive_metrics"], "operation_id": arm["operation_id"], "scenario": arm["scenario"]}
        writer.writerow({key: row[key] for key in fields})
    raw = buffer.getvalue().encode()
    _require(len(raw) <= MAX_DOCUMENT_BYTES, "component descriptive table exceeds bound")
    table = output.write_exclusive(destination / "component_pair_metrics.csv", raw,
                                   label="component actual descriptive metrics", mode=0o444)
    table["path"] = str(destination / "component_pair_metrics.csv")
    with plt.rc_context({"svg.hashsalt": "vast-component-v1"}):
        figure, axis = plt.subplots(figsize=(8, 5))
        try:
            for label, directory in zip(("Baseline", "Shared"), directories, strict=True):
                latency = pd.read_csv(directory / "frames.csv")["e2e_latency_ms"].sort_values().to_numpy()
                axis.step(latency, [(index + 1) / len(latency) for index in range(len(latency))],
                          where="post", label=label + " (n=" + str(len(latency)) + ")")
            axis.axvline(deadline_ms, color="0.4", linestyle="--", label=str(deadline_ms) + " ms deadline")
            axis.set(xlabel="Completed-frame end-to-end latency (ms)", ylabel="Empirical cumulative fraction",
                     ylim=(0, 1.02), title=resource.upper() + ": one native baseline/shared pair")
            axis.legend()
            figure.text(0.5, 0.02, "Topology/load proxy; completed measurement frames; no population inference", ha="center", fontsize=9)
            figure.tight_layout(rect=(0, 0.05, 1, 1))
            graphic = io.BytesIO()
            figure.savefig(graphic, format="svg", metadata={"Date": None})
        finally:
            plt.close(figure)
    raw = graphic.getvalue()
    _require(len(raw) <= MAX_DOCUMENT_BYTES, "component descriptive plot exceeds bound")
    plot = output.write_exclusive(destination / "component_pair_latency_ecdf.svg", raw,
                                  label="component actual latency ECDF", mode=0o444)
    plot["path"] = str(destination / "component_pair_latency_ecdf.svg")
    return {"descriptive_csv": table, "latency_ecdf_svg": plot}


def materialize_component_runtime_v1(*, project_root, component_authority_path, capture_plan_path,
        preprocessing_contract_path, preprocessing_receipt_path, guardian_authority_path,
        analytics_socket_path, scratch_root, output_dir):
    """Use the original ABI-v3 factory for exactly two component bundles."""
    import publication_policy_qualification_runtime_inputs_v2 as factory
    from publication_gstreamer_component_inputs_v1 import held_selected_component_inputs_v1
    from publication_guardian_component_preprocessing_contract_v1 import load_component_guardian_preprocessing_contract_v1
    from publication_operational_runtime_context_v1 import CAPTURE_KEY, CAPTURE_ROLE, OUTPUT_PATH_RULE
    with held_selected_component_inputs_v1(project_root=project_root,
            component_authority_path=component_authority_path) as selected:
        root, inventory = selected["root"], selected["inventory"]
        destination = _absolute(root, output_dir)
        _require(not os.path.lexists(destination), "component runtime output is occupied")
        preprocessing = load_component_guardian_preprocessing_contract_v1(project_root=root,
            preprocessing_contract_path=preprocessing_contract_path, materialization_receipt_path=preprocessing_receipt_path,
            capability_manifest_path=_absolute(root, selected["capability_manifest_descriptor"]["path"]),
            component_authority_path=component_authority_path)
        analytics = factory._socket_record(Path(analytics_socket_path), label="component actual guardian front")
        factory._require_socket_transport(analytics, expected_type="0005", label="component actual guardian front")
        engine_socket = selected["engine_socket"]
        factory._require_socket_transport(engine_socket, expected_type="0001", label="component actual engine socket")
        scratch = factory._external_directory(Path(scratch_root), label="component original runtime scratch")
        dataset, _media = factory._dataset_material(inventory, "h264")
        with PhysicalRootCustodyV1.open(root, label="component runtime materialization") as custody:
            _guardian, guardian_ref = _selected_guardian_v1(custody, root, guardian_authority_path,
                preprocessing=preprocessing, analytics_socket_path=analytics_socket_path, live=True)
            with held_operational_capture_plan_v1(project_root=root, index_path=_absolute(root, capture_plan_path)) as plan:
                _require(plan["index"]["mode"] == DIAGNOSTIC_MODE and len(plan["operations_by_id"]) == 2 and
                         _reference(root, preprocessing["receipt"]["operational_context"]) == plan["index"]["guardian_context"],
                         "component runtime preprocessing/context is detached")
                custody.ensure_directory_owned(destination, label="fresh component runtime bundles")
                engine_target = destination / "container-engine" / "docker"
                custody.ensure_directory_owned(engine_target.parent, label="owned component engine asset")
                copied_engine = factory._copy_engine_asset(root, selected["engine_pin"], engine_target)
                adapter_path, adapter_bytes, adapter_descriptor = factory._adapter_asset(inventory,
                    system="gstreamer_custom", final_root=destination)
                custody.write_exclusive(adapter_path, adapter_bytes, label="component original external analytics manifest", mode=0o444)
                _require(_reference(root, adapter_descriptor) == _descriptor(custody, root, adapter_path),
                         "component external analytics manifest differs from original constructor")
                files = factory._system_file_descriptors_from_pins_v1(root=root,
                    dataset_pin=inventory.dataset_pin, parity_pin=inventory.parity_pin,
                    candidate_pin=selected["candidate_pin"], calibration_pin=selected["calib_pin"],
                    system="gstreamer_custom", fixed=selected["fixed"], engine_asset_path=engine_target,
                    engine_pin=selected["engine_pin"], adapter_descriptor=adapter_descriptor)
                records = []
                cells = selected_cells_v1(selected["document"]["resource"])
                for cell in cells:
                    context = plan["runtime_contexts_by_arm"].get(cell.arm_id)
                    _require(context is not None, "component original pair has no native capture context")
                    contract = factory._runtime_contract_from_material_v1(cell,
                        nvidia=inventory.nvidia,
                        preprocessing_sha256=preprocessing["receipt"]["preprocessing_contract_content_sha256"],
                        files=files, source_files=selected["source_descriptors"],
                        model_files=[*selected["model_descriptors"], *selected["proxy_model_descriptors"]],
                        support_files=factory._support_descriptors(inventory, system="gstreamer_custom"),
                        image=selected["image"], engine_socket=engine_socket, analytics_socket=analytics,
                        scratch_root=scratch, probe=selected["probe"], capability_hashes=selected["capability_hashes"])
                    ref = _reference(root, context["descriptor"])
                    relative = Path(ref["path"]).relative_to(root).as_posix()
                    contract["files"][CAPTURE_ROLE] = {**ref, "path": relative,
                        "container_path": factory._project_container_path(relative)}
                    contract[CAPTURE_KEY] = {"mode": DIAGNOSTIC_MODE, "output_dir": OUTPUT_PATH_RULE}
                    value = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": BUNDLE_KIND,
                        "operation_id": context["operation"]["operation_id"],
                        "component_authority": _reference(root, selected["descriptor"]),
                        "capture_plan": _descriptor(custody, root, capture_plan_path),
                        "preprocessing_contract": _descriptor(custody, root, preprocessing_contract_path),
                        "preprocessing_receipt": _descriptor(custody, root, preprocessing_receipt_path),
                        "guardian_authority": guardian_ref,
                        "original_operation": context["operation"]["original_operation"], "native_context": ref,
                        "runtime_inputs": factory._runtime_inputs_for_cell(cell, dataset=dataset, contract=contract),
                        "launcher_evidence_files": list(CHILD_EVIDENCE_FILES)})
                    path = destination / (cell.arm_id + ".component.json")
                    records.append({"operation_id": value["operation_id"], "descriptor": _write(custody, path, value)})
                selected["verify_barrier"]()
                factory._require_file_pin_unchanged(copied_engine, label="component copied original engine")
                index = payload_with_sha256_v1({"schema_version": 1,
                    "artifact_kind": "vast_gstreamer_component_runtime_index_v1",
                    "component_authority": _reference(root, selected["descriptor"]), "bundles": records,
                    "engine_asset": _descriptor(custody, root, engine_target, 256 * 1024 * 1024),
                    "analytics_manifest": _descriptor(custody, root, adapter_path), **_component_flags()})
                descriptor = _write(custody, destination / "component_runtime_index.v1.json", index)
                custody.verify()
                return {"descriptor": descriptor, "receipt": index}


@contextmanager
def held_component_runtime_v1(*, project_root, component_authority_path, capture_plan_path,
        runtime_bundle_path, operation_id, preprocessing_contract_path, preprocessing_receipt_path,
        guardian_authority_path, analytics_socket_path, scratch_root, live_guardian=True):
    """Select one physically current component request, never full inputs."""
    from publication_gstreamer_component_inputs_v1 import held_selected_component_inputs_v1
    from publication_gstreamer_component_authority_v1 import validate_component_original_native_row_v1
    from publication_guardian_component_preprocessing_contract_v1 import load_component_guardian_preprocessing_contract_v1
    from publication_operational_runtime_context_v1 import CAPTURE_KEY, CAPTURE_ROLE, OUTPUT_PATH_RULE
    with held_selected_component_inputs_v1(project_root=project_root,
            component_authority_path=component_authority_path) as selected:
        root = selected["root"]
        with _held_operational_cold_custody_v1(root) as custody:
            bundle, bundle_ref = _sealed_object(custody, root, runtime_bundle_path, kind=BUNDLE_KIND)
            _require(set(bundle) == {"schema_version", "artifact_kind", "operation_id", "component_authority",
                "capture_plan", "preprocessing_contract", "preprocessing_receipt", "guardian_authority",
                "original_operation", "native_context", "runtime_inputs", "launcher_evidence_files", "sha256"},
                "component bundle fields drifted")
            _require(bundle["operation_id"] == operation_id and
                     _operational_absolute_descriptor(root, bundle["component_authority"]) ==
                     _operational_absolute_descriptor(root, selected["descriptor"]),
                     "component bundle is detached from current selected inputs")
            preprocessing = load_component_guardian_preprocessing_contract_v1(project_root=root,
                preprocessing_contract_path=preprocessing_contract_path, materialization_receipt_path=preprocessing_receipt_path,
                capability_manifest_path=_absolute(root, selected["capability_manifest_descriptor"]["path"]),
                component_authority_path=component_authority_path)
            for role, path in (("preprocessing_contract", preprocessing_contract_path),
                               ("preprocessing_receipt", preprocessing_receipt_path)):
                _require(bundle[role] == _descriptor(custody, root, path),
                         "component runtime preprocessing physical reservation drifted")
            guardian, guardian_ref = _selected_guardian_v1(custody, root, guardian_authority_path,
                preprocessing=preprocessing, analytics_socket_path=analytics_socket_path, live=live_guardian)
            _require(bundle["guardian_authority"] == guardian_ref, "component runtime changed the original guardian")
            with held_operational_capture_plan_v1(project_root=root, index_path=_absolute(root, capture_plan_path),
                    expected_descriptor=_operational_absolute_descriptor(root, bundle["capture_plan"])) as plan:
                _require(plan["index"]["mode"] == DIAGNOSTIC_MODE and len(plan["operations_by_id"]) == 2 and
                         operation_id in plan["operations_by_id"], "component operation is outside its original pair")
                operation = plan["operations_by_id"][operation_id]
                cells = {cell.arm_id: cell for cell in selected_cells_v1(selected["document"]["resource"])}
                cell = cells.get(operation["arm_id"])
                _require(cell is not None and operation["phase"] == "diagnostic" and
                         all(operation[k] == getattr(cell, k) for k in
                             ("run_id", "system", "scenario", "codec", "policy", "deadline_ms")),
                         "component operation changed the frozen coordinates")
                original = _held_operational_object(custody, root, operation["original_operation"])
                source_plan = _held_operational_object(custody, root, operation["descriptors"]["source_plan"],
                                                      require_self_hash=False)
                validate_component_original_native_row_v1(source=selected, row=operation, source_plan=source_plan)
                _require(_reference(root, preprocessing["receipt"]["operational_context"]) == plan["index"]["guardian_context"],
                         "component runtime preprocessing is detached from its capture plan")
                context_ref = plan["runtime_contexts_by_arm"][cell.arm_id]["descriptor"]
                _require(bundle["original_operation"] == operation["original_operation"] and
                         bundle["native_context"] == context_ref and original["operation"] ==
                         {k: v for k, v in operation.items() if k != "original_operation"},
                         "component original/context binding drifted")
                inputs = bundle["runtime_inputs"]
                contract = inputs["dataset"]["gstreamer_custom_publication_runtime_v3"]
                expected_inputs, engine = _expected_runtime_inputs_v1(custody=custody, selected=selected, cell=cell,
                    preprocessing=preprocessing, context_ref=context_ref,
                    bundle_directory=_absolute(root, runtime_bundle_path).parent,
                    analytics=guardian["front_socket"], scratch_root=scratch_root)
                _require(canonical_json_v1(inputs) == canonical_json_v1(expected_inputs),
                         "component runtime differs from exact selected original factory inputs")
                _require(contract["container_image"] == original["container_image"] == selected["image"] and
                         contract.get(CAPTURE_KEY) == {"mode": DIAGNOSTIC_MODE, "output_dir": OUTPUT_PATH_RULE} and
                         _operational_absolute_descriptor(root, {k: contract["files"][CAPTURE_ROLE][k]
                             for k in ("path", "size_bytes", "sha256")}) == context_ref,
                         "component image or active native capture is detached")
                for role, expected in (("policy_capability_manifest", selected["capability_manifest_descriptor"]),
                                       ("policy_calibration", selected["calibration_descriptor"])):
                    observed = {k: contract["files"][role][k] for k in ("path", "size_bytes", "sha256")}
                    _require(_operational_absolute_descriptor(root, observed) == _operational_absolute_descriptor(root, expected),
                             "component runtime changed selected " + role)
                _require(bundle["launcher_evidence_files"] == list(CHILD_EVIDENCE_FILES),
                         "component child evidence domain drifted")
                directory = _absolute(root, original["outputs"]["measurement_dir"])
                authority_ref = _operational_absolute_descriptor(root, selected["descriptor"])
                request = NativePublicationRequestV3(system=cell.system, topology_kind=cell.topology_kind,
                    scenario=cell.scenario, project_root=root, output_dir=directory,
                    arm_contract_path=Path(authority_ref["path"]), arm_contract_file_sha256=authority_ref["sha256"],
                    run_id=cell.run_id, arm_id=cell.arm_id, runtime_inputs=copy.deepcopy(inputs),
                    launcher_evidence_files=CHILD_EVIDENCE_FILES)
                def verify():
                    selected["verify_barrier"]()
                    actual = _descriptor(custody, root, runtime_bundle_path)
                    _require(actual == bundle_ref, "component runtime bundle changed during operation")
                    custody.verify()
                verify()
                yield {"request": request, "cell": cell, "selected": selected, "operation": operation,
                    "original": original, "original_operation_descriptor": operation["original_operation"],
                    "native_context_descriptor": context_ref, "container_image": selected["image"],
                    "engine_descriptor": engine, "execution_barrier": verify, "bundle_descriptor": bundle_ref}
                verify()


def execute_component_operation_v1(**arguments):
    """One original native operation, stopped collector, receipt-last result."""
    _require("live_guardian" not in arguments, "component execution cannot disable actual live guardian custody")
    with held_component_runtime_v1(**arguments) as held:
        root, cell, outputs = held["selected"]["root"], held["cell"], held["original"]["outputs"]
        directory = Path(outputs["measurement_dir"])
        process_dir = Path(outputs["process_receipt"]).parent
        staging = directory.parent / ".hardware-host"
        result_path = directory.parent / RESULT_FILENAME
        _require(all(not os.path.lexists(path) for path in
                     (directory, Path(str(directory) + ".operational"), process_dir, staging, result_path)),
                 "component original output is occupied; automatic retry is forbidden")
        with PhysicalRootCustodyV1.open(root, label="component original output custody") as custody:
            custody.ensure_directory_owned(directory, label="fresh component arm evidence")
            custody.ensure_directory_owned(staging, label="component host hardware capture")
            hardware_path = staging / "hardware_resource_samples.host.csv"
            collector = HardwareResourceCollector(hardware_path, run_id=cell.run_id, interval_s=1.0)
            started = time.time_ns()
            held["execution_barrier"]()
            primary = None
            try:
                collector.start()
                collector.wait_until_ready(timeout_s=60.0)
                with capture_original_engine_processes_v1(project_root=root, output_dir=process_dir,
                        operation_id=arguments["operation_id"], original_operation_descriptor=held["original_operation_descriptor"],
                        native_context_descriptor=held["native_context_descriptor"], container_image=held["container_image"]) as capture:
                    outcome = run_checkpoint_gstreamer_publication_runtime_v3(held["request"])
                    _require(type(outcome) is NativePublicationOutcomeV3 and
                             type(outcome.exit_code) is int and outcome.exit_code == 0 and not outcome.blockers,
                             "original component native terminal is unsuccessful")
            except BaseException as error:
                primary = error
                raise
            finally:
                try:
                    _stop_collector(collector)
                except BaseException as error:
                    if primary is None:
                        raise
                    primary.add_note("component hardware collector cleanup also failed: " + str(error))
            _require(capture.receipt_descriptor is not None and capture.container_receipt_descriptor is not None,
                     "component original process/container custody is missing")
            _require(set(custody.list_directory_names(directory, label="component original child domain")) ==
                     set(CHILD_EVIDENCE_FILES), "component original child domain changed")
            _commit_hardware_v1(custody, root, hardware_path, directory / "hardware_resource_samples.csv")
            with _held_operational_cold_custody_v1(root) as cold:
                _hold_acceptance_inputs_v1(cold, directory)
                process = original_process_validator_v1(project_root=root, receipt_path=outputs["process_receipt"],
                    expected_descriptor=capture.receipt_descriptor, operation_id=arguments["operation_id"],
                    original_operation_descriptor=held["original_operation_descriptor"],
                    native_context_descriptor=held["native_context_descriptor"], expected_container_image=held["container_image"])
                observed_engine = {k: process["measurement"]["launch"]["engine"][k] for k in ("path", "size_bytes", "sha256")}
                _require(observed_engine == held["engine_descriptor"], "component original engine differs from current bundle")
                cold.hold_validated_inputs(process, engine_descriptor=observed_engine)
                container = original_container_validator_v1(project_root=root, receipt_path=outputs["container_receipt"],
                    expected_descriptor=capture.container_receipt_descriptor, process_receipt_path=outputs["process_receipt"],
                    expected_process_descriptor=capture.receipt_descriptor, operation_id=arguments["operation_id"],
                    original_operation_descriptor=held["original_operation_descriptor"],
                    native_context_descriptor=held["native_context_descriptor"], expected_container_image=held["container_image"])
                cold.hold_validated_inputs(container, engine_descriptor=observed_engine)
                _require(container["container_quiescence_verified"] is True, "component original container is not quiescent")
                references = {"native_domain": _descriptor(custody, root, outputs["native_domain"], 64 * 1024 * 1024),
                    "process_receipt": capture.receipt_descriptor, "container_receipt": capture.container_receipt_descriptor,
                    "accepted_ingress": _descriptor(custody, root, directory / "ingress_ledger.csv", 64 * 1024 * 1024),
                    "measurement_decisions": _descriptor(custody, root, directory / "publication_policy_decisions.jsonl", 64 * 1024 * 1024),
                    "hardware": _descriptor(custody, root, directory / "hardware_resource_samples.csv", 64 * 1024 * 1024)}
                # Existing source/cohort/stage/drop/reset validation and physical
                # full-resource validation remain required; no full finalizer.
                measured = _operational_measured_ingress_v1(root=root, operation=held["operation"],
                    directory=directory, ingress_descriptor=references["accepted_ingress"])
                physical = prepare_checkpoint_publication_acceptance(output_dir=directory,
                    expected_run_id=cell.run_id, expected_system=cell.system, expected_scenario=cell.scenario,
                    expected_codec=cell.codec, expected_policy=cell.policy, expected_deadline_ms=cell.deadline_ms,
                    topology_kind=cell.topology_kind, hardware_collector_stopped=True)
                _require(bool(measured) and all(count > 0 for count in physical["completed_frames_by_stream"].values()),
                         "zero-frame component smoke cannot complete an original arm")
                held["execution_barrier"]()
                cold.verify()
                receipt = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": ARM_KIND,
                    "operation_id": arguments["operation_id"], "runtime_bundle": held["bundle_descriptor"],
                    "original_operation": held["original_operation_descriptor"], "native_context": held["native_context_descriptor"],
                    "container_image": held["container_image"], "outputs": references,
                    "started_at_ns": started, "finished_at_ns": time.time_ns(), "original_exit_code": 0,
                    "physical_validation": {k: v for k, v in physical.items() if k not in {"artifact_kind", "status"}},
                    "measurement_ingress_count": len(measured),
                    "scientific_scope": "topology_load_proxy_only", **_component_flags()})
                result_ref = _write(custody, result_path, receipt)
                cold.verify()
                custody.verify()
                return {"descriptor": result_ref, "receipt": receipt}


def cold_component_pair_v1(**arguments):
    """Hold the original selected source leaves for the entire cold pair."""
    from publication_gstreamer_component_authority_v1 import held_component_authority_v1
    with held_component_authority_v1(project_root=arguments["project_root"],
            component_authority_path=arguments["component_authority_path"]) as selected:
        result = _cold_component_pair_from_held_v1(selected=selected, **arguments)
        selected["verify_barrier"]()
        return result


def _cold_component_pair_from_held_v1(*, selected, project_root, component_authority_path, capture_plan_path,
        runtime_bundle_paths, arm_result_paths, guardian_authority_path, guardian_lifecycle_path,
        preprocessing_contract_path, preprocessing_receipt_path, analytics_socket_path, scratch_root, output_dir):
    """Recompute two original arms and their full owned guardian lifetime."""
    from checkpoint_gstreamer_analytics_sidecar import (
        assert_publication_sidecar_service_authority_identity_v1,
        validate_publication_sidecar_service_lifecycle_v1,
    )
    from publication_guardian_component_preprocessing_contract_v1 import load_component_guardian_preprocessing_contract_v1
    from publication_guardian_runtime_expectations_v1 import runtime_expectations_from_preprocessing_receipt_v1
    from publication_operational_request_domain_v1 import load_operational_jsonl_header_v1
    root = Path(project_root)
    _require(type(runtime_bundle_paths) is list and type(arm_result_paths) is list and
             len(runtime_bundle_paths) == len(arm_result_paths) == 2,
             "component cold result requires exactly its two original arms")
    destination = _absolute(root, output_dir)
    _require(not os.path.lexists(destination), "component pair result output is occupied")
    capabilities = selected["worker_capabilities"]
    with _held_operational_cold_custody_v1(root) as custody:
        contract_ref = _descriptor(custody, root, preprocessing_contract_path)
        preprocessing_ref = _descriptor(custody, root, preprocessing_receipt_path)
        preprocessing = load_component_guardian_preprocessing_contract_v1(project_root=root,
            preprocessing_contract_path=preprocessing_contract_path, materialization_receipt_path=preprocessing_receipt_path,
            capability_manifest_path=_absolute(root, selected["capability_manifest_descriptor"]["path"]),
            component_authority_path=component_authority_path)
        _require(contract_ref == _reference(root, preprocessing["receipt"]["preprocessing_contract"])
                 and contract_ref["sha256"] == preprocessing["authority"]["preprocessing_contract_file_sha256"]
                 and preprocessing_ref["sha256"] == preprocessing["authority"]["materialization_receipt_file_sha256"],
                 "component whole-pair preprocessing physical binding drifted")
        expectations = runtime_expectations_from_preprocessing_receipt_v1(preprocessing["receipt"])
        def read_document(path):
            descriptor, raw = custody.read_descriptor(path, label="component cold original metadata",
                maximum=MAX_DOCUMENT_BYTES, capture=True)
            descriptor["path"] = str(root / descriptor["path"])
            return strict_json_object_v1(raw, max_bytes=MAX_DOCUMENT_BYTES), descriptor
        authority, authority_ref = read_document(guardian_authority_path)
        lifecycle, lifecycle_ref = read_document(guardian_lifecycle_path)
        checked = assert_publication_sidecar_service_authority_identity_v1(authority,
            expected_front_socket=analytics_socket_path,
            expected_execution_config_identity_sha256=expectations["execution_config_identity_sha256"],
            expected_binding_set_identity_sha256=expectations["binding_set_identity_sha256"],
            expected_worker_image_ids=expectations["worker_image_ids"],
            expected_preprocessing_contract_authority=preprocessing["authority"],
            expected_service_identity_sha256=lifecycle["service_identity_sha256"],
            expected_policy_contract_sha256=expectations["policy_contract_sha256"])
        checked_lifecycle = validate_publication_sidecar_service_lifecycle_v1(lifecycle, expected_authority=checked)
        _require(checked == authority and checked_lifecycle == lifecycle and
                 authority["readiness_artifact_path"] == authority_ref["path"] and
                 authority["lifecycle_artifact_path"] == lifecycle_ref["path"] and
                 lifecycle["status"] == "clean_stop_nonpublication" and lifecycle["failure"] is None and
                 lifecycle["cleanup_errors"] == [] and
                 all(not os.path.lexists(authority[key]["path"]) for key in ("front_socket", "control_socket")),
                 "component guardian did not reach its original authenticated clean stop")
        with held_operational_capture_plan_v1(project_root=root, index_path=_absolute(root, capture_plan_path)) as plan:
            _require(plan["index"]["mode"] == DIAGNOSTIC_MODE and len(plan["operations_by_id"]) == 2,
                     "component cold context is not exactly the original pair")
            _require(_operational_absolute_descriptor(root, preprocessing["receipt"]["operational_context"]) ==
                     plan["index"]["guardian_context"], "component preprocessing is detached from original capture")
            companion_path = Path(plan["guardian_context"]["output_dir"]) / "operational_group.v1.json"
            companion, companion_ref = read_document(companion_path)
            expected_headers = {}
            for journal in companion["journals"]:
                _require(journal["route"] not in expected_headers, "component guardian journal routes alias")
                entry = _hold_guardian_journal_v1(custody, root, journal)
                header = load_operational_jsonl_header_v1(entry)
                template = copy.deepcopy(plan["guardian_context"]["headers_by_route"][journal["route"]])
                template.update(lifecycle_id=authority["lifecycle_id"], owner=authority["owner_process"],
                                worker_capability=dict(capabilities[tuple(journal["route"].split(":"))]))
                template["descriptors"]["service_authority"] = authority_ref
                template = payload_with_sha256_v1(template)
                _require(header == template, "component observed guardian constants differ from actual current source")
                expected_headers[journal["route"]] = template
            operations = list(plan["operations_by_id"].values())
            domains, measured, arm_summaries, arm_refs, directories = [], [], [], [], []
            seen_inodes = set()
            for operation, bundle_path, result_path in zip(operations, runtime_bundle_paths, arm_result_paths, strict=True):
                receipt, receipt_ref = read_document(result_path)
                _require(set(receipt) == {"schema_version", "artifact_kind", "operation_id", "runtime_bundle",
                         "original_operation", "native_context", "container_image", "outputs", "started_at_ns",
                         "finished_at_ns", "original_exit_code", "physical_validation", "measurement_ingress_count",
                         "scientific_scope", "sha256", *_component_flags()} and
                         type(receipt.get("schema_version")) is int and receipt["schema_version"] == 1
                         and receipt.get("artifact_kind") == ARM_KIND and
                         payload_with_sha256_v1(receipt)["sha256"] == receipt.get("sha256") and
                         receipt["operation_id"] == operation["operation_id"] and
                         receipt["scientific_scope"] == "topology_load_proxy_only" and
                         type(receipt["original_exit_code"]) is int and receipt["original_exit_code"] == 0 and
                         type(receipt["measurement_ingress_count"]) is int and receipt["measurement_ingress_count"] > 0 and
                         type(receipt["started_at_ns"]) is int and type(receipt["finished_at_ns"]) is int and
                         0 < receipt["started_at_ns"] <= receipt["finished_at_ns"] and
                         all(type(receipt.get(k)) is type(v) and receipt[k] == v
                             for k, v in _component_flags().items()),
                         "component arm kind, pair identity or full eligibility drifted")
                with held_component_runtime_v1(project_root=root, component_authority_path=component_authority_path,
                        capture_plan_path=capture_plan_path, runtime_bundle_path=bundle_path,
                        operation_id=operation["operation_id"],
                        preprocessing_contract_path=preprocessing_contract_path,
                        preprocessing_receipt_path=preprocessing_receipt_path,
                        guardian_authority_path=guardian_authority_path, analytics_socket_path=analytics_socket_path,
                        scratch_root=scratch_root, live_guardian=False) as held:
                    _require(Path(result_path) == Path(held["original"]["outputs"]["measurement_dir"]).parent / RESULT_FILENAME,
                             "component arm result escaped its original reservation")
                    for descriptor in (held["bundle_descriptor"], held["original_operation_descriptor"],
                                       held["native_context_descriptor"]):
                        observed, _ = custody.read_descriptor(descriptor["path"], label="component whole-pair original input",
                                                             maximum=MAX_DOCUMENT_BYTES)
                        _require(_reference(root, observed) == descriptor, "component whole-pair original input drifted")
                    _require(receipt["runtime_bundle"] == held["bundle_descriptor"] and
                             receipt["original_operation"] == held["original_operation_descriptor"] and
                             receipt["native_context"] == held["native_context_descriptor"] and
                             receipt["container_image"] == held["container_image"] and receipt["original_exit_code"] == 0,
                             "component original arm custody changed")
                    outputs = receipt["outputs"]
                    _require(set(outputs) == {"native_domain", "process_receipt", "container_receipt",
                        "accepted_ingress", "measurement_decisions", "hardware"}, "component arm outputs drifted")
                    directory = Path(held["original"]["outputs"]["measurement_dir"])
                    _hold_acceptance_inputs_v1(custody, directory)
                    for role in ("native_domain", "process_receipt", "container_receipt"):
                        _require(outputs[role]["path"] == held["original"]["outputs"][role],
                                 "component original output escaped its reservation")
                    for role, filename in (("accepted_ingress", "ingress_ledger.csv"),
                                           ("measurement_decisions", "publication_policy_decisions.jsonl"),
                                           ("hardware", "hardware_resource_samples.csv")):
                        _require(outputs[role]["path"] == str(directory / filename),
                                 "component measured output escaped its reservation")
                    for descriptor in outputs.values():
                        observed, _ = custody.read_descriptor(descriptor["path"], label="component original evidence",
                            maximum=64 * 1024 * 1024)
                        _require(_operational_absolute_descriptor(root, observed) == descriptor,
                                 "component original physical output bytes drifted")
                    process = original_process_validator_v1(project_root=root,
                        receipt_path=outputs["process_receipt"]["path"], expected_descriptor=outputs["process_receipt"],
                        operation_id=operation["operation_id"], original_operation_descriptor=operation["original_operation"],
                        native_context_descriptor=held["native_context_descriptor"], expected_container_image=held["container_image"])
                    engine = {k: process["measurement"]["launch"]["engine"][k] for k in ("path", "size_bytes", "sha256")}
                    _require(engine == held["engine_descriptor"], "component cold original engine drifted")
                    custody.hold_validated_inputs(process, engine_descriptor=engine)
                    container = original_container_validator_v1(project_root=root,
                        receipt_path=outputs["container_receipt"]["path"], expected_descriptor=outputs["container_receipt"],
                        process_receipt_path=outputs["process_receipt"]["path"], expected_process_descriptor=outputs["process_receipt"],
                        operation_id=operation["operation_id"], original_operation_descriptor=operation["original_operation"],
                        native_context_descriptor=held["native_context_descriptor"], expected_container_image=held["container_image"])
                    custody.hold_validated_inputs(container, engine_descriptor=engine)
                    _require(container["container_quiescence_verified"] is True, "component cold original container is not quiescent")
                    native_path = Path(outputs["native_domain"]["path"])
                    info = native_path.lstat()
                    _require((info.st_dev, info.st_ino) not in seen_inodes, "component native outputs physically alias")
                    seen_inodes.add((info.st_dev, info.st_ino))
                    entry = {"path": native_path, "descriptor": outputs["native_domain"]}
                    header = load_operational_jsonl_header_v1(entry)
                    context = plan["native_contexts_by_id"][operation["operation_id"]]["native_header"]
                    _require(all(header[k] == context[k] for k in set(context) - {"counts", "adaptive_history", "sha256"}),
                             "component original native reset/source context drifted")
                    frame_map = _operational_measured_ingress_v1(root=root, operation=operation, directory=directory,
                                                               ingress_descriptor=outputs["accepted_ingress"])
                    physical = prepare_checkpoint_publication_acceptance(output_dir=directory,
                        expected_run_id=operation["run_id"], expected_system=operation["system"],
                        expected_scenario=operation["scenario"], expected_codec=operation["codec"],
                        expected_policy=operation["policy"], expected_deadline_ms=operation["deadline_ms"],
                        topology_kind=held["cell"].topology_kind, hardware_collector_stopped=True)
                    _require(receipt["measurement_ingress_count"] == len(frame_map) > 0 and
                             canonical_json_v1(receipt["physical_validation"]) == canonical_json_v1(
                                 {k: v for k, v in physical.items() if k not in {"artifact_kind", "status"}}),
                             "component stored result differs from strict cold physical validation")
                    domains.append({**entry, "expected_header": header})
                    measured.append({"path": directory / "publication_policy_decisions.jsonl",
                        "descriptor": outputs["measurement_decisions"],
                        "canonical_frames": partial(_operational_measured_ingress_v1, root=root,
                            operation=operation, directory=directory, ingress_descriptor=outputs["accepted_ingress"])})
                    arm_summaries.append({"operation_id": operation["operation_id"], "scenario": operation["scenario"],
                        "cohort_id": physical["cohort_id"], "schedule_sha256": physical["measurement_schedule_fingerprint_sha256"],
                        "summary": physical["summary"], "measurement_ingress_count": len(frame_map),
                        "descriptive_metrics": _descriptive_arm_metrics_v1(directory,
                            operation=operation, admitted=len(frame_map))})
                    directories.append(directory)
                    arm_refs.append(receipt_ref)
                    held["execution_barrier"]()
            pair_schedule = _pair_schedule_v1(arm_summaries)
            reconciliation = reconcile_guardian_operational_workload_v1(producer_domains=domains,
                guardian_companion={"path": companion_path, "descriptor": companion_ref},
                measurement_descriptors=measured, expected_context={"mode": DIAGNOSTIC_MODE,
                    "operation_count": 2, "guardian_headers": expected_headers},
                capability_manifest=selected["capability_manifest"], lifecycle_counters=lifecycle["counters"],
                scratch_root=destination.parent / (destination.name + ".reconciliation-scratch"))
            custody.verify()
            selected["verify_barrier"]()
            value = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": PAIR_KIND,
                "resource": selected["document"]["resource"], "component_arms": 2, "component_pairs": 1,
                "component_authority": selected["descriptor"], "arm_results": arm_refs,
                "guardian_authority": authority_ref, "guardian_lifecycle": lifecycle_ref,
                "guardian_companion": companion_ref, "operational_reconciliation": reconciliation,
                "pair_gate": "equal_measurement_schedule_fingerprint_sha256",
                "measurement_schedule_fingerprint_sha256": pair_schedule,
                "cohort_ids_are_arm_local": True,
                "descriptive_comparison": _descriptive_comparison_v1(arm_summaries),
                "arms": arm_summaries, "scientific_scope": "topology_load_proxy_only",
                "comparison_scope": "one_descriptive_pair_per_resource", "confidence_interval": None,
                "confidence_interval_reason": "one_pair_does_not_establish_population_inference",
                "c_obs_scope": "partial_observed_attributed_stage_elapsed",
                "quality_noninferiority_claim": False, "backend_native_accuracy_claim": False,
                "true_nvdec_busy_time_claim": False, **_component_flags()})
            with PhysicalRootCustodyV1.open(root, label="component pair receipt custody") as output:
                output.ensure_directory_owned(destination, label="fresh component pair results")
                value.update(_write_descriptive_artifacts_v1(output, destination, arm_summaries, directories,
                    resource=selected["document"]["resource"], deadline_ms=operations[0]["deadline_ms"]))
                value = payload_with_sha256_v1(value)
                custody.verify()
                selected["verify_barrier"]()
                descriptor = _write(output, destination / "component_pair_result.v1.json", value)
                output.verify()
            custody.verify()
            selected["verify_barrier"]()
            return {"descriptor": descriptor, "receipt": value}
