#!/usr/bin/env python3
"""Read-only host inventory of literal project imports and runtime COPY closure."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shlex
import stat
import subprocess
import sys
from pathlib import Path


root = Path(sys.argv[1]).resolve(strict=True)
expected_commit = sys.argv[2]
observed = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
assert observed == expected_commit
# Host-only static discovery. This script is never used as an image module path.
sys.path.insert(0, str(root / "scripts"))
import publication_policy_qualification_execution_code_closure_v1 as closure
from publication_image_build_v1 import _logical_dockerfile_lines


def exact_copy_sources(dockerfile_relative: str) -> set[str]:
    """Expand only literal local COPY inputs; never include stage-to-stage COPY."""
    result: set[str] = set()
    for line in _logical_dockerfile_lines((root / dockerfile_relative).read_text(encoding="utf-8")):
        tokens = shlex.split(line, posix=True)
        assert not tokens or tokens[0].upper() != "ADD"
        if not tokens or tokens[0].upper() != "COPY":
            continue
        args = tokens[1:]
        if any(value.startswith("--from=") for value in args):
            continue
        while args and args[0].startswith("--"):
            args.pop(0)
        assert len(args) >= 2
        for value in args[:-1]:
            assert value != "." and not any(character in value for character in "*?[]")
            path = root / value
            assert path.resolve(strict=True).is_relative_to(root) and not path.is_symlink()
            candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
            for candidate in candidates:
                assert not candidate.is_symlink()
                info = candidate.lstat()
                if stat.S_ISDIR(info.st_mode):
                    continue
                assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                result.add(candidate.relative_to(root).as_posix())
    return result

full_seeds = closure.SEED_MODULES
full = {path.relative_to(root).as_posix() for _, path in closure._discover_sources(root)}
guardian_seeds = (
    "publication_guardian_accepted_policy_preprocessing_contract_v1",
    "publication_policy_qualification_transaction_validation_v2",
    "publication_policy_qualification_fragment_validation_v2",
    "publication_policy_qualification_pilot_validation_v2",
)
try:
    closure.SEED_MODULES = guardian_seeds
    guardian = {path.relative_to(root).as_posix() for _, path in closure._discover_sources(root)}
finally:
    closure.SEED_MODULES = full_seeds
assert len(guardian) == 67 and len(full) == 93
assert guardian <= full
host_only = {
    "scripts/publication_qualification_promotion_v2.py",
    "scripts/publication_policy_qualification_transaction_v2.py",
    "scripts/publication_policy_qualification_fragments_from_authority_v2.py",
    "scripts/publication_policy_qualification_index_v2.py",
    "scripts/publication_policy_qualification_bootstrap_v2.py",
    "scripts/publication_policy_qualification_pilot_executor_v2.py",
    "scripts/publication_qualification_operational_owner_v1.py",
}
assert not guardian & host_only
locations = {
    "deepstream": ("deploy/deepstream/checkpoint", "Dockerfile.runtime",
                   "deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt"),
    "savant": ("deploy/savant/publication", "Dockerfile",
               "deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt"),
    "openvino_gva": ("deploy/openvino_gva/publication", "Dockerfile",
                     "deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt"),
    "gstreamer_custom": ("deploy/gstreamer_custom/publication", "Dockerfile",
                         "deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt"),
}
runtime_rows = {}
for system, (directory, dockerfile, dependencies) in locations.items():
    validator_path = root / directory / "validate_runtime_source_closure_v3.py"
    spec = importlib.util.spec_from_file_location("inventory_" + system, validator_path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    manifest = root / directory / "runtime-source-allowlist.txt"
    validated = validator.validate_runtime_source_closure(project_root=root, manifest_path=manifest)
    declared = set(manifest.read_text(encoding="utf-8").splitlines())
    dependency_paths = set((root / dependencies).read_text(encoding="utf-8").splitlines())
    dockerfile_relative = directory + "/" + dockerfile
    copied = exact_copy_sources(dockerfile_relative)
    build_only = set(getattr(validator, "BUILD_ONLY_SOURCES", ())) | {dockerfile_relative}
    # OpenVINO copies its manifest, although that self-file is not a manifest row.
    auxiliary_manifest = {manifest.relative_to(root).as_posix()}
    expected_copy = ((declared | dependency_paths) - build_only) | auxiliary_manifest
    assert copied == expected_copy, (
        system, sorted(copied - expected_copy),
        sorted(expected_copy - copied),
    )
    assert guardian <= declared and not declared & host_only
    python_paths = {path for path in copied if path.startswith("scripts/") and path.endswith(".py")}
    runtime_rows[system] = {
        "source_allowlist": directory + "/runtime-source-allowlist.txt",
        "source_allowlist_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "dockerfile": directory + "/" + dockerfile,
        "dockerfile_sha256": hashlib.sha256((root / directory / dockerfile).read_bytes()).hexdigest(),
        "copy_equals_allowlists_minus_explicit_build_only_sources": True,
        "explicit_allowlist_build_only_sources_not_copied": sorted(build_only),
        "copied_manifest_self_file_not_declared_as_source": sorted(auxiliary_manifest - declared),
        "dockerfile_is_build_context_input_not_local_copy": dockerfile_relative not in copied,
        "actual_runtime_closure_validator_passed": True,
        "guardian_sources_missing": sorted(guardian - declared),
        "host_only_unplanned_members": sorted(declared & host_only),
        "other_planned_runtime_python_sources": sorted(python_paths - guardian),
        "all_runtime_python_paths": sorted(python_paths),
        "all_copy_paths": sorted(copied),
        "dependency_allowlist": dependencies,
        "dependency_allowlist_sha256": hashlib.sha256((root / dependencies).read_bytes()).hexdigest(),
        "local_copy_source_hashes": {path: hashlib.sha256((root / path).read_bytes()).hexdigest()
                                     for path in sorted(copied)},
    }
rows = []
for path in sorted(full | {"scripts/publication_qualification_promotion_v2.py"}):
    payload = (root / path).read_bytes()
    rows.append({"path": path, "size_bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest(),
                 "guardian_shared_leaf_closure": path in guardian,
                 "qualification_full_seed_closure": path in full,
                 "runtime_source_membership": [system for system, row in runtime_rows.items()
                                               if path in row["all_copy_paths"]],
                 "classification": "shared_runtime_reader_dependency" if path in guardian else
                                   "explicit_host_only" if path in host_only else
                                   "other_full_qualification_dependency"})
print(json.dumps({"artifact_kind": "vast_accepted_policy_repair_packaged_closure_inventory_v1",
                  "schema_version": 1, "source_commit": observed,
                  "status": "read_only_source_inventory_not_in_image_execution",
                  "discovery": "existing literal AST imports and literal __import__/importlib.import_module",
                  "guardian_shared_leaf_seeds": guardian_seeds, "guardian_source_count": len(guardian),
                  "qualification_full_seeds": full_seeds, "qualification_full_source_count": len(full),
                  "full_only_sources": sorted(full - guardian),
                  "promotion_is_host_only_and_not_an_image_import_order": True,
                  "runtime_rows": runtime_rows, "project_sources": rows}, sort_keys=True, indent=2))
