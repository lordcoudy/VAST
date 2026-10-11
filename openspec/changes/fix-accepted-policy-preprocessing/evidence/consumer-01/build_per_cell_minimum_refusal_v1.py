#!/usr/bin/env python3
"""Fresh genuine 29-sample cell refusal evidence, never accepted qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback

from build_production_fixture_v2 import (
    _canonical_fixture_directory_v2, _canonical_fixture_root_v2, _fixture_source_root_v2, _fresh_json, _git,
)


REFUSAL_COORDINATE = ("gstreamer_custom", "cpu", "h264", "independent_processes")


def _raw_committed_source_proof(root: Path) -> dict:
    program = (
        "import json,sys; from pathlib import Path; root=Path(" + repr(str(root)) + "); "
        "sys.path.insert(0,str(root/'scripts')); import run_ci_checks as ci; "
        "paths=ci.tracked_paths(root); ci.verify_committed_bytes(root,paths); "
        "print(json.dumps({'raw_committed_bytes_verified':True,'tracked_path_count':len(paths),"
        "'verifier_path':ci.__file__},sort_keys=True))"
    )
    command = [sys.executable, "-B", "-c", program]
    result = subprocess.run(command, cwd=root, capture_output=True)
    return {"command": command, "original_exit_code": result.returncode,
            "stdout": result.stdout.decode("utf-8"), "stderr": result.stderr.decode("utf-8")}


def _select_refusal_operation(prepared: dict) -> str:
    coordinates = {}
    for row in prepared["capture_plan"]["operation_manifest"]["operations"]:
        if row["phase"] != "qualification_cell":
            continue
        source = json.loads(Path(row["descriptors"]["source_plan"]["path"]).read_bytes())
        coordinate = (row["system"], "cpu" if row["policy"] == "cpu_only" else "gpu",
                      row["codec"], source["topology_kind"])
        if coordinate in coordinates:
            raise ValueError("fresh refusal fixture has duplicate qualification coordinates")
        coordinates[coordinate] = row["operation_id"]
    if len(coordinates) != 32 or REFUSAL_COORDINATE not in coordinates:
        raise ValueError("fresh refusal fixture requires all 32 qualification coordinates")
    return coordinates[REFUSAL_COORDINATE]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--artifact-base", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--socket-prefix", default=".apf29")
    args = parser.parse_args()
    source_root = _fixture_source_root_v2(Path(__file__))
    root = _canonical_fixture_root_v2(args.project_root, source_root=source_root)
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) is None:
        raise ValueError("expected source commit must be an exact commit SHA")
    before_head, before_status = _git(root, "rev-parse", "HEAD"), _git(root, "status", "--porcelain", "--untracked-files=no")
    if before_head.decode().strip() != args.expected_source_commit or before_status:
        raise ValueError("refusal fixture requires exact clean frozen source")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", args.namespace) is None:
        raise ValueError("fixture upstream namespace is invalid")
    base = _canonical_fixture_directory_v2(args.artifact_base, root=root, fresh=False)
    output = _canonical_fixture_directory_v2(args.output_dir, root=root, fresh=True)
    before_raw = _raw_committed_source_proof(root)
    if before_raw["original_exit_code"] != 0:
        raise ValueError("stock raw committed source proof failed before refusal fixture")
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.fixtures.accepted_policy_physical_fixture_v2 import (
        build_original_native_fixture_observations_v2, prepared_complete_fixture_inputs_v2,
    )
    from tests.fixtures.accepted_policy_consumer_fixture_v2 import materialize_fixture_completed_execution_v2

    original_sources = loaded_fixture_production_sources_v1(project_root=root)
    config_base = root / "configs" / f"checkpoint_analytics_model_parity.refreshed.v4.{args.namespace}.accepted"
    observations = base / "consumer-runtime-observations-02"
    report = {"schema_version": 1, "campaign_authority": False, "physical_inference_observed": False,
              "accepted_policy_qualification_asserted": False, "complete_consumer_positive_asserted": False,
              "default_guardian_refusal_asserted": False, "source_commit": args.expected_source_commit,
              "project_root": str(root), "entrypoint_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "refusal_coordinate": REFUSAL_COORDINATE, "expected_measured_sample_count": 3960,
              "source_raw_before": before_raw, "initial_loaded_production_sources": original_sources}
    try:
        with prepared_complete_fixture_inputs_v2(
            project_root=root, output_dir=output,
            identity_patch_path=base / "qualification_image_identity_patch.json",
            accepted_model_parity_manifest_path=config_base.with_suffix(".accepted.yaml"),
            accepted_model_parity_assessment_path=Path(str(config_base) + ".assessment.json"),
            accepted_model_parity_receipt_path=Path(str(config_base) + ".acceptance_receipt.json"),
            image_inspections=json.loads((observations / "image-inspect-map.json").read_bytes()),
            device_probes=json.loads((observations / "device-probe-map.json").read_bytes()),
            socket_prefix=args.socket_prefix,
        ) as prepared:
            operation_id = _select_refusal_operation(prepared)
            native = build_original_native_fixture_observations_v2(
                prepared=prepared, samples_per_branch=31,
                qualification_samples_by_operation_id={operation_id: 29},
            )
            chain = materialize_fixture_completed_execution_v2(prepared=prepared, native=native)
            from publication_policy_qualification import QualificationError, assess_policy_qualification, promote_policy_qualification
            from publication_policy_qualification_pilot_validation_v2 import policy_pilot_validator
            from publication_qualification_promotion_v2 import _fragment_validator
            from tests.test_accepted_policy_f5_real_refusals import genuine_f5_context_v1

            context, pilots = genuine_f5_context_v1(root, chain["index_path"])
            counts, total = [], 0
            for pilot in pilots:
                coordinate = tuple(pilot[field] for field in ("system", "resource", "codec", "topology_kind"))
                rows = policy_pilot_validator(pilot, context)
                expected = 29 if coordinate == REFUSAL_COORDINATE else 31
                branch_counts = {branch: sum(row["branch"] == branch for row in rows)
                                 for branch in context["policy"].ANALYTICS_BRANCHES}
                if set(branch_counts.values()) != {expected} or len(rows) != 4 * expected:
                    raise ValueError("actual F5 samples do not match the fresh mixed-cell observations")
                counts.append({"coordinate": coordinate, "branch_counts": branch_counts, "measured_sample_count": len(rows)})
                total += len(rows)
            if len(counts) != 32 or total != 3960:
                raise ValueError("actual F5 mixed-cell measured coverage drifted")
            expected_blocker = (f"pilot {REFUSAL_COORDINATE}/{context['policy'].ANALYTICS_BRANCHES[0]} "
                                "requires at least 30 accepted samples")
            assessment = assess_policy_qualification(
                project_root=root, index_path=chain["index_path"],
                pilot_validator=policy_pilot_validator, fragment_validator=_fragment_validator)
            if assessment.get("passed") is not False or assessment.get("blockers") != [expected_blocker]:
                raise ValueError(f"actual F1 did not reach the exact genuine per-cell minimum refusal: {assessment}")
            promotion_parent = output / "must-remain-absent"
            promotion_output = promotion_parent / "accepted-policy"
            if promotion_parent.exists() or promotion_output.exists():
                raise ValueError("refused promotion namespace is not fresh")
            try:
                promote_policy_qualification(project_root=root, index_path=chain["index_path"], output_dir=promotion_output,
                    pilot_validator=policy_pilot_validator, fragment_validator=_fragment_validator)
            except QualificationError as error:
                if str(error) != "policy qualification is blocked: " + expected_blocker:
                    raise
                promotion_refusal = str(error)
            else:
                raise ValueError("actual promoter accepted an underfilled branch cell")
            if promotion_parent.exists() or promotion_output.exists():
                raise ValueError("refused promotion created an output parent or leaf")
            report.update(original_operation_count=len(native["operations"]), completed_index=str(chain["index_path"]),
                          transaction_receipt=str(prepared["transaction"]["transaction_receipt_path"]),
                          preprocessing_contract=str(prepared["preprocessing"]["contract_path"]),
                          preprocessing_receipt=str(prepared["preprocessing"]["receipt_path"]),
                          execution_config=str(chain["execution_config_path"]), binding_set_dir=str(chain["binding_set_dir"]),
                          execution_closure=str(chain["closure"]["receipt_path"]), measured_sample_count=total,
                          measured_cells=counts, actual_f1_assessment=assessment, actual_promotion_refusal=promotion_refusal,
                          promotion_parent_absent=True, promotion_output_absent=True,
                          complete_original_accounting_cold_validated=True, genuine_per_cell_minimum_refusal_asserted=True)
        current = loaded_fixture_production_sources_v1(project_root=root)
        by_name = {row["module"]: row for row in current}
        if any(by_name.get(row["module"]) != row for row in original_sources):
            raise ValueError("loaded production source provenance changed during refusal fixture")
        report["final_loaded_production_sources"] = current
    except Exception as error:
        if output.is_dir():
            _fresh_json(output / "per-cell-minimum-failure.v1.json",
                        {**report, "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()})
        raise
    finally:
        after_raw = _raw_committed_source_proof(root)
        if output.is_dir():
            _fresh_json(output / "raw-source-after.v1.json", after_raw)
        if (after_raw["original_exit_code"] != 0 or _git(root, "rev-parse", "HEAD") != before_head
                or _git(root, "status", "--porcelain", "--untracked-files=no") != before_status):
            raise ValueError("raw committed source or tracked Git state changed during refusal fixture")
    report["source_raw_after"] = after_raw
    _fresh_json(output / "per-cell-minimum-refusal-report.v1.json", report)
    print(json.dumps({"genuine_per_cell_minimum_refusal_asserted": True, "measured_sample_count": 3960,
                      "default_guardian_refusal_asserted": False,
                      "report_path": str(output / "per-cell-minimum-refusal-report.v1.json")}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
