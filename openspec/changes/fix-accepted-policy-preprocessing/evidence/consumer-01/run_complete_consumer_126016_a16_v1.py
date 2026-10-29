#!/usr/bin/env python3
"""Finite genuine 126016-sample fixture; artificial observations are not Q1."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


SHA = "a16f243e7e80f093342ccdddf717d59d6d46f0a8"
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + SHA)
PY = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
MANAGED = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
CHANGE = Path("openspec/changes/fix-accepted-policy-preprocessing")
SCRIPT = MANAGED / CHANGE / "evidence/consumer-01/run_complete_consumer_126016_a16_v1.py"
FROZEN_ENTRY = ROOT / CHANGE / "evidence/consumer-01/build_production_fixture_v2.py"
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
OUTPUT = BASE / "consumer-fixture-126016-01"
CONTROLS = BASE / "consumer-126016-controls-01"
NAMESPACE = "accepted-policy-repair-20261011a"
SOCKET_PREFIX = ".apf126"
APPROVED_COMMIT = "299c9c0eefb83fe3031096b0e96527236678a4d2"
GUARDIAN_SOURCE = "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"
EXPECTED_TOTAL = 126016
MINIMUM_FREE_BYTES = 40 * 1024**3
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGY_COUNTS = {"independent_processes": 984, "shared_video_dag": 985}
FROZEN_HELPERS = {
    str(FROZEN_ENTRY.relative_to(ROOT)): "068cc6bc174f2526ccd9af6ea7e47c0cce9de83debcc5151e3958a2cfc20995d",
    "tests/fixtures/accepted_policy_native_fixture_v2.py": "a0a3c7c745d5f81c5baafd62e1e1c00f75191ca5b4a1756440085eb2d18765e3",
    "tests/fixtures/accepted_policy_physical_fixture_v2.py": "39c12abb6315a6117d4b238f354b605108df1a4c0d34b0b7a45f5e0f3d5817d2",
    "tests/fixtures/accepted_policy_consumer_fixture_v2.py": "dc8d18b18df5414a30a7f9e8dd235b874ce70962d861c21b0e176d4fddf955a4",
    "tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py": "02c261448654aff23980b110a81cd5f4ecfd5e58f2377ae57e7baeadc5ddef3f",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("ascii") + b"\n"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout


def fresh_json(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value))


def runtime_gate(reviewed_sha256: str) -> None:
    require(os.getuid() == os.getgid() == 1000 and os.environ.get("HOME") == "/home/s-a-balashov", "UID/GID/HOME differs")
    require(sys.implementation.name == "cpython" and sys.version_info[:3] == (3, 12, 3), "canonical Python version differs")
    require(Path(sys.executable).absolute() == PY and sys.dont_write_bytecode, "canonical Python -B launcher required")
    require(Path(__file__).absolute() == SCRIPT and SCRIPT.resolve(strict=True) == SCRIPT, "external recipe origin differs")
    require(len(reviewed_sha256) == 64 and all(character in "0123456789abcdef" for character in reviewed_sha256)
            and digest(SCRIPT) == reviewed_sha256, "reviewed external recipe bytes differ")
    require(ROOT.resolve(strict=True) == ROOT and BASE.resolve(strict=True) == BASE, "source/base path is aliased")
    require(subprocess.check_output(["findmnt", "-rn", "-T", str(ROOT), "-o", "FSTYPE"]).strip() == b"ext4", "source is not native ext4")
    require(git("rev-parse", "HEAD") == (SHA + "\n").encode("ascii")
            and git("status", "--porcelain=v1", "--untracked-files=no") == b"", "source HEAD/clean state differs")
    for relative, expected in FROZEN_HELPERS.items():
        path = ROOT / relative
        require(path.resolve(strict=True) == path and digest(path) == expected
                and path.read_bytes() == git("show", SHA + ":" + relative), "frozen helper changed: " + relative)


def raw_source_proof() -> dict:
    program = (
        "import json,sys; from pathlib import Path; root=Path(" + repr(str(ROOT)) + "); "
        "sys.path.insert(0,str(root/'scripts')); import run_ci_checks as ci; "
        "assert Path(ci.__file__).resolve(strict=True)==root/'scripts/run_ci_checks.py'; "
        "paths=ci.tracked_paths(root); assert len(paths)==12115; ci.verify_committed_bytes(root,paths); "
        "print(json.dumps({'raw_committed_bytes_verified':True,'tracked_path_count':len(paths),"
        "'verifier_path':ci.__file__},sort_keys=True))"
    )
    command = [str(PY), "-B", "-c", program]
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
    proof = json.loads(process.stdout) if process.returncode == 0 else None
    evidence = {"command": command, "cwd": str(ROOT), "started_utc": started,
                "finished_utc": datetime.now(timezone.utc).isoformat(), "original_exit_code": process.returncode,
                "stdout": process.stdout.decode("utf-8"), "stderr": process.stderr.decode("utf-8"), "proof": proof}
    return evidence


def load_frozen_entry() -> object:
    spec = importlib.util.spec_from_file_location("accepted_policy_frozen_positive_entry_a16", FROZEN_ENTRY)
    require(spec is not None and spec.loader is not None, "frozen fixture entry loader unavailable")
    entry = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = entry
    spec.loader.exec_module(entry)
    require(entry._fixture_source_root_v2(FROZEN_ENTRY) == ROOT, "frozen entrypoint root differs")
    return entry


def declared_cells() -> list[dict]:
    rows = [{"system": system, "resource": resource, "codec": codec, "topology_kind": topology,
             "completed_samples_per_branch": count}
            for system in SYSTEMS for resource in RESOURCES for codec in CODECS
            for topology, count in TOPOLOGY_COUNTS.items()]
    require(len(rows) == 32 and sum(row["completed_samples_per_branch"] == 984 for row in rows) == 16
            and sum(row["completed_samples_per_branch"] == 985 for row in rows) == 16
            and 4 * sum(row["completed_samples_per_branch"] for row in rows) == EXPECTED_TOTAL,
            "literal 32-cell count declaration drifted")
    return rows


def bind_actual_operations(prepared: dict) -> tuple[dict[str, int], list[dict]]:
    expected = {tuple(row[key] for key in ("system", "resource", "codec", "topology_kind")):
                row["completed_samples_per_branch"] for row in declared_cells()}
    seen, counts, bindings = set(), {}, []
    operations = prepared["capture_plan"]["operation_manifest"]["operations"]
    require(len(operations) == 37 and len({row["operation_id"] for row in operations}) == 37, "actual capture plan is not unique37")
    for row in operations:
        if row["phase"] != "qualification_cell":
            continue
        source_path = Path(row["descriptors"]["source_plan"]["path"])
        require(source_path.is_relative_to(ROOT) and source_path.resolve(strict=True) == source_path, "source-plan path is foreign/aliased")
        source = json.loads(source_path.read_bytes())
        require(row["policy"] in {"cpu_only", "gpu_only"}, "qualification resource policy differs")
        coordinate = (row["system"], "cpu" if row["policy"] == "cpu_only" else "gpu", row["codec"], source["topology_kind"])
        require(coordinate in expected and coordinate not in seen, "actual qualification coordinate missing/foreign/duplicated")
        seen.add(coordinate)
        counts[row["operation_id"]] = expected[coordinate]
        bindings.append({"operation_id": row["operation_id"], "coordinate": coordinate,
                         "completed_samples_per_branch": expected[coordinate],
                         "source_plan_descriptor": row["descriptors"]["source_plan"]})
    require(seen == set(expected) and len(counts) == 32 and 4 * sum(counts.values()) == EXPECTED_TOTAL,
            "actual mixed32 count binding differs")
    return counts, bindings


def verify_complete_result(consumers: dict, native: dict, guardian_sha256: str) -> None:
    coverage = consumers["assessment"]["coverage"]
    require(consumers["assessment"]["passed"] is True and coverage == {
        "binding_count": 32, "pilot_cell_count": 32, "accepted_sample_count": EXPECTED_TOTAL,
        "minimum_samples_per_branch_cell": 30}, "actual fresh F1 coverage differs")
    require(len(native["operations"]) == 37 and native["qualification_count"] == 32
            and consumers["finalized_cell_count"] == 32, "actual original/finalized coordinate counts differ")
    fresh = consumers["fresh_interpreter_guardian_cold_reader"]
    require(consumers["standalone_guardian_cold_reader_passed"] is True
            and fresh["original_exit_code"] == 0 and fresh["standalone_guardian_cold_reader_passed"] is True
            and fresh["proof"]["default_module_sha256"] == guardian_sha256
            and fresh["proof"]["default_module_path"] == str(ROOT / GUARDIAN_SOURCE)
            and fresh["proof"]["preprocessing_contract_content_sha256"] == consumers["guardian"]["preprocessing_contract_sha256"],
            "fresh guardian-first default cold proof differs")
    require(consumers["identity_policy_component"]["passed"] is True
            and consumers["identity_policy_component"]["accepted_sample_count"] == EXPECTED_TOTAL,
            "actual downstream identity policy count differs")
    require(len(consumers["genuine_cpu_gpu_stock_sample_equality"]) == 2
            and {row["resource"] for row in consumers["genuine_cpu_gpu_stock_sample_equality"]} == {"cpu", "gpu"}
            and all(row["samples_equal_stock"] is True and row["upstream_acceptance_substituted"] is False
                    and row["dataset_substituted"] is False for row in consumers["genuine_cpu_gpu_stock_sample_equality"])
            and consumers["dropped_gpu_qualification_cell_count"] == 15, "real CPU/GPU stock equality/drop coverage differs")


def producer(reviewed_sha256: str) -> None:
    runtime_gate(reviewed_sha256)
    require(CONTROLS.is_dir() and CONTROLS.resolve(strict=True) == CONTROLS and not os.path.lexists(OUTPUT), "producer controls/output not canonical/fresh")
    entry = load_frozen_entry()
    entry._canonical_fixture_directory_v2(OUTPUT, root=ROOT, fresh=True)
    before = raw_source_proof()
    fresh_json(CONTROLS / "source-raw.before.json", before)
    require(before["original_exit_code"] == 0 and before["proof"]["raw_committed_bytes_verified"] is True,
            "stock raw committed source proof refused before fixture")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    # Keep the same initial production imports/order as the frozen positive CLI.
    from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
    from tests.fixtures.accepted_policy_physical_fixture_v2 import build_original_native_fixture_observations_v2, prepared_complete_fixture_inputs_v2
    from tests.fixtures.accepted_policy_consumer_fixture_v2 import complete_fixture_production_consumers_v2

    original_sources = loaded_fixture_production_sources_v1(project_root=ROOT)
    approved_source = git("show", APPROVED_COMMIT + ":" + GUARDIAN_SOURCE)
    guardian_sha256 = hashlib.sha256(git("show", SHA + ":" + GUARDIAN_SOURCE)).hexdigest()
    report = {"artifact_kind": "vast_complete_consumer_126016_fixture_v1", "source_commit": SHA,
              "project_root": str(ROOT), "output_dir": str(OUTPUT), "external_recipe_sha256": reviewed_sha256,
              "frozen_helpers_sha256": FROZEN_HELPERS, "declared_cells": declared_cells(),
              "qualification_branch_coordinate_count": 128, "expected_measured_sample_count": EXPECTED_TOTAL,
              "expected_calibration_samples_per_coordinate": 3938, "ancillary_completed_samples_per_branch": 30,
              "complete_consumer_positive_asserted": False, "campaign_authority": False,
              "physical_inference_observed": False, "source_raw_before": before,
              "initial_loaded_production_sources": original_sources,
              "approved_old_guardian_commit": APPROVED_COMMIT,
              "approved_old_guardian_source_sha256": hashlib.sha256(approved_source).hexdigest(),
              "limits": ["Fresh artificial native protocol observations; no historical/G9/attempt4 rows.",
                         "Real transaction, fragment, acceptance, sidecar, custody, closure, F1 and default guardian validators.",
                         "Shared genuine renewed-v4 inputs; no Docker inference, Q1, Q4, capacity or publication eligibility.",
                         "Identity policy component checks real bindings/calibration, not a fabricated campaign resource envelope."]}

    def phase(name: str) -> None:
        current = loaded_fixture_production_sources_v1(project_root=ROOT)
        by_name = {row["module"]: row for row in current}
        require(all(by_name.get(row["module"]) == row for row in original_sources), "loaded production provenance changed")
        print(json.dumps({"fixture_phase": name, "output_dir": str(OUTPUT), "production_module_count": len(current)}, sort_keys=True), flush=True)
        if OUTPUT.is_dir():
            fresh_json(OUTPUT / ("producer-phase-" + name + ".v1.json"), {"phase": name, "source_commit": SHA,
                       "loaded_production_sources": current, "campaign_authority": False})

    phase("00-imported")
    config = ROOT / "configs" / ("checkpoint_analytics_model_parity.refreshed.v4." + NAMESPACE + ".accepted")
    observations = BASE / "consumer-runtime-observations-02"
    try:
        with prepared_complete_fixture_inputs_v2(
            project_root=ROOT, output_dir=OUTPUT, identity_patch_path=BASE / "qualification_image_identity_patch.json",
            accepted_model_parity_manifest_path=config.with_suffix(".accepted.yaml"),
            accepted_model_parity_assessment_path=Path(str(config) + ".assessment.json"),
            accepted_model_parity_receipt_path=Path(str(config) + ".acceptance_receipt.json"),
            image_inspections=json.loads((observations / "image-inspect-map.json").read_bytes()),
            device_probes=json.loads((observations / "device-probe-map.json").read_bytes()), socket_prefix=SOCKET_PREFIX,
        ) as prepared:
            phase("01-prepared")
            counts, bindings = bind_actual_operations(prepared)
            fresh_json(OUTPUT / "mixed-sample-count-bindings.v1.json", {"bindings": bindings,
                       "accepted_sample_count": EXPECTED_TOTAL, "ancillary_default": 30, "campaign_authority": False})
            native = build_original_native_fixture_observations_v2(
                prepared=prepared, samples_per_branch=30, qualification_samples_by_operation_id=counts)
            phase("02-originals")
            consumers = complete_fixture_production_consumers_v2(
                prepared=prepared, native=native, approved_guardian_source=approved_source, approved_guardian_commit=APPROVED_COMMIT)
            verify_complete_result(consumers, native, guardian_sha256)
            from publication_policy_qualification import CALIBRATION_MAPPING_FILENAME
            calibration = json.loads((OUTPUT / "accepted-policy" / CALIBRATION_MAPPING_FILENAME).read_bytes())
            # The real F1 total plus every aggregate coordinate must retain the mixed map.
            aggregate_counts = [cell["samples"] for system in calibration["calibrations"].values()
                                for branch in system["costs"].values() for cell in branch.values()]
            require(len(aggregate_counts) == 32 and set(aggregate_counts) == {3938}
                    and sum(aggregate_counts) == EXPECTED_TOTAL, "actual complete calibration totals differ")
            phase("03-complete-consumers")
            report.update(consumers=consumers, mixed_operation_bindings=bindings,
                          final_loaded_production_sources=loaded_fixture_production_sources_v1(project_root=ROOT),
                          complete_consumer_positive_asserted=True)
    except Exception as error:
        if OUTPUT.is_dir():
            fresh_json(OUTPUT / "producer-failure.v1.json", {**report, "complete_consumer_positive_asserted": False,
                       "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc()})
        raise
    finally:
        after = raw_source_proof()
        fresh_json(CONTROLS / "source-raw.after.json", after)
        require(after["original_exit_code"] == 0 and after["proof"]["raw_committed_bytes_verified"] is True,
                "stock raw committed source proof refused after fixture")
        runtime_gate(reviewed_sha256)
    report["source_raw_after"] = after
    fresh_json(OUTPUT / "producer-126016-report.v1.json", report)
    print(json.dumps({"complete_consumer_positive_asserted": True, "measured_sample_count": EXPECTED_TOTAL,
                      "report_path": str(OUTPUT / "producer-126016-report.v1.json")}, sort_keys=True), flush=True)


def capture(reviewed_sha256: str, *, check_only: bool, clearance: bool) -> int:
    runtime_gate(reviewed_sha256)
    declared_cells()
    require(not os.path.lexists(OUTPUT) and not os.path.lexists(CONTROLS), "finite output/control namespace is occupied")
    require(OUTPUT.parent.resolve(strict=True) == BASE and CONTROLS.parent.resolve(strict=True) == BASE, "output/control parent differs")
    free = {str(path): shutil.disk_usage(path).free for path in (ROOT, Path("/var/tmp"))}
    require(all(value >= MINIMUM_FREE_BYTES for value in free.values()), "fixture requires 40 GiB free on SOURCE and /var/tmp volumes")
    environment = dict(os.environ, HOME="/home/s-a-balashov", TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    command = [str(PY), "-B", str(SCRIPT), "--reviewed-runner-sha256", reviewed_sha256, "--child"]
    if check_only:
        current_raw = raw_source_proof()
        require(current_raw["original_exit_code"] == 0 and current_raw["proof"]["raw_committed_bytes_verified"] is True,
                "check-only stock raw committed source proof refused")
        print(json.dumps({"check_only": True, "source_commit": SHA, "source_root": str(ROOT), "declared_cells": declared_cells(),
                          "expected_measured_sample_count": EXPECTED_TOTAL, "expected_aggregate_coordinate_samples": 3938,
                          "source_raw_current": current_raw, "command": command, "free_bytes": free,
                          "controls": str(CONTROLS), "output": str(OUTPUT), "socket_prefix": SOCKET_PREFIX,
                          "execution_authorized": False, "campaign_authority": False}, sort_keys=True))
        return 0
    require(clearance, "explicit orchestration clearance is required; no automatic fixture retry")
    CONTROLS.mkdir(mode=0o700)
    started = datetime.now(timezone.utc).isoformat()
    fresh_json(CONTROLS / "command.v1.json", {"command": command, "cwd": str(ROOT), "source_commit": SHA,
               "started_utc": started, "free_bytes": free, "external_recipe_sha256": reviewed_sha256,
               "fixture_output": str(OUTPUT), "orchestration_clearance_confirmed": True, "campaign_authority": False})
    with (CONTROLS / "original.stdout.raw").open("xb") as stdout, (CONTROLS / "original.stderr.raw").open("xb") as stderr:
        process = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr, check=False)
    result = {"source_commit": SHA, "command": command, "started_utc": started,
              "finished_utc": datetime.now(timezone.utc).isoformat(), "original_exit_code": process.returncode,
              "external_recipe_sha256_before": reviewed_sha256, "external_recipe_sha256_after": digest(SCRIPT),
              "streams": {name: {"bytes": (CONTROLS / name).stat().st_size, "sha256": digest(CONTROLS / name)}
                          for name in ("original.stdout.raw", "original.stderr.raw")},
              "complete_consumer_positive_asserted": False, "campaign_authority": False, "automatic_retry": False}
    if process.returncode == 0:
        try:
            report = json.loads((OUTPUT / "producer-126016-report.v1.json").read_bytes())
            require(report["source_commit"] == SHA and report["expected_measured_sample_count"] == EXPECTED_TOTAL
                    and report["complete_consumer_positive_asserted"] is True, "actual producer report differs")
            require(result["external_recipe_sha256_after"] == reviewed_sha256, "external recipe changed during fixture")
            result["complete_consumer_positive_asserted"] = True
        except Exception as error:
            result["runner_validation_error"] = {"error_type": type(error).__name__, "error": str(error)}
    fresh_json(CONTROLS / "original-result.v1.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return process.returncode if (process.returncode != 0 or result["complete_consumer_positive_asserted"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-runner-sha256", required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--orchestration-clearance-confirmed", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    require(not args.child or not (args.check_only or args.orchestration_clearance_confirmed), "child mode options differ")
    if args.child:
        producer(args.reviewed_runner_sha256)
    else:
        raise SystemExit(capture(args.reviewed_runner_sha256, check_only=args.check_only,
                                 clearance=args.orchestration_clearance_confirmed))
