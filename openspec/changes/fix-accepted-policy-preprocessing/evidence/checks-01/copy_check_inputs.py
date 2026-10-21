"""Recipe-only copier: reviewed immutable regression bytes, never execution authority."""

import csv
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def plain(path):
    if path.resolve(strict=True) != path:
        raise RuntimeError(f"noncanonical source or ancestry: {path}")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError(f"source is not plain single-link file: {path}")
    return info


def reviewed(path, expected):
    plain(path)
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None or digest(path) != expected:
        raise RuntimeError(f"unreviewed or changed catalog: {path}")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def safe_relative(value):
    path = Path(value)
    if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
        raise RuntimeError(f"noncanonical catalog path: {value}")
    return path


def main():
    mode, commit, catalog_sha, source_value, target_value, output_value, *rest = sys.argv[1:]
    if mode not in {"regression", "ext4", "assets"} or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError("exact frozen commit and supported copy mode required")
    recipes = Path(__file__).resolve().parent
    catalog = recipes / "regression-inputs.sha256-size-path.tsv"
    reviewed(catalog, catalog_sha)
    source, target, output = map(Path, (source_value, target_value, output_value))
    for root in (source, target):
        if root.resolve(strict=True) != root:
            raise RuntimeError("copy roots must be canonical existing directories")
    if source == target or output.exists():
        raise RuntimeError("copy roots/output must be separate and fresh")
    if git(target, "rev-parse", "HEAD") != commit or git(target, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("target commit or tracked cleanliness differs")
    if mode == "assets":
        if len(rest) != 2 or re.fullmatch(r"[0-9a-f]{40}", rest[1]) is None:
            raise RuntimeError("reviewed asset inventory and exact asset-source commit required")
        expected_source = rest[1]
    else:
        expected_source = "d1a78805dd41f9f946e3f6c4ca673bfeced228b5" if mode == "regression" else commit
    if git(source, "rev-parse", "HEAD") != expected_source:
        raise RuntimeError("source commit differs; no historical source mutation allowed")
    with catalog.open(newline="", encoding="ascii") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    if len(rows) != 31 or any(len(row) != 3 for row in rows):
        raise RuntimeError("exact 31 historical regression fixture files required")
    entries = []
    for sha, size, value in rows:
        relative = safe_relative(value)
        if not (value.startswith("artifacts/qualify_full_benchmark_20261008e/")
                or value.startswith("artifacts/deepstream_publication_v3/")):
            raise RuntimeError("historical regression catalog outside reviewed fixture roots")
        entries.append((relative, int(size), sha))
    if mode in {"ext4", "assets"}:
        if len(rest) != (1 if mode == "ext4" else 2):
            raise RuntimeError("reviewed asset inventory digest required for ext4 clone")
        if mode == "assets":
            entries = []
        asset_path = recipes.parent / "physical-01/asset-copy.inventory.v1.json"
        reviewed(asset_path, rest[0])
        assets = json.loads(asset_path.read_bytes())["files"]
        chosen = [row for row in assets if row["kind"] in {"omz", "parity_model", "kpp_corpus"}]
        if len(chosen) != 34:
            raise RuntimeError("exact 24 models and 10 corpus files required")
        for row in chosen:
            if row["source_relative"] != row["destination_relative"]:
                raise RuntimeError("model/corpus paths must remain unchanged")
            entries.append((safe_relative(row["destination_relative"]), row["size_bytes"], row["sha256"]))
    elif rest:
        raise RuntimeError("unexpected regression copy arguments")
    if len({row[0] for row in entries}) != len(entries):
        raise RuntimeError("duplicate input path")
    # Complete preflight precedes the first copy; no tracked path can be overwritten.
    for relative, size, sha in entries:
        src, dst = source / relative, target / relative
        if re.fullmatch(r"[0-9a-f]{64}", sha) is None or plain(src).st_size != size or digest(src) != sha:
            raise RuntimeError(f"changed immutable input: {relative}")
        if dst.exists() or dst.is_symlink() or dst.resolve(strict=False) != dst:
            raise RuntimeError(f"destination already exists or has aliased ancestry: {relative}")
        if relative.as_posix() in git(target, "ls-files", "--", relative.as_posix()).splitlines():
            raise RuntimeError(f"destination is tracked: {relative}")
        subprocess.run(["git", "-C", str(target), "check-ignore", "-q", "--", relative.as_posix()], check=True)
    copied = []
    for relative, size, sha in entries:
        src, dst = source / relative, target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as reader, dst.open("xb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
        if plain(dst).st_size != size or digest(dst) != sha or digest(src) != sha:
            raise RuntimeError(f"copy identity differs: {relative}")
        copied.append({"path": relative.as_posix(), "size_bytes": size, "sha256": sha})
    if git(target, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("tracked target changed during copy")
    output.write_text(json.dumps({"kind": "reviewed_regression_input_copy_v1",
        "commit": commit, "mode": mode, "catalog_sha256": catalog_sha,
        "source_root": str(source), "target_root": str(target), "copied_files": copied,
        "new_runtime_authority": False, "promoter_materializer_admission": False}, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
