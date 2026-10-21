#!/usr/bin/env python3
"""Retain only reviewed completed check outputs, byte-exact and nonauthoritative."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess


HERE = Path(__file__).resolve().parent
COMMIT = "591a93e778a9a7839da6278326d215e24e91ea45"
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + COMMIT)
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a/checks-01"
OUTPUT = HERE / "completed-check-results"
CATALOGUE = HERE / "completed-check-results.v1.json"
FILE_LIMIT = 16 * 1024 * 1024
TOTAL_LIMIT = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("ascii")


def strict_json(payload):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("nonfinite JSON constant: " + value)

    require(len(payload) <= TOTAL_LIMIT, "JSON exceeds bound")
    return json.loads(payload.decode("ascii"), object_pairs_hook=pairs, parse_constant=reject)


def epoch(info):
    return {name: int(getattr(info, name)) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns",
    )}


def snapshot(path):
    require(path.is_absolute() and path.resolve(strict=True) == path, "aliased result path")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= FILE_LIMIT, "nonplain or oversized result")
    with path.open("rb") as stream:
        require(epoch(os.fstat(stream.fileno())) == epoch(info), "result changed before read")
        payload = stream.read(FILE_LIMIT + 1)
        require(epoch(os.fstat(stream.fileno())) == epoch(info), "result changed during read")
    require(len(payload) == info.st_size and epoch(path.lstat()) == epoch(info), "result changed after read")
    return payload, epoch(info)


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def assert_source():
    require(ROOT.resolve(strict=True) == ROOT and HERE.resolve(strict=True) == HERE, "noncanonical root")
    require(git("rev-parse", "HEAD") == (COMMIT + "\n").encode("ascii"), "source commit differs")
    require(git("status", "--porcelain=v1", "--untracked-files=no") == b"", "tracked source differs")


def literal_files():
    prefix = lambda value: value + "-" + COMMIT
    groups = {
        prefix("source-input-copy"): (
            "asset-copy.report.json", "asset-copy.stderr.log", "asset-copy.stdout.log",
            "fresh-copy.report.json", "fresh-copy.stderr.log", "fresh-copy.stdout.log",
            "independent-before-ext4.v1.json", "regression-copy.report.json",
            "regression-copy.stderr.log", "regression-copy.stdout.log",
        ),
        prefix("focused"): ("commit.txt", "finished.txt", "original.rc.txt", "original.stderr.log",
                             "original.stdout.log", "started.txt", "test-modules.txt"),
        prefix("focused") + "-02": ("commit.txt", "finished.txt", "original.rc.txt", "original.stderr.log",
                                     "original.stdout.log", "started.txt", "test-modules.txt"),
        prefix("final-source-inputs"): (
            "code-closure-cold.stdout.json", "code-closure-materialize.stdout.json", "execution-code-closure.v1.json",
            "external-helpers.sha256.txt", "finished.txt", "fresh-packaged-closure.inventory.v1.json",
            "native-worker.plan.json", "original.rc.txt", "original.stderr.log", "original.stdout.log",
            "source-commit.txt", "source-comparison.v1.json", "started.txt",
        ),
        prefix("reconstruction-inputs-copy"): (
            "external-helper-plan.sha256", "finished.txt", "original.rc.txt", "original.stderr.log",
            "original.stdout.json", "source-commit.txt", "started.txt",
        ),
    }
    ids_path = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/integration-test-ids.txt"
    ids_payload, _ = snapshot(ids_path)
    require(ids_payload == git("show", COMMIT + ":" + ids_path.relative_to(ROOT).as_posix()), "integration IDs differ from commit")
    ids = ids_payload.decode("ascii").splitlines()
    require(len(ids) == len(set(ids)) == 9 and all("/" not in item and "\\" not in item for item in ids), "integration IDs are not exact9")
    common = ("commit.txt", "finished.txt", "integration-test-ids.txt", "results.txt", "started.txt")
    tests = tuple(item + suffix for item in ids for suffix in (".outcome.json", ".stderr.log", ".stdout.log"))
    groups[prefix("integration")] = common + tests
    groups[prefix("integration") + "-02"] = common + (
        "containers.after.txt", "containers.before.txt", "disk.before.txt", "docker-engine-id.txt",
        "gpu-compute.after.txt", "gpu-compute.before.txt",
    ) + tests
    return groups, ids


def plan():
    assert_source()
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CATALOGUE), "retention destination already exists")
    groups, ids = literal_files()
    states = {}
    for group in groups:
        directory = BASE / group
        require(directory.resolve(strict=True) == directory and stat.S_ISDIR(directory.lstat().st_mode), "nonplain completed group")
        if group.startswith("source-input-copy-"):
            review = strict_json(snapshot(directory / "independent-before-ext4.v1.json")[0])
            require(review["commit"] == COMMIT and review["tracked_clean"] is True
                    and review["raw_tracked_bytes_match_commit"] is True, "source-copy state differs")
            states[group] = {"completion_evidence": "independent-before-ext4.v1.json", "commit": COMMIT}
            continue
        marker = "source-commit.txt" if (directory / "source-commit.txt").is_file() else "commit.txt"
        require(snapshot(directory / marker)[0] == (COMMIT + "\n").encode("ascii"), "completed producer commit differs")
        require(snapshot(directory / "finished.txt")[0].strip(), "producer has no finish timestamp")
        state = {"completion_evidence": "finished.txt", "commit": COMMIT}
        if group.startswith("integration-"):
            require(snapshot(directory / "integration-test-ids.txt")[0].decode("ascii").splitlines() == ids, "executed integration selection differs")
            outcomes = [row.split(" ", 1) for row in snapshot(directory / "results.txt")[0].decode("ascii").splitlines()]
            require([row[1] for row in outcomes] == ids and all(row[0] in ("0", "1") for row in outcomes), "integration result rows differ")
            state["original_return_codes"] = [int(row[0]) for row in outcomes]
        else:
            code = snapshot(directory / "original.rc.txt")[0].strip().decode("ascii")
            require(code in ("0", "1"), "unsupported original return code")
            state["original_return_code"] = int(code)
        states[group] = state
    rows = []
    for group, names in sorted(groups.items()):
        for name in sorted(names):
            relative = PurePosixPath(group) / name
            path = BASE / relative
            payload, physical_epoch = snapshot(path)
            rows.append({"source": str(path), "retained": relative.as_posix(), "size_bytes": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest(), "physical_epoch": physical_epoch})
    require(sum(row["size_bytes"] for row in rows) <= TOTAL_LIMIT, "retention total exceeds 32 MiB")
    assert_source()
    return {"artifact_kind": "vast_completed_check_result_retention_plan_v1", "schema_version": 1,
            "source_commit": COMMIT, "source_base": str(BASE), "retention_output": str(OUTPUT),
            "catalogue": str(CATALOGUE), "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "groups": states, "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
            "files": rows, "source_read_only": True, "campaign_authority": False,
            "exclusions": ["Live ext4 full-suite outputs", "All consumer fixture attempts",
                           "Copied corpus, model, runtime and parity input trees", "Pre-existing retained evidence"],
            "limits": ["Failed originals and successful retries are retained separately without normalization.",
                       "Retention preserves bytes; it does not make failed checks pass or establish semantic acceptance."]}


def apply(plan_path, reviewed_sha):
    require(len(reviewed_sha) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha), "invalid review SHA")
    payload = plan_path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha, "reviewed plan bytes differ")
    reviewed = strict_json(payload)
    require(plan() == reviewed, "completed source epochs, bytes or retention plan changed")
    OUTPUT.mkdir(mode=0o700)
    report = []
    for row in reviewed["files"]:
        old = Path(row["source"])
        data, old_epoch = snapshot(old)
        require(old_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"], "source differs before copy")
        new = OUTPUT.joinpath(*PurePosixPath(row["retained"]).parts)
        new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(new.parent.resolve(strict=True) == new.parent, "retention parent is aliased")
        with new.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(snapshot(old) == (data, old_epoch) and snapshot(new)[0] == data, "copy or retained source drifted")
        report.append({"source": row["source"], "retained": new.relative_to(HERE).as_posix(),
                       "size_bytes": len(data), "sha256": row["sha256"], "source_physical_epoch": old_epoch})
    for row in reviewed["files"]:
        data, old_epoch = snapshot(Path(row["source"]))
        require(old_epoch == row["physical_epoch"] and hashlib.sha256(data).hexdigest() == row["sha256"], "source changed during retention")
    assert_source()
    catalogue = {"artifact_kind": "vast_completed_check_result_retention_v1", "status": "retained_exactly",
                 "source_commit": COMMIT, "reviewed_plan_sha256": reviewed_sha,
                 "helper_sha256": reviewed["helper_sha256"], "file_count": len(report), "total_bytes": reviewed["total_bytes"],
                 "groups": reviewed["groups"], "files": report, "source_read_only": True, "campaign_authority": False,
                 "exclusions": reviewed["exclusions"], "limits": reviewed["limits"]}
    with CATALOGUE.open("xb") as stream:
        stream.write(canonical(catalogue))
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": catalogue["status"], "file_count": len(report), "total_bytes": reviewed["total_bytes"],
            "reviewed_plan_sha256": reviewed_sha, "catalogue_sha256": hashlib.sha256(CATALOGUE.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--reviewed-plan-sha256")
    args = parser.parse_args()
    require(args.mode == "plan" or (args.plan and args.reviewed_plan_sha256), "apply requires reviewed plan and SHA")
    result = plan() if args.mode == "plan" else apply(args.plan, args.reviewed_plan_sha256)
    print(canonical(result).decode("ascii"), end="")


if __name__ == "__main__":
    main()
