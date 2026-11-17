#!/usr/bin/env python3
"""Retain literal completed failed-consumer originals after exact plan review."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
COMMON_PATH = HERE.parent / "checks-01/retain_completed_check_results.py"
COMMON_SHA = "01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed"
if hashlib.sha256(COMMON_PATH.read_bytes()).hexdigest() != COMMON_SHA:
    raise ValueError("reviewed retention primitives changed")
_spec = importlib.util.spec_from_file_location("completed_result_retention", COMMON_PATH)
common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(common)
require = common.require
COMMIT = common.COMMIT
ROOT = common.ROOT
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
READINESS = Path("/var/tmp/apf06-readiness-" + COMMIT)
OUTPUT = HERE / "failed-consumer-results"
CATALOGUE = HERE / "failed-consumer-results.v1.json"
FILE_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 4 * 1024 * 1024
STATE_FILES = (
    "source-head.before.txt", "source-head.after.txt",
    "source-tracked-status.before.txt", "source-tracked-status.after.txt",
)
CONTROL_FILES = STATE_FILES + ("run-plan.v1.json", "run-result.v1.json")
RUN_FILES = STATE_FILES + (
    "stdout.raw", "stderr.raw", "original-exit-code.txt",
    "started.v1.json", "finished.v1.json",
)
READINESS_FILES = (
    "before.stdout.raw", "before.stderr.raw", "before.result.v1.json",
    "after.stdout.raw", "after.stderr.raw", "after.result.v1.json",
    "check-only.stdout.raw", "check-only.stderr.raw", "check-only.result.v1.json",
)


def snapshot(path):
    require(path.lstat().st_size <= FILE_LIMIT, "consumer result exceeds 2 MiB")
    return common.snapshot(path)


def document(path):
    return common.strict_json(snapshot(path)[0])


def assert_states(directory):
    for name in STATE_FILES:
        expected = (COMMIT + "\n").encode("ascii") if "source-head." in name else b""
        require(snapshot(directory / name)[0] == expected, "retained source state differs")


def failure_states():
    states = {}
    for attempt in ("04", "06"):
        group = "consumer-complete-" + attempt + "-controls"
        run_name = "consumer-fixture-" + attempt + "-minimum30"
        directory, run_dir = BASE / group, BASE / group / run_name
        assert_states(directory)
        assert_states(run_dir)
        result = document(directory / "run-result.v1.json")
        require(result["source_commit"] == COMMIT and result["exit_code"] == 1
                and result["source_state_unchanged"] is True
                and result["both_complete_consumers_passed"] is False
                and result["campaign_authority"] is False
                and result["finished_utc"], "producer original is not the completed failed run")
        require(len(result["runs"]) == 1, "unexpected consumer execution count")
        finished = document(run_dir / "finished.v1.json")
        require(result["runs"][0] == finished and finished["name"] == run_name
                and finished["original_exit_code"] == 1
                and finished["samples_per_branch"] == 30
                and finished["expected_measured_sample_count"] == 3840
                and finished["complete_consumer_positive_asserted"] is False
                and finished["source_state_unchanged"] is True
                and finished["finished_utc"], "consumer terminal result differs")
        require(snapshot(run_dir / "original-exit-code.txt")[0] == b"1\n", "original exit code differs")
        for filename in ("stdout.raw", "stderr.raw"):
            payload = snapshot(run_dir / filename)[0]
            require(finished[filename] == {"size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest()}, "original stream hash differs")
        failure = document(BASE / run_name / "producer-failure.v2.json")
        require(failure["source_commit"] == COMMIT
                and failure["complete_consumer_positive_asserted"] is False
                and failure["campaign_authority"] is False
                and failure["physical_inference_observed"] is False
                and failure["samples_per_branch"] == 30
                and failure["expected_measured_sample_count"] == 3840
                and failure["error"] and failure["traceback"], "original failure record differs")
        states[group] = {"source_commit": COMMIT, "original_exit_code": 1,
                         "finished_utc": result["finished_utc"], "source_state_unchanged": True,
                         "both_complete_consumers_passed": False, "original_error": failure["error"]}
    for stage in ("before", "after", "check-only"):
        result = document(READINESS / (stage + ".result.v1.json"))
        require(result["original_exit_code"] == 0, "readiness original did not exit zero")
        for stream in ("stdout", "stderr"):
            require(result[stream + "_bytes"] == len(snapshot(READINESS / (stage + "." + stream + ".raw"))[0]),
                    "readiness original byte count differs")
        observed = document(READINESS / (stage + ".stdout.raw"))
        if stage == "check-only":
            require(observed["preflight_passed"] is True and observed["source_commit"] == COMMIT,
                    "consumer preflight report differs")
        else:
            require(observed["raw_committed_bytes_verified"] is True
                    and observed["verifier_path"] == str(ROOT / "scripts/run_ci_checks.py"),
                    "source-byte verifier report differs")
    states[READINESS.name] = {"before_original_exit_code": 0, "after_original_exit_code": 0,
                              "check_only_original_exit_code": 0,
                              "completion_evidence": "Original result/stream files plus completed attempt06; no invented timestamp.",
                              "consumer_positive_asserted": False}
    return states


def literal_paths():
    rows = []
    for attempt in ("04", "06"):
        group = "consumer-complete-" + attempt + "-controls"
        run_name = "consumer-fixture-" + attempt + "-minimum30"
        rows.extend((BASE / group / name, PurePosixPath(group) / name) for name in CONTROL_FILES)
        rows.extend((BASE / group / run_name / name, PurePosixPath(group) / run_name / name) for name in RUN_FILES)
        rows.append((BASE / run_name / "producer-failure.v2.json", PurePosixPath(run_name) / "producer-failure.v2.json"))
    rows.extend((READINESS / name, PurePosixPath(READINESS.name) / name) for name in READINESS_FILES)
    return rows


def plan():
    common.assert_source()
    require(HERE.resolve(strict=True) == HERE, "managed evidence parent is aliased")
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "consumer retention destination exists")
    for attempt, parent in (("05", "04"), ("07", "06")):
        name = "consumer-fixture-" + attempt + "-larger31"
        require(not os.path.lexists(BASE / name)
                and not os.path.lexists(BASE / ("consumer-complete-" + parent + "-controls") / name),
                "unexecuted larger fixture unexpectedly exists")
    states = failure_states()
    files = []
    for path, retained in sorted(literal_paths(), key=lambda row: row[1].as_posix()):
        payload, physical_epoch = snapshot(path)
        files.append({"source": str(path), "retained": retained.as_posix(),
                      "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                      "physical_epoch": physical_epoch})
    total = sum(row["size_bytes"] for row in files)
    require(len(files) == 41 and total <= TOTAL_LIMIT, "consumer retention is not the bounded literal41")
    common.assert_source()
    return {"artifact_kind": "vast_failed_consumer_result_retention_plan_v1", "schema_version": 1,
            "source_commit": COMMIT, "source_base": str(BASE), "readiness_source": str(READINESS),
            "retention_output": str(OUTPUT), "catalogue": str(CATALOGUE),
            "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "snapshot_helper_sha256": COMMON_SHA, "groups": states, "files": files,
            "file_count": len(files), "total_bytes": total,
            "source_read_only": True, "campaign_authority": False, "consumer_positive_asserted": False,
            "exclusions": ["Operational37 plans and raw runtime/native/input trees",
                           "Both execution-code-closure JSONs outside requested original controls/failure subset",
                           "Nonexistent larger attempts05/07", "Live ext4 full-suite outputs",
                           "Any new consumer/source snapshot"],
            "limits": ["Original attempts04/06 remain failed; retention does not grant semantic acceptance.",
                       "Observed readiness originals do not establish a complete consumer positive."]}


def apply(plan_path, reviewed_sha):
    require(len(reviewed_sha) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha), "invalid review SHA")
    payload = plan_path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha, "reviewed failed-consumer plan bytes differ")
    reviewed = common.strict_json(payload)
    require(plan() == reviewed, "failed-consumer source bytes, epochs or plan changed")
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
                "retained consumer bytes or source epochs differ")
    for row in reviewed["files"]:
        data, physical_epoch = snapshot(Path(row["source"]))
        require(physical_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"],
                "original source drifted during retention")
    common.assert_source()
    catalogue = dict(reviewed, artifact_kind="vast_failed_consumer_result_retention_v1",
                     status="retained_exactly", reviewed_plan_sha256=reviewed_sha)
    with CATALOGUE.open("xb") as stream:
        stream.write(common.canonical(catalogue))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": "retained_exactly", "file_count": reviewed["file_count"],
            "total_bytes": reviewed["total_bytes"], "reviewed_plan_sha256": reviewed_sha,
            "catalogue_sha256": hashlib.sha256(CATALOGUE.read_bytes()).hexdigest(),
            "consumer_positive_asserted": False, "campaign_authority": False}


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
