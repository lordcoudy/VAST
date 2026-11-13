#!/usr/bin/env python3
"""Commit-bound v2 copy-only reconstruction inputs; no freeze or campaign authority."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys


DESTINATION_PREFIX = "/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-"
SOURCE_ROOTS = (
    Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a"),
    Path("/mnt/e/STUDY/VAST"),
)
TARGET = "data/videos/kpp/kpp_frozen_reconstruction_v1"
AUTHORITY_MODULES = (
    "kpp_frozen_reconstruction_v1_dataset",
    "freeze_kpp_frozen_reconstruction_v1",
    "freeze_kpp_iss_publication_v3",
    "freeze_kpp_legacy_iss_v2_transcodes",
    "extract_kpp_legacy_iss",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def destination_root(source_commit: str) -> Path:
    require(len(source_commit) == 40 and all(char in "0123456789abcdef" for char in source_commit),
            "invalid exact source commit")
    return Path(DESTINATION_PREFIX + source_commit)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode("ascii") + b"\n"


def strict_json(payload: bytes) -> dict:
    def pairs(rows: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError("nonfinite JSON: " + value)

    require(len(payload) <= 1024 * 1024, "plan exceeds 1 MiB")
    result = json.loads(payload.decode("ascii"), object_pairs_hook=pairs, parse_constant=reject_constant)
    require(type(result) is dict, "plan is not an object")
    return result


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix() == value, "noncanonical relative path")
    require(all(part not in ("", ".", "..") and ":" not in part for part in path.parts), "unsafe relative path")
    require(value.startswith(TARGET + "/"), "input is outside the exact reconstruction corpus")
    return path


def plain_root(root: Path) -> None:
    require(root.is_absolute() and root.resolve(strict=True) == root, "noncanonical root: " + str(root))
    require(stat.S_ISDIR(root.lstat().st_mode), "root is not a plain directory")


def plain_chain(root: Path, path: Path) -> None:
    plain_root(root)
    require(path.is_relative_to(root), "path escapes root")
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        info = current.lstat()
        require(not stat.S_ISLNK(info.st_mode), "linked input: " + str(current))
        require(current.resolve(strict=True) == current, "aliased input: " + str(current))
        if current != path:
            require(stat.S_ISDIR(info.st_mode), "non-directory input ancestor")


def fingerprint(info: os.stat_result) -> dict:
    return {name: int(getattr(info, name)) for name in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns",
    )}


def read_hash(root: Path, relative: str) -> dict:
    path = root.joinpath(*relative_path(relative).parts)
    plain_chain(root, path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "non-plain file: " + relative)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        require(fingerprint(os.fstat(stream.fileno())) == fingerprint(before), "input changed before read")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        require(fingerprint(os.fstat(stream.fileno())) == fingerprint(before), "input changed during read")
    require(fingerprint(path.lstat()) == fingerprint(before), "input changed after read")
    return {"path": relative, "size_bytes": before.st_size, "sha256": digest.hexdigest(),
            "physical_epoch": fingerprint(before)}


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def assert_source(root: Path, source_commit: str) -> None:
    require(root == destination_root(source_commit), "destination is not the exact commit-bound source root")
    plain_root(root)
    require(git(root, "rev-parse", "HEAD") == (source_commit + "\n").encode("ascii"), "destination source commit differs")
    require(git(root, "status", "--porcelain=v1", "--untracked-files=no") == b"", "destination tracked source is dirty")


def authority(root: Path, source_commit: str) -> tuple[object, dict]:
    assert_source(root, source_commit)
    sys.path.insert(0, str(root / "scripts"))
    modules = {name: importlib.import_module(name) for name in AUTHORITY_MODULES}
    hashes = {}
    for name, module in modules.items():
        relative = "scripts/" + name + ".py"
        path = root / relative
        plain_chain(root, path)
        require(Path(module.__file__).resolve(strict=True) == path, "authority module is not from frozen source")
        payload = path.read_bytes()
        require(payload == git(root, "show", source_commit + ":" + relative), "authority module differs from commit")
        hashes[relative] = hashlib.sha256(payload).hexdigest()
    return modules[AUTHORITY_MODULES[0]], hashes


def pinned_rows(gate: object) -> list[dict]:
    rows = []
    manifest = dict(gate.EXPECTED_MANIFEST_DESCRIPTOR)
    rows.append({"path": manifest["path"], "size_bytes": manifest["size_bytes"], "sha256": manifest["file_sha256"]})
    authorization = dict(gate.EXPECTED_AUTHORIZATION_DESCRIPTOR)
    rows.append({key: authorization[key] for key in ("path", "size_bytes", "sha256")})
    for codec in ("h264", "h265"):
        for role in ("underbody", "front_gate"):
            rows.append({key: gate._target_media(codec, role)[key] for key in ("path", "size_bytes", "sha256")})
    for descriptor in [*gate._installed_receipts(), *gate._source_documents().values()]:
        rows.append({key: descriptor[key] for key in ("path", "size_bytes", "sha256")})
    require(len(rows) == 12 and len({row["path"] for row in rows}) == 12, "stock input set is not exact12")
    return sorted(rows, key=lambda row: row["path"])


def validated_inventory(root: Path, gate: object, catalog: dict, expected: list[dict]) -> list[dict]:
    plain_root(root)
    # The h264 file gate validates all four media and the entire receipt tree.
    require(gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
        gate.DATASET_IDS["h264"], catalog[gate.DATASET_IDS["h264"]], project_root=root, require_files=True,
    ) is True, "stock full reconstruction gate refused")
    require(gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
        gate.DATASET_IDS["h265"], catalog[gate.DATASET_IDS["h265"]], project_root=root, require_files=False,
    ) is True, "stock h265 catalog gate refused")
    rows = [read_hash(root, row["path"]) for row in expected]
    require([{key: row[key] for key in ("path", "size_bytes", "sha256")} for row in rows] == expected,
            "physical bytes differ from stock descriptors")
    return rows


def assert_ignored_corpus(root: Path, expected: list[dict]) -> None:
    for row in expected:
        subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--", row["path"]],
                       check=True, capture_output=True)


def plan(root: Path, source_commit: str) -> dict:
    gate, hashes = authority(root, source_commit)
    import yaml
    catalog_path = root / "configs/datasets.yaml"
    plain_chain(root, catalog_path)
    catalog_bytes = catalog_path.read_bytes()
    require(catalog_bytes == git(root, "show", source_commit + ":configs/datasets.yaml"), "catalog differs from final source")
    catalog = yaml.safe_load(catalog_bytes)["datasets"]
    expected = pinned_rows(gate)
    assert_ignored_corpus(root, expected)
    inventories = {str(source): validated_inventory(source, gate, catalog, expected) for source in SOURCE_ROOTS}
    target = root.joinpath(*PurePosixPath(TARGET).parts)
    require(not os.path.lexists(target), "destination reconstruction corpus already exists")
    plain_chain(root, target.parent)
    assert_source(root, source_commit)
    return {
        "schema_version": 1, "artifact_kind": "vast_reconstruction_check_input_copy_plan_v2",
        "source_commit": source_commit, "destination_root": str(root), "selected_source_root": str(SOURCE_ROOTS[0]),
        "target_root": TARGET, "authority_source_sha256": hashes,
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "stock_file_count": 12, "total_bytes": sum(row["size_bytes"] for row in expected),
        "expected_stock_descriptors": expected, "validated_source_inventories": inventories,
        "copy_only": True, "historical_source_unchanged": True, "campaign_authority": False,
        "limits": ["Ignored check inputs only; no source, receipt, manifest or CI policy changes.",
                   "The stock corpus authorizes performance/topology publication only, not historical-v1 identity equivalence.",
                   "No freeze, media transformation, symlink, hardlink, overwrite or partial-run adoption is permitted."],
    }


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def apply_plan(plan_path: Path, reviewed_sha256: str, source_commit: str) -> dict:
    require(len(reviewed_sha256) == 64 and all(char in "0123456789abcdef" for char in reviewed_sha256), "invalid reviewed plan SHA")
    payload = plan_path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == reviewed_sha256, "reviewed plan bytes differ")
    reviewed = strict_json(payload)
    require(reviewed["source_commit"] == source_commit, "apply commit differs from reviewed plan commit")
    root = Path(reviewed["destination_root"])
    require(plan(root, source_commit) == reviewed, "source bytes, physical epochs or reviewed authority inputs changed")
    target = root.joinpath(*PurePosixPath(TARGET).parts)
    target.mkdir(mode=0o700)
    for directory in ("h264", "h265", "receipts"):
        (target / directory).mkdir(mode=0o700)
    rows = reviewed["validated_source_inventories"][reviewed["selected_source_root"]]
    source_root = Path(reviewed["selected_source_root"])
    for row in rows:
        source = source_root.joinpath(*relative_path(row["path"]).parts)
        destination = root.joinpath(*relative_path(row["path"]).parts)
        plain_chain(source_root, source)
        plain_chain(root, destination.parent)
        require(fingerprint(source.lstat()) == row["physical_epoch"], "source epoch changed before copy")
        require(not os.path.lexists(destination), "destination file already exists")
        digest = hashlib.sha256()
        total = 0
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            require(fingerprint(os.fstat(reader.fileno())) == row["physical_epoch"], "source changed before stream copy")
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                total += len(block)
                digest.update(block)
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
            require(fingerprint(os.fstat(reader.fileno())) == row["physical_epoch"], "source changed during copy")
        require(fingerprint(source.lstat()) == row["physical_epoch"], "source changed after copy")
        require(total == row["size_bytes"] and digest.hexdigest() == row["sha256"], "copied stream differs from stock byte pin")
        actual = read_hash(root, row["path"])
        require(actual["size_bytes"] == total and actual["sha256"] == row["sha256"], "destination bytes differ")
    for directory in ("h264", "h265", "receipts"):
        fsync_directory(target / directory)
    fsync_directory(target)
    fsync_directory(target.parent)
    gate, _ = authority(root, source_commit)
    import yaml
    catalog = yaml.safe_load((root / "configs/datasets.yaml").read_bytes())["datasets"]
    assert_ignored_corpus(root, reviewed["expected_stock_descriptors"])
    destination_rows = validated_inventory(root, gate, catalog, reviewed["expected_stock_descriptors"])
    # Re-read both source catalogs after copying; no source or receipt is rewritten.
    after = {str(source): validated_inventory(source, gate, catalog, reviewed["expected_stock_descriptors"]) for source in SOURCE_ROOTS}
    require(after == reviewed["validated_source_inventories"], "retained source changed during copy")
    assert_source(root, source_commit)
    return {"artifact_kind": "vast_reconstruction_check_input_copy_result_v2", "passed": True,
            "source_commit": source_commit, "reviewed_plan_sha256": reviewed_sha256,
            "copy_only": True, "file_count": len(destination_rows), "total_bytes": reviewed["total_bytes"],
            "stock_full_corpus_gate_passed": True, "retained_sources_byte_and_epoch_unchanged": True,
            "destination_inventory": destination_rows, "campaign_authority": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    commands = parser.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("plan")
    prepare.add_argument("--project-root", type=Path)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--reviewed-plan-sha256", required=True)
    args = parser.parse_args()
    root = destination_root(args.source_commit)
    result = (plan(args.project_root or root, args.source_commit) if args.mode == "plan"
              else apply_plan(args.plan, args.reviewed_plan_sha256, args.source_commit))
    sys.stdout.buffer.write(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
