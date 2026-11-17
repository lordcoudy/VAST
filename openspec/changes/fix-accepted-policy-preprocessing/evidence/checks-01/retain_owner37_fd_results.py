"""Literal14 retention of the completed child-local FD diagnosis after review."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
COMMON = HERE / "retain_completed_check_results.py"
COMMON_SHA = "01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed"
if hashlib.sha256(COMMON.read_bytes()).hexdigest() != COMMON_SHA:
    raise ValueError("reviewed retention primitives changed")
spec = importlib.util.spec_from_file_location("owner37_fd_retention_common", COMMON)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
require = common.require
SOURCE = Path("/var/tmp/vast-repair-owner37-fd-591a93e7-01")
OUTPUT = HERE / "completed-check-results/owner37-fd-591a93e7-01"
CATALOGUE = HERE / "owner37-fd-results.v1.json"
DIAGNOSTIC_SHA = "dc3d9eb3eee4530a6afa98752b31843f8c66531b587695f18b413d14ae4bfc1a"
CASE_FILES = ("child-before-import.json", "child-result.json", "fd-counts.jsonl",
              "parent-observation.json", "stderr.log", "stdout.log")
TEST = ("tests.test_publication_qualification_operational_owner_v1.QualificationOwner37Tests."
        "test_owner_executes_exact_37_and_binding_passes_cold_closure_with_real_validators")


def document(relative):
    return common.strict_json(common.snapshot(SOURCE / relative)[0])


def state():
    summary = document("summary.json")
    before_source = document("source-before.json")
    require(summary["commit"] == common.COMMIT and summary["helper_sha256"] == DIAGNOSTIC_SHA
            and summary["test_id"] == TEST and summary["qualification_authority"] is False
            and summary["source_mutations"] is False, "diagnosis provenance differs")
    require(before_source == summary["source_after"] and before_source["stock_raw_byte_verifier_passed"] is True
            and before_source["tracked_status"] == "" and before_source["tracked_paths_count"] == 11757,
            "before/after frozen source raw proof differs")
    cases = []
    for index, (soft, rc, peak) in enumerate(((1024, 1, 1007), (10240, 0, 1193))):
        prefix = "soft-" + str(soft) + "/"
        result = document(prefix + "child-result.json")
        observation = document(prefix + "parent-observation.json")
        before = document(prefix + "child-before-import.json")
        require(summary["cases"][index]["requested_soft_limit"] == soft
                and summary["cases"][index]["original_returncode"] == rc
                and observation["original_returncode"] == rc and observation["requested_soft_limit"] == soft,
                "original child limit or exit differs")
        require(result["tests_run"] == 1 and not result["skips"] and not result["failures"]
                and result["successful"] is (rc == 0)
                and len(result["errors"]) == rc and result["test_id"] == TEST,
                "actual unchanged single test terminal differs")
        if rc:
            require("[Errno 24] Too many open files" in result["errors"][0]["traceback"],
                    "original soft1024 refusal is not EMFILE")
        require(before["identity"]["nofile"] == [soft, 1048576] and before["fds"]["count"] == 3
                and [event["event"] for event in result["events"]] == ["startTest", "stopTest"]
                and [event["fds"]["count"] for event in result["events"]] == [10, 10]
                and result["after_runner_and_class_cleanup"]["fds"]["count"] == 8
                and observation["peak_observed"]["count"] == peak,
                "actual FD phase observations differ")
        cases.append({"soft": soft, "hard": 1048576, "original_child_returncode": rc,
                      "tests_run": 1, "skip_count": 0, "sampled_peak_lower_bound": peak,
                      "before_import": 3, "after_setup": 10, "after_test": 10, "after_class_cleanup": 8})
    return {"source_commit": common.COMMIT, "original_diagnostic_session": 79893, "cases": cases,
            "cold_join_fd_count_restored_on_both_paths": True,
            "warning": "Five guardian evidence directory FDs remain class-held until fixture destruction; not a cold-join leak.",
            "original_full_suite_passed": False, "qualification_authority": False}


def literal_paths():
    return [PurePosixPath(name) for name in ("source-before.json", "summary.json")] + [
        PurePosixPath("soft-" + str(soft)) / name for soft in (1024, 10240) for name in CASE_FILES]


def plan():
    common.assert_source()
    require(SOURCE.resolve(strict=True) == SOURCE and HERE.resolve(strict=True) == HERE, "retention root is aliased")
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "FD retention destination exists")
    paths = sorted(literal_paths())
    require(sorted(path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*") if path.is_file())
            == [path.as_posix() for path in paths], "diagnostic literal14 inventory differs")
    rows = []
    for relative in paths:
        path = SOURCE.joinpath(*relative.parts)
        payload, epoch = common.snapshot(path)
        rows.append({"source": str(path), "retained": relative.as_posix(), "size_bytes": len(payload),
                     "sha256": hashlib.sha256(payload).hexdigest(), "physical_epoch": epoch})
    total = sum(row["size_bytes"] for row in rows)
    require(len(rows) == 14 and total < 2 * 1024 * 1024, "retention exceeds literal14 bounded scope")
    value = {"artifact_kind": "vast_owner37_fd_result_retention_plan_v1", "schema_version": 1,
             "source_output": str(SOURCE), "retention_output": str(OUTPUT), "catalogue": str(CATALOGUE),
             "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "snapshot_helper_sha256": COMMON_SHA,
             "original_state": state(), "files": rows, "file_count": len(rows), "total_bytes": total,
             "source_read_only": True, "original_full_suite_passed": False, "qualification_authority": False}
    common.assert_source()
    return value


def apply(plan_path, reviewed_sha):
    require(len(reviewed_sha) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha), "invalid reviewed SHA")
    payload = plan_path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha, "reviewed FD plan bytes differ")
    reviewed = common.strict_json(payload)
    require(plan() == reviewed, "diagnostic bytes, epochs or scope changed")
    require(OUTPUT.parent.resolve(strict=True) == OUTPUT.parent, "retention parent is aliased")
    OUTPUT.mkdir(mode=0o700)
    for row in reviewed["files"]:
        source = Path(row["source"])
        data, epoch = common.snapshot(source)
        require(epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"], "source changed before copy")
        target = OUTPUT.joinpath(*PurePosixPath(row["retained"]).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(target.parent.resolve(strict=True) == target.parent, "target parent is aliased")
        with target.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(common.snapshot(source) == (data, epoch) and common.snapshot(target)[0] == data,
                "copied bytes or original epochs differ")
    for row in reviewed["files"]:
        data, epoch = common.snapshot(Path(row["source"]))
        require(epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"], "original changed during copy")
    common.assert_source()
    with CATALOGUE.open("xb") as stream:
        stream.write(common.canonical(dict(reviewed, artifact_kind="vast_owner37_fd_result_retention_v1",
                                          status="retained_exactly", reviewed_plan_sha256=reviewed_sha)))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "retained_exactly", "file_count": reviewed["file_count"], "total_bytes": reviewed["total_bytes"],
            "reviewed_plan_sha256": reviewed_sha, "catalogue_sha256": hashlib.sha256(CATALOGUE.read_bytes()).hexdigest(),
            "original_full_suite_passed": False, "qualification_authority": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    parser.add_argument("--plan-output", type=Path)
    args = parser.parse_args()
    require(args.mode == "plan" or (args.plan and args.reviewed_plan_sha256), "apply needs reviewed plan and SHA")
    value = plan() if args.mode == "plan" else apply(args.plan, args.reviewed_plan_sha256)
    raw = common.canonical(value)
    if args.plan_output:
        require(args.mode == "plan" and args.plan_output.parent.resolve(strict=True) == HERE,
                "generated plan must stay in managed evidence only")
        with args.plan_output.open("xb") as stream:
            stream.write(raw)
    print(raw.decode("ascii"), end="")


if __name__ == "__main__":
    main()
