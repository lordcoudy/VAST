#!/usr/bin/env python3
"""Additive default-consumer refusals on completed artificial-observation fixtures."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types


APPROVED_COMMIT = "299c9c0eefb83fe3031096b0e96527236678a4d2"
GUARDIAN_SOURCE = "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"
CASE_PLAN = (
    ("old-standalone-default-red", "old default cold reader", "coverage or actual old default assessor refusal"),
    ("foreign-accepted-trio", "default materializer", "candidate to accepted qualification index promotion drifted"),
    ("foreign-accepted-capability", "default materializer", "accepted policy output namespace drifted"),
    ("candidate-as-accepted-capability", "default materializer", "accepted policy output namespace drifted"),
    ("wrong-bootstrap-index", "default materializer", "completed qualification index aliases the fragment-only bootstrap"),
    ("foreign-completed-index", "default materializer", "completed qualification index drifted from its fragment-only bootstrap"),
    ("foreign-complete-closure", "default materializer", "completed qualification closure cross-run transaction/preprocessing lineage drifted"),
    ("foreign-transaction", "default materializer", "guardian preprocessing transaction/contract binding drifted"),
    ("mutated-transaction-descriptor", "default materializer", "execution closure upstream chain drifted"),
    ("foreign-fragment-descriptor", "default materializer", "guardian preprocessing transaction/contract binding drifted"),
    ("mutated-fragment-descriptor", "default materializer", "qualification transaction deepstream fragment"),
    ("stale-runtime-descriptor", "default materializer", "execution closure upstream chain drifted"),
    ("missing-operational-accounting", "default materializer", "current qualification requires complete original operational accounting"),
    ("wrong-execution-config", "default materializer", "requested execution config differs from v4 parity authority"),
    ("wrong-parity-binding-directory", "default materializer", "requested binding-set directory differs from v4 parity authority"),
    ("unsafe-accepted-receipt-path", "default materializer", "accepted policy qualification receipt path is not canonical relative"),
    ("unsupported-accepted-receipt-kind", "default materializer", "accepted policy qualification receipt schema/status/coverage drifted"),
    ("unsupported-cold-guardian-kind", "default cold reader", "accepted-policy preprocessing receipt identity drifted"),
    ("foreign-cold-capability", "default cold reader", "requested accepted policy capability differs from materialization receipt"),
    ("f5-whole-arm-coordinate-mismatch", "direct unchanged F5 component", "qualification coordinate identity drift: system"),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _semantic_hash(value: dict, field: str) -> dict:
    value = copy.deepcopy(value)
    value.pop(field, None)
    return {**value, field: hashlib.sha256(_canonical(value)).hexdigest()}


def _write_fresh(path: Path, payload: bytes, *, readonly: bool = False) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
    if readonly:
        path.chmod(0o444)


def _write_json(path: Path, value: object, *, readonly: bool = False) -> None:
    _write_fresh(path, _canonical(value) + b"\n", readonly=readonly)


def _descriptor(root: Path, path: Path) -> dict:
    payload = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def _physical_directory(root: Path, value: str, *, fresh: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if ".." in path.parts or str(path) != os.path.normpath(str(path)) or path == root or not path.is_relative_to(root):
        raise ValueError("runner directory is not canonical beneath selected root")
    if fresh:
        if os.path.lexists(path) or path.parent.resolve(strict=True) != path.parent:
            raise ValueError("runner output is not a fresh canonical namespace")
    elif path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("runner input is not a physical canonical directory")
    return path


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout


def _fixture(root: Path, directory: Path, expected_count: int) -> dict:
    report = json.loads((directory / "producer-stage-report.v2.json").read_bytes())
    if (report.get("complete_consumer_positive_asserted") is not True or
            report.get("expected_measured_sample_count") != expected_count or
            report["consumers"]["assessment"]["coverage"]["accepted_sample_count"] != expected_count or
            report["upstream_root"] != str(root)):
        raise ValueError("negative checks require a complete genuine positive fixture of the expected count")
    return report


def _input_inventory(root: Path, directories: tuple[Path, ...]) -> list[dict]:
    result = []
    for directory in directories:
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("fixture contains an unexpected symlink")
            if path.is_file():
                result.append({**_descriptor(root, path), "mode": path.stat().st_mode & 0o777})
    return result


def _materializer_kwargs(root: Path, fixture: dict) -> dict:
    receipt_path = Path(fixture["consumers"]["guardian"]["receipt_path"])
    receipt = json.loads(receipt_path.read_bytes())
    fields = {"qualification_preprocessing_contract_path": "predecessor_qualification_preprocessing_contract",
              "qualification_preprocessing_receipt_path": "predecessor_qualification_preprocessing_receipt",
              "completed_qualification_index_path": "qualification_index",
              "accepted_policy_qualification_receipt_path": "accepted_policy_qualification_receipt",
              "accepted_policy_capability_manifest_path": "accepted_policy_capability_manifest",
              "accepted_policy_calibration_mapping_path": "accepted_policy_calibration_mapping",
              "execution_config_path": "execution_config"}
    return {"project_root": root, **{argument: root / receipt[field]["path"] for argument, field in fields.items()},
            "binding_set_dir": (root / receipt["binding_set_index"]["path"]).parent}


def _cold_kwargs(root: Path, fixture: dict, capability_path: Path) -> dict:
    guardian = fixture["consumers"]["guardian"]
    return {"project_root": root, "preprocessing_contract_path": Path(guardian["contract_path"]),
            "materialization_receipt_path": Path(guardian["receipt_path"]),
            "accepted_policy_capability_manifest_path": capability_path}


def _derivative_closure(root: Path, directory: Path, source_index: dict, source_closure_path: Path,
                        mutation, closure_module) -> Path:
    directory.mkdir()
    original = json.loads(source_closure_path.read_bytes())
    altered = copy.deepcopy(original)
    for field, filename in (("service_authority_snapshot", closure_module.AUTHORITY_SNAPSHOT_FILENAME),
                            ("service_lifecycle_snapshot", closure_module.LIFECYCLE_SNAPSHOT_FILENAME)):
        target = directory / filename
        _write_fresh(target, (root / original["guardian"][field]["path"]).read_bytes(), readonly=True)
        altered["guardian"][field] = _descriptor(root, target)
    mutation(altered)
    receipt_path = directory / closure_module.RECEIPT_FILENAME
    _write_json(receipt_path, _semantic_hash(altered, "receipt_sha256"), readonly=True)
    index = copy.deepcopy(source_index)
    index["qualification_execution_closure"] = _descriptor(root, receipt_path)
    index_path = directory.parent / (directory.name + ".qualification-index.v2.json")
    _write_json(index_path, index, readonly=True)
    return index_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe-cases", action="store_true")
    parser.add_argument("--project-root")
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--minimum-fixture")
    parser.add_argument("--larger-fixture")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    if args.describe_cases:
        print(json.dumps({"cases": CASE_PLAN, "campaign_authority": False}, sort_keys=True))
        return 0
    if any(value is None for value in (args.project_root, args.expected_source_commit, args.minimum_fixture,
                                      args.larger_fixture, args.output_dir)):
        parser.error("all frozen source and positive fixture arguments are required")
    root = Path(args.project_root)
    if not root.is_absolute() or root.resolve(strict=True) != root or str(root) != os.path.normpath(str(root)):
        raise ValueError("runner root must be an exact physical absolute path")
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) is None:
        raise ValueError("source commit must be an exact commit SHA")
    head, status = _git(root, "rev-parse", "HEAD"), _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    if head.decode("ascii").strip() != args.expected_source_commit or status:
        raise ValueError("selected source is not the exact clean reviewed commit")
    minimum_dir = _physical_directory(root, args.minimum_fixture)
    larger_dir = _physical_directory(root, args.larger_fixture)
    output = _physical_directory(root, args.output_dir, fresh=True)
    minimum, larger = _fixture(root, minimum_dir, 3840), _fixture(root, larger_dir, 3968)
    if any(fixture["source_commit"] != args.expected_source_commit for fixture in (minimum, larger)):
        raise ValueError("positive fixture source commit differs from selected source")
    initial_inventory = _input_inventory(root, (minimum_dir, larger_dir))
    output.mkdir()
    _write_fresh(output / "source-head.before.txt", head)
    _write_fresh(output / "source-tracked-status.before.txt", status)
    _write_json(output / "positive-fixture-inputs.before.v1.json", initial_inventory)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian
    import publication_policy_qualification_execution_closure_v1 as closure
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.test_accepted_policy_f5_real_refusals import genuine_f5_context_v1
    from publication_policy_qualification_pilot_validation_v2 import policy_pilot_validator
    from publication_policy_qualification import QualificationError

    base, foreign = _materializer_kwargs(root, minimum), _materializer_kwargs(root, larger)
    index_path = base["completed_qualification_index_path"]
    index = json.loads(index_path.read_bytes())
    foreign_index = json.loads(foreign["completed_qualification_index_path"].read_bytes())
    source_closure_path = root / index["qualification_execution_closure"]["path"]
    source_closure = json.loads(source_closure_path.read_bytes())
    foreign_closure = json.loads((root / foreign_index["qualification_execution_closure"]["path"]).read_bytes())
    derivatives = output / "fresh-adversarial-derivatives"
    derivatives.mkdir()
    results = []
    _write_json(output / "case-plan.v1.json", {"cases": CASE_PLAN, "source_commit": args.expected_source_commit,
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "default_dependencies": True, "campaign_authority": False,
                "limits": ["Fresh derivative artifacts are adversarial fixtures, never accepted authority.",
                           "Direct F5 component refusal is not a full guardian materializer refusal.",
                           "Old source snapshot is exact approved guardian code with actual default dependencies."]})

    def refuse(name, scope, call, expected, exception_type=guardian.AcceptedPolicyGuardianPreprocessingContractV1Error):
        namespace = output / "must-remain-absent" / name
        if os.path.lexists(namespace) or os.path.lexists(namespace.parent):
            raise AssertionError("refusal namespace or its reserved parent was occupied before the case")
        started = _utc()
        try:
            call(namespace)
        except exception_type as error:
            if not any(predicate in str(error) for predicate in expected):
                raise AssertionError("refusal stopped at an unexpected predicate: " + str(error)) from error
            result = {"name": name, "scope": scope, "started_utc": started, "finished_utc": _utc(),
                      "error_type": type(error).__name__, "error": str(error), "expected_predicates": expected,
                      "default_dependencies": True, "reserved_namespace": str(namespace),
                      "reserved_parent_namespace": str(namespace.parent),
                      "materialization_namespace_applicable": scope == "default materializer",
                      "namespace_absent": not os.path.lexists(namespace),
                      "parent_namespace_absent": not os.path.lexists(namespace.parent), "campaign_authority": False}
            if not result["namespace_absent"] or not result["parent_namespace_absent"]:
                raise AssertionError("refusing materializer left its fresh namespace or parent")
            _write_json(output / (name + ".result.v1.json"), result)
            results.append(result)
            print(json.dumps({"case": name, "refusal_passed": True, "scope": scope}, sort_keys=True), flush=True)
            return
        raise AssertionError("negative input unexpectedly passed: " + name)

    def materialize(name, changes, expected):
        refuse(name, "default materializer", lambda namespace: guardian.materialize_accepted_policy_guardian_preprocessing_contract_v1(
            **{**base, **changes, "output_dir": namespace}), expected)

    approved_source = _git(root, "show", APPROVED_COMMIT + ":" + GUARDIAN_SOURCE)
    snapshot_name = "fixture_approved_guardian_cold_snapshot_v1"
    if snapshot_name in sys.modules:
        raise ValueError("approved snapshot module name is occupied")
    snapshot = types.ModuleType(snapshot_name)
    sys.modules[snapshot_name] = snapshot
    try:
        exec(compile(approved_source, APPROVED_COMMIT + ":" + GUARDIAN_SOURCE, "exec"), snapshot.__dict__)
        refuse("old-standalone-default-red", "old default cold reader", lambda _namespace:
            snapshot.load_accepted_policy_guardian_preprocessing_contract_v1(**_cold_kwargs(
                root, minimum, base["accepted_policy_capability_manifest_path"])),
            ["coverage", "qualification assessor", "official candidate to accepted policy promotion validation drifted"],
            snapshot.AcceptedPolicyGuardianPreprocessingContractV1Error)
        results[-1].update(approved_commit=APPROVED_COMMIT,
                           approved_source_sha256=hashlib.sha256(approved_source).hexdigest())
        _write_json(output / "old-standalone-default-red.source.v1.json", results[-1])
    finally:
        sys.modules.pop(snapshot_name, None)

    accepted_fields = ("accepted_policy_qualification_receipt_path", "accepted_policy_capability_manifest_path",
                       "accepted_policy_calibration_mapping_path")
    materialize("foreign-accepted-trio", {field: foreign[field] for field in accepted_fields},
                ["candidate to accepted qualification index promotion drifted"])
    materialize("foreign-accepted-capability", {"accepted_policy_capability_manifest_path": foreign[accepted_fields[1]]},
                ["accepted policy output namespace drifted"])
    preprocessing_receipt = json.loads(base["qualification_preprocessing_receipt_path"].read_bytes())
    materialize("candidate-as-accepted-capability", {"accepted_policy_capability_manifest_path": root / preprocessing_receipt["candidate_manifest"]["path"]},
                ["accepted policy output namespace drifted"])
    materialize("wrong-bootstrap-index", {"completed_qualification_index_path": root / preprocessing_receipt["qualification_index"]["path"]},
                ["completed qualification index aliases the fragment-only bootstrap"])
    materialize("foreign-completed-index", {"completed_qualification_index_path": foreign["completed_qualification_index_path"]},
                ["completed qualification index drifted from its fragment-only bootstrap"])
    foreign_closure_index = copy.deepcopy(index)
    foreign_closure_index["qualification_execution_closure"] = foreign_index["qualification_execution_closure"]
    foreign_closure_index_path = derivatives / "foreign-closure.index.v2.json"
    _write_json(foreign_closure_index_path, foreign_closure_index, readonly=True)
    materialize("foreign-complete-closure", {"completed_qualification_index_path": foreign_closure_index_path},
                ["completed qualification closure cross-run transaction/preprocessing lineage drifted"])

    def altered_closure_case(name, mutation, expected):
        altered_index_path = _derivative_closure(root, derivatives / name, index, source_closure_path, mutation, closure)
        materialize(name, {"completed_qualification_index_path": altered_index_path}, expected)

    altered_closure_case("foreign-transaction", lambda value: value.update(
        qualification_input_transaction=copy.deepcopy(foreign_closure["qualification_input_transaction"])),
        ["guardian preprocessing transaction/contract binding drifted"])
    altered_closure_case("mutated-transaction-descriptor", lambda value:
        value["qualification_input_transaction"]["receipt"].update(sha256="0" * 64),
        ["execution closure upstream chain drifted"])
    transaction_path = root / source_closure["qualification_input_transaction"]["receipt"]["path"]
    original_transaction = json.loads(transaction_path.read_bytes())
    for name, fragment, predicate in (
        ("foreign-fragment-descriptor", foreign_closure["qualification_input_transaction"]["fragments"]["deepstream"],
         "guardian preprocessing transaction/contract binding drifted"),
        ("mutated-fragment-descriptor", {**original_transaction["fragments"]["deepstream"], "sha256": "0" * 64},
         "qualification transaction deepstream fragment")):
        altered_transaction = copy.deepcopy(original_transaction)
        altered_transaction["fragments"]["deepstream"] = copy.deepcopy(fragment)
        altered_transaction = _semantic_hash(altered_transaction, "receipt_sha256")
        altered_transaction_path = derivatives / (name + ".transaction.v2.json")
        _write_json(altered_transaction_path, altered_transaction, readonly=True)
        def bind_altered_transaction(value, path=altered_transaction_path, document=altered_transaction):
            value["qualification_input_transaction"].update(receipt=_descriptor(root, path), receipt_sha256=document["receipt_sha256"])
            value["qualification_input_transaction"]["fragments"]["deepstream"] = document["fragments"]["deepstream"]
        altered_closure_case(name, bind_altered_transaction, [predicate])
    altered_closure_case("stale-runtime-descriptor", lambda value:
        value["runtime_input_materialization"]["receipt"].update(sha256="0" * 64),
        ["execution closure upstream chain drifted"])
    altered_closure_case("missing-operational-accounting", lambda value: value["guardian"].pop("operational_accounting"),
                        ["current qualification requires complete original operational accounting"])
    materialize("wrong-execution-config", {"execution_config_path": root / "configs/analytics_execution_layer.v4.json"},
                ["requested execution config differs from v4 parity authority"])
    materialize("wrong-parity-binding-directory", {"binding_set_dir": base["binding_set_dir"].parent},
                ["requested binding-set directory differs from v4 parity authority"])
    real_receipt = base["accepted_policy_qualification_receipt_path"]
    relative_receipt = real_receipt.relative_to(root)
    unsafe_path = (relative_receipt.parent / ".." / relative_receipt.parent.name / relative_receipt.name).as_posix()
    materialize("unsafe-accepted-receipt-path", {"accepted_policy_qualification_receipt_path": unsafe_path},
                ["accepted policy qualification receipt path is not canonical relative"])
    unsupported_receipt = json.loads(real_receipt.read_bytes())
    unsupported_receipt["artifact_kind"] = "unsupported_fixture_kind"
    unsupported_receipt_path = derivatives / "unsupported-accepted-receipt.json"
    _write_json(unsupported_receipt_path, _semantic_hash(unsupported_receipt, "sha256"), readonly=True)
    materialize("unsupported-accepted-receipt-kind", {"accepted_policy_qualification_receipt_path": unsupported_receipt_path},
                ["accepted policy qualification receipt schema/status/coverage drifted"])
    cold_directory = derivatives / "unsupported-cold-guardian-kind"
    cold_directory.mkdir()
    source_guardian = minimum["consumers"]["guardian"]
    contract_path = cold_directory / guardian.CONTRACT_FILENAME
    _write_fresh(contract_path, Path(source_guardian["contract_path"]).read_bytes(), readonly=True)
    cold_receipt = json.loads(Path(source_guardian["receipt_path"]).read_bytes())
    cold_receipt.update(artifact_kind="unsupported_fixture_kind", preprocessing_contract=_descriptor(root, contract_path))
    cold_receipt_path = cold_directory / guardian.RECEIPT_FILENAME
    _write_json(cold_receipt_path, _semantic_hash(cold_receipt, "receipt_sha256"), readonly=True)
    refuse("unsupported-cold-guardian-kind", "default cold reader", lambda _namespace:
        guardian.load_accepted_policy_guardian_preprocessing_contract_v1(
            project_root=root, preprocessing_contract_path=contract_path, materialization_receipt_path=cold_receipt_path,
            accepted_policy_capability_manifest_path=base["accepted_policy_capability_manifest_path"]),
        ["accepted-policy preprocessing receipt identity drifted"])
    refuse("foreign-cold-capability", "default cold reader", lambda _namespace:
        guardian.load_accepted_policy_guardian_preprocessing_contract_v1(**_cold_kwargs(
            root, minimum, foreign["accepted_policy_capability_manifest_path"])),
        ["requested accepted policy capability differs from materialization receipt"])
    f5_context, pilots = genuine_f5_context_v1(root, index_path)
    original = next(pilot for pilot in pilots if pilot["resource"] == "cpu")
    other = next(pilot for pilot in pilots if pilot["resource"] == "cpu" and pilot["system"] != original["system"])
    wrong_arm = copy.deepcopy(original)
    wrong_arm["evidence"] = copy.deepcopy(other["evidence"])
    refuse("f5-whole-arm-coordinate-mismatch", "direct unchanged F5 component", lambda _namespace:
        policy_pilot_validator(wrong_arm, f5_context), ["qualification coordinate identity drift: system"], QualificationError)
    final_inventory = _input_inventory(root, (minimum_dir, larger_dir))
    final_head, final_status = _git(root, "rev-parse", "HEAD"), _git(root, "status", "--porcelain=v1", "--untracked-files=no")
    _write_json(output / "positive-fixture-inputs.after.v1.json", final_inventory)
    _write_fresh(output / "source-head.after.txt", final_head)
    _write_fresh(output / "source-tracked-status.after.txt", final_status)
    if final_inventory != initial_inventory or final_head != head or final_status != status:
        raise AssertionError("negative checks changed retained positive inputs or selected source")
    if [row["name"] for row in results] != [row[0] for row in CASE_PLAN]:
        raise AssertionError("case execution differs from the reviewed plan")
    _write_json(output / "default-consumer-refusals.v1.json", {"schema_version": 1, "passed": True,
                "source_commit": args.expected_source_commit, "finished_utc": _utc(), "cases": results,
                "retained_positive_inputs_unchanged": True, "default_dependencies": True,
                "loaded_production_sources": loaded_fixture_production_sources_v1(project_root=root),
                "campaign_authority": False, "physical_inference_observed": False})
    return 0


if __name__ == "__main__":
    sys.exit(main())
