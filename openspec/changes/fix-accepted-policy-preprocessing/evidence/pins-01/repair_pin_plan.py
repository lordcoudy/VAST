#!/usr/bin/env python3
"""Reuse the reviewed literal-pin planner with explicit fresh repair authorities."""
from __future__ import annotations

import ast
import difflib
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BUILD = Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
OLD_ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
BUILD_COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
OLD_DIR = "artifacts/qualify_full_benchmark_20261008e"
NEW_DIR = "artifacts/accepted_policy_repair_20261011a"
OLD_NS = "qfb-20261008e"
NEW_NS = "accepted-policy-repair-20261011a"
LIBRARY = ROOT / "openspec/changes/qualify-full-benchmark/evidence/software-v11-repin-20261008e/rebind_host_identity_pins_qfb_v4.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=1) + "\n").encode()


def planner():
    require(ROOT.resolve(strict=True) == ROOT and BUILD.resolve(strict=True) == BUILD,
            "pin root alias")
    require(subprocess.check_output(["git", "-C", str(BUILD), "rev-parse", "HEAD"],
                                    text=True).strip() == BUILD_COMMIT,
            "physical build root commit drifted")
    spec = importlib.util.spec_from_file_location("reviewed_repair_literal_planner", LIBRARY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.BUILD, module.G_ROOT = ROOT, BUILD, OLD_ROOT
    module.OLD_DIR, module.NEW_DIR = OLD_DIR, NEW_DIR
    module.OLD, module.NEW = OLD_ROOT / OLD_DIR, BUILD / NEW_DIR
    module.OLD_NS, module.NEW_NS, module.BUILD_COMMIT = OLD_NS, NEW_NS, BUILD_COMMIT
    module.DECISION28_REL = OLD_DIR + "/selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json"
    module.DECISION28 = ROOT / module.DECISION28_REL
    module.GSTREAMER_TRACKED_COPY_REL = NEW_DIR + "/selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json"
    module.EXPLICIT_SIZE_SITES = (
        ("tests/test_publication_runtime_frozen_identity_constants_v1.py", 332,
         "6976", module.DECISION28_REL),
    )
    module.HISTORICAL_PREFIXES += (
        "configs/analytics_execution_layer.refreshed.v4." + OLD_NS,
        "configs/checkpoint_analytics_model_parity.refreshed.v4." + OLD_NS,
    )
    native_git = Path("/mnt/c/Program Files/Git/cmd/git.exe")
    require(native_git.is_file(), "current worktree native Git unavailable")
    windows_root = subprocess.check_output(["wslpath", "-w", str(ROOT)], text=True).strip()
    def source_files():
        names = {item.decode() for item in subprocess.check_output(
            [str(native_git), "-C", windows_root, "ls-files", "--cached", "--others",
             "--exclude-standard", "-z"],
        ).split(b"\0") if item}
        # The original planner excludes narrative/artifact paths from pin sites.
        return sorted(name for name in names
                      if name.startswith(module.SCAN_PREFIXES) or name in module.FILES)

    module.tracked_files = source_files
    return module


def planned(module):
    plans, mapping, provenance, numeric, sizes, configs = module.plan_all()
    report = module.report(plans, mapping, configs, "planned")
    report.update(tool="repair_pin_plan.py", reviewed_planner_path=str(LIBRARY.relative_to(ROOT)),
                  reviewed_planner_sha256=digest(LIBRARY.read_bytes()))
    return plans, mapping, provenance, numeric, sizes, configs, report


def generic_build_defaults(module, inventory):
    registry = "configs/publication_qualification_image_refreeze_v1.json"
    groups = {
        "deepstream": (15, 16, 35, "DEEPSTREAM", 7),
        "savant": (73, 74, 93, "SAVANT", 10),
        "openvino_gva": (143, 144, 168, "OPENVINO_GVA", 7),
        "gstreamer_custom": (211, 212, 236, "GSTREAMER", 7),
    }
    value = json.loads((ROOT / registry).read_bytes())
    require(value["schema_version"] == 1 and value["artifact_kind"]
            == "vast_publication_qualification_image_refreeze_registry_v1", "generic registry kind drift")
    systems = {row["system"]: row for row in value["systems"]}
    require(len(value["systems"]) == len(systems) == 4 and set(systems) == set(groups),
            "generic registry system set drift")
    allowed, files = set(), {registry}
    for system, (first, second, final, variable, shell_line) in groups.items():
        repository = "vast/" + system.replace("_", "-") + "-publication-runtime-v3"
        reference = repository + ":materialized"
        row = systems[system]
        require(row["repository"] == repository and row["final_reference"] == reference
                and row["deterministic_references"] == [reference + "-determinism-a",
                                                        reference + "-determinism-b"],
                "generic canonical references drift")
        allowed.update((registry, number, ref) for number, ref in (
            (first, reference + "-determinism-a"), (second, reference + "-determinism-b"),
            (final, reference)))
        shell = "scripts/build_" + system + "_publication_runtime_v3.sh"
        files.add(shell)
        expected = 'image_ref="${VAST_' + variable + '_RUNTIME_IMAGE:-' + reference + '}"'
        require((ROOT / shell).read_text().splitlines()[shell_line - 1] == expected,
                "generic shell override/default drift")
        allowed.add((shell, shell_line, reference))
    hashes = {}
    for name in sorted(files):
        payload = (ROOT / name).read_bytes()
        committed = subprocess.check_output(["git", "-C", str(BUILD), "show", BUILD_COMMIT + ":" + name])
        require(payload == committed, "generic build configuration changed since frozen build")
        hashes[name] = digest(payload)
    control = BUILD / NEW_DIR / "runtime-build-control"
    before = (control / "canonical-tags.before.txt").read_bytes()
    require(before == (control / "canonical-tags.after.txt").read_bytes()
            and len(before.splitlines()) == 12, "protected canonical tag observations differ")
    classified = [dict(row, classification="unchanged_generic_build_default",
                       file_sha256=hashes[row["file"]])
                  for row in inventory["sites"]
                  if (row["file"], row["line"], row["old"]) in allowed]
    require(len(classified) == len(allowed) == 16
            and {(row["file"], row["line"], row["old"]) for row in classified} == allowed,
            "generic default occurrence set differs")
    return classified, digest(before)


def review(module, values, *, write_patch=True):
    plans, mapping, provenance, numeric, sizes, configs, report = values
    require((HERE / "host-pin-rebind.plan.v1.json").read_bytes() == encode(report),
            "saved pin plan drifted")
    inventory = module.inventory(mapping, provenance, numeric, sizes)
    generic, canonical_sha = generic_build_defaults(module, inventory)
    generic_sites = {(row["file"], row["line"], row["old"]) for row in generic}
    current_sources = [{"path": name, "sha256": digest((ROOT / name).read_bytes())}
                       for name in module.tracked_files()
                       if name.startswith(module.SCAN_PREFIXES) and (ROOT / name).is_file()]
    inv_sites = {(row["file"], row["line"]) for row in inventory["sites"] + inventory["size_sites"]
                 if (row["file"], row["line"], row["old"]) not in generic_sites}
    sites = {(row["file"], edit["line"]) for row in plans for edit in row["edits"]}
    require(inv_sites == sites, "pin inventory/plan coverage differs: inventory_only="
            + repr(sorted(inv_sites - sites)) + "; plan_only=" + repr(sorted(sites - inv_sites)))
    require(not any(row["status"] == "old_value_without_pair_ERROR"
                    for row in inventory["hex_literal_classification"]),
            "unpaired old literal")

    class Normalize(ast.NodeTransformer):
        def __init__(self, size_lines):
            self.size_lines = size_lines

        def visit_Constant(self, node):
            if isinstance(node.value, str):
                node.value = ""
            elif type(node.value) is int and node.lineno in self.size_lines:
                node.value = 0
            return node

    patch, files = [], []
    for row in plans:
        size_lines = {edit["line"] for edit in row["edits"] if "size" in edit["kind"]}
        before = ast.dump(Normalize(size_lines).visit(ast.parse(row["before"])), include_attributes=False)
        after = ast.dump(Normalize(size_lines).visit(ast.parse(row["after"])), include_attributes=False)
        require(before == after, "non-pin AST changed: " + row["file"])
        old_lines = row["before"].decode().splitlines(keepends=True)
        new_lines = row["after"].decode().splitlines(keepends=True)
        require(len(old_lines) == len(new_lines), "pin line count changed")
        changed = {index + 1 for index, pair in enumerate(zip(old_lines, new_lines)) if pair[0] != pair[1]}
        require(changed == {edit["line"] for edit in row["edits"]}, "unplanned changed line")
        patch.extend(difflib.unified_diff(old_lines, new_lines, fromfile="a/" + row["file"],
                                        tofile="b/" + row["file"]))
        files.append({"file": row["file"], "changed_lines": sorted(changed), "edits": len(row["edits"])})
    payload = "".join(patch).encode()
    patch_path = HERE / "host-pin-rebind.planned.patch"
    if write_patch:
        with patch_path.open("xb") as stream:
            stream.write(payload)
    else:
        require(patch_path.read_bytes() == payload, "reviewed rendered patch drifted")
    return {"status": "verified_plan_rendered", "plan_sha256": digest(encode(report)),
            "patch_sha256": digest(payload), "non_pin_ast_unchanged": True,
            "inventory_sites_equal_planned_sites": True, "files": files,
            "unchanged_generic_build_defaults": generic,
            "protected_canonical_tags_observation_sha256": canonical_sha,
            "current_source_inventory_sha256": digest(encode(current_sources)),
            "current_sources": current_sources}


def main():
    require(sys.flags.optimize == 0, "requires unoptimized Python")
    module = planner()
    values = planned(module)
    plans, mapping, provenance, numeric, sizes, configs, report = values
    args = sys.argv[1:]
    if args == ["inventory"]:
        result = module.inventory(mapping, provenance, numeric, sizes)
        result.update(mapping=[{"old": key, "new": mapping[key], "source": provenance[key]}
                               for key in sorted(mapping)], mapping_size=len(mapping),
                      file_sizes={key: list(value) for key, value in sorted(sizes.items())})
    elif args == ["plan"]:
        result = report
    elif args == ["render"]:
        result = review(module, values)
    else:
        require(len(args) == 2 and args[0] == "apply", "usage: inventory | plan | render | apply PLAN_SHA256")
        require(digest(encode(report)) == args[1], "reviewed plan SHA drifted")
        require((HERE / "host-pin-rebind.plan.v1.json").read_bytes() == encode(report), "saved plan drifted")
        rendered = review(module, values, write_patch=False)
        require((HERE / "host-pin-rebind.review.v1.json").read_bytes() == encode(rendered),
                "reviewed inventory/AST/render evidence drifted")
        module.apply_plans(plans)
        result = dict(report, status="applied")
    print(encode(result).decode(), end="")


if __name__ == "__main__":
    main()
