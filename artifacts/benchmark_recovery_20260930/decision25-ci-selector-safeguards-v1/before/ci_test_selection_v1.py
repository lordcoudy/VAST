"""Explicit individual integration obligations; every other discovered case is portable."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import unittest

MANIFEST = ".ci/integration-test-selection.v1.json"
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
))
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
        if name.split(".", 1)[0] in {"test_checkpoint_analytics_execution_client_cpp", "test_backend_publication_process_supervisor_v3", "test_ci_external_test_observer_v1", "test_run_ci_checks", "test_ci_test_selection_v1"}:
            raise ValueError("mandatory contract cannot be skipped: " + name)
        if (not isinstance(row.get("reason"), str) or not row["reason"].strip()
                        or row.get("acceptance_claim") is not False
                        or row.get("classification") not in {"platform_or_explicit_physical_prerequisite", "existing_retired_schema_migration"}):
            raise ValueError("invalid explicit portable skip declaration: " + name)
        if row["classification"] == "existing_retired_schema_migration":
            case = next(case for case in cases if case.id() == name)
            if (not getattr(type(case), "__unittest_skip__", False)
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
