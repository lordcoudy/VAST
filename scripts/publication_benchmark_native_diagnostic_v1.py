#!/usr/bin/env python3
"""Run one original forced native diagnostic through the stock runtime spine."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import stat
import time

import publication_policy_qualification_pilot_executor_v2 as pilot
from checkpoint_gstreamer_publication_runtime_v3 import run_checkpoint_gstreamer_publication_runtime_v3
from checkpoint_publication_launcher_adapter_v3 import NativePublicationOutcomeV3
from checkpoint_qualification_pilot_acceptance_v1 import (
    finalize_checkpoint_qualification_pilot_acceptance_v1,
    validate_checkpoint_qualification_pilot_acceptance_v1,
)
from collect_metrics import HardwareResourceCollector
from publication_operational_container_custody_v1 import original_container_validator_v1
from publication_operational_process_custody_v1 import (
    capture_original_engine_processes_v1, original_process_validator_v1,
)
from publication_policy_qualification_execution_closure_v1 import _held_operational_cold_custody_v1
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1
from publication_operational_stock_operations_v1 import held_stock_operational_request_v1
from publication_physical_io_v1 import PhysicalRootCustodyV1

RECEIPT_FILENAME = "native_diagnostic.execution.v1.json"
MAX_RECEIPT_BYTES = 65536
INPUT_ARGUMENTS = ("runtime_bundle_path", "candidate_index_path", "preprocessing_contract_path",
    "preprocessing_receipt_path", "runtime_materialization_receipt_path", "guardian_authority_path",
    "transaction_receipt_path", "bootstrap_mapping_path", "bootstrap_receipt_path")


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _stop_collector(collector):
    error = None
    for action in (collector.stop, lambda: collector.join(timeout=30.0),
            lambda: _require(not collector.is_alive(), "original diagnostic hardware collector survived stop"),
            collector.raise_if_failed):
        try:
            action()
        except BaseException as observed:
            if error is None:
                error = observed
            else:
                error.add_note("Original diagnostic collector cleanup also failed: " + str(observed))
    if error is not None:
        raise error


def _descriptor(custody, root, path, maximum):
    value, _ = custody.read_descriptor(path, label="original diagnostic physical output",
        maximum=maximum, capture=False)
    value["path"] = str(root / value["path"])
    return value


def execute_native_diagnostic_operation_v1(*, project_root, capture_plan_path, operation_id,
        runtime_bundle_path, candidate_index_path, preprocessing_contract_path, preprocessing_receipt_path,
        runtime_materialization_receipt_path, guardian_authority_path, transaction_receipt_path,
        bootstrap_mapping_path, bootstrap_receipt_path):
    """Execute once, stop the host collector, and retain separate nonpromoting facts.

    The held stock loader owns all input, bundle, mode and coordinate validation.
    CLI/container custody is independently recomputed before host finalization;
    a NativePublicationOutcome alone cannot stand in for original execution.
    """
    arguments = dict(project_root=project_root, capture_plan_path=capture_plan_path, operation_id=operation_id,
        runtime_bundle_path=runtime_bundle_path, candidate_index_path=candidate_index_path,
        preprocessing_contract_path=preprocessing_contract_path, preprocessing_receipt_path=preprocessing_receipt_path,
        runtime_materialization_receipt_path=runtime_materialization_receipt_path, guardian_authority_path=guardian_authority_path,
        transaction_receipt_path=transaction_receipt_path, bootstrap_mapping_path=bootstrap_mapping_path,
        bootstrap_receipt_path=bootstrap_receipt_path)
    with held_stock_operational_request_v1(**arguments) as held:
        root, cell = held["inputs"].root, held["cell"]
        outputs = held["original"]["outputs"]
        directory = Path(outputs["measurement_dir"])
        receipt_path = directory.parent / RECEIPT_FILENAME
        staging = directory.parent / ".hardware-host"
        process_dir = Path(outputs["process_receipt"]).parent
        _require(all(not os.path.lexists(path) for path in (directory, Path(str(directory) + ".operational"),
            process_dir, receipt_path, staging)), "original diagnostic output is occupied; no new launch is permitted")
        with PhysicalRootCustodyV1.open(root, label="original diagnostic output custody") as custody:
            custody.ensure_directory_owned(directory, label="fresh original diagnostic evidence")
            custody.ensure_directory_owned(staging, label="fresh original diagnostic host staging")
            hardware_path = staging / "hardware_resource_samples.host.csv"
            started = time.time_ns()
            held["execution_barrier"]()
            collector = HardwareResourceCollector(hardware_path, run_id=cell.run_id, interval_s=1.0)
            original_error = None
            try:
                collector.start()
                collector.wait_until_ready(timeout_s=60.0)
                with capture_original_engine_processes_v1(project_root=root, output_dir=process_dir,
                        operation_id=operation_id, original_operation_descriptor=held["original_operation_descriptor"],
                        native_context_descriptor=held["native_context_descriptor"], container_image=held["container_image"]) as capture:
                    outcome = run_checkpoint_gstreamer_publication_runtime_v3(held["request"])
                    _require(type(outcome) is NativePublicationOutcomeV3 and outcome.exit_code == 0
                        and outcome.blockers == (), "original native diagnostic returned non-success")
            except BaseException as error:
                original_error = error
                raise
            finally:
                try:
                    _stop_collector(collector)
                except BaseException as cleanup_error:
                    if original_error is None:
                        raise
                    original_error.add_note("Original diagnostic collector cleanup failed: " + str(cleanup_error))
            held["execution_barrier"]()
            _require(capture.receipt_descriptor is not None and capture.container_receipt_descriptor is not None
                and capture.receipt_descriptor["path"] == outputs["process_receipt"]
                and capture.container_receipt_descriptor["path"] == outputs["container_receipt"],
                "original diagnostic process/container receipts are missing or detached")
            with _held_operational_cold_custody_v1(root) as cold:
                process_summary = original_process_validator_v1(project_root=root,
                    receipt_path=outputs["process_receipt"], expected_descriptor=capture.receipt_descriptor,
                    operation_id=operation_id, original_operation_descriptor=held["original_operation_descriptor"],
                    native_context_descriptor=held["native_context_descriptor"], expected_container_image=held["container_image"])
                observed_engine = {field: process_summary["measurement"]["launch"]["engine"][field]
                    for field in ("path", "size_bytes", "sha256")}
                _require(observed_engine == held["engine_descriptor"],
                    "original diagnostic executable differs from validated stock engine")
                cold.hold_validated_inputs(process_summary, engine_descriptor=held["engine_descriptor"])
                del process_summary
                original_custody = original_container_validator_v1(project_root=root,
                    receipt_path=outputs["container_receipt"], expected_descriptor=capture.container_receipt_descriptor,
                    process_receipt_path=outputs["process_receipt"], expected_process_descriptor=capture.receipt_descriptor,
                    operation_id=operation_id, original_operation_descriptor=held["original_operation_descriptor"],
                    native_context_descriptor=held["native_context_descriptor"], expected_container_image=held["container_image"])
                cold.hold_validated_inputs(original_custody, engine_descriptor=held["engine_descriptor"])
                _require(original_custody["container_quiescence_verified"] is True,
                    "original diagnostic container terminal is unverified")
                _require(set(custody.list_directory_names(directory, label="original diagnostic child namespace"))
                    == set(pilot.CHILD_EVIDENCE_FILES), "original diagnostic child namespace drifted")
                for name in pilot.CHILD_EVIDENCE_FILES:
                    info = (directory / name).lstat()
                    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                        "original diagnostic child evidence is not single-link regular bytes")
                pilot._validate_request(held["request"], inputs=held["inputs"], cell=cell, output_dir=directory)
                pilot._validate_pending_candidate(directory / "checkpoint_publication_candidate.json", root=root, cell=cell)
                hardware = _descriptor(custody, root, hardware_path, 1024 * 1024 * 1024)
                _require(hardware["size_bytes"] > 0, "original diagnostic hardware evidence is empty")
                pilot._commit_file_noreplace(hardware_path, directory / pilot.HARDWARE_EVIDENCE_FILENAME)
                acceptance = finalize_checkpoint_qualification_pilot_acceptance_v1(**held["finalizer_kwargs"])
                _require(type(acceptance) is dict, "original diagnostic stock finalizer returned invalid data")
                pilot._validate_final_namespace(directory, root=root, cell=cell,
                    expected_operational_binding=pilot._expected_operational_binding(
                        inputs=held["inputs"], operational=held["operational"], cell=cell))
                validate_checkpoint_qualification_pilot_acceptance_v1(project_root=root,
                    acceptance_path=directory / pilot.ACCEPTANCE_FILENAME, expected_system=cell.system,
                    expected_resource=cell.resource, expected_codec=cell.codec, expected_topology_kind=cell.topology_kind,
                    expected_run_id=cell.run_id, expected_arm_id=cell.arm_id)
                held["execution_barrier"]()
                _require(type(original_custody["validated_inputs"]) is list and bool(original_custody["validated_inputs"]),
                    "original diagnostic physical custody witnesses are missing")
                cold.verify()
                references = {"native_domain": _descriptor(custody, root, outputs["native_domain"], 64 * 1024 * 1024),
                    "process_receipt": copy.deepcopy(capture.receipt_descriptor),
                    "container_receipt": copy.deepcopy(capture.container_receipt_descriptor),
                    "hardware": _descriptor(custody, root, directory / pilot.HARDWARE_EVIDENCE_FILENAME, 1024 * 1024 * 1024),
                    "qualification_acceptance": _descriptor(custody, root, directory / pilot.ACCEPTANCE_FILENAME, 1024 * 1024)}
                receipt = payload_with_sha256_v1({"schema_version": 1,
                    "artifact_kind": "vast_original_native_diagnostic_execution_v1", "operation_id": operation_id,
                    "original_operation": held["original_operation_descriptor"], "native_context": held["native_context_descriptor"],
                    "container_image": held["container_image"], "outputs": references,
                    "started_at_ns": started, "finished_at_ns": time.time_ns(), "status": "complete_original_native_diagnostic",
                    "accepted": False, "publication_ready": False, "authorization_eligible": False,
                    "blockers": ["diagnostic_operation_is_not_full_qualification_or_publication"]})
                raw = canonical_json_v1(receipt) + b"\n"
                _require(len(raw) <= MAX_RECEIPT_BYTES, "original diagnostic receipt exceeds byte bound")
                descriptor = custody.write_exclusive(receipt_path, raw, label="original diagnostic nonpromoting receipt",
                    create_parents=False)
                descriptor["path"] = str(root / descriptor["path"])
                cold.verify()
                custody.verify()
                return {"descriptor": descriptor, "receipt": receipt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--capture-plan-path", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    for name in INPUT_ARGUMENTS:
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    try:
        result = execute_native_diagnostic_operation_v1(**vars(parser.parse_args(argv)))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(78, "original native diagnostic failed: " + str(error) + "\n")
    print(json.dumps(result["descriptor"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
