#!/usr/bin/env python3
"""Explicit complete real-consumer fixture; artificial observations are not Q1."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback


APPROVED_COMMIT = "299c9c0eefb83fe3031096b0e96527236678a4d2"
GUARDIAN_SOURCE = "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"


def _lexical_path_argument(value: str | Path, *, root: Path | None = None) -> Path:
    raw = os.fspath(value)
    path = Path(raw)
    if not raw or ".." in path.parts or raw != os.path.normpath(raw):
        raise ValueError("fixture path argument has noncanonical components")
    if not path.is_absolute():
        if root is None:
            raise ValueError("fixture project root must be an exact absolute path")
        path = root / path
    if root is not None and (path == root or not path.is_relative_to(root)):
        raise ValueError("fixture directory escaped the selected project root")
    return path


def _canonical_fixture_root_v2(value: str | Path, *, source_root: Path) -> Path:
    root = _lexical_path_argument(value)
    if root.resolve(strict=True) != root or not root.is_dir() or root != source_root:
        raise ValueError("fixture project root must be the exact unaliased frozen source root")
    return root


def _canonical_fixture_directory_v2(value: str | Path, *, root: Path, fresh: bool) -> Path:
    path = _lexical_path_argument(value, root=root)
    if fresh:
        if os.path.lexists(path) or path.parent.resolve(strict=True) != path.parent or not path.parent.is_dir():
            raise ValueError("fixture output must be fresh with a canonical physical parent")
    elif path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("fixture input directory must be canonical and physical")
    return path


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def _fresh_json(path: Path, value: object) -> None:
    with path.open("x", encoding="ascii") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--artifact-base", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--socket-prefix", default=".apfv2")
    parser.add_argument("--samples-per-branch", type=int, default=30)
    parser.add_argument("--stage", choices=("inputs", "original-observations", "complete"), default="complete")
    args = parser.parse_args()
    source_root = Path(__file__).resolve(strict=True).parents[5]
    root = _canonical_fixture_root_v2(args.project_root, source_root=source_root)
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_source_commit) is None:
        raise ValueError("expected source commit must be an exact commit SHA")
    if _git(root, "rev-parse", "HEAD").decode().strip() != args.expected_source_commit:
        raise ValueError("fixture source HEAD differs from the explicitly pinned commit")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("fixture tracked source is not clean")
    if type(args.samples_per_branch) is not int or args.samples_per_branch < 30:
        raise ValueError("complete fixture requires at least 30 samples in every branch cell")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", args.namespace) is None:
        raise ValueError("fixture upstream namespace is invalid")
    base = _canonical_fixture_directory_v2(args.artifact_base, root=root, fresh=False)
    output = _canonical_fixture_directory_v2(args.output_dir, root=root, fresh=True)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.fixtures.accepted_policy_physical_fixture_v2 import (
        build_original_native_fixture_observations_v2, prepared_complete_fixture_inputs_v2,
    )
    from tests.fixtures.accepted_policy_consumer_fixture_v2 import complete_fixture_production_consumers_v2

    original_sources = loaded_fixture_production_sources_v1(project_root=root)
    approved_source = _git(root, "show", APPROVED_COMMIT + ":" + GUARDIAN_SOURCE)
    report = {"schema_version": 2, "fixture_stage": args.stage,
              "campaign_authority": False, "physical_inference_observed": False,
              "complete_consumer_positive_asserted": False,
              "upstream_root": str(root), "source_commit": args.expected_source_commit,
              "entrypoint_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "samples_per_branch": args.samples_per_branch,
              "expected_measured_sample_count": 32 * 4 * args.samples_per_branch,
              "approved_old_guardian_commit": APPROVED_COMMIT,
              "approved_old_guardian_source_sha256": hashlib.sha256(approved_source).hexdigest(),
              "initial_loaded_production_sources": original_sources}

    def phase(name: str) -> None:
        current = loaded_fixture_production_sources_v1(project_root=root)
        by_name = {row["module"]: row for row in current}
        if any(by_name.get(row["module"]) != row for row in original_sources):
            raise ValueError("previously loaded production source changed during the fixture")
        print(json.dumps({"fixture_phase": name, "output_dir": str(output),
                          "production_module_count": len(current)}, sort_keys=True), flush=True)
        if output.is_dir():
            _fresh_json(output / ("producer-phase-" + name + ".v2.json"),
                        {"phase": name, "source_commit": args.expected_source_commit,
                         "loaded_production_sources": current, "campaign_authority": False})

    phase("00-imported")
    config_base = root / "configs" / f"checkpoint_analytics_model_parity.refreshed.v4.{args.namespace}.accepted"
    observations = base / "consumer-runtime-observations-02"
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
            phase("01-prepared")
            report.update(transaction_receipt=str(prepared["transaction"]["transaction_receipt_path"]),
                          preprocessing_receipt=str(prepared["preprocessing"]["receipt_path"]),
                          capture_plan=prepared["capture_plan_descriptor"],
                          runtime_input_receipt=str(prepared["runtime"]["receipt_path"]))
            if args.stage != "inputs":
                native = build_original_native_fixture_observations_v2(prepared=prepared, samples_per_branch=args.samples_per_branch)
                phase("02-originals")
                report.update(original_operation_count=len(native["operations"]),
                              qualification_count=native["qualification_count"], native_domains=native["native_domains"])
                if args.stage == "complete":
                    consumers = complete_fixture_production_consumers_v2(
                        prepared=prepared, native=native, approved_guardian_source=approved_source,
                        approved_guardian_commit=APPROVED_COMMIT,
                    )
                    if consumers["assessment"]["coverage"]["accepted_sample_count"] != report["expected_measured_sample_count"]:
                        raise ValueError("real F1 measured sample count includes a drop or loses a branch cell")
                    phase("03-complete-consumers")
                    report.update(consumers=consumers, complete_consumer_positive_asserted=True)
            report["final_loaded_production_sources"] = loaded_fixture_production_sources_v1(project_root=root)
            _fresh_json(output / "producer-stage-report.v2.json", report)
            print(json.dumps({"fixture_completed": args.stage,
                              "complete_consumer_positive_asserted": report["complete_consumer_positive_asserted"],
                              "report_path": str(output / "producer-stage-report.v2.json")}, sort_keys=True), flush=True)
    except Exception as error:
        if output.is_dir() and not (output / "producer-failure.v2.json").exists():
            _fresh_json(output / "producer-failure.v2.json",
                        {**report, "complete_consumer_positive_asserted": False,
                         "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    main()
