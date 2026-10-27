"""Explicit physical-input fixture setup for accepted-policy consumer evidence.

This is deliberately not a discovered test: full-v4 and authenticated KPP
inputs must come from the freshly renewed repair root. Container commands
use one held artificial ELF boundary; all authority readers and builders
remain production defaults. No historical qualification arm is an input.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import csv
import io
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
from publication_physical_io_v1 import PhysicalRootCustodyV1, _file_identity
from tests.fixtures.accepted_policy_original_custody_fixture_v1 import prepare_original_fixture_engine_v1
from tests.fixtures.accepted_policy_original_custody_fixture_v1 import preflight_original_fixture_engine_v1
from tests.fixtures.accepted_policy_original_custody_fixture_v1 import capture_original_fixture_operation_v1
from tests.fixtures.accepted_policy_native_fixture_v2 import (
    MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2, _FIXTURE_SIDECAR_SPECS_V2,
    write_native_policy_fixture_cell_v2,
)
from tests.fixtures.accepted_policy_fixture_report_v1 import fixture_report_bytes_v1
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as fixture_admission


STOCK_EQUIVALENCE_GPU_COORDINATE_V2 = ("gstreamer_custom", "gpu", "h264", "independent_processes")


class _FixtureCapturedEngineErrorV2(ValueError):
    def __init__(self, primary, secondary):
        super().__init__("fixture captured engine failed; distinct causes retained")
        self.primary, self.secondary = primary, tuple(secondary)


class _FixturePreparationCleanupErrorV2(ValueError):
    def __init__(self, primary, secondary):
        super().__init__("fixture preparation failed; distinct cleanup causes retained")
        self.primary, self.secondary = primary, tuple(secondary)


@contextmanager
def _held_fixture_captured_engine_v2(path, preparation_absolute_deadline_ns):
    """Stream-hash the fixed captured ELF and lend one explicitly owned raw FD."""
    custody, fd, before = None, -1, None
    primary, secondary = None, []

    def retain(error):
        nonlocal primary
        if primary is None:
            primary = error
        elif error is not primary and not any(error is previous for previous in secondary):
            secondary.append(error)

    def verify_pin():
        if (_file_identity(before) != _file_identity(os.fstat(fd))
                or _file_identity(before) != _file_identity(path.lstat())):
            raise ValueError("fixture captured engine identity changed")
        custody.verify()

    try:
        fixture_admission._compiler_preparation_clock_v1(preparation_absolute_deadline_ns)
        custody = PhysicalRootCustodyV1.open(path.parent, label="fixture captured engine")
        before = path.lstat()
        descriptor, _, inode = custody.read_descriptor_identity(path,
            label="fixture captured engine", maximum=16 * 1024**2, capture=False)
        fixture_admission._compiler_preparation_clock_v1(preparation_absolute_deadline_ns)
        if inode != (before.st_dev, before.st_ino) or descriptor["size_bytes"] != before.st_size:
            raise ValueError("fixture captured engine identity disagrees with hash")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        verify_pin()
        fixture_admission._compiler_preparation_clock_v1(preparation_absolute_deadline_ns)
        yield SimpleNamespace(path=path, fd=fd, size=descriptor["size_bytes"],
            sha256=descriptor["sha256"], proc_path=f"/proc/self/fd/{fd}")
    except BaseException as error:
        retain(error)
    finally:
        if fd >= 0:
            try:
                verify_pin()
            except BaseException as error:
                retain(error)
            try:
                os.close(fd)
            except BaseException as error:
                retain(error)
        if custody is not None:
            try:
                custody.close()
            except BaseException as error:
                retain(error)
    if primary is not None:
        if secondary:
            raise _FixtureCapturedEngineErrorV2(primary, secondary) from primary
        raise primary


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
        with PhysicalRootCustodyV1.open(identity_patch_path.parent, label="fixture image patch") as custody:
            _, payload = custody.read_descriptor(identity_patch_path, label="fixture image patch",
                maximum=16 * 1024**2, capture=True)
            custody.verify()
        patch_systems = json.loads(payload)["systems"]
        del payload
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
    compiler_qualification=None,
    compiler_admission=None,
    compiler_absolute_deadline_ns=None,
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
    preflight_original_fixture_engine_v1(project_root=root, output_dir=output / "command-boundary",
        image_inspections=inspection_aliases, device_probes=probe_replies,
        compiler_qualification=compiler_qualification, compiler_admission=compiler_admission,
        compiler_absolute_deadline_ns=compiler_absolute_deadline_ns)
    fixture_admission._compiler_preparation_clock_v1(compiler_absolute_deadline_ns)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    fixture_admission._compiler_preparation_clock_v1(compiler_absolute_deadline_ns)
    native_socket_root = Path(tempfile.mkdtemp(prefix=socket_prefix.removeprefix(".") + "-", dir="/var/tmp"))
    fixture_admission._compiler_preparation_clock_v1(compiler_absolute_deadline_ns)
    socket_dir = native_socket_root / "runtime"
    socket_dir.mkdir(mode=0o700, exist_ok=False)
    front_path = socket_dir / "analytics-execution.sock"
    control_path = socket_dir / "analytics-control.sock"
    engine_path = socket_dir / "engine.sock"
    for path in (front_path, control_path, engine_path):
        if path.exists() or path.is_symlink() or len(str(path).encode()) >= 108:
            raise ValueError("fixture socket reservation is occupied or exceeds AF_UNIX bound")
    fixture_admission._compiler_preparation_clock_v1(compiler_absolute_deadline_ns)
    front, control, primary = None, None, None
    secondary = []
    try:
        front = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        control = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        fixture_admission._compiler_preparation_clock_v1(compiler_absolute_deadline_ns)
        front.bind(str(front_path))
        front.listen(2)
        control.bind(str(control_path))
        with prepare_original_fixture_engine_v1(
            project_root=root, output_dir=output / "command-boundary",
            image_inspections=inspection_aliases, device_probes=probe_replies,
            socket_path=engine_path,
            compiler_qualification=compiler_qualification, compiler_admission=compiler_admission,
            compiler_absolute_deadline_ns=compiler_absolute_deadline_ns,
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
                with _held_fixture_captured_engine_v2(captured_engine_path,
                        compiler_absolute_deadline_ns) as captured_engine:
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
    except BaseException as error:
        primary = error
    finally:
        for owned in (front, control):
            if owned is None:
                continue
            try:
                owned.close()
            except BaseException as error:
                if primary is None:
                    primary = error
                elif error is not primary and not any(error is previous for previous in secondary):
                    secondary.append(error)
    if primary is not None:
        if secondary:
            raise _FixturePreparationCleanupErrorV2(primary, secondary) from primary
        raise primary


def _fixture_operation_sample_counts_v2(
    plan: Mapping[str, Any], *, samples_per_branch: int,
    qualification_samples_by_operation_id: Mapping[str, int] | None,
) -> dict[str, int]:
    if (type(samples_per_branch) is not int
            or not 30 <= samples_per_branch <= MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2):
        raise ValueError("complete fixture default sample count must be in 30..985")
    overrides = {} if qualification_samples_by_operation_id is None else qualification_samples_by_operation_id
    if type(overrides) is not dict or len(overrides) > 32:
        raise ValueError("mixed qualification sample counts require at most 32 explicit entries")
    operations = plan["operation_manifest"]["operations"]
    if type(operations) is not list or len(operations) != 37:
        raise ValueError("complete fixture requires exactly 37 operations")
    operation_ids = [row["operation_id"] for row in operations]
    qualification_ids = {row["operation_id"] for row in operations if row["phase"] == "qualification_cell"}
    if len(qualification_ids) != 32:
        raise ValueError("complete fixture requires exactly 32 qualification operations")
    if len(set(operation_ids)) != len(operation_ids) or not set(overrides).issubset(qualification_ids):
        raise ValueError("mixed sample counts must name unique existing qualification operations")
    if any(type(value) is not int or not 1 <= value <= MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2
           for value in overrides.values()):
        raise ValueError("mixed qualification sample counts must be in 1..985")
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
    capability_path = Path(prepared["transaction"]["candidate_manifest_path"])
    with PhysicalRootCustodyV1.open(capability_path.parent, label="fixture candidate capability") as custody:
        _, payload = custody.read_descriptor(capability_path, label="fixture candidate capability",
            maximum=16 * 1024**2, capture=True)
        custody.verify()
    capability = json.loads(payload)
    del payload
    contexts = {row["operation_id"]: row["descriptor"] for row in plan["index"]["native_contexts"]}
    operations = []
    domains = []
    for row in plan["operation_manifest"]["operations"]:
        original_path = Path(row["original_operation"]["path"])
        with PhysicalRootCustodyV1.open(original_path.parent, label="fixture original operation") as custody:
            _, payload = custody.read_descriptor(original_path, label="fixture original operation",
                maximum=1024**2, capture=True)
            custody.verify()
        original = json.loads(payload)
        del payload
        source_plan_path = Path(row["descriptors"]["source_plan"]["path"])
        with PhysicalRootCustodyV1.open(source_plan_path.parent, label="fixture source plan") as custody:
            _, payload = custody.read_descriptor(source_plan_path, label="fixture source plan",
                maximum=16 * 1024**2, capture=True)
            custody.verify()
        source_plan = json.loads(payload)
        del payload
        calibration_path = Path(row["descriptors"]["calibration"]["path"])
        with PhysicalRootCustodyV1.open(calibration_path.parent, label="fixture calibration") as custody:
            _, payload = custody.read_descriptor(calibration_path, label="fixture calibration",
                maximum=16 * 1024**2, capture=True)
            custody.verify()
        calibration = json.loads(payload)
        del payload
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
        native_path = producer_operational / "native_operational_requests.v1.jsonl"
        with PhysicalRootCustodyV1.open(producer_operational, label="fixture native payload") as custody:
            _, native_payload = custody.read_descriptor(native_path, label="fixture native payload",
                maximum=64 * 1024**2, capture=True)
            custody.verify()
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


def _fixture_finalization_table_v2(directory, filename):
    """Admit the two fixed finalization tables before pandas allocates them."""
    if filename not in ("frames.csv", "ingress_ledger.csv"):
        raise ValueError("unsupported fixture finalization table")
    columns, row_limit, row_bytes, file_limit = _FIXTURE_SIDECAR_SPECS_V2[filename]
    with PhysicalRootCustodyV1.open(directory, label="fixture finalization table") as custody:
        _, payload = custody.read_descriptor(directory / filename, label="fixture finalization table",
            maximum=file_limit, capture=True)
        custody.verify()
    reader = csv.reader(io.StringIO(payload.decode("ascii"), newline=""), strict=True)
    if next(reader, None) != list(columns):
        raise ValueError("fixture finalization CSV header drifted")
    count = 0
    for record in reader:
        if not record:
            continue
        count += 1
        if count > row_limit or len(record) != len(columns):
            raise ValueError("fixture finalization CSV row/column bound exceeded")
        upper = len(record) + sum(len(field) + field.count('"') + 2 for field in record)
        if upper > row_bytes:
            raise ValueError("fixture finalization CSV record bound exceeded")
    if count == 0:
        raise ValueError("fixture finalization CSV is empty")
    return pd.read_csv(io.BytesIO(payload), nrows=row_limit + 1)


def _fixture_finalization_hashes_v2(directory, policy):
    evidence = {}
    with PhysicalRootCustodyV1.open(directory, label="fixture finalization evidence") as custody:
        for name in _acceptance_evidence_files(policy):
            if name in _FIXTURE_SIDECAR_SPECS_V2:
                maximum = _FIXTURE_SIDECAR_SPECS_V2[name][3]
            elif name in ("policy_decisions.csv", "publication_policy_decisions.jsonl"):
                maximum = 64 * 1024**2
            else:
                raise ValueError("unsupported fixture finalization hash role")
            descriptor, _ = custody.read_descriptor(directory / name,
                label="fixture finalization evidence", maximum=maximum, capture=False)
            evidence[name] = descriptor["sha256"]
        custody.verify()
    return evidence


def finalize_fixture_qualification_cells_v2(*, prepared: Mapping[str, Any], native: Mapping[str, Any], guardian_authority_path: Path) -> list[dict[str, Any]]:
    """Run the default real pilot finalizer while the fixture guardian is live."""
    runtime_receipt_path = Path(prepared["runtime"]["receipt_path"])
    with PhysicalRootCustodyV1.open(runtime_receipt_path.parent, label="fixture runtime receipt") as custody:
        _, payload = custody.read_descriptor(runtime_receipt_path, label="fixture runtime receipt",
            maximum=64 * 1024**2, capture=True)
        custody.verify()
    runtime_receipt = json.loads(payload)
    del payload
    bundles = {record["arm_id"]: record for record in runtime_receipt["bundles"]}
    transaction = prepared["transaction"]
    result = []
    for item in native["operations"]:
        row = item["operation"]
        if row["phase"] != "qualification_cell":
            continue
        directory = Path(item["original"]["outputs"]["measurement_dir"])
        frames = _fixture_finalization_table_v2(directory, "frames.csv")
        ingress = _fixture_finalization_table_v2(directory, "ingress_ledger.csv")
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
            "evidence_sha256": _fixture_finalization_hashes_v2(directory, row["policy"]),
            "pending_full_resource_evidence": list(FULL_RESOURCE_EVIDENCE_FILES),
        }
        path = directory / "checkpoint_publication_candidate.json"
        candidate_raw = fixture_report_bytes_v1(candidate, limit=8192 - (len(os.linesep) - 1))
        with path.open("x", encoding="ascii") as stream:
            if stream.write(candidate_raw.decode("ascii")) != len(candidate_raw):
                raise OSError("fixture finalization candidate short write")
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
