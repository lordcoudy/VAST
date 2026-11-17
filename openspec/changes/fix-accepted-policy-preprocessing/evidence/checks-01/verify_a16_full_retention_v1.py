#!/usr/bin/env python3
"""Independent bounded byte/epoch audit; no retainer imports or source writes."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import traceback


HERE = Path(__file__).resolve().parent
COMMIT = "a16f243e7e80f093342ccdddf717d59d6d46f0a8"
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + COMMIT)
CI = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-" + COMMIT)
OUTPUT = HERE / "a16-full-originals"
PLAN = HERE / "a16-full-originals.retention-plan.v1.json"
CATALOGUE = HERE / "a16-full-originals.v1.json"
CONTROL = HERE / "a16-full-independent-control-01"
PYTHON = "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python"
PLAN_SHA = "e7ed026de152f1e2f3e2472669c87db66eaa937e5b970909a82d8c846a66ee19"
SUBJECTS = {
    "retain_a16_full_originals.py": "ad27c8fdbd8823b20ba363bfbbe9dab1d4805e3d3b3c0508d4e300adc9fc742d",
    "retain_a16_completed_originals.py": "65fb7ef980246e1fd5b8054a4eaad6c04e6015928523532420c9f5e37bc68941",
    "run_a16_full_retention_apply_v1.py": "c8c43968bc602a3edf02980841a1946a7526f42ab4d630809d851e74c817d928",
}
EPOCH_FIELDS = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def epoch(info):
    return {name: int(getattr(info, name)) for name in EPOCH_FIELDS}


def held_read(path):
    require(path.is_absolute() and path.resolve(strict=True) == path, "noncanonical audit path")
    for ancestor in (path, *path.parents):
        require(not stat.S_ISLNK(ancestor.lstat().st_mode), "linked audit ancestor")
    initial = path.lstat()
    require(stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1 and initial.st_size <= 16 * 1024 * 1024, "nonplain/oversized audit file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(epoch(os.fstat(stream.fileno())) == epoch(initial), "audit file changed before read")
        payload = stream.read(16 * 1024 * 1024 + 1)
        require(epoch(os.fstat(stream.fileno())) == epoch(initial), "audit file changed during read")
    require(len(payload) == initial.st_size and epoch(path.lstat()) == epoch(initial), "audit file changed after read")
    return payload, epoch(initial)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload):
    def pairs(rows):
        result = {}
        for name, value in rows:
            require(name not in result, "duplicate audit JSON key")
            result[name] = value
        return result
    return json.loads(payload.decode("ascii"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite audit JSON: " + value)))


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("ascii")


def source_observations():
    observations = []
    for root in (ROOT, CI):
        require(root.resolve(strict=True) == root, "current source root aliased")
        for tail, expected in ((["rev-parse", "HEAD"], (COMMIT + "\n").encode("ascii")),
                               (["status", "--porcelain=v1", "--untracked-files=no"], b"")):
            argv = ["git", "--no-optional-locks", "-C", str(root), *tail]
            result = subprocess.run(argv, capture_output=True, check=False)
            require(result.returncode == 0 and result.stdout == expected and result.stderr == b"", "current HEAD/status check failed")
            observations.append({"argv": argv, "original_exit_code": result.returncode,
                                 "stdout_ascii": result.stdout.decode("ascii"), "stderr_ascii": result.stderr.decode("ascii")})
    return observations


def audit():
    require(HERE == Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01"), "audit origin differs")
    before_observations = source_observations()
    plan_raw, _ = held_read(PLAN)
    require(digest(plan_raw) == PLAN_SHA, "reviewed plan bytes differ")
    plan = strict_json(plan_raw)
    require(plan["source_commit"] == COMMIT and plan["retention_output"] == str(OUTPUT) and plan["catalogue"] == str(CATALOGUE), "catalogue/plan origins differ")
    for name, expected in SUBJECTS.items():
        require(digest(held_read(HERE / name)[0]) == expected, "sealed helper changed")
    catalogue_raw, _ = held_read(CATALOGUE)
    catalogue = strict_json(catalogue_raw)
    expected_catalogue = dict(plan, artifact_kind="vast_a16_full_original_retention_v1", status="retained_exactly", reviewed_plan_sha256=PLAN_SHA)
    require(catalogue == expected_catalogue and catalogue_raw == encoded(expected_catalogue), "catalogue fields/bytes differ")
    rows = plan["files"]
    refs = plan["existing_managed_outer_controls_untouched"]
    require(len(rows) == 82 and len(refs) == 8 and len({item["source"] for item in rows + refs}) == 90
            and sum(item["size_bytes"] for item in rows) == 13115499, "finite inventory differs")
    expected_files, expected_dirs, targets = set(), {OUTPUT}, []
    for item in rows:
        relative = PurePosixPath(item["retained"])
        require(not relative.is_absolute() and all(part not in ("", ".", "..") for part in relative.parts), "unsafe audit target")
        target = OUTPUT.joinpath(*relative.parts)
        require(str(target) == item["target"] and target.is_relative_to(OUTPUT), "target differs from reviewed literal path")
        original, physical_epoch = held_read(Path(item["source"]))
        require(physical_epoch == item["physical_epoch"] and len(original) == item["size_bytes"] and digest(original) == item["sha256"], "original bytes/epoch differ")
        retained, retained_epoch = held_read(target)
        require(retained == original, "retained bytes differ")
        expected_files.add(target)
        expected_dirs.update(parent for parent in target.parents if parent.is_relative_to(OUTPUT))
        targets.append({"path": str(target), "sha256": digest(retained), "size_bytes": len(retained), "physical_epoch": retained_epoch})
    require(len(expected_files) == 82, "duplicate retained target")
    actual_files, actual_dirs = set(), set()
    for parent, dirs, files in os.walk(OUTPUT, followlinks=False):
        require(len(actual_files) <= 82 and len(actual_dirs) <= 82, "retention namespace exceeds bounded inventory")
        directory = Path(parent)
        actual_dirs.add(directory)
        require(directory.resolve(strict=True) == directory and stat.S_ISDIR(directory.lstat().st_mode), "retained directory is not plain")
        for name in dirs:
            require(not stat.S_ISLNK((directory / name).lstat().st_mode), "retained directory symlink")
        actual_files.update(directory / name for name in files)
    require(actual_files == expected_files and actual_dirs == expected_dirs, "extra/missing retained filesystem entries")
    for item in rows + refs:
        original, physical_epoch = held_read(Path(item["source"]))
        require(physical_epoch == item["physical_epoch"] and len(original) == item["size_bytes"] and digest(original) == item["sha256"], "original/reference changed during independent audit")
    for name, expected in SUBJECTS.items():
        require(digest(held_read(HERE / name)[0]) == expected, "sealed helper changed during independent audit")
    after_observations = source_observations()
    return {"kind": "vast_a16_full_retention_independent_audit_v1", "passed": True, "source_commit": COMMIT,
            "reviewed_plan_sha256": PLAN_SHA, "catalogue_sha256": digest(catalogue_raw), "retained_file_count": 82,
            "retained_total_bytes": 13115499, "unchanged_original_reference_count": 90, "no_extra_files_or_directories": True,
            "all_files_plain_single_link": True, "original_epochs_unchanged": True, "targets": targets,
            "current_head_status_before": before_observations, "current_head_status_after": after_observations,
            "new_live_12115_raw_source_acceptance_gate_executed": False, "campaign_authority": False}


def capture():
    require(not os.path.lexists(CONTROL) and CONTROL.resolve(strict=False) == CONTROL, "independent control exists/aliased")
    CONTROL.mkdir(mode=0o700)
    command = [PYTHON, "-B", str(Path(__file__).resolve())]
    with (CONTROL / "command.json").open("xb") as stream:
        stream.write(encoded(command))
    started = datetime.now(timezone.utc).isoformat()
    interruptions = []
    with (CONTROL / "original.stdout.raw").open("xb") as stdout, (CONTROL / "original.stderr.raw").open("xb") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        while True:
            try:
                actual_rc = child.wait()
                break
            except BaseException as error:
                interruptions.append({"utc": datetime.now(timezone.utc).isoformat(), "type": type(error).__name__,
                                      "message": str(error), "traceback": traceback.format_exc()})
    finished = datetime.now(timezone.utc).isoformat()
    with (CONTROL / "original.result.json").open("xb") as stream:
        stream.write(encoded({"started_utc": started, "finished_utc": finished, "original_exit_code": actual_rc,
            "command": command, "interruptions": interruptions, "streams": {name: {"size_bytes": len(held_read(CONTROL / name)[0]),
                      "sha256": digest(held_read(CONTROL / name)[0])} for name in ("original.stdout.raw", "original.stderr.raw")}}))
    require(actual_rc == 0 and not interruptions, "independent audit/capture failed; original result preserved")
    result = strict_json(held_read(CONTROL / "original.stdout.raw")[0])
    return {"status": "closed", "original_exit_code": actual_rc, "control": str(CONTROL),
            "catalogue_sha256": result["catalogue_sha256"], "retained_file_count": result["retained_file_count"],
            "retained_total_bytes": result["retained_total_bytes"], "campaign_authority": False}


if __name__ == "__main__":
    require(sys.executable == PYTHON and not sys.flags.optimize and os.getuid() == os.getgid() == 1000
            and os.environ["HOME"] == "/home/s-a-balashov", "independent audit runtime differs")
    require(sys.argv[1:] in ([], ["--capture"]), "unexpected audit argv")
    print(encoded(capture() if sys.argv[1:] else audit()).decode("ascii"), end="")
