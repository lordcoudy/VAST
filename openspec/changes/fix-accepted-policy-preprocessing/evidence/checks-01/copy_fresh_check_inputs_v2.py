"""Archive-aware v2 fresh copy; the sealed v1 copy predicates remain unchanged."""

import json
from datetime import date
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


def recipe_origin(root, commit, path):
    """Require an actual committed helper in the selected native-ext4 checkout."""
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "exact source commit required")
    require(root in {
        Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + commit),
        Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-" + commit),
    }, "recipe checkout is outside exact commit-bound ext4 roots")
    require(root.resolve(strict=True) == root, "recipe root is aliased")
    require(subprocess.check_output(["findmnt", "-rn", "-T", str(root), "-o", "FSTYPE"]).strip() == b"ext4",
            "recipe checkout is not native ext4")
    require(path.is_absolute() and ".." not in path.parts and path.resolve(strict=True) == path,
            "recipe file is not its exact physical origin")
    relative = path.relative_to(root)
    parts = relative.parts
    change_name = "fix-accepted-policy-preprocessing"
    if len(parts) == 6 and parts[:3] == ("openspec", "changes", change_name):
        require(parts[3:5] == ("evidence", "checks-01"), "active recipe origin layout differs")
        change_relative = Path(*parts[:3])
    elif len(parts) == 7 and parts[:3] == ("openspec", "changes", "archive"):
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-" + re.escape(change_name), parts[3])
        require(match is not None and parts[4:6] == ("evidence", "checks-01"), "archived recipe origin layout differs")
        date.fromisoformat(match[1])
        change_relative = Path(*parts[:4])
    else:
        raise ValueError("recipe is outside the real active or supported dated archive")
    active = root / "openspec/changes" / change_name
    candidates = [active] if active.exists() or active.is_symlink() else []
    candidates += list((root / "openspec/changes/archive").glob("*-" + change_name))
    require(candidates == [root / change_relative], "active/archive recipe origin is ambiguous")
    plain(path)
    require(git(root, "rev-parse", "HEAD") == commit and
            not git(root, "status", "--porcelain", "--untracked-files=no"), "recipe checkout HEAD/status drifted")
    require(subprocess.check_output(["git", "-C", str(root), "show", commit + ":" + relative.as_posix()])
            == path.read_bytes(), "recipe bytes differ from the selected commit")
    return {"relative_path": relative.as_posix(), "change_relative": change_relative.as_posix(),
            "sha256": digest(path), "source_commit": commit}


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
    copier_roots = (source, target) if source_commit == commit else (target,)
    self_path = Path(__file__)
    origins = [recipe_origin(root, commit, self_path) for root in copier_roots if self_path.is_relative_to(root)]
    require(len(origins) == 1 and self_path.name == "copy_fresh_check_inputs_v2.py",
            "copier must have one exact committed source or destination recipe origin")
    selected_origin = origins[0]
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
        destination.write(json.dumps({"artifact_kind": "vast_fresh_check_input_copy_v2",
            "copier_origin": selected_origin,
            "sealed_v1_copy_predicates_preserved": True,
            "commit": commit, "input_source_commit": source_commit, "catalog_sha256": catalog_sha,
            "source_root": str(source), "target_root": str(target),
            "copied_files": catalog["copy_files"], "copy_total_bytes": catalog["copy_total_bytes"],
            "fixture_observation_files": observations, "fixture_observations_parity_audited": False,
            "copy_confers_qualification_authority": False, "historical_catalog_modified": False}, sort_keys=True, indent=1) + "\n")


if __name__ == "__main__":
    require(sys.flags.optimize == 0, "unoptimized Python required")
    main()
