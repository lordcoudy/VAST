"""Explicit individual integration obligations; every other discovered case is portable."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import unittest

MANIFEST = ".ci/integration-test-selection.v1.json"
# Current portable operation/ownership boundaries have no optional prerequisites.
# Keep this finite inventory explicit; newly discovered tests remain portable by default.
RUNTIME_SAFETY_MODULES = frozenset((
    "test_ci_namespace_diagnostic_v1",
    "test_ci_userns_profile_v1",
    "test_backend_publication_broker_terminal_v3",
    "test_backend_runtime_replay_handle_abi_authority_v1",
    "test_backend_runtime_replay_runner_authority_v2",
    "test_backend_runtime_replay_runner_authority_v3",
    "test_backend_runtime_replay_runner_invocation_v2",
    "test_backend_runtime_replay_runner_invocation_protocol_v3",
    "test_backend_runtime_replay_runner_invocation_protocol_v4",
    "test_checkpoint_native_policy_runtime",
    "test_checkpoint_native_policy_publication_projection_v1",
    "test_checkpoint_operational_admission_guard_v1",
    "test_publication_qualification_operational_owner_v1",
    "test_qualification_operational_closure_cold_gate_v1",
    "test_qualification_complete_operational_promotion_gate_v1",
    "test_publication_runtime_source_closure_guardian_v1",
    "test_publication_operational_boundary_v1",
    "test_publication_operational_capture_plan_v1",
    "test_publication_operational_container_custody_v1",
    "test_publication_operational_execution_binding_v1",
    "test_publication_operational_pilot_custody_v1",
    "test_publication_operational_process_custody_v1",
    "test_publication_operational_request_domain_v1",
    "test_publication_operational_runtime_context_v1",
    "test_publication_operational_runtime_input_binding_v1",
    "test_publication_operational_stock_operations_v1",
    "test_publication_operational_stock_request_v1",
    "test_publication_operational_wrapper_composition_v1",
    "test_publication_guardian_accepted_policy_preprocessing_contract_v1",
    "test_publication_guardian_capture_context_v1",
    "test_publication_guardian_component_preprocessing_contract_v1",
    "test_publication_guardian_operational_recorder_v1",
    "test_publication_guardian_preprocessing_contract_v1",
    "test_publication_guardian_runtime_expectations_v1",
    "test_publication_gstreamer_component_cli_v1",
    "test_publication_gstreamer_component_inputs_v1",
    "test_publication_gstreamer_component_runtime_v1",
))
# These production boundaries are always exercised by the portable lane.
MANDATORY_MODULES = frozenset((
    "test_checkpoint_analytics_execution_client_cpp",
    "test_backend_publication_process_supervisor_v3",
    "test_backend_publication_runtime_authority",
    "test_backend_runtime_validator_authority",
    "test_checkpoint_source_runtime_closure_authority_v1",
    "test_publication_policy_qualification_execution_code_closure_v1",
    "test_ci_external_test_observer_v1", "test_run_ci_checks", "test_ci_test_selection_v1",
    "test_replay_broker_contract_v4", "test_replay_broker_prepared_handles_v4",
    "test_replay_broker_artifact_bytes_observation_v4",
)) | RUNTIME_SAFETY_MODULES
# Only these original schema-v1 methods can retain the existing migration skip.
RETIRED_MIGRATION_IDS = frozenset(
    "test_checkpoint_model_parity.AssessmentTests." + method for method in (
        "test_calibration_and_evaluation_sample_ids_must_be_disjoint",
        "test_calibration_minimum_and_numeric_tolerances_are_enforced",
        "test_complete_common_source_contract_passes",
        "test_image_command_cannot_pull_or_run",
        "test_lineage_preprocessing_and_toolchain_drift_fail_closed",
        "test_non_finite_tolerance_is_rejected",
        "test_openvino_gpu_execution_evidence_is_not_cuda",
        "test_repository_state_is_honestly_blocked",
        "test_symlinked_model_artifact_is_not_accepted",
        "test_verified_equivalent_derivations_can_replace_a_local_source",
    )
)
EXACT_ID = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\.[A-Za-z_][A-Za-z_0-9]*\.test_[A-Za-z_0-9]+\Z")

def _cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _cases(item)
        elif isinstance(item, unittest.TestCase):
            yield item
        else:
            raise ValueError("discovered suite contains a non-test case")

def _identifier(row, label):
    name = row.get("test_id") if isinstance(row, dict) else None
    if not isinstance(name, str) or EXACT_ID.fullmatch(name) is None:
        raise ValueError(label + " must name an exact individual test method")
    return name

def select_portable_suite_v1(discovered_suite, *, project_root):
    """Partition the original case objects; no rediscovery, skipped fixture, or error filtering."""
    path = Path(project_root).resolve(strict=True) / MANIFEST
    raw = path.read_bytes()
    if len(raw) > 128 * 1024 or path.is_symlink():
        raise ValueError("selection manifest must be a bounded regular project file")
    document = json.loads(raw)
    if (document.get("schema_version") != 1 or document.get("kind") != "vast_ci_explicit_test_lanes_v1"
                    or document.get("default_lane") != "mandatory_portable"):
        raise ValueError("invalid explicit CI lane contract")
    cases = list(_cases(discovered_suite));names = [case.id() for case in cases]
    if len(names) != len(set(names)):
        raise ValueError("duplicate discovered test identity")
    known = set(names);integrations = {}
    rows = document.get("integration_declarations")
    if not isinstance(rows, list):
        raise ValueError("integration declarations must be a list")
    for row in rows:
        name = _identifier(row, "integration declaration")
        if name in integrations:
            raise ValueError("duplicate integration declaration: " + name)
        if name not in known:
            raise ValueError("integration declaration absent from discovery: " + name)
        if name.split(".", 1)[0] in MANDATORY_MODULES:
            raise ValueError("mandatory contract cannot be deferred: " + name)
        capabilities = row.get("required_capabilities")
        if (not isinstance(row.get("reason"), str) or not row["reason"].strip()
                        or not isinstance(capabilities, list) or not capabilities
                        or any(not isinstance(c, str) or not c.strip() for c in capabilities)):
            raise ValueError("integration declaration requires reason and capabilities")
        integrations[name] = row
    allowed = {};skip_rows = document.get("allowed_portable_skips")
    if not isinstance(skip_rows, list):
        raise ValueError("allowed portable skips must be a list")
    for row in skip_rows:
        name = _identifier(row, "portable skip declaration")
        if name in allowed:
            raise ValueError("duplicate portable skip declaration: " + name)
        if name not in known or name in integrations:
            raise ValueError("portable skip declaration absent from discovery/portable lane: " + name)
        # Platform-specific Windows custody methods remain discoverable on Linux.
        # Native execution and actual namespace/isolation tests never become optional.
        if name.split(".", 1)[0] in ({"test_checkpoint_analytics_execution_client_cpp", "test_backend_publication_process_supervisor_v3", "test_ci_external_test_observer_v1", "test_run_ci_checks", "test_ci_test_selection_v1"} | RUNTIME_SAFETY_MODULES):
            raise ValueError("mandatory contract cannot be skipped: " + name)
        if (not isinstance(row.get("reason"), str) or not row["reason"].strip()
                        or row.get("acceptance_claim") is not False
                        or row.get("classification") not in {"platform_or_explicit_physical_prerequisite", "existing_retired_schema_migration"}):
            raise ValueError("invalid explicit portable skip declaration: " + name)
        if row["classification"] == "existing_retired_schema_migration":
            case = next(case for case in cases if case.id() == name)
            if (name not in RETIRED_MIGRATION_IDS
                            or not getattr(type(case), "__unittest_skip__", False)
                            or getattr(type(case), "__unittest_skip_why__", None) != row["reason"]
                            or row["reason"] != "schema-v1 fixture retained only as migration history"):
                raise ValueError("retired declaration is not an existing source migration tombstone: " + name)
        allowed[name] = row
    portable = [case for case in cases if case.id() not in integrations]
    report = {"schema_version": 1, "manifest_path": MANIFEST,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(), "discovered_ids": sorted(names),
        "portable_ids": sorted(case.id() for case in portable),
        "integration_declarations": [integrations[n] for n in sorted(integrations)],
        "allowed_portable_skips": [allowed[n] for n in sorted(allowed)],
        "counts": {"discovered": len(cases), "portable": len(portable), "integration": len(integrations)},
        "integration_executed": False, "hardware_acceptance": False}
    return unittest.TestSuite(portable), report

def validate_portable_skips_v1(skipped, selection_report):
    """An audited nonexecution is never counted as a successful portable test."""
    allowed = {r["test_id"]: r for r in selection_report["allowed_portable_skips"]}
    audit = [];seen = set()
    for item in skipped:
        if isinstance(item, dict):
            name, reason = item.get("test_id"), item.get("reason")
        else:
            case, reason = item;name = case.id()
        if name in seen or name not in allowed or allowed[name]["reason"] != reason:
            raise ValueError("unapproved portable skip identity/reason: " + str(name))
        seen.add(name);audit.append(dict(allowed[name]))
    return sorted(audit, key=lambda row: row["test_id"])
