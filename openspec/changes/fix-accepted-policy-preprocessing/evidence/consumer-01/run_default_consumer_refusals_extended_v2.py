#!/usr/bin/env python3
"""Review-gated additive A-D refusals; never campaign or accepted authority."""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback


BASELINE_HELPER_SHA256 = "7ed86a2721371ba4f9c362dc66ceee5127d068ca0f50589ad2071a02758433df"
PROMOTION_DRIFT = "official candidate to accepted policy promotion validation drifted"
COVERAGE_DRIFT = "accepted policy measured coverage keys/types/minima drifted"
PARITY_DRIFT = "guardian preprocessing model-parity acceptance binding drifted"
ROLE_FILES = {
    "checkpoint_acceptance": "checkpoint_qualification_pilot_acceptance.json",
    "policy_decisions_jsonl": "publication_policy_decisions.jsonl",
    "resource_intervals": "resource_intervals.csv",
    "ingress_ledger": "ingress_ledger.csv",
    "topology_events": "topology_events.csv",
    "frames": "frames.csv",
    "frame_events": "frame_events.csv",
    "branch_terminals": "branch_terminals.csv",
}
A_CASES = (
    "count-bool", "count-string", "count-fraction", "coverage-missing-key", "coverage-extra-key",
    "binding-count31", "pilot-count31", "branch-minimum29", "count3839", "calibration-missing-system",
    "calibration-extra-system", "calibration-missing-branch", "calibration-extra-branch",
    "calibration-missing-resource", "calibration-extra-resource", "aggregate-bool", "aggregate-string",
    "aggregate-fraction", "aggregate119-with-compensation", "declared-total-disagreement",
    "fresh-assessment-count-disagreement", "fresh-assessment-calibration-disagreement",
)
B_CASES = ("missing-pilot", "duplicate-pilot", "unknown-pilot", "fresh29-cell")
C_CASES = (
    "completed-gpu-no-transfer", "dropped-original-reconstruction", "dropped-replay-output",
    "dropped-native-event-duplicate", "duplicate-csv-decision",
    "duplicate-jsonl-decision", "dropped-trace-linkage", "dropped-terminal-missing", "dropped-ingress-missing",
    "reset-missing", "reset-malformed", "reset-five-streams", "native-stale-descriptor",
)
D_CASES = ("stale-v4-binding-identity", "stale-v4-cpu-probe", "stale-v4-gpu-probe")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _write(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
    path.chmod(0o444)


def _json(path: Path, value: object) -> None:
    _write(path, _canonical(value) + b"\n")


def _read(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if type(value) is not dict:
        raise ValueError("expected a physical JSON object: " + str(path))
    return value


def _rehash(value: dict, field: str) -> dict:
    value = copy.deepcopy(value)
    value.pop(field, None)
    return {**value, field: hashlib.sha256(_canonical(value)).hexdigest()}


def _descriptor(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def _load_baseline(path: Path):
    if path.resolve(strict=True) != path or hashlib.sha256(path.read_bytes()).hexdigest() != BASELINE_HELPER_SHA256:
        raise ValueError("sealed baseline helper bytes or physical origin drifted")
    spec = importlib.util.spec_from_file_location("reviewed_consumer_refusals_baseline_v1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_source_proof(root: Path, directory: Path, name: str) -> dict:
    program = (
        "import json,sys; from pathlib import Path; root=Path(" + repr(str(root)) + "); "
        "sys.path.insert(0,str(root/'scripts')); import run_ci_checks as ci; "
        "paths=ci.tracked_paths(root); ci.verify_committed_bytes(root,paths); "
        "print(json.dumps({'raw_committed_bytes_verified':True,'tracked_path_count':len(paths),"
        "'verifier_path':ci.__file__},sort_keys=True))"
    )
    environment = dict(os.environ, TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    command = [sys.executable, "-B", "-c", program]
    started = _utc()
    child = subprocess.run(command, cwd=root, env=environment, capture_output=True, check=False)
    _write(directory / ("raw-source-" + name + ".stdout.raw"), child.stdout)
    _write(directory / ("raw-source-" + name + ".stderr.raw"), child.stderr)
    result = {"command": command, "cwd": str(root), "started_utc": started, "finished_utc": _utc(),
              "original_exit_code": child.returncode, "stdout_sha256": hashlib.sha256(child.stdout).hexdigest(),
              "stderr_sha256": hashlib.sha256(child.stderr).hexdigest(), "proof_validated": False}
    if child.returncode == 0:
        try:
            proof = json.loads(child.stdout)
            result["proof"] = proof
            result["proof_validated"] = (type(proof) is dict and proof.get("raw_committed_bytes_verified") is True
                                         and proof.get("verifier_path") == str(root / "scripts/run_ci_checks.py"))
        except (ValueError, UnicodeError) as error:
            result["validation_error"] = str(error)
    _json(directory / ("raw-source-" + name + ".result.v1.json"), result)
    return result


def _accepted_derivative(*, root: Path, directory: Path, source: dict, index_path: Path,
                         mutation=None, capability: dict | None = None, calibration: dict | None = None) -> dict:
    directory.mkdir()
    accepted = _read(source["accepted_policy_qualification_receipt_path"])
    capability = copy.deepcopy(capability if capability is not None else _read(source["accepted_policy_capability_manifest_path"]))
    calibration = copy.deepcopy(calibration if calibration is not None else _read(source["accepted_policy_calibration_mapping_path"]))
    if mutation is not None:
        mutation(accepted, calibration)
    receipt_path = directory / source["accepted_policy_qualification_receipt_path"].name
    capability_path = directory / source["accepted_policy_capability_manifest_path"].name
    calibration_path = directory / source["accepted_policy_calibration_mapping_path"].name
    _json(capability_path, capability)
    _json(calibration_path, calibration)
    accepted["qualification_index_sha256"] = _descriptor(root, index_path)["sha256"]
    accepted["outputs"] = {
        "capability_manifest": {**_descriptor(root, capability_path), "path": capability_path.name},
        "calibration_mapping": {**_descriptor(root, calibration_path), "path": calibration_path.name},
    }
    _json(receipt_path, _rehash(accepted, "sha256"))
    return {"accepted_policy_qualification_receipt_path": receipt_path,
            "accepted_policy_capability_manifest_path": capability_path,
            "accepted_policy_calibration_mapping_path": calibration_path,
            "completed_qualification_index_path": index_path}


def _cold_derivative(*, root: Path, directory: Path, fixture: dict, inputs: dict, guardian) -> dict:
    source = fixture["consumers"]["guardian"]
    receipt = _read(Path(source["receipt_path"]))
    if (_descriptor(root, inputs["execution_config_path"]) != receipt["execution_config"]
            or inputs["binding_set_dir"] != (root / receipt["binding_set_index"]["path"]).parent):
        raise ValueError("cold derivative execution config/binding directory differs from its genuine source")
    directory.mkdir()
    contract_path = directory / guardian.CONTRACT_FILENAME
    _write(contract_path, Path(source["contract_path"]).read_bytes())
    receipt["preprocessing_contract"] = _descriptor(root, contract_path)
    for argument, field in (
        ("qualification_preprocessing_contract_path", "predecessor_qualification_preprocessing_contract"),
        ("qualification_preprocessing_receipt_path", "predecessor_qualification_preprocessing_receipt"),
        ("completed_qualification_index_path", "qualification_index"),
        ("accepted_policy_qualification_receipt_path", "accepted_policy_qualification_receipt"),
        ("accepted_policy_capability_manifest_path", "accepted_policy_capability_manifest"),
        ("accepted_policy_calibration_mapping_path", "accepted_policy_calibration_mapping"),
    ):
        receipt[field] = _descriptor(root, inputs[argument])
    receipt["predecessor_qualification_preprocessing_receipt_identity_sha256"] = _read(inputs["qualification_preprocessing_receipt_path"])["receipt_sha256"]
    receipt["accepted_policy_qualification_receipt_identity_sha256"] = _read(inputs["accepted_policy_qualification_receipt_path"])["sha256"]
    receipt["accepted_policy_capability_manifest_content_sha256"] = hashlib.sha256(_canonical(_read(inputs["accepted_policy_capability_manifest_path"]))).hexdigest()
    receipt["accepted_policy_calibration_mapping_content_sha256"] = hashlib.sha256(_canonical(_read(inputs["accepted_policy_calibration_mapping_path"]))).hexdigest()
    receipt_path = directory / guardian.RECEIPT_FILENAME
    _json(receipt_path, _rehash(receipt, "receipt_sha256"))
    return {"project_root": root, "preprocessing_contract_path": contract_path,
            "materialization_receipt_path": receipt_path,
            "accepted_policy_capability_manifest_path": inputs["accepted_policy_capability_manifest_path"]}


def _csv_rows(raw: bytes) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""))
    return list(reader.fieldnames), list(reader)


def _csv_bytes(fields: list[str], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _reseal_projected_adversarial_record(record: dict) -> dict:
    """Rebind derivative commitments so real replay/uniqueness sees altered data."""
    projected = copy.deepcopy(record)
    metadata = projected["publication_projection"]
    original = copy.deepcopy(projected)
    original.pop("publication_projection")
    original["trace_id"] = original["request"]["trace_id"] = metadata["original_worker_trace_id"]
    original["decision_seq"] = original["request"]["decision_seq"] = metadata["original_runtime_decision_seq"]
    original = _rehash(original, "sha256")
    issued = copy.deepcopy(original)
    issued["record_status"] = "replayable_not_runtime_accepted"
    issued["native_decision_evidence"] = None
    issued = _rehash(issued, "sha256")
    metadata["accepted_record_sha256"] = original["sha256"]
    metadata["issued_record_sha256"] = issued["sha256"]
    return _rehash(projected, "sha256")


def _arm_derivative(*, root: Path, directory: Path, pilot: dict, mutation, full_resource_files: tuple,
                    stale_interval_descriptor: bool = False) -> dict:
    directory.mkdir()
    source_acceptance_path = root / pilot["evidence"]["checkpoint_acceptance"]["path"]
    acceptance = _read(source_acceptance_path)
    payloads = {filename: (source_acceptance_path.parent / filename).read_bytes()
                for filename in acceptance["evidence_sha256"]}
    original_interval = payloads["resource_intervals.csv"]
    mutation(payloads)
    for filename, payload in payloads.items():
        _write(directory / filename, payload)
    # Missing reset deliberately retains its real original hash and fails at physical evidence.
    acceptance["evidence_sha256"] = {
        filename: hashlib.sha256(payloads[filename]).hexdigest() if filename in payloads else old_sha
        for filename, old_sha in acceptance["evidence_sha256"].items()
    }
    acceptance["full_resource_evidence_sha256"] = {
        filename: acceptance["evidence_sha256"][filename] for filename in full_resource_files
    }
    acceptance_path = directory / source_acceptance_path.name
    _json(acceptance_path, _rehash(acceptance, "sha256"))
    altered = copy.deepcopy(pilot)
    altered["evidence"] = {role: _descriptor(root, directory / filename) for role, filename in ROLE_FILES.items()}
    if stale_interval_descriptor:
        altered["evidence"]["resource_intervals"].update(size_bytes=len(original_interval),
            sha256=hashlib.sha256(original_interval).hexdigest())
    return altered


def _plan() -> dict:
    return {"schema_version": 2, "cohort_A": A_CASES, "cohort_B": B_CASES,
            "cohort_C": C_CASES, "cohort_D": D_CASES,
            "default_materializer_and_cold_reader_per_case": True,
            "direct_component_predicates_retained_separately": True,
            "review_required": True, "campaign_authority": False,
            "limits": ["Requires two complete genuine positive reports and the fresh genuine29 F1 refusal report.",
                       "Copies and rehashed claims are adversarial inputs, not accepted original authority.",
                       "No assessment, acceptance, reset, dataset, fragment or custody validator substitution.",
                       "Direct F5/assessment predicates and full guardian refusals are different observed scopes.",
                       "No Q1, physical inference or126016-sample pilot replay is asserted."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe-cases", action="store_true")
    parser.add_argument("--project-root")
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--baseline-helper-path")
    parser.add_argument("--minimum-fixture")
    parser.add_argument("--larger-fixture")
    parser.add_argument("--per-cell-refusal-fixture")
    parser.add_argument("--output-dir")
    parser.add_argument("--reviewed-runner-sha256")
    parser.add_argument("--orchestration-clearance-confirmed", action="store_true")
    args = parser.parse_args()
    if args.describe_cases:
        print(json.dumps(_plan(), sort_keys=True))
        return 0
    required = (args.project_root, args.expected_source_commit, args.baseline_helper_path, args.minimum_fixture,
                args.larger_fixture, args.per_cell_refusal_fixture, args.output_dir, args.reviewed_runner_sha256)
    if any(value is None for value in required) or not args.orchestration_clearance_confirmed:
        parser.error("all frozen input arguments, reviewed helper hash and explicit scheduling clearance are required")
    root = Path(args.project_root)
    if (not root.is_absolute() or root.resolve(strict=True) != root or str(root) != os.path.normpath(str(root))
            or ".." in root.parts or re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) is None):
        raise ValueError("source root or expected commit is not exact physical canonical input")
    runner_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if re.fullmatch(r"[0-9a-f]{64}", args.reviewed_runner_sha256) is None or args.reviewed_runner_sha256 != runner_sha:
        raise ValueError("external recipe differs from its exact reviewed hash")
    baseline_path = Path(args.baseline_helper_path)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    baseline_path.relative_to(root)
    prior = _load_baseline(baseline_path)
    head, status = prior._git(root, "rev-parse", "HEAD"), prior._git(root, "status", "--porcelain=v1", "--untracked-files=no")
    if head.decode("ascii").strip() != args.expected_source_commit or status:
        raise ValueError("selected source is not the exact clean reviewed commit")
    minimum_dir = prior._physical_directory(root, args.minimum_fixture)
    larger_dir = prior._physical_directory(root, args.larger_fixture)
    refusal_dir = prior._physical_directory(root, args.per_cell_refusal_fixture)
    output = prior._physical_directory(root, args.output_dir, fresh=True)
    minimum, larger = prior._fixture(root, minimum_dir, 3840), prior._fixture(root, larger_dir, 3968)
    refusal = _read(refusal_dir / "per-cell-minimum-refusal-report.v1.json")
    if (any(report["source_commit"] != args.expected_source_commit for report in (minimum, larger, refusal))
            or any(report["consumers"]["fresh_interpreter_guardian_cold_reader"]["original_exit_code"] != 0
                   or report["consumers"]["fresh_interpreter_guardian_cold_reader"]["standalone_guardian_cold_reader_passed"] is not True
                   for report in (minimum, larger))
            or refusal.get("genuine_per_cell_minimum_refusal_asserted") is not True
            or refusal.get("complete_original_accounting_cold_validated") is not True
            or refusal.get("measured_sample_count") != 3960
            or refusal.get("default_guardian_refusal_asserted") is not False
            or len(refusal.get("measured_cells", [])) != 32):
        raise ValueError("genuine positive/fresh29 reports are incomplete or foreign")
    inventory_before = prior._input_inventory(root, (minimum_dir, larger_dir, refusal_dir))
    output.mkdir(mode=0o700)
    _write(output / "source-head.before.txt", head)
    _write(output / "source-tracked-status.before.txt", status)
    _json(output / "input-inventory.before.v2.json", inventory_before)
    _json(output / "case-plan.v2.json", {**_plan(), "source_commit": args.expected_source_commit,
                                      "runner_sha256": runner_sha, "started_utc": _utc()})
    before_raw = _raw_source_proof(root, output, "before")
    if not before_raw["proof_validated"]:
        raise ValueError("stock raw committed-byte proof failed before negative calls")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian
    from publication_policy_qualification import QualificationError
    from publication_policy_qualification_pilot_validation_v2 import policy_pilot_validator
    from publication_acceptance_evidence import FULL_RESOURCE_EVIDENCE_FILES
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.test_accepted_policy_f5_real_refusals import genuine_f5_context_v1
    base = prior._materializer_kwargs(root, minimum)
    original_index = _read(base["completed_qualification_index_path"])
    derivatives = output / "adversarial-derivatives"
    derivatives.mkdir()
    results = []

    def expected_refusal(name, scope, call, predicate, error_type, mutation):
        started = _utc()
        try:
            call()
        except error_type as error:
            if predicate not in str(error):
                raise AssertionError(f"{name} reached an unexpected {scope} predicate: {error}") from error
            result = {"name": name, "scope": scope, "started_utc": started, "finished_utc": _utc(),
                      "error_type": type(error).__name__, "error": str(error), "expected_predicate": predicate,
                      "mutation": mutation, "default_dependencies": True, "campaign_authority": False}
            _json(output / (name + "." + scope.replace(" ", "-") + ".result.v2.json"), result)
            results.append(result)
            print(json.dumps({"case": name, "scope": scope, "refusal_passed": True}, sort_keys=True), flush=True)
            return
        raise AssertionError(f"{name} unexpectedly passed its actual {scope}")

    def consumers(name, changes, predicate, mutation, source_base=None):
        inputs = {**(base if source_base is None else source_base), **changes}
        reserved_parent = output / ("must-remain-absent-" + name)
        namespace = reserved_parent / "guardian"
        if os.path.lexists(reserved_parent) or os.path.lexists(namespace):
            raise AssertionError("reserved materialization parent or leaf already exists")
        expected_refusal(name, "default materializer", lambda:
            guardian.materialize_accepted_policy_guardian_preprocessing_contract_v1(**inputs, output_dir=namespace),
            predicate, guardian.AcceptedPolicyGuardianPreprocessingContractV1Error, mutation)
        if os.path.lexists(reserved_parent) or os.path.lexists(namespace):
            raise AssertionError("refusing default materializer left its reserved parent or leaf")
        _json(output / (name + ".namespace-absence.v2.json"), {"parent": str(reserved_parent), "leaf": str(namespace),
              "parent_absent_before_and_after": True, "leaf_absent_before_and_after": True})
        cold = _cold_derivative(root=root, directory=derivatives / (name + "-cold"), fixture=minimum,
                                inputs=inputs, guardian=guardian)
        expected_refusal(name, "default cold reader", lambda:
            guardian.load_accepted_policy_guardian_preprocessing_contract_v1(**cold), predicate,
            guardian.AcceptedPolicyGuardianPreprocessingContractV1Error, mutation)

    try:
        system, branch, resource = guardian.SYSTEMS[0], guardian.BRANCHES[0], guardian.RESOURCES[0]
        def aggregate(calibration):
            return calibration["calibrations"][system]["costs"][branch][resource]
        for case in A_CASES:
            name = "A-" + case
            predicate = COVERAGE_DRIFT
            def mutate(receipt, calibration, case=case):
                coverage = receipt["coverage"]
                if case == "count-bool": coverage["accepted_sample_count"] = True
                elif case == "count-string": coverage["accepted_sample_count"] = str(coverage["accepted_sample_count"])
                elif case == "count-fraction": coverage["accepted_sample_count"] = coverage["accepted_sample_count"] + 0.5
                elif case == "coverage-missing-key": coverage.pop("minimum_samples_per_branch_cell")
                elif case == "coverage-extra-key": coverage["unexpected_fixture_key"] = 1
                elif case == "binding-count31": coverage["binding_count"] = 31
                elif case == "pilot-count31": coverage["pilot_cell_count"] = 31
                elif case == "branch-minimum29": coverage["minimum_samples_per_branch_cell"] = 29
                elif case == "count3839": coverage["accepted_sample_count"] = 3839
                elif case == "calibration-missing-system": calibration["calibrations"].pop(system)
                elif case == "calibration-extra-system": calibration["calibrations"]["foreign_fixture_system"] = copy.deepcopy(calibration["calibrations"][system])
                elif case == "calibration-missing-branch": calibration["calibrations"][system]["costs"].pop(branch)
                elif case == "calibration-extra-branch": calibration["calibrations"][system]["costs"]["foreign_fixture_branch"] = copy.deepcopy(calibration["calibrations"][system]["costs"][branch])
                elif case == "calibration-missing-resource": calibration["calibrations"][system]["costs"][branch].pop(resource)
                elif case == "calibration-extra-resource": calibration["calibrations"][system]["costs"][branch]["foreign_fixture_resource"] = copy.deepcopy(aggregate(calibration))
                elif case == "aggregate-bool": aggregate(calibration)["samples"] = True
                elif case == "aggregate-string": aggregate(calibration)["samples"] = str(aggregate(calibration)["samples"])
                elif case == "aggregate-fraction": aggregate(calibration)["samples"] = aggregate(calibration)["samples"] + 0.5
                elif case == "aggregate119-with-compensation":
                    difference = aggregate(calibration)["samples"] - 119
                    aggregate(calibration)["samples"] = 119
                    calibration["calibrations"][system]["costs"][branch][guardian.RESOURCES[1]]["samples"] += difference
                elif case == "declared-total-disagreement": coverage["accepted_sample_count"] += 1
                elif case == "fresh-assessment-count-disagreement":
                    for row in calibration["calibrations"].values():
                        for resources in row["costs"].values():
                            for value in resources.values(): value["samples"] += 4
                    coverage["accepted_sample_count"] += 128
                elif case == "fresh-assessment-calibration-disagreement": aggregate(calibration)["service_ms"] += 0.125
                else: raise AssertionError("unknown A case")
            if case in {"calibration-missing-system", "calibration-extra-system"}:
                predicate = "accepted policy calibration system coverage drifted"
            elif case in {"calibration-missing-branch", "calibration-extra-branch"}:
                predicate = "accepted policy calibration branch coverage drifted for " + system
            elif case in {"calibration-missing-resource", "calibration-extra-resource"}:
                predicate = f"accepted policy calibration resource coverage drifted for {system}/{branch}"
            elif case.startswith("aggregate"):
                predicate = f"accepted policy balanced calibration samples drifted for {system}/{branch}/{resource}"
            elif case == "declared-total-disagreement":
                predicate = "accepted policy measured coverage/calibration total drifted"
            elif case.startswith("fresh-assessment"):
                predicate = PROMOTION_DRIFT
            changes = _accepted_derivative(root=root, directory=derivatives / name, source=base,
                                           index_path=base["completed_qualification_index_path"], mutation=mutate)
            consumers(name, changes, predicate, {"cohort": "A", "operation": case,
                      "rebound": ["output byte descriptors", "accepted receipt self-hash"],
                      "original_index_and_all_original_accounting_unchanged": True})

        for case in B_CASES[:3]:
            name = "B-" + case
            index = copy.deepcopy(original_index)
            if case == "missing-pilot": index["pilots"].pop()
            elif case == "duplicate-pilot": index["pilots"][-1] = copy.deepcopy(index["pilots"][0])
            else: index["pilots"][-1]["codec"] = "foreign_fixture_codec"
            index_path = derivatives / (name + ".qualification-index.v2.json")
            _json(index_path, index)
            changes = _accepted_derivative(root=root, directory=derivatives / name, source=base, index_path=index_path)
            if case != "missing-pilot":
                assessment = guardian._default_assess_policy_qualification(project_root=root, index_path=index_path)
                coordinate = tuple(index["pilots"][-1][field] for field in ("system", "resource", "codec", "topology_kind"))
                blocker = "pilot_cell_set_mismatch: duplicate/unknown " + str(coordinate)
                if assessment.get("passed") is not False or assessment.get("blockers") != [blocker]:
                    raise AssertionError("actual default assessment did not reach exact pilot coordinate blocker")
                _json(output / (name + ".actual-default-assessment.v2.json"), assessment)
            consumers(name, changes, "completed qualification index drifted from its fragment-only bootstrap"
                      if case == "missing-pilot" else PROMOTION_DRIFT,
                      {"cohort": "B", "operation": case, "original_closure_and_transaction_unchanged": True})

        name = "B-fresh29-cell"
        underfilled_index_path = root / Path(refusal["completed_index"]).relative_to(root)
        underfilled_base = {**base, "qualification_preprocessing_contract_path": Path(refusal["preprocessing_contract"]),
            "qualification_preprocessing_receipt_path": Path(refusal["preprocessing_receipt"]),
            "completed_qualification_index_path": underfilled_index_path,
            "execution_config_path": Path(refusal["execution_config"]), "binding_set_dir": Path(refusal["binding_set_dir"])}
        underfilled_preprocessing = _read(underfilled_base["qualification_preprocessing_receipt_path"])
        underfilled_capability = _read(root / underfilled_preprocessing["candidate_manifest"]["path"])
        calibration = _read(base["accepted_policy_calibration_mapping_path"])
        for row in calibration["calibrations"].values():
            for resources in row["costs"].values():
                for value in resources.values(): value["samples"] = 0
        for cell in refusal["measured_cells"]:
            cell_system, cell_resource, _, _ = cell["coordinate"]
            for cell_branch, count in cell["branch_counts"].items():
                calibration["calibrations"][cell_system]["costs"][cell_branch][cell_resource]["samples"] += count
        changes = _accepted_derivative(root=root, directory=derivatives / name, source=base,
            index_path=underfilled_index_path, capability=underfilled_capability, calibration=calibration,
            mutation=lambda receipt, _calibration: receipt["coverage"].update(accepted_sample_count=3960))
        assessment = guardian._default_assess_policy_qualification(project_root=root, index_path=underfilled_index_path)
        if assessment.get("passed") is not False or assessment.get("blockers") != refusal["actual_f1_assessment"]["blockers"]:
            raise AssertionError("default assessor did not preserve the genuine fresh29 F1 blocker")
        _json(output / (name + ".actual-default-assessment.v2.json"), assessment)
        consumers(name, changes, PROMOTION_DRIFT, {"cohort": "B", "operation": "fresh29-cell",
            "measured_total": 3960, "fresh_original_accounting_preserved": True,
            "declared_accepted_triplet_is_adversarial_and_not_accepted": True}, source_base=underfilled_base)

        context, pilots = genuine_f5_context_v1(root, base["completed_qualification_index_path"])
        dropped = next(pilot for pilot in pilots if pilot["resource"] == "gpu"
                       and pilot["topology_kind"] == "independent_processes" and any(
            row["terminal_status"] == "drop" for row in _csv_rows((root / pilot["evidence"]["ingress_ledger"]["path"]).read_bytes())[1]))
        positive = next(pilot for pilot in pilots if pilot["resource"] == "gpu" and not any(
            row["terminal_status"] == "drop" for row in _csv_rows((root / pilot["evidence"]["ingress_ledger"]["path"]).read_bytes())[1]))
        unchanged_copy = _arm_derivative(root=root, directory=derivatives / "C-copy-viability", pilot=dropped,
                                        mutation=lambda _payloads: None, full_resource_files=FULL_RESOURCE_EVIDENCE_FILES)
        original_rows = policy_pilot_validator(dropped, context)
        copied_rows = policy_pilot_validator(unchanged_copy, context)
        if original_rows != copied_rows:
            raise AssertionError("unchanged arm copy changed actual F5 samples or upstream acceptance")
        _json(output / "C-copy-viability.v2.json", {"actual_upstream_acceptance": True,
              "actual_F5_sample_equality": True, "sample_count": len(copied_rows), "campaign_authority": False})
        for case in C_CASES:
            name = "C-" + case
            pilot = positive if case == "completed-gpu-no-transfer" else dropped
            source_arm = (root / pilot["evidence"]["checkpoint_acceptance"]["path"]).parent
            _, ingress_rows = _csv_rows((source_arm / "ingress_ledger.csv").read_bytes())
            drop_trace = next((row["trace_id"] for row in ingress_rows if row["terminal_status"] == "drop"), None)
            def mutate_arm(payloads, case=case, drop_trace=drop_trace):
                if case == "reset-missing": payloads.pop("reset_evidence.csv"); return
                if case in {"duplicate-jsonl-decision", "dropped-original-reconstruction", "dropped-replay-output",
                            "dropped-native-event-duplicate", "dropped-trace-linkage"}:
                    records = [json.loads(line) for line in payloads["publication_policy_decisions.jsonl"].splitlines()]
                    selected = next(record for record in records if record["trace_id"] == drop_trace)
                    if case == "duplicate-jsonl-decision": records.append(copy.deepcopy(selected))
                    elif case == "dropped-original-reconstruction":
                        selected["publication_projection"]["accepted_record_sha256"] = "0" * 64
                        selected.update(_rehash(selected, "sha256"))
                    elif case == "dropped-replay-output":
                        selected["reason"] = "adversarial-fixture-replay-output"
                        selected.update(_reseal_projected_adversarial_record(selected))
                    elif case == "dropped-native-event-duplicate":
                        other = next(record for record in records if record["trace_id"] != drop_trace)
                        selected["native_decision_evidence"]["event_id"] = other["native_decision_evidence"]["event_id"]
                        selected.update(_reseal_projected_adversarial_record(selected))
                    else:
                        selected["trace_id"] = "foreign-fixture-trace"
                        selected["request"]["trace_id"] = "foreign-fixture-trace"
                        selected.update(_rehash(selected, "sha256"))
                    payloads["publication_policy_decisions.jsonl"] = b"".join(_canonical(record) + b"\n" for record in records)
                    return
                filename = {"completed-gpu-no-transfer": "resource_intervals.csv",
                    "duplicate-csv-decision": "policy_decisions.csv", "dropped-terminal-missing": "branch_terminals.csv",
                    "dropped-ingress-missing": "ingress_ledger.csv", "reset-malformed": "reset_evidence.csv",
                    "reset-five-streams": "reset_evidence.csv", "native-stale-descriptor": "resource_intervals.csv"}[case]
                fields, rows = _csv_rows(payloads[filename])
                if case == "completed-gpu-no-transfer":
                    trace = next(row["trace_id"] for row in rows if row["component"] == "transfer")
                    rows = [row for row in rows if not (row["trace_id"] == trace and row["component"] == "transfer")]
                elif case == "duplicate-csv-decision":
                    selected = next(row for row in rows if row["trace_id"] == drop_trace)
                    rows[0]["decision_id"] = selected["decision_id"]
                elif case == "dropped-terminal-missing":
                    selected = next(row for row in rows if row["trace_id"] == drop_trace and row["terminal_status"] == "completed")
                    rows.remove(selected)
                elif case == "dropped-ingress-missing": rows = [row for row in rows if row["trace_id"] != drop_trace]
                elif case == "reset-malformed":
                    fields.remove("reset_provenance")
                    for row in rows: row.pop("reset_provenance")
                elif case == "reset-five-streams": rows = [row for row in rows if row["stream_id"] != "5"]
                else: rows[0]["bytes"] = str(int(rows[0]["bytes"]) + 1)
                payloads[filename] = _csv_bytes(fields, rows)
            altered_pilot = _arm_derivative(root=root, directory=derivatives / name, pilot=pilot,
                mutation=mutate_arm, full_resource_files=FULL_RESOURCE_EVIDENCE_FILES,
                stale_interval_descriptor=case == "native-stale-descriptor")
            expected = {
                "completed-gpu-no-transfer": "pilot sidecar revalidation failed: full resource evidence rejected: resource interval linkage coverage is incomplete",
                "dropped-original-reconstruction": "canonical policy projection rejected: original accepted hash mismatch",
                "dropped-replay-output": "canonical policy projection rejected: replayed decision does not match recorded output",
                "dropped-native-event-duplicate": "canonical policy projection rejected: duplicate publication original native event_id",
                "duplicate-csv-decision": "duplicate decision_id",
                "duplicate-jsonl-decision": "canonical/CSV native decision linkage drifted",
                "dropped-trace-linkage": "canonical/CSV native decision linkage drifted",
                "dropped-terminal-missing": "terminal ingress row does not cover every required branch",
                "dropped-ingress-missing": "native drop counter does not match ingress ledger",
                "reset-missing": "checkpoint acceptance is not a qualification pilot: qualification evidence reset_evidence.csv must exist under project_root",
                "reset-malformed": "reset_evidence.csv", "reset-five-streams": "reset process coverage differs; missing=",
                "native-stale-descriptor": "pilot resource_intervals artifact size/SHA drift",
            }[case]
            if case == "reset-malformed": expected = "missing or empty value for reset_provenance"
            mutation = {"cohort": "C", "operation": case, "copied_arm": str(source_arm),
                        "original_raw_inputs_unchanged": True, "substituted_validators": []}
            expected_refusal(name, "direct actual F5 component", lambda pilot=altered_pilot:
                policy_pilot_validator(pilot, context), expected, QualificationError, mutation)
            index = copy.deepcopy(original_index)
            coordinate = tuple(pilot[field] for field in ("system", "resource", "codec", "topology_kind"))
            positions = [position for position, row in enumerate(index["pilots"])
                         if tuple(row[field] for field in ("system", "resource", "codec", "topology_kind")) == coordinate]
            if len(positions) != 1: raise AssertionError("original pilot coordinate is not unique")
            index["pilots"][positions[0]] = altered_pilot
            index_path = derivatives / (name + ".qualification-index.v2.json")
            _json(index_path, index)
            changes = _accepted_derivative(root=root, directory=derivatives / (name + "-declared-accepted"),
                                           source=base, index_path=index_path)
            consumers(name, changes, PROMOTION_DRIFT, mutation)

        for case in D_CASES:
            name = "D-" + case
            directory = derivatives / name
            directory.mkdir()
            contract_path = directory / base["qualification_preprocessing_contract_path"].name
            _write(contract_path, base["qualification_preprocessing_contract_path"].read_bytes())
            receipt = _read(base["qualification_preprocessing_receipt_path"])
            receipt["preprocessing_contract"] = _descriptor(root, contract_path)
            if case == "stale-v4-binding-identity": receipt["model_parity_acceptance_binding_sha256"] = "0" * 64
            else:
                changed_resource = "cpu" if case == "stale-v4-cpu-probe" else "gpu"
                receipt["model_parity_refresh_authority"]["runtime_probes"][changed_resource]["sha256"] = "0" * 64
                receipt["model_parity_refresh_authority_sha256"] = hashlib.sha256(_canonical(receipt["model_parity_refresh_authority"])).hexdigest()
            receipt_path = directory / base["qualification_preprocessing_receipt_path"].name
            _json(receipt_path, _rehash(receipt, "receipt_sha256"))
            consumers(name, {"qualification_preprocessing_contract_path": contract_path,
                            "qualification_preprocessing_receipt_path": receipt_path}, PARITY_DRIFT,
                      {"cohort": "D", "operation": case, "actual_full_v4_upstream_reload": True,
                       "original_contract_transaction_candidate_parity_unchanged": True})
        expected_names = ["A-" + name for name in A_CASES] + ["B-" + name for name in B_CASES]
        expected_names += ["C-" + name for name in C_CASES] + ["D-" + name for name in D_CASES]
        materializer_names = [row["name"] for row in results if row["scope"] == "default materializer"]
        cold_names = [row["name"] for row in results if row["scope"] == "default cold reader"]
        if materializer_names != expected_names or cold_names != expected_names:
            raise AssertionError("actual case order or boundary set differs from the reviewed plan")
        final_sources = loaded_fixture_production_sources_v1(project_root=root)
        _json(output / "loaded-production-source-provenance.v2.json", final_sources)
    except BaseException as error:
        _json(output / "original-failure.v2.json", {"error_type": type(error).__name__, "error": str(error),
              "traceback": traceback.format_exc(), "finished_utc": _utc(), "completed_results": results,
              "passed": False, "campaign_authority": False})
        raise
    finally:
        inventory_after = prior._input_inventory(root, (minimum_dir, larger_dir, refusal_dir))
        final_head = prior._git(root, "rev-parse", "HEAD")
        final_status = prior._git(root, "status", "--porcelain=v1", "--untracked-files=no")
        _json(output / "input-inventory.after.v2.json", inventory_after)
        _write(output / "source-head.after.txt", final_head)
        _write(output / "source-tracked-status.after.txt", final_status)
        after_raw = _raw_source_proof(root, output, "after")
        if inventory_after != inventory_before or final_head != head or final_status != status or not after_raw["proof_validated"]:
            raise AssertionError("negative checks changed original inputs or raw committed source")
    _json(output / "extended-default-consumer-refusals.v2.json", {"schema_version": 2, "passed": True,
          "source_commit": args.expected_source_commit, "runner_sha256": runner_sha, "finished_utc": _utc(),
          "cases": results, "retained_inputs_unchanged": True, "source_raw_before": before_raw,
          "source_raw_after": after_raw, "default_dependencies": True, "campaign_authority": False,
          "physical_inference_observed": False, "measured126016_pilot_replay_asserted": False})
    return 0


if __name__ == "__main__":
    sys.exit(main())
