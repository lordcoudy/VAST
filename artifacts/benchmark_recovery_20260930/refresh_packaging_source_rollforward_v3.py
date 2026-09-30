"""One-off nonauthorizing physical source audit; never build or launch images."""
from contextlib import ExitStack
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "scripts"))
import publication_image_build_v1 as build
import publication_qualification_image_refreeze_v1 as refreeze
import publication_policy_qualification_execution_code_closure_v1 as host

prior_name = "artifacts/benchmark_recovery_20260929/packaging-final-capture-custody-invalidation.v1.json"
supplement_name = "artifacts/benchmark_recovery_20260929/custody-budget-supplement.v2.json"
audit_name = "artifacts/benchmark_recovery_20260930/packaging-source-rollforward.v3.json"
current_supplement_name = "artifacts/benchmark_recovery_20260930/custody-budget-supplement.v3.json"
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
def epoch(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
held = {}
def descriptor(name):
    if name in held:
        return dict(held[name][2])
    path = root / name
    assert path.resolve(strict=True) == path and path.is_relative_to(root)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    stack.callback(os.close, fd)
    info = os.fstat(fd)
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and epoch(path.lstat()) == epoch(info)
    digest = hashlib.sha256()
    total = 0
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
        total += len(chunk)
    assert total == info.st_size and epoch(os.fstat(fd)) == epoch(info) and epoch(path.lstat()) == epoch(info)
    result = {"path": name, "size_bytes": total, "sha256": digest.hexdigest()}
    held[name] = (fd, epoch(info), result)
    return dict(result)
def document(name):
    value = descriptor(name)
    assert value["size_bytes"] <= 2 * 1024 * 1024
    fd = held[name][0]
    os.lseek(fd, 0, os.SEEK_SET)
    return json.loads(os.read(fd, value["size_bytes"]))
def aggregate(pins):
    return hashlib.sha256("".join(row["sha256"] + "  " + row["path"] + "\n"
        for row in sorted(pins, key=lambda item: item["path"])).encode("ascii")).hexdigest()
def copy_sources(dockerfile, context):
    # Runtime builders use literal wheels directories. Check their complete
    # actual file inventory against the already frozen dependency allowlist;
    # never expand a glob or admit undeclared bytes.
    result = {dockerfile}
    for line in build._logical_dockerfile_lines((root / dockerfile).read_text("utf-8")):
        parts = shlex.split(line)
        if not parts or parts[0].upper() != "COPY" or any(item.startswith("--from=") for item in parts):
            continue
        args = parts[1:]
        while args and args[0].startswith("--"):
            args.pop(0)
        for name in args[:-1]:
            assert not any(value in name for value in "*?[]") and name != "."
            if name.endswith("/"):
                assert name.endswith("/wheels/") and (root / name).resolve(strict=True) == root / name.rstrip("/")
                observed = {path.relative_to(root).as_posix() for path in (root / name).iterdir()}
                assert observed == {path for path in context if path.startswith(name)}
                for path in observed:
                    descriptor(path)
                result.update(observed)
            else:
                result.add(build._canonical_relative(name))
    return result
def git_source_comparison(pins):
    declared_gitdir = (root / ".git").read_text("ascii").strip()
    assert declared_gitdir.startswith("gitdir: E:/STUDY/VAST/.git/worktrees/")
    gitdir = "/mnt/e/" + declared_gitdir.removeprefix("gitdir: E:/")
    assert Path(gitdir).resolve(strict=True) == Path(gitdir)
    prefix = ["git", "--git-dir=" + gitdir, "--work-tree=" + str(root)]
    head = subprocess.check_output(prefix + ["rev-parse", "HEAD"], cwd=root).decode("ascii").strip()
    assert head == "7f3dfa42858c85d6e3db2cb1274dd13af35696c9", head
    names = [row["path"] for row in pins]
    diff_argv = prefix + ["diff", "--ignore-cr-at-eol", "--name-only", "-z", "HEAD", "--", *names]
    semantic = set(subprocess.check_output(diff_argv, cwd=root).decode("utf-8").rstrip("\0").split("\0")) - {""}
    exact, cr_only, changed, absent = [], [], [], []
    child = subprocess.Popen(prefix + ["cat-file", "--batch"], cwd=root,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for row in pins:
        name = row["path"]
        child.stdin.write(("HEAD:" + name + "\n").encode("utf-8"))
        child.stdin.flush()
        header = child.stdout.readline().decode("ascii").rstrip("\n")
        if header.endswith(" missing"):
            absent.append(dict(row))
            continue
        object_id, object_type, size_text = header.split(" ")
        assert object_type == "blob"
        remaining = int(size_text)
        digest, size = hashlib.sha256(), 0
        while remaining:
            chunk = child.stdout.read(min(1024 * 1024, remaining))
            assert chunk
            digest.update(chunk)
            size += len(chunk)
            remaining -= len(chunk)
        assert child.stdout.read(1) == b"\n"
        head_descriptor = {"git_object": "HEAD:" + name, "git_object_id": object_id,
            "size_bytes": size, "sha256": digest.hexdigest()}
        entry = {"current": dict(row), "head": head_descriptor}
        if row["size_bytes"] == size and row["sha256"] == digest.hexdigest():
            exact.append(entry)
        elif name not in semantic:
            cr_only.append(entry)
        else:
            changed.append(entry)
    child.stdin.close()
    assert child.wait() == 0 and not child.stderr.read()
    assert {row["current"]["path"] for row in changed} == semantic
    historical_names = {row["path"] for row in prior["final_actual_source_manifest"]["project_sources"]}
    categories = {"tracked_exact_bytes": exact, "tracked_CR_at_EOL_only": cr_only,
        "tracked_semantic_uncommitted": changed, "absent_from_HEAD": absent}
    def entry_path(entry):
        return entry.get("current", entry)["path"]
    return {"head": head, "comparison_scope": "all_165_actual_source_dependencies_including_the_historical_157_not_entire_project",
        "source_count": len(pins),
        "tracked_exact_bytes": exact, "tracked_CR_at_EOL_only": cr_only,
        "tracked_semantic_uncommitted": changed, "absent_from_HEAD": absent,
        "historical_157_category_counts": {key: sum(entry_path(entry) in historical_names for entry in entries)
            for key, entries in categories.items()},
        "all_current_165_category_counts": {key: len(entries) for key, entries in categories.items()},
        "semantic_check_argv": diff_argv,
        "HEAD_blob_reader_argv": prefix + ["cat-file", "--batch"],
        "no_source_normalization_or_staging": True}
def final_verify():
    for name, (fd, original_epoch, expected) in held.items():
        path = root / name
        assert path.resolve(strict=True) == path and epoch(path.lstat()) == original_epoch and epoch(os.fstat(fd)) == original_epoch
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        assert digest.hexdigest() == expected["sha256"] and epoch(os.fstat(fd)) == original_epoch
        assert epoch(path.lstat()) == original_epoch
def write_new(name, value):
    value["sha256"] = hashlib.sha256(canonical(value)).hexdigest()
    raw = canonical(value) + b"\n"
    with (root / name).open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return {"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

with ExitStack() as stack:
    prior = document(prior_name)
    supplement = document(supplement_name)
    registry = refreeze.load_refreeze_registry(project_root=root,
        registry_path=root / "configs/publication_qualification_image_refreeze_v1.json")
    runtime_rows = []
    all_sources = {row["path"] for row in prior["final_actual_source_manifest"]["project_sources"]}
    for old, system in zip(prior["invalidated_runtime_contexts"], registry["systems"], strict=True):
        assert old["system"] == system["system"]
        source = refreeze._source_identity(root, system)
        paths = tuple(refreeze._read_allowlist(root, system["source_allowlist"]))
        deps = tuple(refreeze._read_allowlist(root, system["dependency_allowlist"]))
        build_manifest = str(Path(system["source_allowlist"]).with_name("runtime-build-context-allowlist.txt"))
        auxiliary = tuple(refreeze._read_allowlist(root, build_manifest)) if system["system"] in {"openvino_gva", "gstreamer_custom"} else ()
        context = sorted(set(paths).union(deps, auxiliary))
        copies = copy_sources(old["dockerfile"]["path"], context)
        assert copies.issubset(context), (system["system"], sorted(copies - set(context)))
        metadata = sorted(set(context) - copies)
        validator_path = old["validator_source"]["path"]
        spec = importlib.util.spec_from_file_location("rollforward_" + system["system"], root / validator_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        build_metadata = module.BUILD_ONLY_SOURCES if hasattr(module, "BUILD_ONLY_SOURCES") else module.FIXED_BUILD_SOURCES
        assert set(metadata) == (set(build_metadata) | set(auxiliary)) - copies, (system["system"], metadata)
        closure = module.validate_runtime_source_closure(project_root=root,
            manifest_path=root / system["source_allowlist"])
        assert set(closure.get("all_sources", closure.get("declared_sources", ()))) == set(paths), (system["system"], tuple(closure))
        context_pins = [descriptor(path) for path in context]
        source_hash = aggregate([descriptor(path) for path in paths])
        dependency_hash = aggregate([descriptor(path) for path in deps])
        assert source_hash == source["runtime_source_sha256"] and dependency_hash == source["dependency_set_sha256"]
        assert dependency_hash == old["current_source_identity"]["dependency_set_sha256"]
        assert source["native_source_sha256"] == old["current_source_identity"]["native_source_sha256"]
        runtime_rows.append({"system": system["system"], "source_identity": source,
            "exact_python_import_closure": list(closure["python_sources"]),
            "exact_Docker_COPY_sources": sorted(copies), "context_metadata_not_copied": metadata,
            "actual_build_context": {"source_set_sha256": source_hash, "dependency_set_sha256": dependency_hash,
                "build_context_sha256": aggregate(context_pins), "exact_context_members": context_pins},
            "source_allowlist": descriptor(system["source_allowlist"]),
            "dependency_allowlist": descriptor(system["dependency_allowlist"]),
            "build_context_auxiliary_allowlist": descriptor(build_manifest) if auxiliary else None,
            "build_context_auxiliary_inputs": [descriptor(path) for path in auxiliary],
            "dockerfile": descriptor(old["dockerfile"]["path"]), "validator_source": descriptor(validator_path),
            "disposition": "all_runtime_receipts_and_prior_runtime_builds_invalidated_until_new_current_build_and_live_inspect"})
        all_sources.update(context)
    native_plan = build.publication_image_build_plan(project_root=root, registry_path=root / build.REGISTRY_RELATIVE_PATH)
    plan_by_name = {row["name"]: row for row in native_plan["images"]}
    unchanged = []
    for old in prior["unchanged_native_and_worker_contexts"]:
        current = plan_by_name[old["name"]]
        actual = {key: current[key] for key in old["original_hashes"]}
        assert actual == old["original_hashes"] == old["current_hashes"]
        for path in current["relative_paths"]:
            descriptor(path)
        unchanged.append({"name": old["name"], "original_freeze_receipt": descriptor(old["original_freeze_receipt_path"]),
            "original_hashes": old["original_hashes"], "current_hashes": actual, "exact_equal": True,
            "current_context_members": [descriptor(path) for path in current["relative_paths"]],
            "disposition": "physical_source_dependency_context_unchanged_live_image_inspect_still_required"})
        all_sources.update(current["relative_paths"])
    host_paths = [path.relative_to(root).as_posix() for _, path in host._discover_sources(root)]
    assert host_paths == prior["host_execution_code_closure"]["exact_project_source_paths"] and len(host_paths) == 78
    all_sources.update(host_paths)
    pins = [descriptor(path) for path in sorted(all_sources)]
    old_pins = {row["path"]: row for row in prior["final_actual_source_manifest"]["project_sources"]}
    changed = [row for row in pins if row["path"] in old_pins and old_pins[row["path"]] != row]
    newly_inventoried = [row for row in pins if row["path"] not in old_pins]
    assert len(pins) == 165 and len(newly_inventoried) == 8
    assert {row["path"] for row in changed} == {
        "scripts/publication_operational_process_custody_v1.py",
        "scripts/publication_operational_container_custody_v1.py"}, [(row["path"], "new_inventory_entry" if row["path"] not in old_pins else "changed_bytes") for row in changed]
    git_comparison = git_source_comparison(pins)
    evidence_names = [
        "artifacts/benchmark_recovery_20260930/gva-image-schema-repair/focused.execution.v1.json",
        "artifacts/benchmark_recovery_20260930/runtime-custody-live-repair/focused-process-container.execution.v1.json",
        "artifacts/benchmark_recovery_20260930/runtime-custody-live-repair/independent-review.v1.json",
        "artifacts/benchmark_recovery_20260930/runtime-custody-live-repair/original-inspect.execution.v1.json",
        "artifacts/benchmark_recovery_20260930/fresh-stock-native-pair-command-recipe.v1.md",
    ]
    references = [descriptor(name) for name in evidence_names]
    current_supplement = {key: value for key, value in supplement.items() if key not in {"supersedes", "source_files", "sha256"}}
    current_supplement.update(source_files=[descriptor(row["path"]) for row in supplement["source_files"]],
        supersedes={"descriptor": descriptor(supplement_name),
            "reason": "Current physical source pins after exact stock GVA3 preservation and exact Docker absence single-LF handling; all quantitative bounds unchanged."},
        source_only_rollforward=True, bounds_changed=False,
        repair_semantics=["GVA3 is smaller than the already bounded native/SDK contracts; no base image field is invented.",
            "Exact single-LF inspect absence output is retained within the existing capture bound; no whitespace normalization."],
        repair_evidence=references[:4])
    final_verify()
    supplement_ref = write_new(current_supplement_name, current_supplement)
    audit = {"schema_version": 3, "artifact_kind": "vast_benchmark_recovery_packaging_source_rollforward_v3",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
        "scope": "physical_current_source_and_dependency_audit_not_runtime_image_or_model_acceptance",
        "source_commit_before_repairs": "7f3dfa42858c85d6e3db2cb1274dd13af35696c9",
        "supersedes_nonaccepted_audit": descriptor(prior_name),
        "historical_evidence_preserved": True, "only_changed_production_sources": changed,
        "newly_inventoried_existing_build_metadata_sources": newly_inventoried,
        "historical_audit_scope_correction": "For native GStreamer and GVA, actual staged build context includes the separate runtime-build-context-allowlist metadata manifest in addition to runtime source and dependency manifests. Previous audit labeled only the source/dependency union as actual context. Eight existing auxiliary metadata/validator/build-script files were absent from its final 157-file union; several were separately pinned there. Current complete inventory has 165 files and current context scope is derived from the original builder's three --manifest arguments. No dependency file was newly added or edited by this scope correction. Runtime/native/dependency hash scopes are unchanged.",
        "host_execution_code_closure": {"source_count": len(host_paths), "seeds": list(host.SEED_MODULES),
            "exact_project_source_paths": host_paths, "exact_project_source_pins": [descriptor(path) for path in host_paths],
            "disposition": "previous_receipts_invalidated_new_stock_receipt_required"},
        "invalidated_runtime_contexts": runtime_rows, "unchanged_native_and_worker_contexts": unchanged,
        "original_freeze_sources": [descriptor(row["path"]) for row in prior["original_freeze_sources"]],
        "final_actual_source_manifest": {"source_count": len(pins), "project_sources": pins,
            "aggregate_sha256": aggregate(pins), "hash_algorithm": "sha256_of_sorted_sha256_two_spaces_relative_path_LF_rows"},
        "git_HEAD_vs_current_physical_bytes": git_comparison,
        "custody_budget_supplement": supplement_ref,
        "current_regression_and_review_receipts": references,
        "prior_regression_reviews": {"classification": "historical_scope_only_not_current_reexecution",
            "receipts": prior["validation"]["regression_and_review_receipts"]},
        "verification": {"all_four_exact_runtime_python_native_and_COPY_closures_recomputed": True,
            "native_three_worker_two_exact_unchanged_against_original_receipts": True,
            "host_source_count": 78, "physical_namespace_and_held_fd_epoch7_bytes_checked_before_after": True,
            "no_production_or_dependency_bytes_changed_by_this_audit": True,
            "no_image_build_container_model_parity_or_benchmark_execution": True}}
    final_verify()
    result = write_new(audit_name, audit)
    final_verify()
    print(json.dumps({"audit": result, "supplement": supplement_ref,
        "source_count": len(pins), "source_aggregate_sha256": aggregate(pins),
        "runtime_contexts": {row["system"]: row["actual_build_context"]["build_context_sha256"] for row in runtime_rows}}, sort_keys=True))
