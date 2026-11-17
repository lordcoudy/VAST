#!/usr/bin/env python3
"""Explicit real-validator fixture producer; never a physical campaign replay."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--artifact-base", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--socket-prefix", default=".apf01")
    parser.add_argument("--samples-per-branch", type=int, default=30)
    parser.add_argument("--stage", choices=("inputs", "original-observations"), default="original-observations")
    args = parser.parse_args()
    worktree = Path(__file__).resolve().parents[5]
    root = args.project_root.resolve(strict=True)
    base = args.artifact_base if args.artifact_base.is_absolute() else root / args.artifact_base
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    sys.path.insert(0, str(worktree))
    sys.path.insert(0, str(root / "scripts"))
    from tests.fixtures.accepted_policy_physical_fixture_v1 import (
        build_original_native_fixture_observations_v1, prepared_complete_fixture_inputs_v1,
    )
    # Existing row-producer test modules prepend their own scripts directory.
    # The physical-input run must resolve lazy production imports at its root.
    sys.path.insert(0, str(root / "scripts"))

    config_base = root / "configs" / f"checkpoint_analytics_model_parity.refreshed.v4.{args.namespace}.accepted"
    observations = base / "consumer-runtime-observations-02"
    report = {"campaign_authority": False, "physical_inference_observed": False,
              "fixture_stage": args.stage, "upstream_root": str(root), "samples_per_branch": args.samples_per_branch}
    with prepared_complete_fixture_inputs_v1(
        project_root=root, output_dir=output,
        identity_patch_path=base / "qualification_image_identity_patch.json",
        accepted_model_parity_manifest_path=config_base.with_suffix(".accepted.yaml"),
        accepted_model_parity_assessment_path=Path(str(config_base) + ".assessment.json"),
        accepted_model_parity_receipt_path=Path(str(config_base) + ".acceptance_receipt.json"),
        image_inspections=json.loads((observations / "image-inspect-map.json").read_bytes()),
        device_probes=json.loads((observations / "device-probe-map.json").read_bytes()),
        socket_prefix=args.socket_prefix,
    ) as prepared:
        report.update(transaction_receipt=str(prepared["transaction"]["transaction_receipt_path"]),
                      preprocessing_receipt=str(prepared["preprocessing"]["receipt_path"]),
                      capture_plan=prepared["capture_plan_descriptor"], runtime_input_receipt=str(prepared["runtime"]["receipt_path"]))
        if args.stage == "original-observations":
            native = build_original_native_fixture_observations_v1(prepared=prepared, samples_per_branch=args.samples_per_branch)
            report.update(original_operation_count=len(native["operations"]), qualification_count=native["qualification_count"],
                          native_domains=native["native_domains"])
        report["complete_consumer_positive_asserted"] = False
        path = output / "producer-stage-report.json"
        path.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
        print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
