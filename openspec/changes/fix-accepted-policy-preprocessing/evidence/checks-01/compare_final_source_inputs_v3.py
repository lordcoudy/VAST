#!/usr/bin/env python3
"""Archive-aware v3 source comparison; sealed v2 byte and graph gates unchanged."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import stat
import subprocess

from copy_fresh_check_inputs_v2 import recipe_origin


BUILD_COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
PLANNED_HOST_CHANGES = {
    "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
    "scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py",
    "scripts/checkpoint_openvino_gva_publication_runtime_v3.py",
    "scripts/checkpoint_openvino_gva_qualification_fragment_v3.py",
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def physical_bytes(root: Path, relative: str) -> bytes:
    path = root / relative
    require(path.resolve(strict=True) == path, "aliased input: " + relative)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "non-plain input: " + relative)
    return path.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--fresh-inventory", type=Path, required=True)
    parser.add_argument("--native-worker-plan", type=Path, required=True)
    args = parser.parse_args()
    source_commit = args.source_commit
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "exact source commit required")
    root = args.project_root
    require(root == Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + source_commit),
            "root differs from selected frozen source commit")
    require(root.is_absolute() and root.resolve(strict=True) == root, "noncanonical source root")
    before = git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain=v1", "--untracked-files=no")
    require(before == ((source_commit + "\n").encode("ascii"), b""), "source commit or tracked state differs")
    self_path = Path(__file__)
    require(self_path.name == "compare_final_source_inputs_v3.py", "comparison helper identity differs")
    origin = recipe_origin(root, source_commit, self_path)
    evidence = Path(origin["change_relative"]) / "evidence/physical-01"
    old = json.loads(physical_bytes(root, (evidence / "packaged-closure.aca94dd0.inventory.v1.json").as_posix()))
    fresh = json.loads(args.fresh_inventory.read_bytes())
    require(old["source_commit"] == BUILD_COMMIT and fresh["source_commit"] == source_commit, "inventory commit differs")
    for key in ("guardian_source_count", "qualification_full_source_count", "full_only_sources",
                "guardian_shared_leaf_seeds", "qualification_full_seeds"):
        require(old[key] == fresh[key], "source closure membership differs: " + key)
    require(fresh["guardian_source_count"] == 67 and fresh["qualification_full_source_count"] == 93, "closure count differs")
    require(old["runtime_rows"] == fresh["runtime_rows"], "runtime COPY inputs or allowlists differ from built images")
    checked_build_inputs = {}
    for row in fresh["runtime_rows"].values():
        checked_build_inputs.update(row["local_copy_source_hashes"])
        for path_key, hash_key in (("dockerfile", "dockerfile_sha256"),
                                   ("source_allowlist", "source_allowlist_sha256"),
                                   ("dependency_allowlist", "dependency_allowlist_sha256")):
            checked_build_inputs[row[path_key]] = row[hash_key]
    for relative, digest in checked_build_inputs.items():
        payload = physical_bytes(root, relative)
        require(hashlib.sha256(payload).hexdigest() == digest, "current build input hash differs: " + relative)
        require(payload == git(root, "show", BUILD_COMMIT + ":" + relative), "raw build source differs: " + relative)
    old_rows = {row["path"]: row for row in old["project_sources"]}
    fresh_rows = {row["path"]: row for row in fresh["project_sources"]}
    require(old_rows.keys() == fresh_rows.keys(), "full source path membership differs")
    changed = []
    for relative, row in fresh_rows.items():
        old_row = old_rows[relative]
        require({key: value for key, value in row.items() if key not in ("sha256", "size_bytes")} ==
                {key: value for key, value in old_row.items() if key not in ("sha256", "size_bytes")},
                "source classification differs: " + relative)
        if row["sha256"] != old_row["sha256"]:
            require(relative in PLANNED_HOST_CHANGES and not row["runtime_source_membership"], "unplanned changed source: " + relative)
            changed.append({"path": relative, "build_sha256": old_row["sha256"], "source_sha256": row["sha256"]})
    native = json.loads(physical_bytes(root, (evidence / "native-worker-inputs.pre-freeze.inventory.v1.json").as_posix()))
    plan = json.loads(args.native_worker_plan.read_bytes())
    require(native["build_registry_sha256"] == plan["registry_sha256"], "native/worker registry differs")
    plans = {row["name"]: row for row in plan["images"]}
    require(set(plans) == {row["name"] for row in native["images"]} and len(plans) == 5, "native/worker image set differs")
    keys = ("source_set_sha256", "dependency_set_sha256", "build_context_sha256")
    for row in native["images"]:
        require(all(row[key] == plans[row["name"]][key] for key in keys), "native/worker planned input differs: " + row["name"])
        for relative in row["relative_paths"]:
            require(physical_bytes(root, relative) == git(root, "show", BUILD_COMMIT + ":" + relative), "native/worker raw input differs: " + relative)
    after = git(root, "rev-parse", "HEAD"), git(root, "status", "--porcelain=v1", "--untracked-files=no")
    require(after == before, "source changed during comparison")
    print(json.dumps({"artifact_kind": "vast_final_repair_source_input_comparison_v3", "passed": True,
        "helper_origin": origin, "sealed_v2_byte_and_graph_predicates_preserved": True,
        "build_commit": BUILD_COMMIT, "source_commit": source_commit,
        "runtime_package_inputs_byte_identical": True, "runtime_build_input_count": len(checked_build_inputs),
        "runtime_python_counts": {name: len(row["all_runtime_python_paths"]) for name, row in fresh["runtime_rows"].items()},
        "guardian_source_count": 67, "qualification_full_source_count": 93,
        "host_only_changed_closure_sources": sorted(changed, key=lambda row: row["path"]),
        "all_five_native_worker_source_dependency_context_hashes_equal": True,
        "source_unchanged": True, "campaign_authority": False,
        "limits": ["Build and image execution evidence remains bound to the earlier build commit.",
                   "This comparison is not a Q1 execution or a completed downstream acceptance."]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
