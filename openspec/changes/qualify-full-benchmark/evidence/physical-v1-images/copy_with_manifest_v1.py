#!/usr/bin/env python3
"""Copy git-ignored input trees into the exact-commit root with two-sided manifests (Amendment 2)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

SOURCE_ROOT = Path("/mnt/e/STUDY/VAST")
ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
OUT = ROOT / "artifacts/qualify_full_benchmark_20261007a/input_copies"


def manifest(top: Path) -> dict[str, dict]:
    rows = {}
    for directory, dirs, files in os.walk(top, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise SystemExit(f"refusing non-regular entry: {path}")
        for name in files:
            path = Path(directory) / name
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    h.update(chunk)
            rows[path.relative_to(top).as_posix()] = {"size_bytes": path.stat().st_size, "sha256": h.hexdigest()}
    return rows


def main() -> None:
    OUT.mkdir(mode=0o700, exist_ok=True)
    for tree in sys.argv[1:]:
        source, target = SOURCE_ROOT / tree, ROOT / tree
        assert source.is_dir() and not source.is_symlink(), tree
        before = manifest(source)
        (OUT / f"{tree}.source-manifest.v1.json").write_text(json.dumps({"root": str(source), "files": before}, sort_keys=True, indent=1) + "\n")
        if not target.exists():
            shutil.copytree(source, target, symlinks=True)
        else:  # partially tracked tree: existing files must already be byte-equal, the rest is copied
            existing = manifest(target)
            for relative, row in existing.items():
                if relative in before and before[relative] != row:
                    raise SystemExit(f"{tree}/{relative}: existing target differs from source")
            for relative in sorted(set(before) - set(existing)):
                (target / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, target / relative)
        after = manifest(target)
        (OUT / f"{tree}.target-manifest.v1.json").write_text(json.dumps({"root": str(target), "files": after}, sort_keys=True, indent=1) + "\n")
        if before != after:
            raise SystemExit(f"{tree}: manifests differ (extra={sorted(set(after)-set(before))[:5]} missing={sorted(set(before)-set(after))[:5]})")
        print(json.dumps({"tree": tree, "files": len(after), "bytes": sum(r["size_bytes"] for r in after.values()), "equal": True}))


if __name__ == "__main__":
    main()
