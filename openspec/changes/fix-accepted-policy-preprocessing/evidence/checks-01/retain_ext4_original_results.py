#!/usr/bin/env python3
"""Retain only the completed original591 ext4 controls and reports after review."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
COMMON_PATH = HERE / "retain_completed_check_results.py"
COMMON_SHA = "01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed"
if hashlib.sha256(COMMON_PATH.read_bytes()).hexdigest() != COMMON_SHA:
    raise ValueError("reviewed retention primitives changed")
_spec = importlib.util.spec_from_file_location("completed_result_retention", COMMON_PATH)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require = common.require
COMMIT = common.COMMIT
SOURCE = common.BASE / ("ext4-" + COMMIT)
OUTPUT = HERE / "ext4-original-results"
CATALOGUE = HERE / "ext4-original-results.v1.json"
CONTROL_FILES = (
    "checkout.stderr.log", "checkout.stdout.log", "clone.stderr.log", "clone.stdout.log",
    "commit.txt", "finished.txt", "started.txt", "fresh-input-copy.report.json",
    "fresh-input-copy.stderr.log", "fresh-input-copy.stdout.log",
    "global-mountinfo.after.txt", "global-mountinfo.before.txt",
    "input-copy.report.json", "input-copy.stderr.log", "input-copy.stdout.log",
    "original-mount-namespace.txt", "parent.rc", "parent.stderr.log", "parent.stdout.log",
    "private-mount-namespace.txt", "privileged-launcher.txt", "runtime-mount.check.json",
    "runtime-mount.materialization.json", "runtime-source.mount.txt", "runtime-target.mount.txt",
    "sudo-prerequisite.stderr.log", "sudo-prerequisite.stdout.log",
)
REPORT_FILES = (
    "factory-appsrc.json", "factory-appsrc.stderr", "factory-appsrc.stdout",
    "factory-queue.json", "factory-queue.stderr", "factory-queue.stdout",
    "factory-videoconvert.json", "factory-videoconvert.stderr", "factory-videoconvert.stdout",
    "gstreamer-packages.json", "gstreamer-packages.stderr", "gstreamer-packages.stdout",
    "host-facts.original.json", "model-assets.json", "model-assets.stderr", "model-assets.stdout",
    "native-build.json", "native-build.stderr", "native-build.stdout",
    "native-configure.json", "native-configure.stderr", "native-configure.stdout",
    "report.json", "specification-inventory.json", "tracked-source.after.json",
    "tracked-source.before.json", "unittest.original.log", "unittest-child.report.json",
)
NAMESPACE_FILES = (
    "capture.json", "kernel-denial.json", "stdout.raw", "stderr.raw",
    "kernel-query/capture.json", "kernel-query/stdout.raw", "kernel-query/stderr.raw",
)
OBSERVER_FILES = (
    "events.original.jsonl", "trace.original.log", "terminal.v1.json",
    "responses.original.jsonl", "launch.v1.json",
)
MODEL_FILES = (
    "report.json", "asset-00.json", "asset-01.json", "asset-02.json", "asset-03.json",
    "asset-04.json", "asset-05.json", "asset-06.json", "asset-07.json",
)


def snapshot(path):
    return common.snapshot(path)


def document(relative):
    return common.strict_json(snapshot(SOURCE / relative)[0])


def original_state():
    require(snapshot(SOURCE / "commit.txt")[0] == (COMMIT + "\n").encode("ascii"), "original producer commit differs")
    require(snapshot(SOURCE / "parent.rc")[0] == b"1\n", "original parent exit differs")
    require(snapshot(SOURCE / "finished.txt")[0].strip(), "original producer is not finished")
    report = document("original/report.json")
    suite = report["unittest"]
    require(report["commit"] == COMMIT and report["successful"] is False
            and report["raw_checkout_bytes_match_commit"] is True
            and report["changed_tracked_paths"] == []
            and report["hardware_acceptance"] is False, "original failed report differs")
    require(suite["tests_run"] == 3291 and len(suite["successful_test_ids"]) == 3202
            and len(suite["failures"]) == 2 and len(suite["errors"]) == 1
            and len(suite["skips"]) == 86 and suite["successful"] is False,
            "original suite terminal counts differ")
    selection = suite["selection"]
    require(selection["counts"] == {"discovered": 3300, "integration": 9, "portable": 3291}
            and selection["integration_executed"] is False, "original selection differs")
    manifest_bytes = common.git("show", COMMIT + ":.ci/integration-test-selection.v1.json")
    require(hashlib.sha256(manifest_bytes).hexdigest() == selection["manifest_sha256"], "original selection manifest differs")
    manifest = common.strict_json(manifest_bytes)
    allowed = {row["test_id"]: row for row in manifest["allowed_portable_skips"]}
    require(len(allowed) == len(manifest["allowed_portable_skips"]), "duplicate declared skip")
    require(len({row["test_id"] for row in suite["skips"]}) == len(suite["skips"]), "duplicate original skip")
    require(all(row["test_id"] in allowed and row["reason"] == allowed[row["test_id"]]["reason"]
                and allowed[row["test_id"]]["acceptance_claim"] is False for row in suite["skips"]),
            "original skip is outside unchanged declared policy")
    require(suite["portable_skip_audit"] == sorted((allowed[row["test_id"]] for row in suite["skips"]),
                                                   key=lambda row: row["test_id"]), "original strict skip audit differs")
    before = snapshot(SOURCE / "original/tracked-source.before.json")[0]
    after = snapshot(SOURCE / "original/tracked-source.after.json")[0]
    require(before == after, "original harness tracked source bytes differ")
    observer = document("original/external-test-observer/terminal.v1.json")
    require(observer["returncode"] == 1 and observer["successful"] is False,
            "original observer failure differs")
    mount_before = snapshot(SOURCE / "global-mountinfo.before.txt")[0]
    mount_after = snapshot(SOURCE / "global-mountinfo.after.txt")[0]
    require(mount_before != mount_after, "original stopped outer mount comparison is unexpectedly equal")
    require(not os.path.lexists(SOURCE / "global-mountinfo.sha256.txt"), "unexpected post-comparison outer marker exists")
    return {"source_commit": COMMIT, "original_outer_session": 44214, "original_parent_return_code": 1,
            "tests_run": 3291, "successful_test_count": 3202, "failure_count": 2, "error_count": 1,
            "skip_count": 86, "strict_skip_ids_reasons_and_audit_match_original_manifest": True,
            "selection_manifest_sha256": selection["manifest_sha256"], "selection_counts": selection["counts"],
            "failure_test_ids": [row["test_id"] for row in suite["failures"]],
            "error_test_ids": [row["test_id"] for row in suite["errors"]],
            "tracked_before_after_bytes_equal": True,
            "tracked_source_inventory_sha256": hashlib.sha256(before).hexdigest(),
            "harness_raw_checkout_bytes_match_commit": True, "harness_changed_tracked_paths": [],
            "observer_original_child_return_code": 1, "outer_whole_mount_equal": False,
            "outer_post_comparison_final_source_gate_executed": False,
            "finished_timestamp": snapshot(SOURCE / "finished.txt")[0].decode("ascii").strip(),
            "integration_executed": False, "hardware_acceptance": False, "campaign_authority": False}


def literal_paths():
    return (tuple(PurePosixPath(name) for name in CONTROL_FILES)
            + tuple(PurePosixPath("original") / name for name in REPORT_FILES)
            + tuple(PurePosixPath("original/namespace-diagnostic") / name for name in NAMESPACE_FILES)
            + tuple(PurePosixPath("original/external-test-observer") / name for name in OBSERVER_FILES)
            + tuple(PurePosixPath("original/model-acquisition") / name for name in MODEL_FILES))


def plan():
    common.assert_source()
    require(HERE.resolve(strict=True) == HERE and SOURCE.resolve(strict=True) == SOURCE, "retention root is aliased")
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "ext4 retention destination exists")
    state = original_state()
    rows = []
    for relative in sorted(literal_paths()):
        path = SOURCE.joinpath(*relative.parts)
        payload, physical_epoch = snapshot(path)
        rows.append({"source": str(path), "retained": relative.as_posix(), "size_bytes": len(payload),
                     "sha256": hashlib.sha256(payload).hexdigest(), "physical_epoch": physical_epoch})
    total = sum(row["size_bytes"] for row in rows)
    require(len(rows) == 76 and total <= common.TOTAL_LIMIT, "ext4 retention is not bounded literal76")
    common.assert_source()
    return {"artifact_kind": "vast_ext4_original_result_retention_plan_v1", "schema_version": 1,
            "source_commit": COMMIT, "source_output": str(SOURCE), "retention_output": str(OUTPUT),
            "catalogue": str(CATALOGUE), "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "snapshot_helper_sha256": COMMON_SHA, "original_state": state, "files": rows,
            "file_count": len(rows), "total_bytes": total, "source_read_only": True,
            "campaign_authority": False, "original_full_suite_passed": False,
            "exclusions": ["Compiled build trees and binaries", "Copied model/corpus/runtime/input trees",
                           "Any subsequent source or full-suite retry", "Consumer fixtures",
                           "Independent follow-up source proof, which remains a separately attributed observation"],
            "limits": ["The original suite and outer wrapper remain failed.",
                       "Original whole-mount comparison failed before the wrapper's final source/byte gate.",
                       "Harness source inventories are retained exactly; no stopped outer gate is retroactively asserted."]}


def apply(plan_path, reviewed_sha):
    require(len(reviewed_sha) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha), "invalid review SHA")
    payload = plan_path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha, "reviewed ext4 plan bytes differ")
    reviewed = common.strict_json(payload)
    require(plan() == reviewed, "completed ext4 bytes, epochs or plan changed")
    OUTPUT.mkdir(mode=0o700)
    for row in reviewed["files"]:
        source = Path(row["source"])
        data, physical_epoch = snapshot(source)
        require(physical_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"],
                "source changed before retention")
        target = OUTPUT.joinpath(*PurePosixPath(row["retained"]).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(target.parent.resolve(strict=True) == target.parent, "retention parent is aliased")
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(snapshot(source) == (data, physical_epoch) and snapshot(target)[0] == data,
                "retained ext4 bytes or source epochs differ")
    for row in reviewed["files"]:
        data, physical_epoch = snapshot(Path(row["source"]))
        require(physical_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"],
                "original source changed during retention")
    common.assert_source()
    catalogue = dict(reviewed, artifact_kind="vast_ext4_original_result_retention_v1",
                     status="retained_exactly", reviewed_plan_sha256=reviewed_sha)
    with CATALOGUE.open("xb") as stream:
        stream.write(common.canonical(catalogue))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "retained_exactly", "file_count": reviewed["file_count"], "total_bytes": reviewed["total_bytes"],
            "reviewed_plan_sha256": reviewed_sha, "catalogue_sha256": hashlib.sha256(CATALOGUE.read_bytes()).hexdigest(),
            "original_full_suite_passed": False, "campaign_authority": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    args = parser.parse_args()
    require(args.mode == "plan" or (args.plan and args.reviewed_plan_sha256), "apply requires reviewed plan and SHA")
    result = plan() if args.mode == "plan" else apply(args.plan, args.reviewed_plan_sha256)
    print(common.canonical(result).decode("ascii"), end="")


if __name__ == "__main__":
    main()
