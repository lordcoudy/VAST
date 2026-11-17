#!/usr/bin/env python3
"""Read-only checks executed by an actual runtime image, never a host fallback."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


SOURCE_COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
PACKAGE_ROOT = Path("/opt/vast/checkpoint")
LEAVES = (
    "publication_policy_qualification_transaction_validation_v2",
    "publication_policy_qualification_fragment_validation_v2",
    "publication_policy_qualification_pilot_validation_v2",
)
HOST_ONLY = (
    "publication_qualification_promotion_v2",
    "publication_policy_qualification_transaction_v2",
    "publication_policy_qualification_fragments_from_authority_v2",
    "publication_policy_qualification_index_v2",
    "publication_policy_qualification_bootstrap_v2",
    "publication_policy_qualification_pilot_executor_v2",
    "publication_qualification_operational_owner_v1",
)
SIDECAR = "checkpoint_gstreamer_analytics_sidecar"
GUARDIAN = "publication_guardian_accepted_policy_preprocessing_contract_v1"
MODES = tuple("standalone:" + leaf for leaf in LEAVES) + (
    "leaves-first", "sidecar-first", "cold-descriptors", "cold-descriptors-held",
)
DEFAULT_PYTHONPATH = {
    "deepstream": "/opt/vast/checkpoint",
    "savant": "/opt/vast/checkpoint:/opt/savant",
    "openvino_gva": "/opt/vast/checkpoint:/opt/vast/python",
    "gstreamer_custom": "/opt/vast/checkpoint:/opt/vast/python",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def file_sha(path: Path) -> str:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_nlink == 1,
            "not one physical file: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_packaged_bytes(inventory: dict, system: str) -> dict:
    require(inventory["source_commit"] == SOURCE_COMMIT, "source inventory commit drifted")
    require(os.environ.get("PYTHONPATH") == DEFAULT_PYTHONPATH[system],
            "image default PYTHONPATH drifted or was overridden")
    require(sys.dont_write_bytecode, "actual interpreter must be invoked with -B")
    require(str(PACKAGE_ROOT) in sys.path, "packaged project path is unavailable")
    require(not any(path.startswith(("/mnt/", "/repair-fixture")) for path in sys.path),
            "host or fixture import fallback is forbidden")
    row = inventory["runtime_rows"][system]
    expected = {Path(path).name: digest for path, digest in row["local_copy_source_hashes"].items()
                if path in row["all_runtime_python_paths"]}
    observed = {path.name for path in PACKAGE_ROOT.glob("*.py")}
    require(observed == set(expected), "actual packaged project module set differs from exact COPY inventory")
    for basename, digest in sorted(expected.items()):
        require(file_sha(PACKAGE_ROOT / basename) == digest, "packaged source hash drifted: " + basename)
    shared = [source for source in inventory["project_sources"] if source["guardian_shared_leaf_closure"]]
    require(len(shared) == 67, "shared source count drifted")
    for source in shared:
        name = Path(source["path"]).stem
        spec = importlib.util.find_spec(name)
        require(spec is not None and spec.origin == str(PACKAGE_ROOT / (name + ".py")),
                "shared module resolves outside actual package: " + name)
    for name in HOST_ONLY:
        require(importlib.util.find_spec(name) is None, "host-only module was packaged: " + name)
    return {"shared_project_source_count": 67, "all_packaged_project_source_count": len(expected),
            "all_project_source_hashes_verified": True, "host_only_modules_absent": list(HOST_ONLY),
            "default_pythonpath": os.environ["PYTHONPATH"]}


def verify_loaded_origins(inventory: dict, system: str) -> list[str]:
    expected = {Path(path).stem for path in inventory["runtime_rows"][system]["all_runtime_python_paths"]}
    loaded = []
    for name, module in sorted(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if origin and origin.startswith(str(PACKAGE_ROOT) + "/"):
            require(name in expected and origin == str(PACKAGE_ROOT / (name + ".py")),
                    "unexpected loaded project module origin: " + name)
            loaded.append(name)
    require(not set(HOST_ONLY) & set(sys.modules), "a host-only module was eagerly loaded")
    return loaded


def verify_fixture(fixture: Path) -> dict:
    fixture = fixture.resolve(strict=True)
    require(fixture == Path("/repair-fixture"), "fixture must be the dedicated bind mount")
    require(os.statvfs(fixture).f_flag & os.ST_RDONLY, "fixture bind mount is not read-only")
    manifest = json.loads((fixture / "fixture.inventory.v1.json").read_bytes())
    require(manifest["fixture_only"] is True and manifest["semantic_eligibility"] is False
            and manifest["historical_campaign_bytes_used"] is False
            and manifest["payload_descriptor_count"] == 18, "fixture scope drifted")
    observed = {path.relative_to(fixture).as_posix() for path in fixture.rglob("*") if path.is_file()}
    require(observed == set(manifest["files"]) | {"fixture.inventory.v1.json"}, "fixture file set drifted")
    for relative, descriptor in manifest["files"].items():
        path = fixture / relative
        require(path.stat().st_size == descriptor["size_bytes"] and file_sha(path) == descriptor["sha256"],
                "fixture bytes drifted: " + relative)
    return manifest


def cold_descriptor_execution(fixture: Path, *, held: bool) -> dict:
    """Exercise real reader bytes; these artificial payloads prove descriptors only."""
    reader = importlib.import_module(LEAVES[0])
    receipt_path = fixture / "valid.receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    descriptors = [receipt[field] for field in (
        "hardware_resource_collector", "image_identity_patch", "accepted_model_parity_manifest",
        "accepted_model_parity_assessment", "accepted_model_parity_receipt",
    )]
    descriptors += list(receipt["fragments"].values()) + list(receipt["candidate"].values())
    descriptors += [receipt["bootstrap"]["mapping"], *receipt["bootstrap"]["calibrations"].values(),
                    receipt["bootstrap"]["receipt"]]
    require(len(descriptors) == 18, "fixture descriptor coverage drifted")
    failures = {
        "bad-descriptor.receipt.json": "transaction receipt descriptor drifted: hardware_resource_collector",
        "bad-kind.receipt.json": "cold transaction receipt identity drifted",
        "bad-coverage.receipt.json": "transaction receipt fragment coverage drifted",
        "noncanonical.receipt.json": "cold transaction receipt is not canonical JSON",
    }

    def execute() -> None:
        for _ in range(2):
            reader.cold_validate_committed_transaction_v2(root=fixture, receipt_path=receipt_path)
        for descriptor in descriptors:
            require(reader.file_descriptor(fixture, descriptor["path"]) == descriptor,
                    "actual physical descriptor output drifted")
        for name, expected_error in failures.items():
            try:
                reader.cold_validate_committed_transaction_v2(root=fixture, receipt_path=fixture / name)
            except reader.QualificationTransactionV2Error as error:
                require(str(error) == expected_error, "wrong refusal predicate: " + name + ": " + str(error))
            else:
                raise AssertionError("negative fixture was accepted: " + name)

    require(reader._ACTIVE_CUSTODY.get() is None, "fresh interpreter inherited custody")
    if held:
        with reader.PhysicalRootCustodyV1.open(fixture, label="read-only packaged descriptor fixture") as custody:
            require(custody._posix_custody is not None, "real Linux descriptor-held custody is unavailable")
            token = reader._ACTIVE_CUSTODY.set(custody)
            try:
                execute()
                custody.verify()
            finally:
                reader._ACTIVE_CUSTODY.reset(token)
    else:
        execute()
    require(reader._ACTIVE_CUSTODY.get() is None, "custody ContextVar was not restored")
    return {"positive_cold_loads": 2, "physical_descriptors_checked": len(descriptors),
            "exact_negative_predicates_checked": failures, "held_posix_custody": held,
            "semantic_qualification_acceptance_claimed": False}


def run_mode(args: argparse.Namespace, inventory: dict) -> dict:
    result = verify_packaged_bytes(inventory, args.runtime)
    if args.mode.startswith("standalone:"):
        name = args.mode.split(":", 1)[1]
        module = importlib.import_module(name)
        require(module.__file__ == str(PACKAGE_ROOT / (name + ".py")), "leaf origin drifted")
        require(not ({SIDECAR, GUARDIAN, "publication_guardian_preprocessing_contract_v1"}
                     & set(sys.modules)), "standalone leaf eagerly imported guardian or sidecar")
        if name == LEAVES[0]:
            require(module.QualificationTransactionV2Error.__module__ == name,
                    "transaction exception is not leaf-owned")
            require(module.cold_validate_committed_transaction_v2 is module._cold_validate_committed_transaction,
                    "cold reader alias lost identity")
        elif name == LEAVES[1]:
            require(module.QualificationFragmentsFromAuthorityV2Error.__module__ == name
                    and module.FragmentAuthorityDependenciesV2.__module__ == name,
                    "fragment dependency/exception objects are not leaf-owned")
        else:
            require(module.policy_pilot_validator.__module__ == name, "pilot validator is not leaf-owned")
    elif args.mode in {"leaves-first", "sidecar-first"}:
        sequence = (*LEAVES, SIDECAR, GUARDIAN) if args.mode == "leaves-first" else (SIDECAR, *LEAVES, GUARDIAN)
        for name in sequence:
            importlib.import_module(name)
        result["supported_actual_image_import_sequence"] = list(sequence)
    else:
        verify_fixture(args.fixture)
        result["cold_descriptor_execution"] = cold_descriptor_execution(
            args.fixture, held=args.mode == "cold-descriptors-held")
    result["loaded_project_modules"] = verify_loaded_origins(inventory, args.runtime)
    result.update({"mode": args.mode, "passed": True, "source_commit": SOURCE_COMMIT,
                   "python_executable": sys.executable, "python_version": sys.version.split()[0]})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--runtime", choices=tuple(DEFAULT_PYTHONPATH), required=True)
    parser.add_argument("--mode", choices=("all", *MODES), default="all")
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_bytes())
    if args.mode != "all":
        print(json.dumps(run_mode(args, inventory), sort_keys=True))
        return
    verify_packaged_bytes(inventory, args.runtime)
    verify_fixture(args.fixture)
    runs = []
    for mode in MODES:
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--inventory", str(args.inventory),
                   "--fixture", str(args.fixture), "--runtime", args.runtime, "--mode", mode]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        require(completed.returncode == 0, "fresh interpreter failed for " + mode + ": " + completed.stderr)
        runs.append(json.loads(completed.stdout))
    print(json.dumps({"artifact_kind": "vast_accepted_policy_repair_packaged_reader_checks_v1",
                      "source_commit": SOURCE_COMMIT, "runtime": args.runtime, "passed": True,
                      "fresh_interpreter_count": len(runs), "runs": runs,
                      "promotion_first_actual_image_check": "unsupported_by_approved_host_only_F1_scope",
                      "host_production_scripts_mounted": False, "historical_campaign_bytes_used": False},
                     sort_keys=True))


if __name__ == "__main__":
    main()
