#!/usr/bin/env python3
"""Hash-reviewed additive byte snapshots from fresh physical repair authorities."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BUILD = Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
OLD_DIR = "artifacts/qualify_full_benchmark_20261008e"
NEW_DIR = "artifacts/accepted_policy_repair_20261011a"
NS = "accepted-policy-repair-20261011a"
FIXTURES = ".ci/fixtures/gstreamer_fragment_unit_v1"
ORIGINS = ".ci/fixtures/additional-origins.v1.json"
PIN_PLAN = "openspec/changes/fix-accepted-policy-preprocessing/evidence/pins-01/host-pin-rebind.plan.v1.json"
CONFIGS = (
    f"configs/analytics_execution_layer.refreshed.v4.{NS}.json",
    f"configs/checkpoint_analytics_model_parity.refreshed.v4.{NS}.yaml",
    f"configs/checkpoint_analytics_model_parity.refreshed.v4.{NS}.accepted.yaml",
    f"configs/checkpoint_analytics_model_parity.refreshed.v4.{NS}.accepted.assessment.json",
    f"configs/checkpoint_analytics_model_parity.refreshed.v4.{NS}.accepted.acceptance_receipt.json",
)
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
COPY_SUFFIXES = ("bindings/index.json", "runtime_probes/cpu_runtime_probe.json",
                 "runtime_probes/gpu_runtime_probe.json") + tuple(
    f"bindings/{branch}.{engine}.json" for branch in BRANCHES
    for engine in ("openvino_cpu", "tensorrt_cuda"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def epoch(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


def physical(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    require(bool(relative) and pure.as_posix() == relative and not pure.is_absolute()
            and all(part not in {"", ".", ".."} for part in pure.parts), "unsafe relative input")
    path = root.joinpath(*pure.parts)
    require(path.resolve(strict=True) == path and all(not parent.is_symlink() for parent in (path, *path.parents)),
            "input path alias: " + str(path))
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 4 * 1024**2,
            "input is not a bounded single-link physical file: " + str(path))
    return path


def plan() -> tuple[dict, dict[tuple[str, str], tuple[bytes, dict]], bytes]:
    require(sys.flags.optimize == 0 and os.getuid() == 1000, "requires unoptimized WSL UID1000")
    require(ROOT.resolve(strict=True) == ROOT and BUILD.resolve(strict=True) == BUILD, "root alias")
    require(subprocess.check_output(["git", "-C", str(BUILD), "rev-parse", "HEAD"], text=True).strip()
            == COMMIT, "fresh build commit drifted")
    cache: dict[tuple[str, str], tuple[bytes, dict]] = {}

    def read(root: Path, relative: str) -> tuple[bytes, dict]:
        key = (str(root), relative)
        if key in cache:
            return cache[key]
        path = physical(root, relative)
        before = path.lstat()
        with path.open("rb") as stream:
            require(epoch(os.fstat(stream.fileno())) == epoch(before), "input replaced at open")
            raw = stream.read(4 * 1024**2 + 1)
            require(epoch(os.fstat(stream.fileno())) == epoch(before), "input changed while reading")
        require(epoch(physical(root, relative).lstat()) == epoch(before) and len(raw) == before.st_size,
                "input changed after reading")
        row = {"project_root": str(root), "path": relative, "size_bytes": len(raw),
               "sha256": sha(raw), "epoch": epoch(before)}
        cache[key] = (raw, row)
        return raw, row

    def document(root: Path, relative: str, seal: str | None = None) -> dict:
        raw, _row = read(root, relative)
        value = json.loads(raw, object_pairs_hook=pairs)
        require(type(value) is dict, "input JSON is not a mapping")
        if seal:
            require(value.get(seal) == sha(canonical({k: v for k, v in value.items() if k != seal})),
                    "input self-hash drifted: " + relative)
        return value

    def descriptor(value: dict) -> dict:
        _raw, observed = read(BUILD, value["path"])
        require(all(value[field] == observed[field] for field in ("path", "size_bytes", "sha256")),
                "fresh authority descriptor drifted: " + value["path"])
        return observed

    origins_raw, origins_before = read(ROOT, ORIGINS)
    origins = document(ROOT, ORIGINS)
    require(encode(origins) == origins_raw and origins["schema_version"] == 1
            and origins["artifact_kind"] == "vast_ci_additional_declared_metadata_fixture_origins_v1"
            and origins["fixture_only"] is True and origins["publication_eligible"] is False
            and origins["component_accepted"] is False and origins["current_media_model_image_authority"] is False,
            "origin schema/scope drifted")
    read(ROOT, ".ci/fixtures/origin-manifest.v1.json")
    old = {row["original_path"]: row for row in origins["files"]
           if row["original_path"].startswith(OLD_DIR + "/model_parity_v4/")}
    require(set(old) == {OLD_DIR + "/model_parity_v4/" + suffix for suffix in COPY_SUFFIXES},
            "expected exact eleven previous raw snapshots")
    require(len({row["fixture_path"] for row in origins["files"]}) == len(origins["files"])
            and len({row["original_path"] for row in origins["files"]}) == len(origins["files"]),
            "duplicate origin namespace")
    historical_fixtures = []
    for original, entry in sorted(old.items()):
        require(entry["fixture_path"] == FIXTURES + "/" + original and entry["encoding"] == "original_raw",
                "previous fixture layout drifted")
        _raw, facts = read(ROOT, entry["fixture_path"])
        require(facts["sha256"] == entry["stored_sha256"] == entry["original_sha256"]
                and facts["size_bytes"] == entry["stored_size_bytes"] == entry["original_size_bytes"],
                "previous fixture bytes drifted")
        historical_fixtures.append(facts)

    pins = document(ROOT, PIN_PLAN)
    require(pins["build_commit"] == COMMIT and pins["status"] == "planned" and len(pins["files"]) == 8,
            "paired eight-file pin plan drifted")
    require({row["path"] for row in pins["copied_configs"]} == set(CONFIGS), "pin config scope drifted")
    for row in pins["copied_configs"]:
        fresh_raw, fresh = read(BUILD, row["path"])
        copied_raw, copied = read(ROOT, row["path"])
        require(fresh_raw == copied_raw and all(fresh[key] == row[key] for key in ("sha256", "size_bytes")),
                "copied fresh config drifted: " + row["path"])

    # These original stock receipt readers perform no Docker or inference.
    sys.path.insert(0, str(BUILD / "scripts"))
    import publication_image_build_v1 as images
    import publication_qualification_image_refreeze_v1 as refreeze
    import publication_physical_io_v1 as physical_io
    for module in (images, refreeze, physical_io):
        require(Path(module.__file__).parent == BUILD / "scripts", "receipt reader import escaped fresh root")
        read(BUILD, "scripts/" + Path(module.__file__).name)
    registry = document(BUILD, refreeze.REGISTRY_RELATIVE_PATH)
    document(BUILD, refreeze.BUILD_REGISTRY_RELATIVE_PATH)
    for system in registry["systems"]:
        for field in ("dockerfile", "source_allowlist", "dependency_allowlist"):
            read(BUILD, system[field])
    patch_relative = NEW_DIR + "/qualification_image_identity_patch.json"
    patch = refreeze.load_identity_patch(project_root=BUILD, patch_path=BUILD / patch_relative)
    document(BUILD, patch_relative, "patch_sha256")
    descriptor(patch["build_registry"])
    descriptor(patch["refreeze_registry"])
    descriptor(patch["receipts"]["native_probe"])
    descriptor(patch["receipts"]["analytics_worker"])
    native_a = read(BUILD, NEW_DIR + "/native-a/native_probe.freeze.json")[0]
    native_b = read(BUILD, NEW_DIR + "/native-b/native_probe.freeze.json")[0]
    require(native_a == native_b, "native A/B receipt bytes differ")
    for name, group in (("native-a/native_probe.freeze.json", "native_probe"),
                        ("worker_images/analytics-worker.freeze.json", "analytics_worker")):
        path = physical(BUILD, NEW_DIR + "/" + name)
        value = images.load_publication_image_freeze_receipt(path)
        require(value["group"] == group, "native/worker receipt group drifted")
    runtime_ids = {}
    for system in SYSTEMS:
        row = patch["receipts"]["runtime_images"][system]
        descriptor(row)
        value = refreeze.load_runtime_image_receipt(BUILD / row["path"])
        require(value["system"] == system and value["candidate_binding_eligible"] is True
                and value["blockers"] == [], "fresh runtime receipt is ineligible")
        require(value["physical_identity"]["final_reference"].endswith(":" + NS), "fresh runtime tag differs")
        runtime_ids[system] = value["physical_identity"]["image_id"]
    selected = NEW_DIR + "/selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json"
    selected_raw, _selected_row = read(ROOT, selected)
    require(selected_raw == read(BUILD, patch["receipts"]["runtime_images"]["gstreamer_custom"]["path"])[0],
            "selected GStreamer copied receipt differs")

    binding_relative = NEW_DIR + "/model_parity_v4/acceptance_binding.v4.json"
    binding = document(BUILD, binding_relative, "binding_sha256")
    receipt_relative = CONFIGS[-1]
    receipt = document(BUILD, receipt_relative, "receipt_sha256")
    require(binding["artifact_kind"] == "vast_verified_model_parity_acceptance_binding_v4"
            and receipt["artifact_kind"] == "vast_checkpoint_model_parity_acceptance_receipt_v4"
            and binding["schema_version"] == receipt["schema_version"] == 4
            and receipt["status"] == "accepted_physical_model_parity_v4" and receipt["blockers"] == []
            and receipt["publication_ready"] is True and receipt["evidence_count"] == 32,
            "fresh parity receipt/binding state differs")
    for field in ("receipt", "accepted_assessment", "accepted_manifest", "transaction_index"):
        descriptor(binding[field])
    descriptor(binding["refresh_authority"]["image_identity_patch"])
    descriptor(binding["refresh_authority"]["execution_config"])
    require(binding["receipt"]["path"] == receipt_relative
            and binding["acceptance_identity_sha256"] == receipt["receipt_sha256"]
            and binding["refresh_authority"]["image_identity_patch"]["patch_sha256"] == patch["patch_sha256"],
            "parity/patch lineage differs")
    descriptor(binding["refresh_authority"]["binding_set"]["index"])
    for row in binding["refresh_authority"]["binding_set"]["bindings"].values():
        descriptor(row)
    for row in binding["refresh_authority"]["runtime_probes"].values():
        descriptor(row)

    audit_relative = NEW_DIR + "/independent_parity_audit_v1/audit.v1.json"
    audit = document(BUILD, audit_relative, "payload_sha256")
    require(audit["status"] == "verified" and audit["build_commit"] == COMMIT
            and audit["physical_execution_count"] == 480 and audit["groups"] == 32
            and audit["individual_tensor_files_bound"] == 960 and audit["execution_members_rehashed"] == 1920
            and audit["all_tensor_pairs_match_canonical_reference"] is True
            and audit["stock_cold_reader_calls"] == 1, "independent fresh audit differs")
    for field in ("acceptance_binding", "acceptance_receipt", "transaction_index"):
        descriptor(audit[field])
    audited = {row["path"]: row for row in audit["verified_physical_descriptors"]}

    rows, appended = [], []
    for suffix in COPY_SUFFIXES:
        original = NEW_DIR + "/model_parity_v4/" + suffix
        require(original in audited, "new snapshot absent from independent audit")
        observed = descriptor(audited[original])
        raw = read(BUILD, original)[0]
        fixture = FIXTURES + "/" + original
        require(not (ROOT / fixture).exists() and not (ROOT / fixture).is_symlink(), "fresh fixture already exists")
        previous = old[OLD_DIR + "/model_parity_v4/" + suffix]
        entry = dict(previous)
        entry.update(contains_crlf=b"\r\n" in raw, fixture_path=fixture,
                     original_epoch=observed["epoch"], original_path=original,
                     original_project_root=str(BUILD), original_sha256=observed["sha256"],
                     original_size_bytes=observed["size_bytes"], stored_sha256=observed["sha256"],
                     stored_size_bytes=observed["size_bytes"])
        appended.append(entry)
        rows.append({"source": observed, "fixture_path": fixture})
    index = document(BUILD, NEW_DIR + "/model_parity_v4/bindings/index.json")
    bound_names = {Path(row["source"]["path"]).name for row in rows
                   if "/bindings/" in row["source"]["path"]} - {"index.json"}
    require(len(index["files"]) == 8 and bound_names == {row["path"] for row in index["files"]},
            "fresh binding index copy coverage differs")
    for member in index["files"]:
        observed = read(BUILD, NEW_DIR + "/model_parity_v4/bindings/" + member["path"])[1]
        require(member["sha256"] == observed["sha256"] and member["bytes"] == observed["size_bytes"],
                "fresh binding index descriptor differs")
    replacement = dict(origins, files=origins["files"] + appended)
    origins_after = encode(replacement)
    require(replacement["files"][:len(origins["files"])] == origins["files"], "historical origins changed")
    report = {
        "artifact_kind": "vast_accepted_policy_repair_ci_fixture_plan_v1", "schema_version": 1,
        "status": "planned", "build_commit": COMMIT, "generator_sha256": sha(Path(__file__).read_bytes()),
        "project_root": str(ROOT), "physical_root": str(BUILD), "pin_plan_sha256": read(ROOT, PIN_PLAN)[1]["sha256"],
        "required_applied_pin_files": [{"path": row["file"], "sha256": row["after_sha256"]} for row in pins["files"]],
        "origins_before": origins_before, "origins_after_sha256": sha(origins_after),
        "origin_rows_before": len(origins["files"]), "origin_rows_after": len(replacement["files"]),
        "historical_origin_rows_preserved": True, "historical_fixture_files": historical_fixtures,
        "new_fixture_count": len(rows), "byte_copy_total": sum(row["source"]["size_bytes"] for row in rows),
        "new_fixtures": rows, "new_origin_entries": appended, "runtime_image_ids": runtime_ids,
        "identity_patch_candidate_binding_eligible": patch["candidate_binding_eligible"],
        "identity_patch_refresh_blockers": patch["blockers"],
        "accepted_parity_status": receipt["status"],
        "upstream_independent_audit_sha256": read(BUILD, audit_relative)[1]["sha256"],
        "inputs": [row for _raw, row in sorted(cache.values(), key=lambda item: (item[1]["project_root"], item[1]["path"]))],
        "fixture_only": True, "publication_eligible": False, "semantic_parity_replay_performed": False,
        "live_docker_observation_performed": False,
    }
    return report, cache, origins_after


def apply_reviewed(report: dict, cache: dict, origins_after: bytes, reviewed_sha: str) -> dict:
    require(sha(encode(report)) == reviewed_sha, "reviewed fixture plan hash drifted")
    require((HERE / "ci-fixtures.plan.v1.json").read_bytes() == encode(report), "saved fixture plan drifted")
    for row in report["required_applied_pin_files"]:
        require(sha(physical(ROOT, row["path"]).read_bytes()) == row["sha256"],
                "paired eight-file pin plan not yet applied: " + row["path"])
    for (root, relative), (raw, row) in cache.items():
        path = physical(Path(root), relative)
        require(epoch(path.lstat()) == row["epoch"] and sha(path.read_bytes()) == row["sha256"],
                "reviewed input changed before first fixture write")
    namespace = ROOT / FIXTURES / NEW_DIR
    require(not namespace.exists() and not namespace.is_symlink(), "fresh fixture namespace already exists")
    require(namespace.parent.resolve(strict=True) == namespace.parent, "fresh fixture parent alias")
    namespace.mkdir(mode=0o755)
    for row in report["new_fixtures"]:
        source = row["source"]
        raw = cache[(source["project_root"], source["path"])][0]
        target = ROOT / row["fixture_path"]
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(target.read_bytes() == raw, "new fixture byte copy differs")
    temporary = ROOT / ".ci/fixtures/additional-origins.accepted-policy-repair-20261011a.pending.json"
    with temporary.open("xb") as stream:
        stream.write(origins_after)
        stream.flush()
        os.fsync(stream.fileno())
    require(sha((ROOT / ORIGINS).read_bytes()) == report["origins_before"]["sha256"], "origin metadata changed before commit")
    os.replace(temporary, ROOT / ORIGINS)
    require((ROOT / ORIGINS).read_bytes() == origins_after, "additive origin metadata differs")
    for row in report["historical_fixture_files"]:
        require(sha(physical(ROOT, row["path"]).read_bytes()) == row["sha256"], "historical snapshot changed")
    for (root, relative), (raw, row) in cache.items():
        if root == str(ROOT) and relative == ORIGINS:
            continue
        require(sha(physical(Path(root), relative).read_bytes()) == row["sha256"], "preserved input changed by apply")
    return dict(report, status="applied", reviewed_plan_sha256=reviewed_sha)


def main() -> None:
    args = sys.argv[1:]
    require(args == ["plan"] or (len(args) == 2 and args[0] == "apply"), "usage: plan | apply REVIEWED_PLAN_SHA256")
    report, cache, origins_after = plan()
    if args[0] == "apply":
        report = apply_reviewed(report, cache, origins_after, args[1])
    print(encode(report).decode("ascii"), end="")


if __name__ == "__main__":
    main()
