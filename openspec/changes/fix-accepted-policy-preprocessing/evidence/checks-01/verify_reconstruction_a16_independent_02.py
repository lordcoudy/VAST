#!/usr/bin/env python3
"""Read-only A16 reconstruction proof; capture only outside the frozen checkout."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


SHA = "a16f243e7e80f093342ccdddf717d59d6d46f0a8"
PY = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-a16f243e7e80f093342ccdddf717d59d6d46f0a8")
MANAGED = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01")
SCRIPT = MANAGED / "verify_reconstruction_a16_independent_02.py"
HELPER = MANAGED / "copy_reconstruction_inputs_v2.py"
WRAPPER = MANAGED / "run_reconstruction_input_copy_v2.sh"
PLAN = MANAGED / "reconstruction-inputs.copy-plan.a16f243e7e80f093342ccdddf717d59d6d46f0a8.v2.json"
HELPER_SHA = "d6e3fc1286fabb9127cae9417de0b6f05689c6d3e1c90951dd0149cbe4bbfbf6"
WRAPPER_SHA = "31bbb99e0ed4a4aa3593abb1e9e97a24dc78ef1c5896d80c0b1566813f40df58"
PLAN_SHA = "f5e5ac4e73a5232389237d38bb5c194a1c4a9add240368db1b8b6927c1e1633a"
CHECKS = ROOT / "artifacts/accepted_policy_repair_20261011a/checks-01"
COPY = CHECKS / ("reconstruction-inputs-copy-v2-" + SHA)
FOCUSED = CHECKS / ("focused-" + SHA + "-01")
COMPARISON = CHECKS / ("final-source-inputs-" + SHA)
ORIGINAL_CAPTURE = Path("/var/tmp/vast-repair-reconstruction-a16f243e-01")
OUT = ORIGINAL_CAPTURE / "independent-02"
CODE_CLOSURE_SEMANTIC_SHA = "5c70c1265e3eaf0fb7742c39d391c5c756c5131495e29a3ac9da084b6727c6ac"
CODE_CLOSURE_FILE_SHA = "7eb06189ccbd194a626bb60722262e3a5d8e4fbbfa32efe30aefe85a1dc4a444"
SKIP_LINE = (
    "test_live_fix_benchmark_preflight_matches_runtime_materializer "
    "(tests.test_publication_runtime_frozen_identity_constants_v1."
    "PublicationRuntimeFrozenIdentityConstantsV1Tests."
    "test_live_fix_benchmark_preflight_matches_runtime_materializer) ... skipped "
    "'requires VAST_LIVE_PREFLIGHT=1, live WSL Docker and OMZ proxy models'"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode("ascii") + b"\n"


def runtime_gate() -> None:
    require(os.getuid() == 1000 and os.environ.get("HOME") == "/home/s-a-balashov", "UID/HOME differs")
    require(Path(sys.executable).absolute() == PY, "not the literal canonical Python launcher")
    require(sys.version_info[:3] == (3, 12, 3) and sys.implementation.name == "cpython", "Python version differs")
    require(sys.dont_write_bytecode, "bytecode writes are not disabled")
    require(Path(__file__).absolute() == SCRIPT, "not the literal reviewed verifier path")


def load_file(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    require(Path(module.__file__).resolve(strict=True) == path.resolve(strict=True), "module origin differs")
    return module


def control(path: Path, maximum: int = 1024 * 1024) -> bytes:
    require(path.is_relative_to(ROOT) or path.is_relative_to(ORIGINAL_CAPTURE), "control path outside literal roots")
    current = path
    while current != Path("/"):
        require(not stat.S_ISLNK(current.lstat().st_mode), "linked control path")
        current = current.parent
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum,
            "control is not a bounded single-link regular file")
    payload = path.read_bytes()
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(all(getattr(before, field) == getattr(path.lstat(), field) for field in fields), "control changed during read")
    return payload


def recipe_controls(directory: Path, commit_name: str) -> dict:
    require(control(directory / "original.rc.txt").decode("ascii").strip() == "0", "original recipe RC file is not zero")
    require(control(directory / commit_name).decode("ascii").strip() == SHA, "recipe commit control differs")
    times = {}
    for name in ("started.txt", "finished.txt"):
        value = control(directory / name).decode("ascii").strip()
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        times[name] = value
    require(times["started.txt"] <= times["finished.txt"], "recipe UTC order differs")
    return {"directory": str(directory), "original_recipe_rc_file": 0, "utc_controls": times}


def verify_child() -> dict:
    runtime_gate()
    reviewed = {HELPER: HELPER_SHA, WRAPPER: WRAPPER_SHA, PLAN: PLAN_SHA}
    require(all(digest(path) == expected for path, expected in reviewed.items()), "reviewed helper/wrapper/plan bytes changed")
    helper = load_file("repair_reconstruction_reviewed_v2", HELPER)
    plan = helper.strict_json(PLAN.read_bytes())
    require(plan["source_commit"] == SHA and plan["destination_root"] == str(ROOT), "plan source binding differs")
    require(plan["stock_file_count"] == 12 and plan["total_bytes"] == 1393960908, "plan count/size differs")
    require(plan["helper_sha256"] == HELPER_SHA and plan["campaign_authority"] is False and plan["copy_only"] is True,
            "plan helper/authority boundary differs")
    helper.assert_source(ROOT, SHA)

    ci_names = ("run_ci_checks.py", "ci_external_test_observer_v1.py", "ci_test_selection_v1.py", "ci_userns_profile_v1.py")
    ci_hashes = {}
    for name in ci_names:
        path = ROOT / "scripts" / name
        helper.plain_chain(ROOT, path)
        raw = path.read_bytes()
        require(raw == helper.git(ROOT, "show", SHA + ":scripts/" + name), "stock raw-gate source differs")
        ci_hashes["scripts/" + name] = hashlib.sha256(raw).hexdigest()
    ci = load_file("repair_frozen_run_ci_checks_a16", ROOT / "scripts/run_ci_checks.py")
    paths_before = ci.tracked_paths(ROOT)
    require(len(paths_before) == 12115, "frozen tracked-source count differs")
    ci.verify_committed_bytes(ROOT, paths_before)

    copy_controls = recipe_controls(COPY, "source-commit.txt")
    copied = helper.strict_json(control(COPY / "original.stdout.json"))
    require(copied["passed"] is True and copied["source_commit"] == SHA and copied["reviewed_plan_sha256"] == PLAN_SHA,
            "original copy result binding differs")
    require(copied["file_count"] == 12 and copied["total_bytes"] == 1393960908 and copied["copy_only"] is True,
            "original copy result count/scope differs")
    require(copied["stock_full_corpus_gate_passed"] is True and copied["retained_sources_byte_and_epoch_unchanged"] is True
            and copied["campaign_authority"] is False, "original copy result boundaries differ")
    require(control(COPY / "original.stderr.log") == b"", "original copy helper stderr is not empty")
    external = control(COPY / "external-helper-plan-wrapper.sha256").decode("ascii").splitlines()
    external_rows = dict((Path(line.split(maxsplit=1)[1]).name, line.split(maxsplit=1)[0]) for line in external)
    require(external_rows == {HELPER.name: HELPER_SHA, WRAPPER.name: WRAPPER_SHA, PLAN.name: PLAN_SHA}, "copy original helper/plan pins differ")
    original_outer = helper.strict_json(control(ORIGINAL_CAPTURE / "original.result.v1.json"))
    require(original_outer["original_exit_code"] == 0 and original_outer["source_commit"] == SHA,
            "actual emitted original copy outer result differs")
    require(original_outer["command"] == ["/bin/bash", str(WRAPPER), "--source-commit", SHA, "--plan", str(PLAN),
            "--reviewed-plan-sha256", PLAN_SHA, "--reviewed-helper-sha256", HELPER_SHA], "copy outer argv differs")
    for name, facts in original_outer["streams"].items():
        require(name in ("original.stdout.raw", "original.stderr.raw"), "unexpected original stream path")
        raw = control(ORIGINAL_CAPTURE / name)
        require(len(raw) == facts["bytes"] and hashlib.sha256(raw).hexdigest() == facts["sha256"], "original captured stream differs")

    gate, authority_hashes = helper.authority(ROOT, SHA)
    require(authority_hashes == plan["authority_source_sha256"], "stock authority source hashes differ")
    import yaml
    catalog_path = ROOT / "configs/datasets.yaml"
    helper.plain_chain(ROOT, catalog_path)
    catalog_raw = catalog_path.read_bytes()
    require(catalog_raw == helper.git(ROOT, "show", SHA + ":configs/datasets.yaml"), "stock catalog differs from commit")
    require(hashlib.sha256(catalog_raw).hexdigest() == plan["catalog_sha256"], "stock catalog SHA differs")
    catalog = yaml.safe_load(catalog_raw)["datasets"]
    expected = helper.pinned_rows(gate)
    require(expected == plan["expected_stock_descriptors"], "stock exact12 descriptors differ from reviewed plan")
    helper.assert_ignored_corpus(ROOT, expected)
    destination = helper.validated_inventory(ROOT, gate, catalog, expected)
    require(destination == copied["destination_inventory"], "actual copied12 bytes/epochs differ from original result")
    retained = {str(source): helper.validated_inventory(source, gate, catalog, expected) for source in helper.SOURCE_ROOTS}
    require(retained == plan["validated_source_inventories"], "historical24 bytes/physical epochs changed")

    focused_controls = recipe_controls(FOCUSED, "commit.txt")
    require(control(FOCUSED / "original.stdout.log") == b"", "focused stdout differs from observed empty stream")
    focused_lines = control(FOCUSED / "original.stderr.log").decode("utf-8").splitlines()
    cases = [line for line in focused_lines if line.startswith("test_")]
    require(len(cases) == 212 and sum(line.endswith(" ... ok") for line in cases) == 211, "focused actual case count/status differs")
    require([line for line in cases if " ... skipped " in line] == [SKIP_LINE], "focused skip ID/reason differs")
    require(focused_lines[-3:] == ["Ran 212 tests in 131.755s", "", "OK (skipped=1)"], "focused terminal outcome differs")
    focused_recipe = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/run_focused_suite.sh"
    recipe_raw = focused_recipe.read_bytes()
    require(recipe_raw == helper.git(ROOT, "show", SHA + ":" + focused_recipe.relative_to(ROOT).as_posix()), "focused recipe differs from frozen commit")
    modules = recipe_raw.decode("ascii").split("MODULES=(\n", 1)[1].split("\n)\n", 1)[0].splitlines()
    require(control(FOCUSED / "test-modules.txt").decode("ascii").splitlines() == [row.strip() for row in modules],
            "focused executed module inventory differs from frozen recipe")

    comparison_controls = recipe_controls(COMPARISON, "source-commit.txt")
    require(control(COMPARISON / "original.stdout.log") == b"" and control(COMPARISON / "original.stderr.log") == b"",
            "source comparison original streams differ")
    comparison = helper.strict_json(control(COMPARISON / "source-comparison.v1.json"))
    for key, expected_value in {
        "source_commit": SHA, "build_commit": "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795", "passed": True,
        "source_unchanged": True, "runtime_build_input_count": 128, "guardian_source_count": 67,
        "qualification_full_source_count": 93, "runtime_package_inputs_byte_identical": True,
        "all_five_native_worker_source_dependency_context_hashes_equal": True, "campaign_authority": False,
        "runtime_python_counts": {"deepstream": 73, "savant": 81, "openvino_gva": 68, "gstreamer_custom": 68},
    }.items():
        require(comparison[key] == expected_value, "source comparison predicate differs: " + key)
    require([row["path"] for row in comparison["host_only_changed_closure_sources"]] == [
        "scripts/checkpoint_gstreamer_publication_runtime_v3.py", "scripts/checkpoint_openvino_gva_publication_runtime_v3.py"],
        "source comparison host-only changed path set differs")
    closure_path = COMPARISON / "execution-code-closure.v1.json"
    closure_raw = control(closure_path)
    require(hashlib.sha256(closure_raw).hexdigest() == CODE_CLOSURE_FILE_SHA, "actual93 closure receipt physical file hash differs")
    closure = helper.strict_json(closure_raw)
    closure_source = ROOT / "scripts/publication_policy_qualification_execution_code_closure_v1.py"
    helper.plain_chain(ROOT, closure_source)
    require(closure_source.read_bytes() == helper.git(ROOT, "show", SHA + ":" + closure_source.relative_to(ROOT).as_posix()),
            "stock semantic closure source differs from frozen commit")
    stock_closure = load_file("repair_frozen_execution_code_closure_a16", closure_source)
    closure_body = {key: value for key, value in closure.items() if key != "receipt_sha256"}
    require(closure["receipt_sha256"] == CODE_CLOSURE_SEMANTIC_SHA
            and stock_closure.semantic_sha256_v1(closure_body) == CODE_CLOSURE_SEMANTIC_SHA,
            "actual93 closure semantic self-hash differs")
    require(closure_raw == stock_closure._canonical_bytes(closure), "actual93 closure receipt is not stock canonical JSON")
    for name, status_value in (("code-closure-materialize.stdout.json", "published"), ("code-closure-cold.stdout.json", "validated")):
        observed = helper.strict_json(control(COMPARISON / name))
        require(observed == {"project_source_count": 93, "receipt_path": str(closure_path),
                "receipt_sha256": CODE_CLOSURE_SEMANTIC_SHA, "status": status_value}, "actual93 producer/cold report differs")

    helper.assert_source(ROOT, SHA)
    paths_after = ci.tracked_paths(ROOT)
    require(paths_after == paths_before, "tracked-source path inventory changed")
    ci.verify_committed_bytes(ROOT, paths_after)
    require(all(digest(path) == expected_value for path, expected_value in reviewed.items()), "reviewed helper/plan changed during proof")
    require(helper.validated_inventory(ROOT, gate, catalog, expected) == destination, "copied12 bytes/epochs changed during proof")
    require({str(source): helper.validated_inventory(source, gate, catalog, expected) for source in helper.SOURCE_ROOTS} == retained,
            "historical24 bytes/epochs changed during proof")
    return {
        "artifact_kind": "vast_reconstruction_independent_read_only_proof_a16_v1", "passed": True,
        "source_commit": SHA, "source_root": str(ROOT), "stock_raw_tracked_file_count": len(paths_after),
        "stock_full_reconstruction_gate_passed": True, "destination_inventory": destination,
        "retained_source_inventory_count": 24, "retained_sources_byte_and_epoch_unchanged": True,
        "authority_source_sha256": authority_hashes, "stock_raw_gate_source_sha256": ci_hashes,
        "reviewed_helper_plan_wrapper_sha256": {str(path): value for path, value in reviewed.items()},
        "copy_recipe_controls": copy_controls, "actual_copy_outer_original_result": original_outer,
        "focused_recipe_controls": focused_controls, "focused_actual_tests": 212, "focused_skips": [SKIP_LINE],
        "source_comparison_recipe_controls": comparison_controls, "source_comparison": comparison,
        "code_closure_receipt_semantic_sha256": CODE_CLOSURE_SEMANTIC_SHA,
        "code_closure_receipt_file_sha256": CODE_CLOSURE_FILE_SHA,
        "limits": ["Comparison success is based on actual recipe RC/report controls; its outer tool completion was not emitted.",
                   "This independent proof is not the failed independent original, an integration execution, hosted CI, or Q1.",
                   "No historical corpus, frozen source, receipt, manifest, CI policy, or authority is rewritten."],
        "campaign_authority": False,
    }


def capture() -> int:
    runtime_gate()
    require(ORIGINAL_CAPTURE.resolve(strict=True) == ORIGINAL_CAPTURE, "capture parent is aliased")
    require(not OUT.exists() and not OUT.is_symlink(), "independent-02 output already exists")
    OUT.mkdir(mode=0o700)
    before = digest(SCRIPT)
    argv = [str(PY), "-B", str(SCRIPT), "--child"]
    started = datetime.now(timezone.utc).isoformat()
    (OUT / "command.v1.json").write_bytes(json_bytes({"argv": argv, "cwd": str(ORIGINAL_CAPTURE),
        "source_commit": SHA, "verifier_sha256": before, "started_utc": started, "source_writes_permitted": False}))
    environment = dict(os.environ, HOME="/home/s-a-balashov", TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    with (OUT / "original.stdout.raw").open("xb") as stdout, (OUT / "original.stderr.raw").open("xb") as stderr:
        process = subprocess.run(argv, cwd=ORIGINAL_CAPTURE, env=environment, stdout=stdout, stderr=stderr, check=False)
    finished = datetime.now(timezone.utc).isoformat()
    after = digest(SCRIPT)
    streams = {name: {"bytes": (OUT / name).stat().st_size, "sha256": digest(OUT / name)}
               for name in ("original.stdout.raw", "original.stderr.raw")}
    result = {"artifact_kind": "vast_independent_original_capture_v1", "source_commit": SHA, "command": argv,
        "started_utc": started, "finished_utc": finished, "original_exit_code": process.returncode,
        "verifier_sha256_before": before, "verifier_sha256_after": after, "verifier_unchanged": before == after,
        "streams": streams, "output_directory": str(OUT), "source_writes_permitted": False, "campaign_authority": False}
    (OUT / "original.result.v1.json").write_bytes(json_bytes(result))
    sys.stdout.buffer.write(json_bytes(result))
    return process.returncode if before == after else 1


if __name__ == "__main__":
    require(sys.argv[1:] in ([], ["--child"]), "only literal capture or child invocation is supported")
    if sys.argv[1:] == ["--child"]:
        sys.stdout.buffer.write(json_bytes(verify_child()))
    else:
        raise SystemExit(capture())
