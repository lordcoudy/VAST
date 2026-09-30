"""Fast original hosted observations; never a substitute for the full CPU job."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import run_ci_checks as checks


TEST_IDS = (
    "test_analytics_model_contract.AnalyticsModelContractTests."
    "test_repository_manifest_is_complete_and_hash_bound",
    "test_analytics_peer_identity.AnalyticsPeerIdentityAuthorityTests."
    "test_observer_reads_exact_proc_file_and_small_docker_projection",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output == checks.ROOT or checks.ROOT in output.parents:
        raise RuntimeError("host diagnostic outputs must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    report = {"kind": "vast_cpu_host_diagnostics_v1", "diagnostic_tests_only": True,
              "full_ci_successful": False, "hardware_acceptance": False, "test_ids": TEST_IDS}
    paths = checks.tracked_paths(checks.ROOT)
    before = checks.manifest(checks.ROOT, paths)
    checks.write_json(output / "tracked-source.before.json", before)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checks.ROOT,
                                         timeout=10, text=True).strip()
        if commit != args.expected_commit:
            raise RuntimeError("host diagnostic commit differs from requested commit")
        report["commit"] = commit
        checks.verify_committed_bytes(checks.ROOT, paths)
        checks.write_json(output / "host-facts.original.json", checks.host_facts())
        checks.command([sys.executable, "-I", "-B",
                        str(checks.ROOT / "scripts/prepare_ci_model_assets.py"),
                        "--output-dir", str(output / "model-acquisition")],
                       output, "model-assets", 590)
        # Only these two previously observed prerequisite/host IDs; the full job remains independent.
        child = (
            "import sys,unittest; "
            "sys.path[:0]=sys.argv[1:3]; "
            "import run_ci_checks as checks; "
            "suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3:]); "
            "result=unittest.TextTestRunner(verbosity=2,resultclass=checks.RecordedResult).run(suite); "
            "sys.exit(0 if result.wasSuccessful() and result.testsRun==2 "
            "and set(sys.argv[3:])<=set(result.successes) else 1)"
        )
        report["original_process"] = checks.command(
            [sys.executable, "-I", "-B", "-c", child, str(checks.ROOT / "tests"),
             str(checks.ROOT / "scripts"), *TEST_IDS], output, "host-prerequisites", 20)
        report["diagnostic_passed"] = True
    except Exception as exc:
        report["diagnostic_passed"] = False
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        after = checks.manifest(checks.ROOT, checks.tracked_paths(checks.ROOT))
        checks.write_json(output / "tracked-source.after.json", after)
        report["changed_tracked_paths"] = checks.source_changes(before, after)
        if report["changed_tracked_paths"]:
            report["diagnostic_passed"] = False
        checks.write_json(output / "report.json", report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["diagnostic_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
