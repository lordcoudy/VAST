#!/usr/bin/env python3
"""Plan finite retention of the naturally closed A16 full check originals."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
COMMON_PATH = HERE / "retain_a16_completed_originals.py"
COMMON_SHA = "65fb7ef980246e1fd5b8054a4eaad6c04e6015928523532420c9f5e37bc68941"
if hashlib.sha256(COMMON_PATH.read_bytes()).hexdigest() != COMMON_SHA:
    raise ValueError("reviewed A16 retention primitives changed")
_spec = importlib.util.spec_from_file_location("a16_completed_retention", COMMON_PATH)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require = common.require
COMMIT = common.COMMIT
ROOT = common.ROOT
CI = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-" + COMMIT)
SOURCE = common.BASE / ("ext4-" + COMMIT)
OUTER = HERE / "full-a16-control-01"
OUTPUT = HERE / "a16-full-originals"
CATALOGUE = HERE / "a16-full-originals.v1.json"
PLAN_PATH = HERE / "a16-full-originals.retention-plan.v1.json"
PLAN_CONTROLS = HERE / "a16-full-plan-control-01"
PYTHON = "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python"
RECIPE_REL = "openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/run_ext4_suite.sh"
RECIPE_SHA = "045cdded701dfb59100ce600344079f615a7be5991778befa4123eb209cb106d"
CAPTURE_SHA = "0e8d109c3311b49da75f5da281fe97f8ea1ae732706968c7d066355f9d38fd8f"
CATALOG_SHAS = (
    "8b9111ab5855bf73b0bac2532599b1a77d36235e05a544d0a08c47cdbcaac0e7",
    "b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d",
    "9b38ca696ee662bcd26f78a293f899fb6333b581670f486a5c9cfae4f9e48d45",
)
CONTROL_FILES = (
    "checkout.stderr.log", "checkout.stdout.log", "clone.stderr.log", "clone.stdout.log",
    "commit.txt", "finished.txt", "started.txt", "fresh-input-copy.report.json",
    "fresh-input-copy.stderr.log", "fresh-input-copy.stdout.log",
    "global-mountinfo.after.txt", "global-mountinfo.before.txt", "global-mountinfo.sha256.txt",
    "input-copy.report.json", "input-copy.stderr.log", "input-copy.stdout.log",
    "original-mount-namespace.txt", "parent.rc", "parent.stderr.log", "parent.stdout.log",
    "private-mount-namespace.txt", "privileged-launcher.txt", "runtime-mount.check.json",
    "runtime-mount.materialization.json", "runtime-source.mount.txt", "runtime-target.mount.txt",
    "sudo-prerequisite.stderr.log", "sudo-prerequisite.stdout.log", "ordinary-user-limits.json",
    "ci-user-limits.before.json", "ci-user-limits.after.json", "test-temporary-base.mount.txt",
    "test-temporary-base.stat.txt",
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
OUTER_FILES = (
    "command.json", "environment.json", "finished.txt", "original.rc.txt",
    "original.stderr.log", "original.stdout.log", "preflight.json", "started.txt",
)
REQUIRED_SUCCESSES = (
    "test_backend_publication_output_transaction_production_v3.BackendPublicationOutputTransactionProductionV3Tests.test_canonical_wsl_venv_requires_plain_copied_python",
    "test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_client_regression",
    "test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_policy_topology_regression",
    "test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_reset_queue_level_regression",
)
BUILT_TARGETS = (
    "vast_native_gst_probe", "vast_checkpoint_source", "gstadaptivescheduler",
    "gstvastanalyticsterminal", "gstvastanalyticsqueue", "gstvastcheckpointprefixqueue",
)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def data(path):
    return common.snapshot(path)[0]


def document(path):
    return common.strict_json(data(path))


def assert_sources():
    common.assert_source()
    require(HERE == common.HERE and SOURCE.resolve(strict=True) == SOURCE
            and CI.resolve(strict=True) == CI, "retention roots are aliased")
    require(subprocess.check_output(["git", "--no-optional-locks", "-C", str(CI),
                                     "rev-parse", "HEAD"]).strip() == COMMIT.encode("ascii"), "CI commit differs")
    require(subprocess.check_output(["git", "--no-optional-locks", "-C", str(CI), "status",
                                     "--porcelain=v1", "--untracked-files=no"]) == b"", "CI tracked source differs")


def timestamps(directory):
    start = data(directory / "started.txt").decode("ascii").strip()
    finish = data(directory / "finished.txt").decode("ascii").strip()
    parsed = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (start, finish)]
    require(all(value.utcoffset() is not None for value in parsed) and parsed[0] <= parsed[1], "original UTC order differs")
    return {"started_utc": start, "finished_utc": finish}


def original_state():
    require({item.name for item in OUTER.iterdir()} == set(OUTER_FILES), "closed outer8 inventory differs")
    require({item.name for item in SOURCE.iterdir() if item.is_file()} == set(CONTROL_FILES), "original root controls differ")
    require(data(SOURCE / "commit.txt") == (COMMIT + "\n").encode("ascii")
            and data(SOURCE / "parent.rc") == data(OUTER / "original.rc.txt") == b"0\n", "original RC/commit differs")
    recipe = data(ROOT / RECIPE_REL)
    require(digest(recipe) == RECIPE_SHA and common.git("show", COMMIT + ":" + RECIPE_REL) == recipe,
            "original committed recipe differs")
    require(digest(data(HERE / "run_full_a16_capture_v1.py")) == CAPTURE_SHA, "original outer capture helper differs")
    require(document(OUTER / "command.json") == ["/bin/bash", str(ROOT / RECIPE_REL), COMMIT, *CATALOG_SHAS], "outer argv differs")
    require(document(OUTER / "environment.json") == {"VAST_REPAIR_CHECK_ROOT": str(ROOT), "HOME": "/home/s-a-balashov",
            "USER": "s-a-balashov", "LOGNAME": "s-a-balashov"}, "outer environment differs")
    preflight = document(OUTER / "preflight.json")
    require(preflight == {"source_commit": COMMIT, "uid": 1000, "gid": 1000, "nofile": [10240, 1048576],
            "docker": "", "gpu": "", "source_actors": [], "ci_absent": True, "deep_out_absent": True,
            "unchanged_recipe_sha256": RECIPE_SHA}, "original preflight differs")
    require(document(OUTER / "original.stdout.log") == {"full_ext4_regression_checks": "passed", "commit": COMMIT,
            "tests_run": 3307, "approved_nonexecution_count": 86, "new_runtime_qualification": False}
            and data(OUTER / "original.stderr.log") == b"", "actual outer streams differ")
    outer_utc = timestamps(OUTER)
    recipe_utc = timestamps(SOURCE)
    report_raw = data(SOURCE / "original/report.json")
    require(digest(report_raw) == "31ff129bac45518957739888945c7d748a3ed1ceccc452c796a1f91cfe41e4b3", "original report bytes differ")
    report = common.strict_json(report_raw)
    suite = report["unittest"]
    require(report["commit"] == COMMIT and report["successful"] is True and report["raw_checkout_bytes_match_commit"] is True
            and report["changed_tracked_paths"] == [] and report["hardware_acceptance"] is False, "original report status differs")
    require(suite["tests_run"] == 3307 and suite["successful"] is True and len(suite["successful_test_ids"]) == 3221
            and len(suite["skips"]) == 86 and all(suite[name] == [] for name in
                ("failures", "errors", "expected_failures", "unexpected_successes", "missing_required_successes")), "original test counts differ")
    successes = suite["successful_test_ids"]
    require(len(set(successes)) == len(successes) and all(item in successes for item in REQUIRED_SUCCESSES), "required actual success differs")
    selection = suite["selection"]
    require(selection["counts"] == {"discovered": 3316, "integration": 9, "portable": 3307}
            and selection["integration_executed"] is False, "portable selection differs")
    manifest_raw = common.git("show", COMMIT + ":.ci/integration-test-selection.v1.json")
    require(digest(manifest_raw) == selection["manifest_sha256"] == "09e9268069e88b957f9ae54a827960bc18ee13a00d4319994d108d3cb81a0805",
            "original selection manifest differs")
    manifest = common.strict_json(manifest_raw)
    allowed = {row["test_id"]: row for row in manifest["allowed_portable_skips"]}
    require(len(allowed) == len(manifest["allowed_portable_skips"]) and len({row["test_id"] for row in suite["skips"]}) == 86,
            "duplicate declared/actual skip")
    require(all(row["test_id"] in allowed and row["reason"] == allowed[row["test_id"]]["reason"]
                and allowed[row["test_id"]]["acceptance_claim"] is False for row in suite["skips"]), "unapproved skip identity/reason")
    audit = sorted((allowed[row["test_id"]] for row in suite["skips"]), key=lambda row: row["test_id"])
    require(suite["portable_skip_audit"] == audit, "strict original skip audit differs")
    classifications = {key: sum(row["classification"] == key for row in audit) for key in sorted({row["classification"] for row in audit})}
    before = data(SOURCE / "original/tracked-source.before.json")
    require(before == data(SOURCE / "original/tracked-source.after.json"), "original tracked inventories differ")
    observer = document(SOURCE / "original/external-test-observer/terminal.v1.json")
    require(observer == report["observer"] and observer["returncode"] == 0 and observer["successful"] is True
            and observer["forced_sigkill"] is False and observer["forced_sigterm"] is False
            and observer["descendant_quiescence"] == "not established by original-child status", "original observer differs")
    mount_before = data(SOURCE / "global-mountinfo.before.txt")
    mount_sha = digest(mount_before)
    require(mount_before == data(SOURCE / "global-mountinfo.after.txt") and len(mount_before.splitlines()) == 261
            and mount_sha == "eeba47ce95f1968cfeeef091ea908a5cfacce874ba4569190e86385611e209d7", "whole global mount comparison differs")
    require(data(SOURCE / "global-mountinfo.sha256.txt") == "".join(mount_sha + "  " + str(SOURCE / name) + "\n"
            for name in ("global-mountinfo.before.txt", "global-mountinfo.after.txt")).encode("ascii"), "original mount hash marker differs")
    namespaces = [data(SOURCE / name).decode("ascii").strip() for name in ("original-mount-namespace.txt", "private-mount-namespace.txt")]
    require(namespaces[0] != namespaces[1] and all(re.fullmatch(r"mnt:\[[0-9]+\]", value) for value in namespaces), "private namespace differs")
    ordinary = document(SOURCE / "ordinary-user-limits.json")
    child_before = document(SOURCE / "ci-user-limits.before.json")
    child_after = document(SOURCE / "ci-user-limits.after.json")
    require(ordinary == {"uid": 1000, "gid": 1000, "nofile": [10240, 1048576],
            "source": "observed ordinary UID1000 caller, not a requested increase"}, "observed ordinary limits differ")
    require(child_before["uid"] == child_before["gid"] == child_after["uid"] == child_after["gid"] == 1000
            and child_before["nofile"] == [1024, 1048576] and child_after["nofile"] == ordinary["nofile"]
            and child_before["process_status"] == child_after["process_status"]
            and all(child_after["process_status"][name] == "0000000000000000" for name in ("CapInh", "CapPrm", "CapEff", "CapAmb")),
            "private child identity/capabilities/limit restoration differs")
    require(data(SOURCE / "test-temporary-base.stat.txt").decode("ascii").strip().split(":")[:3] == ["1777", "0", "0"]
            and data(SOURCE / "test-temporary-base.mount.txt").decode("ascii").startswith("/ ext4 "), "original /tmp custody differs")
    for name, status in (("runtime-mount.check.json", "verified"), ("runtime-mount.materialization.json", "materialized")):
        require(document(SOURCE / name) == {"artifact_kind": "vast_publication_runtime_mount_v1", "status": status,
                "source_read_only": True, "target_read_only": True}, "supported private read-only runtime mount differs")
    for name in ("native-build", "native-configure", "model-assets", "gstreamer-packages", "factory-appsrc", "factory-queue", "factory-videoconvert"):
        result = document(SOURCE / ("original/" + name + ".json"))
        require(result["returncode"] == 0 and result["timed_out"] is False and result["cleanup_error"] is None, "original native/prerequisite command differs")
    require(tuple(report["built_targets"]) == BUILT_TARGETS and len(report["python_syntax"]) == 535
            and len(report["bash_syntax"]) == 16 and report["elapsed_s"] == 2691.150726158987
            and report["namespace_profile"] == {"attempted": False, "load_verified": False, "status": "not_required", "unload_verified": False},
            "original native/syntax/profile facts differ")
    copies = [document(SOURCE / name) for name in ("input-copy.report.json", "fresh-input-copy.report.json")]
    require(all(row["commit"] == COMMIT and row["source_root"] == str(ROOT) and row["target_root"] == str(CI) for row in copies)
            and copies[0]["catalog_sha256"] == CATALOG_SHAS[0] and len(copies[0]["copied_files"]) == 65
            and copies[0]["new_runtime_authority"] is False and copies[0]["promoter_materializer_admission"] is False
            and copies[1]["catalog_sha256"] == CATALOG_SHAS[2] and len(copies[1]["copied_files"]) == 2473
            and len(copies[1]["fixture_observation_files"]) == 2 and copies[1]["copy_confers_qualification_authority"] is False,
            "original finite portable input copy differs")
    return {"source_commit": COMMIT, "original_outer_return_code": 0, "original_private_child_return_code": 0,
            "outer_utc": outer_utc, "recipe_utc": recipe_utc, "report_sha256": digest(report_raw),
            "original_full_suite_passed": True, "tests_run": 3307, "successful_test_count": 3221,
            "failure_count": 0, "error_count": 0, "skip_count": 86, "elapsed_s": report["elapsed_s"],
            "strict_skip_ids_reasons_audit_match_committed_manifest": True, "skip_classifications": classifications,
            "selection_counts": selection["counts"], "selection_manifest_sha256": digest(manifest_raw),
            "portable_integration_executed": False, "required_actual_successes": list(REQUIRED_SUCCESSES),
            "tracked_before_after_bytes_equal": True, "tracked_inventory_sha256": digest(before),
            "original_raw_checkout_bytes_match_commit": True, "original_changed_tracked_paths": [],
            "whole_global_mount_bytes_equal": True, "whole_global_mount_sha256": mount_sha, "whole_global_mount_rows": 261,
            "caller_mount_namespace": namespaces[0], "private_mount_namespace": namespaces[1],
            "private_uid_gid": [1000, 1000], "observed_ordinary_nofile": ordinary["nofile"],
            "private_nofile_before": child_before["nofile"], "private_nofile_after": child_after["nofile"],
            "private_child_hard_limit_unchanged": True, "private_child_capabilities_before_after_equal": True,
            "test_temporary_base": "/tmp", "native_built_targets": list(BUILT_TARGETS), "python_syntax_files": 535,
            "bash_syntax_files": 16, "namespace_profile": report["namespace_profile"],
            "observer_descendant_quiescence": observer["descendant_quiescence"], "hardware_acceptance": False,
            "portable_input_files": {"regression_and_assets": 65, "fresh": 2473, "fixture_observation_maps": 2}}


def literal_paths():
    return (tuple(PurePosixPath(name) for name in CONTROL_FILES)
            + tuple(PurePosixPath("original") / name for name in REPORT_FILES)
            + tuple(PurePosixPath("original/namespace-diagnostic") / name for name in NAMESPACE_FILES)
            + tuple(PurePosixPath("original/external-test-observer") / name for name in OBSERVER_FILES)
            + tuple(PurePosixPath("original/model-acquisition") / name for name in MODEL_FILES))


def row(path, relative=None):
    payload, physical_epoch = common.snapshot(path)
    result = {"source": str(path), "size_bytes": len(payload), "sha256": digest(payload), "physical_epoch": physical_epoch}
    if relative is not None:
        require(not relative.is_absolute() and all(part not in ("", ".", "..") for part in relative.parts), "unsafe retention path")
        result.update({"retained": relative.as_posix(), "target": str(OUTPUT.joinpath(*relative.parts))})
    return result


def plan():
    assert_sources()
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "finite retention destination exists")
    state = original_state()
    rows = [row(SOURCE.joinpath(*relative.parts), relative) for relative in sorted(literal_paths())]
    references = [row(OUTER / name) for name in OUTER_FILES]
    total = sum(item["size_bytes"] for item in rows)
    require(len(rows) == len({item["source"] for item in rows}) == len({item["target"] for item in rows}) == 82
            and total <= common.TOTAL_LIMIT, "finite82 retention bounds differ")
    for item in [*rows, *references]:
        payload, physical_epoch = common.snapshot(Path(item["source"]))
        require(physical_epoch == item["physical_epoch"] and digest(payload) == item["sha256"], "original changed during planning")
    assert_sources()
    return {"artifact_kind": "vast_a16_full_original_retention_plan_v1", "schema_version": 1,
            "source_commit": COMMIT, "source_output": str(SOURCE), "ci_root": str(CI), "retention_output": str(OUTPUT),
            "catalogue": str(CATALOGUE), "helper_sha256": digest(data(Path(__file__).resolve())),
            "snapshot_helper_sha256": COMMON_SHA, "original_state": state, "files": rows, "file_count": len(rows),
            "total_bytes": total, "per_file_limit_bytes": common.FILE_LIMIT, "total_limit_bytes": common.TOTAL_LIMIT,
            "existing_managed_outer_controls_untouched": references, "source_read_only": True, "campaign_authority": False,
            "exclusions": ["Native compiled build trees and binaries", "Copied model/corpus/runtime/native/tensor/input trees",
                           "Separate SOURCE physical-nine results and reconstruction corpus", "Every consumer output",
                           "Historical591 original results", "Existing managed outer8 controls (referenced, not recopied)",
                           "Absent namespace-profile files"],
            "limits": ["Retention is mechanical provenance, not complete-consumer acceptance, archive or Q1.",
                       "The portable report excludes the physical nine; their independent SOURCE execution is not inferred here.",
                       "Original observer explicitly does not establish descendant quiescence from original-child status.",
                       "No original command, stream, timestamp, result, metadata or epoch is rewritten or reconstructed.",
                       "Backing-capacity and failed consumer08 limitations are separate and remain unresolved by this check."]}


def apply(plan_path, reviewed_sha):
    require(re.fullmatch(r"[0-9a-f]{64}", reviewed_sha or "") is not None, "invalid reviewed plan SHA")
    payload = data(plan_path)
    require(digest(payload) == reviewed_sha, "reviewed plan bytes differ")
    reviewed = common.strict_json(payload)
    require(plan() == reviewed, "finite plan, original bytes, epochs or helper changed")
    OUTPUT.mkdir(mode=0o700)
    for item in reviewed["files"]:
        old, new = Path(item["source"]), Path(item["target"])
        original, physical_epoch = common.snapshot(old)
        require(physical_epoch == item["physical_epoch"] and digest(original) == item["sha256"], "original changed before retention")
        require(new.is_relative_to(OUTPUT) and not os.path.lexists(new), "retention target is not fresh/bounded")
        new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(new.parent.resolve(strict=True) == new.parent, "retention parent is aliased")
        with new.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        require(common.snapshot(old) == (original, physical_epoch) and data(new) == original, "original or retained bytes changed")
    for item in [*reviewed["files"], *reviewed["existing_managed_outer_controls_untouched"]]:
        original, physical_epoch = common.snapshot(Path(item["source"]))
        require(physical_epoch == item["physical_epoch"] and digest(original) == item["sha256"], "original/reference changed during retention")
    assert_sources()
    catalogue = dict(reviewed, artifact_kind="vast_a16_full_original_retention_v1", status="retained_exactly", reviewed_plan_sha256=reviewed_sha)
    with CATALOGUE.open("xb") as stream:
        stream.write(common.canonical(catalogue))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "retained_exactly", "file_count": len(reviewed["files"]), "total_bytes": reviewed["total_bytes"],
            "reviewed_plan_sha256": reviewed_sha, "catalogue_sha256": digest(data(CATALOGUE)), "campaign_authority": False}


def capture_plan():
    require(sys.executable == PYTHON and not sys.flags.optimize and os.getuid() == os.getgid() == 1000, "plan capture runtime differs")
    require(not os.path.lexists(PLAN_CONTROLS) and not os.path.lexists(PLAN_PATH), "plan/control output exists")
    PLAN_CONTROLS.mkdir(mode=0o700)
    command = [PYTHON, "-B", str(Path(__file__).resolve()), "plan"]
    started = datetime.now(timezone.utc).isoformat()
    with (PLAN_CONTROLS / "command.json").open("xb") as stream:
        stream.write(common.canonical(command))
    with (PLAN_CONTROLS / "original.stdout.raw").open("xb") as stdout, (PLAN_CONTROLS / "original.stderr.raw").open("xb") as stderr:
        child = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    finished = datetime.now(timezone.utc).isoformat()
    result = {"command": command, "started_utc": started, "finished_utc": finished, "original_exit_code": child.returncode,
              "source_commit": COMMIT, "retention_applied": False,
              "streams": {name: {"size_bytes": len(data(PLAN_CONTROLS / name)), "sha256": digest(data(PLAN_CONTROLS / name))}
                          for name in ("original.stdout.raw", "original.stderr.raw")}}
    with (PLAN_CONTROLS / "original.result.json").open("xb") as stream:
        stream.write(common.canonical(result))
    require(child.returncode == 0, "original plan generator failed; raw result preserved")
    payload = data(PLAN_CONTROLS / "original.stdout.raw")
    generated = common.strict_json(payload)
    with PLAN_PATH.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    require(data(PLAN_PATH) == payload, "plan retention bytes differ")
    return {"status": "plan_only", "original_exit_code": 0, "plan_sha256": digest(payload),
            "helper_sha256": generated["helper_sha256"], "file_count": generated["file_count"],
            "total_bytes": generated["total_bytes"], "controls": str(PLAN_CONTROLS), "retention_applied": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "capture-plan"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    args = parser.parse_args()
    require(not sys.flags.optimize, "optimized interpretation prohibited")
    require(args.mode != "apply" or (args.plan and args.reviewed_plan_sha256), "apply requires reviewed plan/hash")
    result = capture_plan() if args.mode == "capture-plan" else plan() if args.mode == "plan" else apply(args.plan, args.reviewed_plan_sha256)
    print(common.canonical(result).decode("ascii"), end="")


if __name__ == "__main__":
    main()
