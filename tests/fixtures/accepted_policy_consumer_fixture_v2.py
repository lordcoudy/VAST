"""Complete artificial observations through unchanged production consumers.

Fresh physical full-v4 parity, authenticated KPP, image metadata and device
probes are prerequisites. Only original runtime/front observations are
artificial. Every acceptance, closure, fragment, F5 and guardian reader is
the selected project's actual implementation, without dependency overrides.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from checkpoint_gstreamer_analytics_sidecar import load_execution_config, load_materialized_binding_set
from publication_guardian_preprocessing_contract_v1 import load_guardian_preprocessing_contract_v1
from publication_guardian_runtime_expectations_v1 import runtime_expectations_from_preprocessing_receipt_v1
from publication_operational_request_domain_v1 import payload_with_sha256_v1
from publication_qualification_operational_owner_v1 import write_operational_execution_binding_v1
from publication_policy_qualification_execution_closure_v1 import (
    load_publication_policy_qualification_execution_closure_v1,
    materialize_publication_policy_qualification_execution_closure_v1,
)
from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
from tests.fixtures.accepted_policy_consumer_assertions_v1 import (
    check_fixture_measured_coverage_refusals_v1,
    run_approved_guardian_snapshot_red_v1,
    validate_fixture_identity_policy_component_v1,
)
from tests.fixtures.accepted_policy_guardian_journal_fixture_v1 import write_fixture_guardian_operational_journals_v1
from tests.fixtures.accepted_policy_guardian_lifecycle_fixture_v1 import begin_fixture_guardian_lifecycle_v1, finish_fixture_guardian_lifecycle_v1
from tests.fixtures.accepted_policy_physical_fixture_v2 import finalize_fixture_qualification_cells_v2
from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import run_fixture_standalone_guardian_cold_reader_v2


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _descriptor(root: Path, path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _write_fixture_operational_binding_v2(
    *, prepared: Mapping[str, Any], native: Mapping[str, Any], journals: Mapping[str, Any],
) -> Path:
    """Preserve original absolute descriptors at the stock binding boundary."""
    root, output = prepared["root"], prepared["output_dir"]
    outputs = []
    for item in native["operations"]:
        row, capture = item["operation"], item["capture"]
        directory = Path(item["original"]["outputs"]["measurement_dir"])
        decisions, ingress = directory / "publication_policy_decisions.jsonl", directory / "ingress_ledger.csv"
        outputs.append({"operation_id": row["operation_id"],
            **{name: dict(capture[name]) for name in ("native_domain", "process_receipt", "container_receipt")},
            "measurement_decisions": {**_descriptor(root, decisions), "path": str(decisions)},
            "accepted_ingress": {**_descriptor(root, ingress), "path": str(ingress)}})
    accounting_path = output / "original-operational-binding.v1.json"
    write_operational_execution_binding_v1(
        project_root=root, binding_path=accounting_path,
        mode="complete_qualification_operational_identity_v1",
        capture_plan=prepared["capture_plan_descriptor"], guardian_companion=journals["operational_group"],
        operation_outputs=outputs,
    )
    return accounting_path


def materialize_fixture_completed_execution_v2(
    *, prepared: Mapping[str, Any], native: Mapping[str, Any],
) -> dict[str, Any]:
    """Create real finalized evidence and a cold-validated complete closure."""
    from tests.fixtures.accepted_policy_checkpoint_fixture_v1 import write_complete_fixture_checkpoint_v1

    root, output = prepared["root"], prepared["output_dir"]
    transaction, preprocessing = prepared["transaction"], prepared["preprocessing"]
    loaded_preprocessing = load_guardian_preprocessing_contract_v1(
        project_root=root, preprocessing_contract_path=preprocessing["contract_path"],
        materialization_receipt_path=preprocessing["receipt_path"], candidate_manifest_path=transaction["candidate_manifest_path"],
    )
    refresh = loaded_preprocessing["receipt"]["model_parity_refresh_authority"]
    config_path = root / refresh["execution_config"]["path"]
    binding_dir = (root / refresh["binding_set"]["index"]["path"]).parent
    probes = {resource: _json(root / descriptor["path"]) for resource, descriptor in refresh["runtime_probes"].items()}
    materialized = load_materialized_binding_set(binding_dir, execution_config=load_execution_config(config_path), runtime_probes=probes)
    capabilities = {":".join(route): capability for route, capability in materialized.capabilities.items()}
    expectations = runtime_expectations_from_preprocessing_receipt_v1(loaded_preprocessing["receipt"])
    authority_path, lifecycle_path = output / "guardian-authority.v1.json", output / "guardian-lifecycle.v1.json"
    session = begin_fixture_guardian_lifecycle_v1(
        project_root=root, authority_path=authority_path, lifecycle_path=lifecycle_path,
        front_socket=prepared["front_socket"], control_socket=prepared["control_socket"],
        preprocessing_authority=loaded_preprocessing["authority"], runtime_expectations=expectations,
        route_capabilities=capabilities,
    )
    try:
        headers = copy.deepcopy(prepared["capture_plan"]["guardian_context"]["headers_by_route"])
        for route, header in headers.items():
            header.update(lifecycle_id=session.authority["lifecycle_id"], owner=session.owner_process, worker_capability=capabilities[route])
            header["descriptors"]["service_authority"] = {**session.authority_descriptor, "path": str(authority_path)}
            headers[route] = payload_with_sha256_v1(header)
        journals = write_fixture_guardian_operational_journals_v1(
            output_dir=prepared["guardian_output_dir"], headers_by_route=headers,
            native_domains=native["native_domains"], capability_manifest=native["capability_manifest"],
        )
        finalized = finalize_fixture_qualification_cells_v2(prepared=prepared, native=native, guardian_authority_path=authority_path)
        checkpoint = write_complete_fixture_checkpoint_v1(prepared=prepared, guardian_authority_path=authority_path)
        lifecycle = finish_fixture_guardian_lifecycle_v1(session, counters=journals["lifecycle_counters"], operational_group=journals["operational_group"])
    finally:
        session.close()
    from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
        load_accepted_policy_guardian_preprocessing_contract_v1,
        materialize_accepted_policy_guardian_preprocessing_contract_v1,
    )
    from publication_qualification_promotion_v2 import _fragment_validator
    from publication_policy_qualification import (
        CALIBRATION_MAPPING_FILENAME, CAPABILITY_MANIFEST_FILENAME, QUALIFICATION_RECEIPT_FILENAME,
        assess_policy_qualification, promote_policy_qualification,
    )
    from publication_policy_qualification_index_v2 import build_policy_qualification_index_v2
    from publication_policy_qualification_pilot_validation_v2 import policy_pilot_validator

    accounting_path = _write_fixture_operational_binding_v2(prepared=prepared, native=native, journals=journals)
    closure = materialize_publication_policy_qualification_execution_closure_v1(
        project_root=root, qualification_transaction_receipt_path=transaction["transaction_receipt_path"],
        preprocessing_contract_path=preprocessing["contract_path"], preprocessing_materialization_receipt_path=preprocessing["receipt_path"],
        runtime_input_materialization_receipt_path=prepared["runtime"]["receipt_path"], guardian_service_authority_path=authority_path,
        guardian_service_lifecycle_path=lifecycle_path, pilot_root=prepared["pilot_root"], checkpoint_path=checkpoint,
        output_dir=output / "complete-execution-closure", operational_accounting_binding_path=accounting_path,
    )
    independent_closure = load_publication_policy_qualification_execution_closure_v1(
        project_root=root, receipt_path=closure["receipt_path"], require_complete_operational_accounting=True,
    )
    if independent_closure["receipt"]["guardian"]["operational_accounting"]["original_operation_count"] != 37:
        raise ValueError("independent complete closure did not account for all 37 originals")
    completed = build_policy_qualification_index_v2(project_root=root, fragment_paths=transaction["fragment_paths"],
        pilot_root=prepared["pilot_root"], output_dir=output / "completed-policy-index", fragment_validator=_fragment_validator,
        execution_closure_receipt_path=closure["receipt_path"])
    index_path = completed["index_path"]
    return {"index_path": index_path, "execution_config_path": config_path, "binding_set_dir": binding_dir,
            "finalized": finalized, "journals": journals, "lifecycle": lifecycle, "closure": closure,
            "independent_closure": independent_closure}


def complete_fixture_production_consumers_v2(*, prepared: Mapping[str, Any], native: Mapping[str, Any],
                                           approved_guardian_source: bytes, approved_guardian_commit: str,
                                           standalone_reader_deadline: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Use actual live finalization and real stopped closure/F1/default guardian.

    The standalone reader runs only under the recipe's sealed deadline (Decision16).
    """
    chain = materialize_fixture_completed_execution_v2(prepared=prepared, native=native)
    root, output = prepared["root"], prepared["output_dir"]
    preprocessing = prepared["preprocessing"]
    index_path, config_path, binding_dir = chain["index_path"], chain["execution_config_path"], chain["binding_set_dir"]
    finalized, journals, lifecycle, closure = (chain[name] for name in ("finalized", "journals", "lifecycle", "closure"))
    from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
        load_accepted_policy_guardian_preprocessing_contract_v1,
        materialize_accepted_policy_guardian_preprocessing_contract_v1,
    )
    from publication_qualification_promotion_v2 import _fragment_validator
    from publication_policy_qualification import (
        CALIBRATION_MAPPING_FILENAME, CAPABILITY_MANIFEST_FILENAME, QUALIFICATION_RECEIPT_FILENAME,
        assess_policy_qualification, promote_policy_qualification,
    )
    from publication_policy_qualification_pilot_validation_v2 import policy_pilot_validator
    from tests.test_accepted_policy_f5_real_refusals import genuine_f5_context_v1, assert_genuine_f5_stock_samples_v1

    f5_context, f5_pilots = genuine_f5_context_v1(root, index_path)
    cpu_positive = next(pilot for pilot in f5_pilots if pilot["resource"] == "cpu")
    gpu_positive = next(pilot for pilot in f5_pilots if all(
        pilot[field] == value for field, value in native["stock_positive_gpu_coordinate"].items()
    ))
    stock_equality = [assert_genuine_f5_stock_samples_v1(pilot, f5_context) for pilot in (cpu_positive, gpu_positive)]
    assessment = assess_policy_qualification(project_root=root, index_path=index_path,
        pilot_validator=policy_pilot_validator, fragment_validator=_fragment_validator)
    if assessment.get("passed") is not True:
        raise ValueError(f"actual F1 policy assessor refused: {assessment}")
    promoted = promote_policy_qualification(project_root=root, index_path=index_path, output_dir=output / "accepted-policy",
        pilot_validator=policy_pilot_validator, fragment_validator=_fragment_validator)
    accepted_dir = output / "accepted-policy"
    guardian_kwargs = dict(
        project_root=root, qualification_preprocessing_contract_path=preprocessing["contract_path"],
        qualification_preprocessing_receipt_path=preprocessing["receipt_path"], completed_qualification_index_path=index_path,
        accepted_policy_qualification_receipt_path=accepted_dir / QUALIFICATION_RECEIPT_FILENAME,
        accepted_policy_capability_manifest_path=accepted_dir / CAPABILITY_MANIFEST_FILENAME,
        accepted_policy_calibration_mapping_path=accepted_dir / CALIBRATION_MAPPING_FILENAME,
        execution_config_path=config_path, binding_set_dir=binding_dir,
    )
    old_red = run_approved_guardian_snapshot_red_v1(
        approved_source=approved_guardian_source, approved_commit=approved_guardian_commit,
        materializer_kwargs={**guardian_kwargs, "output_dir": output / "old-approved-guardian-red"},
    )
    guardian = materialize_accepted_policy_guardian_preprocessing_contract_v1(
        **guardian_kwargs, output_dir=output / "accepted-policy-guardian",
    )
    cold_guardian = load_accepted_policy_guardian_preprocessing_contract_v1(
        project_root=root, preprocessing_contract_path=guardian["contract_path"],
        materialization_receipt_path=guardian["receipt_path"],
        accepted_policy_capability_manifest_path=accepted_dir / CAPABILITY_MANIFEST_FILENAME,
    )
    if cold_guardian["receipt"]["preprocessing_contract_content_sha256"] != guardian["preprocessing_contract_sha256"]:
        raise ValueError("independent accepted-policy guardian reader disagrees with materialized identity")
    standalone = run_fixture_standalone_guardian_cold_reader_v2(
        project_root=root, output_dir=output, guardian=guardian,
        accepted_capability_path=accepted_dir / CAPABILITY_MANIFEST_FILENAME,
        deadline=standalone_reader_deadline,
    )
    identity_policy = validate_fixture_identity_policy_component_v1(project_root=root, accepted_dir=accepted_dir)
    refusals = check_fixture_measured_coverage_refusals_v1(accepted_dir=accepted_dir)
    return {"campaign_authority": False, "physical_inference_observed": False, "finalized_cell_count": len(finalized),
            "journals": journals["operational_group"], "lifecycle": lifecycle["lifecycle_descriptor"], "execution_closure": str(closure["receipt_path"]),
            "completed_index": str(index_path), "assessment": assessment, "promotion": promoted, "guardian": guardian,
            "standalone_guardian_cold_reader_passed": True,
            "fresh_interpreter_guardian_cold_reader": standalone,
            "approved_old_default_red": old_red, "identity_policy_component": identity_policy,
            "measured_coverage_refusals": refusals,
            "genuine_cpu_gpu_stock_sample_equality": stock_equality,
            "dropped_gpu_qualification_cell_count": native["dropped_gpu_qualification_cell_count"],
            "loaded_production_sources": loaded_fixture_production_sources_v1(project_root=root)}
