"""Copy the additive reviewed fresh graph, never alter historical regression rows."""

import json
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys

from copy_check_inputs import digest, git, plain, reviewed, safe_relative


BASE = "artifacts/accepted_policy_repair_20261011a"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(root, row):
    path = root / safe_relative(row["path"])
    require(plain(path).st_size == row["size_bytes"] and digest(path) == row["sha256"],
            "fresh physical input changed: " + row["path"])


def main():
    require(len(sys.argv) == 7, "SOURCE_COMMIT TARGET_COMMIT CATALOG_SHA SOURCE_ROOT TARGET_ROOT OUTPUT_REPORT required")
    source_commit, commit, catalog_sha, source_value, target_value, output_value = sys.argv[1:]
    require(all(re.fullmatch(r"[0-9a-f]{40}", value) is not None for value in (source_commit, commit)),
            "exact source and target commits required")
    source, target, output = map(Path, (source_value, target_value, output_value))
    require(source != target and all(root.resolve(strict=True) == root for root in (source, target)),
            "fresh copy roots must be canonical and separate")
    recipe_relative = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/copy_fresh_check_inputs.py")
    copier_roots = (source, target) if source_commit == commit else (target,)
    require(any(Path(__file__).resolve() == root / recipe_relative for root in copier_roots),
            "copier must come from the selected frozen check source or destination root")
    require((source_commit == commit) or (source == Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
            and source_commit == "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"),
            "distinct input-source commit must be the untouched physical build root")
    for root, expected_commit in ((source, source_commit), (target, commit)):
        require(git(root, "rev-parse", "HEAD") == expected_commit
                and not git(root, "status", "--porcelain", "--untracked-files=no"), "fresh copy tracked commit drifted")
    require(not output.exists() and output.resolve(strict=False) == output
            and output.parent.resolve(strict=True) == output.parent, "fresh copy report occupied or aliased")
    harness_path = target / "scripts/run_ci_checks.py"
    plain(harness_path)
    require(subprocess.check_output(["git", "-C", str(target), "show", "HEAD:scripts/run_ci_checks.py"])
            == harness_path.read_bytes(), "original raw-byte verifier differs from the source commit")
    spec = importlib.util.spec_from_file_location("run_ci_checks", harness_path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    for root in (source, target):
        harness.verify_committed_bytes(root, harness.tracked_paths(root))
    catalog_path = Path(__file__).resolve().parent / "fresh-inputs.catalog.v1.json"
    reviewed(catalog_path, catalog_sha)
    catalog = json.loads(catalog_path.read_bytes())
    require(catalog["schema_version"] == 1 and catalog["artifact_kind"] == "vast_fresh_check_input_catalog_v1"
            and catalog["copy_file_count"] == len(catalog["copy_files"]) == 2473
            and len(catalog["tracked_cross_checks"]) == 8 and len(catalog["asset_cross_checks"]) == 5
            and len(catalog["fixture_observation_files"]) == 2
            and catalog["fixture_observations_parity_audited"] is False
            and catalog["historical_catalog_modified"] is False and catalog["policy_pilot_attempts_included"] is False
            and catalog["copy_confers_qualification_authority"] is False, "fresh reviewed catalog shape drifted")
    require(len({row["path"] for row in catalog["copy_files"]}) == 2473, "fresh copy path duplicated")
    require(catalog["copy_total_bytes"] == sum(row["size_bytes"] for row in catalog["copy_files"]),
            "fresh graph total size drifted")
    observations = catalog["fixture_observation_files"]
    require({row["path"] for row in observations} == {
        BASE + "/consumer-runtime-observations-02/image-inspect-map.json",
        BASE + "/consumer-runtime-observations-02/device-probe-map.json"}, "fixture observation paths drifted")
    entries = catalog["copy_files"] + observations
    require(len({row["path"] for row in entries}) == 2475, "fresh or observation path duplicated")
    tracked = set(subprocess.check_output(["git", "-C", str(target), "ls-files", "-z"]).decode().split("\0"))
    for row in catalog["tracked_cross_checks"]:
        relative = safe_relative(row["path"]).as_posix()
        require(relative in tracked, "fresh config/selected-copy is not tracked")
        verify(target, row)
    for row in catalog["asset_cross_checks"]:
        verify(source, row)
        verify(target, row)
    paths = [safe_relative(row["path"]).as_posix() for row in entries]
    ignored = subprocess.run(["git", "-C", str(target), "check-ignore", "--stdin", "-z"],
        input=("\0".join(paths) + "\0").encode(), capture_output=True, check=True).stdout.decode().split("\0")
    require(set(ignored) - {""} == set(paths), "fresh copier requires every target path to be ignored")
    # Verify all 1.5 GB of fresh evidence before the first write; no partial preflight admission.
    for row in entries:
        relative = safe_relative(row["path"])
        require(relative.as_posix().startswith(BASE + "/"), "fresh copy outside exact repair artifact root")
        verify(source, row)
        destination = target / relative
        require(not destination.exists() and not destination.is_symlink()
                and destination.resolve(strict=False) == destination, "fresh destination occupied or aliased")
        require(relative.as_posix() not in tracked,
                "fresh copier cannot overwrite tracked input")
    for row in entries:
        relative = safe_relative(row["path"])
        src, dst = source / relative, target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as reader, dst.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
        verify(target, row)
        verify(source, row)
    require(not git(target, "status", "--porcelain", "--untracked-files=no"), "fresh copy mutated tracked source")
    for root, expected_commit in ((source, source_commit), (target, commit)):
        require(git(root, "rev-parse", "HEAD") == expected_commit, "source commit changed during fresh copy")
        harness.verify_committed_bytes(root, harness.tracked_paths(root))
    with output.open("x", encoding="ascii") as destination:
        destination.write(json.dumps({"artifact_kind": "vast_fresh_check_input_copy_v1",
            "commit": commit, "input_source_commit": source_commit, "catalog_sha256": catalog_sha,
            "source_root": str(source), "target_root": str(target),
            "copied_files": catalog["copy_files"], "copy_total_bytes": catalog["copy_total_bytes"],
            "fixture_observation_files": observations, "fixture_observations_parity_audited": False,
            "copy_confers_qualification_authority": False, "historical_catalog_modified": False}, sort_keys=True, indent=1) + "\n")


if __name__ == "__main__":
    require(sys.flags.optimize == 0, "unoptimized Python required")
    main()
