#!/usr/bin/env python3
"""B2: byte copies of NEW parity artifacts as .ci fixtures + rebound additional-origins pairs.

No fixture is string-edited. For every additional-origins entry whose original lies under the
20261008d artifact dir, the corresponding NEW original (same relative path under
qualify_full_benchmark_20261008e in the build root) is copied byte-for-byte to the mirrored
fixture path, verified by sha256, and the entry is rewritten from the NEW original's facts
(path, project root, lstat epoch, size, sha256). Old fixture copies are reported; removal is
done separately with `git rm` only when nothing references them.

v3 for task 6C.7 (Amendment 6). Usage: materialize_ci_fixtures_qfb_v2.py plan|apply
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST")
BUILD = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
ORIGINS = ROOT / ".ci/fixtures/additional-origins.v1.json"
FIXTURE_ROOT = ".ci/fixtures/gstreamer_fragment_unit_v1"
OLD_DIR = "artifacts/qualify_full_benchmark_20261008d/"
NEW_DIR = "artifacts/qualify_full_benchmark_20261008e/"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def facts(path: Path) -> tuple[bytes, list[int]]:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, f"single-link regular file: {path}")
    payload = path.read_bytes()
    after = path.lstat()
    epoch = [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
             info.st_mtime_ns, info.st_ctime_ns]
    require(epoch == [after.st_dev, after.st_ino, after.st_mode, after.st_nlink, after.st_size,
                      after.st_mtime_ns, after.st_ctime_ns] and len(payload) == info.st_size,
            f"unstable original: {path}")
    return payload, epoch


def main() -> None:
    require(sys.argv[1:] in (["plan"], ["apply"]), "usage: plan|apply")
    apply = sys.argv[1] == "apply"
    raw = ORIGINS.read_bytes()
    document = json.loads(raw)
    require((json.dumps(document, indent=2, sort_keys=True) + "\n").encode() == raw,
            "origins file is not in canonical indent=2 sorted form")
    rows = []
    copies = []
    for entry in document["files"]:
        if not entry["original_path"].startswith(OLD_DIR):
            continue
        require(entry["fixture_path"] == f"{FIXTURE_ROOT}/{entry['original_path']}",
                "unexpected fixture mirror layout")
        require(entry["encoding"] == "original_raw", "only raw fixtures are rebound")
        new_original = NEW_DIR + entry["original_path"][len(OLD_DIR):]
        payload, epoch = facts(BUILD / new_original)
        digest = hashlib.sha256(payload).hexdigest()
        new_fixture = f"{FIXTURE_ROOT}/{new_original}"
        replacement = dict(entry)
        replacement.update({
            "contains_crlf": b"\r\n" in payload,
            "fixture_path": new_fixture,
            "original_epoch": epoch,
            "original_path": new_original,
            "original_project_root": str(BUILD),
            "original_sha256": digest,
            "original_size_bytes": len(payload),
            "stored_sha256": digest,
            "stored_size_bytes": len(payload),
        })
        rows.append({"old": entry, "new": replacement})
        copies.append((ROOT / new_fixture, payload))
    require(len(rows) == 11, f"expected 11 rebound fixture entries, found {len(rows)}")
    index = json.loads(next(payload for path, payload in copies if path.name == "index.json"))
    bound = {path.name for path, _ in copies if path.parent.name == "bindings"} - {"index.json"}
    require(bound == {row["path"] for row in index["files"]}, "fixture subset differs from new index")
    replaced = {id(row["old"]): row["new"] for row in rows}
    document["files"] = [replaced.get(id(entry), entry) for entry in document["files"]]
    output = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    if apply:
        for path, payload in copies:
            require(not path.exists(), f"fixture already exists: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(payload)
            require(path.read_bytes() == payload, f"fixture copy differs: {path}")
        ORIGINS.write_bytes(output)
        require(ORIGINS.read_bytes() == output, "origins write differs")
    print(json.dumps({
        "status": "applied" if apply else "planned",
        "origins_before_sha256": hashlib.sha256(raw).hexdigest(),
        "origins_after_sha256": hashlib.sha256(output).hexdigest(),
        "entries": [{"old_fixture_path": row["old"]["fixture_path"],
                     "new_fixture_path": row["new"]["fixture_path"],
                     "new_original": f"{row['new']['original_project_root']}/{row['new']['original_path']}",
                     "old_sha256": row["old"]["original_sha256"], "new_sha256": row["new"]["original_sha256"],
                     "old_size_bytes": row["old"]["original_size_bytes"],
                     "new_size_bytes": row["new"]["original_size_bytes"],
                     "new_epoch": row["new"]["original_epoch"]} for row in rows],
    }, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
