#!/usr/bin/env python3
"""Independent read-only verification of failed consumer08 retention."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys


HERE = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01")
PLAN = HERE / "consumer08-originals.retention-plan.v1.json"
HELPER = HERE / "retain_consumer08_originals.py"
COMMON = HERE.parent / "checks-01/retain_a16_completed_originals.py"
OUTPUT = HERE / "consumer08-originals"
CATALOGUE = HERE / "consumer08-originals.v1.json"
PLAN_SHA = "dcad9b5c4c766673370b64c13ef0e843d52ae12169f80901cc6859d9f987409e"
HELPER_SHA = "89eff34e1ff8222a4417187daf490a65b1b0293bde9cb37654995b039590ca2f"
COMMON_SHA = "65fb7ef980246e1fd5b8054a4eaad6c04e6015928523532420c9f5e37bc68941"
CATALOGUE_SHA = "f4cd5bee57a58fed5ad6c142c29d115e98e959a230a039ed344b728f4ebc0db4"
FIELDS = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def epoch(info):
    return {name: int(getattr(info, name)) for name in FIELDS}


def read(path):
    require(path.is_absolute() and path.resolve(strict=True) == path, "aliased absolute file")
    current = path
    while current != Path("/"):
        require(not stat.S_ISLNK(current.lstat().st_mode), "linked file/ancestor")
        current = current.parent
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 2 * 1024 * 1024,
            "file is not bounded single-link regular")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        require(epoch(os.fstat(stream.fileno())) == epoch(before), "file changed before read")
        payload = stream.read(2 * 1024 * 1024 + 1)
        require(epoch(os.fstat(stream.fileno())) == epoch(before), "file changed during read")
    require(epoch(path.lstat()) == epoch(before) and path.resolve(strict=True) == path and len(payload) == before.st_size,
            "file changed after read")
    return payload, epoch(before)


def main():
    require(os.getuid() == 1000 and os.environ.get("HOME") == "/home/s-a-balashov" and sys.dont_write_bytecode,
            "unexpected UID/HOME/bytecode mode")
    plan_raw = read(PLAN)[0]
    catalogue_raw = read(CATALOGUE)[0]
    require(hashlib.sha256(plan_raw).hexdigest() == PLAN_SHA and hashlib.sha256(read(HELPER)[0]).hexdigest() == HELPER_SHA,
            "reviewed helper/plan changed")
    require(hashlib.sha256(read(COMMON)[0]).hexdigest() == COMMON_SHA, "snapshot dependency changed")
    require(hashlib.sha256(catalogue_raw).hexdigest() == CATALOGUE_SHA, "reported catalogue file hash differs")
    plan = json.loads(plan_raw)
    catalogue = json.loads(catalogue_raw)
    require(plan["file_count"] == len(plan["files"]) == 28 and plan["total_bytes"] == 51804,
            "literal28 plan count/size differs")
    require(catalogue["status"] == "retained_exactly" and catalogue["reviewed_plan_sha256"] == PLAN_SHA
            and catalogue["helper_sha256"] == HELPER_SHA and catalogue["source_commit"] == plan["source_commit"]
            and catalogue["file_count"] == 28 and catalogue["total_bytes"] == 51804
            and catalogue["completed_state"] == plan["completed_state"] and catalogue["campaign_authority"] is False
            and catalogue["consumer_positive_asserted"] is False,
            "retention catalogue boundaries differ")
    original_rows = [*plan["files"], *plan["existing_managed_postmortem_references_untouched"]]
    require(len(original_rows) == 45 and len({row["source"] for row in original_rows}) == 45, "literal45 originals differ")
    for row in original_rows:
        payload, actual_epoch = read(Path(row["source"]))
        require(actual_epoch == row["physical_epoch"] and len(payload) == row["size_bytes"]
                and hashlib.sha256(payload).hexdigest() == row["sha256"], "original/reference bytes or epoch changed")
    expected_paths = set()
    expected_directories = set()
    target_total = 0
    for expected, retained in zip(plan["files"], catalogue["files"], strict=True):
        path = OUTPUT.joinpath(*PurePosixPath(expected["retained"]).parts)
        require(str(path) == expected["target"] and path.is_relative_to(OUTPUT), "literal target differs/escapes")
        require(retained == expected, "catalogue copied row differs")
        payload, _ = read(path)
        require(len(payload) == expected["size_bytes"] and hashlib.sha256(payload).hexdigest() == expected["sha256"],
                "retained bytes differ from reviewed original")
        expected_paths.add(path)
        target_total += len(payload)
        parent = path.parent
        while parent != OUTPUT:
            expected_directories.add(parent)
            parent = parent.parent
    actual_paths = set()
    actual_directories = set()
    for path in OUTPUT.rglob("*"):
        require(path.resolve(strict=True) == path and not stat.S_ISLNK(path.lstat().st_mode), "linked retained tree member")
        if stat.S_ISDIR(path.lstat().st_mode):
            actual_directories.add(path)
        else:
            actual_paths.add(path)
    require(actual_paths == expected_paths and actual_directories == expected_directories and target_total == 51804,
            "retained inventory has missing/unplanned members")
    require(hashlib.sha256(read(PLAN)[0]).hexdigest() == PLAN_SHA and hashlib.sha256(read(HELPER)[0]).hexdigest() == HELPER_SHA
            and hashlib.sha256(read(CATALOGUE)[0]).hexdigest() == CATALOGUE_SHA
            and hashlib.sha256(read(COMMON)[0]).hexdigest() == COMMON_SHA, "plan/helper/catalogue drifted during proof")
    return {"passed": True, "source_commit": plan["source_commit"], "original_reference_files_verified": 45,
            "retained_files_verified": 28, "retained_bytes": target_total, "source_epochs_unchanged": True,
            "all_files_plain_single_link": True, "no_unplanned_retained_members": True,
            "live_raw12115_gate_executed": False, "consumer_positive_asserted": False,
            "catalogue_sha256": CATALOGUE_SHA, "plan_sha256": PLAN_SHA, "helper_sha256": HELPER_SHA,
            "campaign_authority": False, "limits": "Mechanical retention proof only; failed originals stay failed."}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True, indent=2) + "\n", end="")
