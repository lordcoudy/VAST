"""Explicit physical-input fixture setup for accepted-policy consumer evidence.

This is deliberately not a discovered test: full-v4 and authenticated KPP
inputs must come from the freshly renewed repair root. Container commands
use one held artificial ELF boundary; all authority readers and builders
remain production defaults. No historical qualification arm is an input.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import re
import socket
import tempfile
from types import SimpleNamespace
from typing import Any, Mapping

import pandas as pd

from publication_guardian_preprocessing_contract_v1 import materialize_guardian_preprocessing_contract_v1
from publication_operational_capture_plan_v1 import held_operational_capture_plan_v1
from publication_operational_stock_operations_v1 import prepare_stock_operational_capture_plan_v1
from publication_policy_qualification_execution_code_closure_v1 import materialize_execution_code_closure_v1
from publication_policy_qualification_runtime_inputs_v2 import DOCKER_ASSET, materialize_publication_policy_qualification_runtime_inputs_v2
from publication_policy_qualification_transaction_v2 import materialize_publication_policy_qualification_transaction_v2
from checkpoint_admission import schedule_fingerprint_for_records
from checkpoint_publication_runtime import NATIVE_EXECUTION_BINDING_PROVENANCE, _acceptance_evidence_files
from checkpoint_qualification_pilot_acceptance_v1 import finalize_checkpoint_qualification_pilot_acceptance_v1
from publication_acceptance_evidence import FULL_RESOURCE_EVIDENCE_FILES
from tests.fixtures.accepted_policy_original_custody_fixture_v1 import prepare_original_fixture_engine_v1
from tests.fixtures.accepted_policy_original_custody_fixture_v1 import capture_original_fixture_operation_v1
from tests.fixtures.accepted_policy_native_fixture_v2 import write_native_policy_fixture_cell_v2


STOCK_EQUIVALENCE_GPU_COORDINATE_V2 = ("gstreamer_custom", "gpu", "h264", "independent_processes")


def _fixture_command_replies_v2(
    *, identity_patch_path: Path, image_inspections: Mapping[str, Any], device_probes: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(image_inspections) is not dict or type(device_probes) is not dict:
        raise ValueError("fixture command reply maps must be explicit objects")
    if not image_inspections and not device_probes:
        return {}, {}
    systems = {"openvino_gva", "gstreamer_custom"}
    if set(device_probes) != systems or any(type(value) is not dict for value in device_probes.values()):
        raise ValueError("fixture device probe map requires exactly two system objects")
    aliases = dict(image_inspections)
    for key, image in image_inspections.items():
        if (type(image) is not dict or type(key) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", key) is None or image.get("Id") != key):
            raise ValueError("captured fixture image key and Id must agree exactly")
        references = [key]
        for name in ("RepoTags", "RepoDigests"):
            values = image.get(name)
            if values is None:
                values = []
            if type(values) is not list or any(type(value) is not str or not value.isascii() or not value for value in values):
                raise ValueError("captured fixture image aliases are malformed")
            references.extend(values)
        for reference in references:
            previous = aliases.setdefault(reference, image)
            if previous != image:
                raise ValueError("captured image inspection aliases disagree")
    try:
        patch_systems = json.loads(identity_patch_path.read_bytes())["systems"]
        identities = {system: (
            patch_systems[system]["physical_identity"]["image_id"],
            patch_systems[system]["fragment_identity"]["image_id"],
        ) for system in systems}
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise ValueError("fixture device probe identity patch is malformed") from error
    replies = {}
    for system, (image_id, fragment_id) in identities.items():
        if (type(image_id) is not str or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
                or image_id != fragment_id):
            raise ValueError("fixture device probe physical and fragment image IDs disagree")
        if image_id not in image_inspections or image_inspections[image_id]["Id"] != image_id:
            raise ValueError("fixture device probe image is missing from captured inspections")
        if image_id in replies:
            raise ValueError("fixture device probe systems share one image ID")
        replies[image_id] = device_probes[system]
    return aliases, replies


@contextmanager
def prepared_complete_fixture_inputs_v2(
    *,
    project_root: Path,
    output_dir: Path,
    identity_patch_path: Path,
    accepted_model_parity_manifest_path: Path,
    accepted_model_parity_assessment_path: Path,
    accepted_model_parity_receipt_path: Path,
    image_inspections: Mapping[str, Any],
    device_probes: Mapping[str, Any],
    socket_prefix: str = ".apf01",
):
    """Hold a real cold-validated 37-operation plan and runtime input bundle."""
    root = project_root.resolve(strict=True)
    output = output_dir.absolute()
    if output.resolve(strict=False) != output or not output.is_relative_to(root) or output.exists():
        raise ValueError("explicit consumer fixture requires a fresh canonical project namespace")
    if not socket_prefix.startswith(".") or "/" in socket_prefix or len(socket_prefix) > 36:
        raise ValueError("fixture socket prefix is invalid")
    inspection_aliases, probe_replies = _fixture_command_replies_v2(
        identity_patch_path=identity_patch_path, image_inspections=image_inspections, device_probes=device_probes,
    )
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    native_socket_root = Path(tempfile.mkdtemp(prefix=socket_prefix.removeprefix(".") + "-", dir="/var/tmp"))
    socket_dir = native_socket_root / "runtime"
    socket_dir.mkdir(mode=0o700, exist_ok=False)
    front_path = socket_dir / "analytics-execution.sock"
    control_path = socket_dir / "analytics-control.sock"
    engine_path = socket_dir / "engine.sock"
    for path in (front_path, control_path, engine_path):
        if path.exists() or path.is_symlink() or len(str(path).encode()) >= 108:
            raise ValueError("fixture socket reservation is occupied or exceeds AF_UNIX bound")
    front = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    control = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        front.bind(str(front_path))
        front.listen(2)
        control.bind(str(control_path))
        with prepare_original_fixture_engine_v1(
            project_root=root, output_dir=output / "command-boundary",
            image_inspections=inspection_aliases, device_probes=probe_replies,
            socket_path=engine_path,
        ) as engine:
            transaction = materialize_publication_policy_qualification_transaction_v2(
                project_root=root, identity_patch_path=identity_patch_path,
                accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
                accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
                accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
                output_root=output / "qualification-transaction", docker=str(engine.engine.path),
            )
            preprocessing = materialize_guardian_preprocessing_contract_v1(
                project_root=root, qualification_transaction_receipt_path=transaction["transaction_receipt_path"],
                output_dir=output / "guardian-preprocessing",
            )
            closure_path = output / "execution-code-closure.v1.json"
            code_closure = materialize_execution_code_closure_v1(project_root=root, receipt_path=closure_path)
            pilot_root = output / "pilots"
            guardian_output = output / "guardian-journals"
            common = {key: transaction[key] for key in (
                "candidate_index_path", "candidate_manifest_path", "candidate_receipt_path",
                "bootstrap_mapping_path", "bootstrap_receipt_path", "bootstrap_dir", "transaction_receipt_path",
            )}
            capture = prepare_stock_operational_capture_plan_v1(
                project_root=root, output_dir=output / "operational-capture",
                mode="complete_qualification_operational_identity_v1", **common,
                preprocessing_contract_path=preprocessing["contract_path"],
                preprocessing_receipt_path=preprocessing["receipt_path"],
                execution_code_closure_path=closure_path, pilot_root=pilot_root,
                guardian_output_dir=guardian_output, container_engine_path=engine.engine.path,
                container_engine_socket_path=engine.engine_socket["path"],
            )
            with held_operational_capture_plan_v1(
                project_root=root, index_path=capture["descriptor"]["path"], expected_descriptor=capture["descriptor"],
            ) as held_plan:
                runtime = materialize_publication_policy_qualification_runtime_inputs_v2(
                    project_root=root, **common, container_engine_path=engine.engine.path,
                    container_engine_socket_path=engine.engine_socket["path"],
                    analytics_socket_path=front_path, scratch_root=output,
                    operational_capture_plan_path=capture["descriptor"]["path"],
                )
                # The materializer's two live transport probes do not exchange requests.
                front.setblocking(False)
                try:
                    for _ in range(2):
                        connection, _ = front.accept()
                        connection.close()
                finally:
                    front.setblocking(True)
                captured_engine_path = runtime["runtime_input_root"] / DOCKER_ASSET
                captured_engine_fd = os.open(captured_engine_path, os.O_RDONLY | os.O_NOFOLLOW)
                captured_engine_bytes = captured_engine_path.read_bytes()
                captured_engine = SimpleNamespace(path=captured_engine_path, fd=captured_engine_fd,
                    size=len(captured_engine_bytes), sha256=hashlib.sha256(captured_engine_bytes).hexdigest(),
                    proc_path=f"/proc/self/fd/{captured_engine_fd}")
                try:
                    yield {
                    "root": root, "output_dir": output, "engine": engine,
                    "capture_engine": captured_engine,
                    "front_socket": front, "control_socket": control,
                    "front_socket_path": front_path, "control_socket_path": control_path,
                    "native_socket_root": native_socket_root,
                    "transaction": transaction, "preprocessing": preprocessing,
                    "code_closure": code_closure, "code_closure_path": closure_path,
                    "capture_plan": held_plan, "capture_plan_descriptor": capture["descriptor"],
                    "runtime": runtime, "pilot_root": pilot_root, "guardian_output_dir": guardian_output,
                    "limits": {"campaign_authority": False, "physical_inference_observed": False,
                               "upstream": "fresh_physical_full_v4_and_authenticated_kpp",
                               "command_boundary": "held_artificial_elf_not_docker"},
                    }
                finally:
                    os.close(captured_engine_fd)
    finally:
        front.close()
        control.close()


def _fixture_operation_sample_counts_v2(
    plan: Mapping[str, Any], *, samples_per_branch: int,
    qualification_samples_by_operation_id: Mapping[str, int] | None,
) -> dict[str, int]:
    if type(samples_per_branch) is not int or samples_per_branch < 30:
        raise ValueError("complete fixture default requires at least 30 samples per branch")
    overrides = {} if qualification_samples_by_operation_id is None else qualification_samples_by_operation_id
    if type(overrides) is not dict:
        raise ValueError("mixed qualification sample counts must be an explicit object")
    operations = plan["operation_manifest"]["operations"]
    operation_ids = [row["operation_id"] for row in operations]
    qualification_ids = {row["operation_id"] for row in operations if row["phase"] == "qualification_cell"}
    if len(set(operation_ids)) != len(operation_ids) or not set(overrides).issubset(qualification_ids):
        raise ValueError("mixed sample counts must name unique existing qualification operations")
    if any(type(value) is not int or value < 1 for value in overrides.values()):
        raise ValueError("mixed qualification sample counts must be positive integers")
    return {operation_id: overrides.get(operation_id, samples_per_branch) for operation_id in operation_ids}


def build_original_native_fixture_observations_v2(
    *, prepared: Mapping[str, Any], samples_per_branch: int = 30,
    qualification_samples_by_operation_id: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Create all 37 originals and cold-validate real child/container custody."""
    root, output = prepared["root"], prepared["output_dir"]
    plan = prepared["capture_plan"]
    sample_counts = _fixture_operation_sample_counts_v2(
        plan, samples_per_branch=samples_per_branch,
        qualification_samples_by_operation_id=qualification_samples_by_operation_id,
    )
    capability = json.loads(Path(prepared["transaction"]["candidate_manifest_path"]).read_bytes())
    contexts = {row["operation_id"]: row["descriptor"] for row in plan["index"]["native_contexts"]}
    operations = []
    domains = []
    for row in plan["operation_manifest"]["operations"]:
        original = json.loads(Path(row["original_operation"]["path"]).read_bytes())
        source_plan = json.loads(Path(row["descriptors"]["source_plan"]["path"]).read_bytes())
        calibration = json.loads(Path(row["descriptors"]["calibration"]["path"]).read_bytes())
        native_context = plan["native_contexts_by_id"][row["operation_id"]]
        coordinate_resource = "cpu" if row["policy"] == "cpu_only" else "gpu"
        coordinate = (row["system"], coordinate_resource, row["codec"], source_plan["topology_kind"])
        stock_positive_gpu = row["phase"] == "qualification_cell" and coordinate == STOCK_EQUIVALENCE_GPU_COORDINATE_V2
        worker_ids = {(branch, worker["stream_id"]): worker["worker_id"]
                      for route, workers in row["front_workers_by_route"].items()
                      for branch, resource in [route.split(":")] if resource == coordinate_resource
                      for worker in workers}
        source_sha256 = {}
        for stream in source_plan["streams"]:
            sources = stream["workers"] if source_plan["topology_kind"] == "independent_processes" else [stream["graph_process"]]
            hashes = {source["source_sha256"] for source in sources}
            if len(hashes) != 1:
                raise ValueError("stock fixture stream source hashes disagree")
            source_sha256[int(stream["stream_id"])] = hashes.pop()
        directory = Path(original["outputs"]["measurement_dir"])
        producer_operational = output / "native-producer" / row["operation_id"]
        metadata = write_native_policy_fixture_cell_v2(
            output_dir=directory, capability=capability, system=row["system"], resource=coordinate_resource,
            codec=row["codec"], topology_kind=source_plan["topology_kind"],
            samples_per_branch=sample_counts[row["operation_id"]],
            dropped_ingress=coordinate_resource == "gpu" and not stock_positive_gpu,
            source_sha256_by_stream=source_sha256, run_id=row["run_id"], arm_id=row["arm_id"],
            calibration=calibration,
            operational_context={"header": native_context["native_header"], "output_dir": producer_operational},
            worker_ids_by_branch_stream=worker_ids,
            limits_path=output / "observation-limits" / f"{row['operation_id']}.json",
        )
        native_payload = (producer_operational / "native_operational_requests.v1.jsonl").read_bytes()
        capture = capture_original_fixture_operation_v1(
            project_root=root, operation_id=row["operation_id"], original_operation_descriptor=row["original_operation"],
            native_context_descriptor=contexts[row["operation_id"]], expected_container_image=original["container_image"],
            native_domain_payload=native_payload, engine=prepared["capture_engine"],
            engine_socket=prepared["engine"].engine_socket,
            scratch_dir=output / "child-scratch" / row["operation_id"],
            native_domain_output=Path(original["outputs"]["native_domain"]),
            process_receipt_output=Path(original["outputs"]["process_receipt"]),
            container_receipt_output=Path(original["outputs"]["container_receipt"]),
        )
        domains.append({"operation_id": row["operation_id"], "descriptor": capture["native_domain"]})
        operations.append({"operation": row, "original": original, "source_plan": source_plan,
                           "metadata": metadata, "capture": capture})
    if len(operations) != 37:
        raise ValueError("complete fixture lost a required original operation")
    positive_gpu = [item for item in operations if item["operation"]["phase"] == "qualification_cell"
                    and item["operation"]["policy"] == "gpu_only" and item["metadata"]["limits"]["dropped_ingress_frames"] == 0]
    dropped_gpu = [item for item in operations if item["operation"]["phase"] == "qualification_cell"
                   and item["operation"]["policy"] == "gpu_only" and item["metadata"]["limits"]["dropped_ingress_frames"] == 1]
    if len(positive_gpu) != 1 or len(dropped_gpu) != 15:
        raise ValueError("complete fixture must retain one stock-positive GPU cell and 15 dropped GPU cells")
    return {"operations": operations, "native_domains": domains, "capability_manifest": capability,
            "qualification_count": sum(item["operation"]["phase"] == "qualification_cell" for item in operations),
            "stock_positive_gpu_coordinate": dict(zip(("system", "resource", "codec", "topology_kind"), STOCK_EQUIVALENCE_GPU_COORDINATE_V2)),
            "dropped_gpu_qualification_cell_count": len(dropped_gpu),
            "campaign_authority": False, "physical_inference_observed": False}


def finalize_fixture_qualification_cells_v2(*, prepared: Mapping[str, Any], native: Mapping[str, Any], guardian_authority_path: Path) -> list[dict[str, Any]]:
    """Run the default real pilot finalizer while the fixture guardian is live."""
    runtime_receipt = json.loads(Path(prepared["runtime"]["receipt_path"]).read_bytes())
    bundles = {record["arm_id"]: record for record in runtime_receipt["bundles"]}
    transaction = prepared["transaction"]
    result = []
    for item in native["operations"]:
        row = item["operation"]
        if row["phase"] != "qualification_cell":
            continue
        directory = Path(item["original"]["outputs"]["measurement_dir"])
        frames = pd.read_csv(directory / "frames.csv")
        ingress = pd.read_csv(directory / "ingress_ledger.csv")
        fingerprint = schedule_fingerprint_for_records({**record, "sequence": record["admission_seq"]} for record in ingress.to_dict(orient="records"))
        candidate = {
            "schema_version": 2, "artifact_kind": "checkpoint_publication_runtime_candidate",
            "status": "pending_full_resource_validation", "run_id": row["run_id"],
            "system": row["system"], "scenario": row["scenario"], "codec": row["codec"],
            "policy": row["policy"], "deadline_ms": row["deadline_ms"],
            "execution_binding_provenance": NATIVE_EXECUTION_BINDING_PROVENANCE,
            "topology_kind": item["source_plan"]["topology_kind"], "cohort_id": str(ingress.iloc[0]["cohort_id"]),
            "measurement_schedule_fingerprint_sha256": fingerprint,
            "completed_frames_by_stream": {str(stream): int(count) for stream, count in frames.groupby("stream_id").size().items()},
            "summary": {"campaign_authority": False, "physical_inference_observed": False, "fixture_observations": True},
            "evidence_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in _acceptance_evidence_files(row["policy"])},
            "pending_full_resource_evidence": list(FULL_RESOURCE_EVIDENCE_FILES),
        }
        path = directory / "checkpoint_publication_candidate.json"
        with path.open("x", encoding="ascii") as stream:
            stream.write(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
        bundle_path = Path(prepared["runtime"]["receipt_path"]).parent / bundles[row["arm_id"]]["path"]
        calibration_path = Path(row["descriptors"]["calibration"]["path"])
        acceptance = finalize_checkpoint_qualification_pilot_acceptance_v1(
            project_root=prepared["root"], output_dir=directory, expected_run_id=row["run_id"],
            expected_arm_id=row["arm_id"], expected_system=row["system"],
            expected_resource="cpu" if row["policy"] == "cpu_only" else "gpu", expected_scenario=row["scenario"],
            expected_codec=row["codec"], expected_policy=row["policy"], expected_deadline_ms=row["deadline_ms"],
            topology_kind=item["source_plan"]["topology_kind"], hardware_collector_stopped=True,
            candidate_manifest_path=transaction["candidate_manifest_path"], candidate_receipt_path=transaction["candidate_receipt_path"],
            qualification_index_path=transaction["candidate_index_path"], bootstrap_mapping_path=transaction["bootstrap_mapping_path"],
            bootstrap_calibration_path=calibration_path, bootstrap_receipt_path=transaction["bootstrap_receipt_path"],
            qualification_transaction_receipt_path=transaction["transaction_receipt_path"],
            runtime_input_materialization_receipt_path=prepared["runtime"]["receipt_path"], runtime_input_bundle_path=bundle_path,
            guardian_service_authority_path=guardian_authority_path,
            preprocessing_contract_path=prepared["preprocessing"]["contract_path"],
            preprocessing_contract_receipt_path=prepared["preprocessing"]["receipt_path"],
        )
        result.append({"operation_id": row["operation_id"], "acceptance_sha256": acceptance["sha256"]})
    if len(result) != 32:
        raise ValueError("complete fixture finalizer did not accept exactly 32 cells")
    return result
