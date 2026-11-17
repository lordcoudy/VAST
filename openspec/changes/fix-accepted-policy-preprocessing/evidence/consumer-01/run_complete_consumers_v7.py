#!/usr/bin/env python3
"""One reviewed exact-source sequential 24/25 consumer run, without retries."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback


SOURCE_PREFIX = "/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-"
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
BASE_RELATIVE = Path("artifacts/accepted_policy_repair_20261011a")
ENTRYPOINT_RELATIVE = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py")
WRAPPER_RELATIVE = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/run_complete_consumers_v7.py")
CONTROLS_NAME = "consumer-complete-24-controls"
RUNS = ((30, "consumer-fixture-24-minimum30", ".apf24"),
        (31, "consumer-fixture-25-larger31", ".apf25"))
FROZEN_HELPERS = {
    ENTRYPOINT_RELATIVE.as_posix(): "068cc6bc174f2526ccd9af6ea7e47c0cce9de83debcc5151e3958a2cfc20995d",
    "tests/fixtures/accepted_policy_native_fixture_v2.py": "a0a3c7c745d5f81c5baafd62e1e1c00f75191ca5b4a1756440085eb2d18765e3",
    "tests/fixtures/accepted_policy_physical_fixture_v2.py": "1b8e2fc7e468d1b54ab9571ef2eea6c4a04f77a0430207c1b292ade2fb4b4106",
    "tests/fixtures/accepted_policy_consumer_fixture_v2.py": "ba3c13459080fc52f188f3e576d8514fb9d1f418962764d2617a7089f9b69bca",
    "tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py": "02c261448654aff23980b110a81cd5f4ecfd5e58f2377ae57e7baeadc5ddef3f",
    "tests/fixtures/accepted_policy_guardian_lifecycle_fixture_v1.py": "fed4a3e74107761590d608da11ee2b9e1d29c086de8432006538fcd6683dcdcf",
    "tests/test_accepted_policy_f5_real_refusals.py": "c8577f673f04dc6fe54ef533ef0ff5d67f058c28a46a2e191a19f511b736d13c",
    "tests/fixtures/accepted_policy_stock_sample_reference_v1.py": "eeabb3b44e83f4dff767d3a4ded2235e1694a923517ed231c433d37b6bed7297",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_bytes(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)


def _fresh_json(path: Path, value: object) -> None:
    _fresh_bytes(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *arguments], capture_output=True, check=True).stdout


def _source_state(root: Path) -> dict[str, bytes]:
    return {"head": _git(root, "rev-parse", "HEAD"),
            "tracked_status": _git(root, "status", "--porcelain=v1", "--untracked-files=no")}


def _require_clean_source_state(state: dict[str, bytes], expected_commit: str) -> None:
    if state["head"].decode("ascii").strip() != expected_commit or state["tracked_status"]:
        raise ValueError("frozen source is not the exact clean reviewed commit")


def _save_state(directory: Path, name: str, state: dict[str, bytes]) -> None:
    for kind, value in state.items():
        _fresh_bytes(directory / ("source-" + kind.replace("_", "-") + "." + name + ".txt"), value)


def _raw_source_proof(root: Path, *, environment: dict[str, str], directory: Path | None, name: str) -> dict:
    program = (
        "import json,sys; from pathlib import Path; root=Path(" + repr(str(root)) + "); "
        "sys.path.insert(0,str(root/'scripts')); import run_ci_checks as ci; "
        "paths=ci.tracked_paths(root); ci.verify_committed_bytes(root,paths); "
        "print(json.dumps({'raw_committed_bytes_verified':True,'tracked_path_count':len(paths),"
        "'verifier_path':ci.__file__},sort_keys=True))"
    )
    command = [str(PYTHON), "-B", "-c", program]
    started = _utc()
    child = subprocess.run(command, cwd=root, env=environment, capture_output=True)
    result = {"command": command, "cwd": str(root), "started_utc": started, "finished_utc": _utc(),
              "original_exit_code": child.returncode, "stdout_bytes": len(child.stdout), "stderr_bytes": len(child.stderr),
              "stdout_sha256": hashlib.sha256(child.stdout).hexdigest(),
              "stderr_sha256": hashlib.sha256(child.stderr).hexdigest(), "proof": None, "proof_validated": False}
    if directory is not None:
        _fresh_bytes(directory / ("raw-source-" + name + ".stdout.raw"), child.stdout)
        _fresh_bytes(directory / ("raw-source-" + name + ".stderr.raw"), child.stderr)
    else:
        result["stdout_base64"] = base64.b64encode(child.stdout).decode("ascii")
        result["stderr_base64"] = base64.b64encode(child.stderr).decode("ascii")
    if child.returncode == 0 and not child.stderr:
        try:
            result["proof"] = json.loads(child.stdout)
            result["proof_validated"] = (type(result["proof"]) is dict
                and result["proof"].get("raw_committed_bytes_verified") is True
                and type(result["proof"].get("tracked_path_count")) is int and result["proof"]["tracked_path_count"] > 0
                and result["proof"].get("verifier_path") == str(root / "scripts/run_ci_checks.py"))
        except (ValueError, UnicodeError) as error:
            result["verifier_validation_error"] = str(error)
    if directory is not None:
        _fresh_json(directory / ("raw-source-" + name + ".result.v1.json"), result)
    return result


def _recipe_proof(root: Path, expected_commit: str, reviewed_wrapper_sha256: str) -> dict:
    wrapper = Path(__file__).absolute()
    if wrapper != root / WRAPPER_RELATIVE:
        raise ValueError("v5 wrapper must be the exact frozen source-root recipe")
    if re.fullmatch(r"[0-9a-f]{64}", reviewed_wrapper_sha256) is None or wrapper.resolve(strict=True) != wrapper:
        raise ValueError("reviewed wrapper identity is malformed or aliased")
    wrapper_raw = wrapper.read_bytes()
    wrapper_sha256 = hashlib.sha256(wrapper_raw).hexdigest()
    if wrapper_sha256 != reviewed_wrapper_sha256:
        raise ValueError("reviewed wrapper bytes differ")
    if wrapper_raw != _git(root, "show", expected_commit + ":" + WRAPPER_RELATIVE.as_posix()):
        raise ValueError("v5 wrapper differs from the frozen commit bytes")
    hashes = {}
    for relative, expected in FROZEN_HELPERS.items():
        path = root / relative
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if path.resolve(strict=True) != path or actual != expected or raw != _git(root, "show", expected_commit + ":" + relative):
            raise ValueError("frozen fixture helper differs: " + relative)
        hashes[relative] = actual
    module = root / "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"
    raw = module.read_bytes()
    if module.resolve(strict=True) != module or raw != _git(root, "show", expected_commit + ":" + module.relative_to(root).as_posix()):
        raise ValueError("frozen default guardian module differs")
    return {"wrapper_path": str(wrapper), "wrapper_sha256": wrapper_sha256, "helper_hashes": hashes,
            "default_guardian_module_path": str(module), "default_guardian_module_sha256": hashlib.sha256(raw).hexdigest()}


def _post_source_guards(root: Path, *, environment: dict[str, str], directory: Path,
                        expected_commit: str, reviewed_wrapper_sha256: str) -> dict:
    result = {"state": None, "raw_source": None, "recipe": None, "passed": False, "errors": []}
    try:
        state = _source_state(root)
        result["state"] = {name: value.decode("ascii") for name, value in state.items()}
        _save_state(directory, "after", state)
        _require_clean_source_state(state, expected_commit)
    except Exception as error:
        result["errors"].append({"guard": "head_status", "type": type(error).__name__, "message": str(error)})
    try:
        result["raw_source"] = _raw_source_proof(root, environment=environment, directory=directory, name="after")
        if not result["raw_source"]["proof_validated"]:
            raise ValueError("stock raw committed byte proof refused")
    except Exception as error:
        result["errors"].append({"guard": "raw_source", "type": type(error).__name__, "message": str(error)})
    try:
        result["recipe"] = _recipe_proof(root, expected_commit, reviewed_wrapper_sha256)
    except Exception as error:
        result["errors"].append({"guard": "recipe", "type": type(error).__name__, "message": str(error)})
    result["passed"] = not result["errors"]
    return result


def _preflight(expected_commit: str) -> tuple[Path, Path, Path, dict[str, bytes]]:
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise ValueError("expected source commit must be an exact lowercase 40-character SHA")
    root = Path(SOURCE_PREFIX + expected_commit)
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("exact frozen source root is missing or aliased")
    base = root / BASE_RELATIVE
    if base.resolve(strict=True) != base or not base.is_dir():
        raise ValueError("fixture base is missing or aliased")
    if not PYTHON.is_file() or not (root / ENTRYPOINT_RELATIVE).is_file():
        raise ValueError("canonical Python or frozen producer is missing")
    controls = base / CONTROLS_NAME
    for path in (controls, *(base / name for _, name, _ in RUNS)):
        if os.path.lexists(path):
            raise ValueError("exclusive output already exists: " + str(path))
    state = _source_state(root)
    _require_clean_source_state(state, expected_commit)
    return root, base, controls, state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--reviewed-wrapper-sha256", required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--orchestration-clearance-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.check_only and not args.orchestration_clearance_confirmed:
        parser.error("execution requires explicit selected-root writer scheduling clearance")
    if (os.getuid() != 1000 or os.getgid() != 1000 or os.environ.get("HOME") != "/home/s-a-balashov"
            or Path(sys.executable).absolute() != PYTHON or not sys.dont_write_bytecode
            or sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 12, 3)):
        raise ValueError("canonical UID/GID/HOME/Python -B runtime differs")
    root, base, controls, initial = _preflight(args.expected_source_commit)
    if subprocess.check_output(["findmnt", "-rn", "-T", str(root), "-o", "FSTYPE"]).strip() != b"ext4":
        raise ValueError("frozen source is not native ext4")
    initial_recipe = _recipe_proof(root, args.expected_source_commit, args.reviewed_wrapper_sha256)
    environment = dict(os.environ, TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    commands = [[str(PYTHON), "-B", str(root / ENTRYPOINT_RELATIVE),
                 "--project-root", str(root), "--expected-source-commit", args.expected_source_commit,
                 "--artifact-base", BASE_RELATIVE.as_posix(), "--namespace", "accepted-policy-repair-20261011a",
                 "--output-dir", (BASE_RELATIVE / name).as_posix(), "--socket-prefix", prefix,
                 "--samples-per-branch", str(samples), "--stage", "complete"]
                for samples, name, prefix in RUNS]
    if args.check_only:
        raw = _raw_source_proof(root, environment=environment, directory=None, name="check-only")
        current = _source_state(root)
        current_recipe = _recipe_proof(root, args.expected_source_commit, args.reviewed_wrapper_sha256)
        passed = raw["proof_validated"] and current == initial and current_recipe == initial_recipe
        print(json.dumps({"preflight_passed": passed, "source_commit": args.expected_source_commit,
                          "project_root": str(root), "controls_dir": str(controls), "commands": commands,
                          "raw_source_proof": raw, "recipe_proof": current_recipe,
                          "execution_authorized": False}, sort_keys=True), flush=True)
        return 0 if passed else 1
    controls.mkdir(mode=0o700)
    _save_state(controls, "before", initial)
    _fresh_json(controls / "run-plan.v4.json", {"schema_version": 4, "started_utc": _utc(),
        "source_commit": args.expected_source_commit, "project_root": str(root), "commands": commands,
        "recipe_proof": initial_recipe, "environment": {"TMPDIR": "/var/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
        "orchestration_clearance_confirmed": True, "campaign_authority": False, "physical_inference_observed": False,
        "limits": ["Earlier wrappers, source clones, producer failures and original results remain preserved.",
                   "The two fresh fixtures use exact reviewed source and actual unchanged production defaults.",
                   "Original child failure or runner/post-guard error stops the sequence; no automatic retry.",
                   "Scheduling clearance is orchestration evidence, not production qualification authority.",
                   "Artificial observations are not Q1 or a126016-sample native fixture."]})
    results, exit_code, outer_error, before_raw = [], 1, None, None
    try:
        before_raw = _raw_source_proof(root, environment=environment, directory=controls, name="before")
        if not before_raw["proof_validated"]:
            raise ValueError("outer stock raw committed source proof refused before sequence")
        exit_code = 0
        for (samples, name, _), command in zip(RUNS, commands):
            if exit_code:
                break
            run_controls = controls / name
            run_controls.mkdir(mode=0o700)
            before = _source_state(root)
            _save_state(run_controls, "before", before)
            _require_clean_source_state(before, args.expected_source_commit)
            before_recipe = _recipe_proof(root, args.expected_source_commit, args.reviewed_wrapper_sha256)
            child_before_raw = _raw_source_proof(root, environment=environment, directory=run_controls, name="before")
            if not child_before_raw["proof_validated"]:
                exit_code = 1
                results.append({"name": name, "child_not_started": True,
                                "complete_consumer_positive_asserted": False, "raw_source_before": child_before_raw})
                break
            started_utc, started_ns = _utc(), time.monotonic_ns()
            _fresh_json(run_controls / "started.v4.json", {"started_utc": started_utc, "command": command,
                        "samples_per_branch": samples, "expected_measured_sample_count": 32 * 4 * samples,
                        "source_commit": args.expected_source_commit, "recipe_proof": before_recipe,
                        "orchestration_clearance_confirmed": True, "campaign_authority": False})
            print(json.dumps({"fixture_started": name, "started_utc": started_utc,
                              "stdout_path": str(run_controls / "stdout.raw"),
                              "stderr_path": str(run_controls / "stderr.raw")}, sort_keys=True), flush=True)
            child, original_rc, runner_error, wait_interruptions = None, None, None, []
            try:
                with (run_controls / "stdout.raw").open("xb") as stdout, (run_controls / "stderr.raw").open("xb") as stderr:
                    child = subprocess.Popen(command, cwd=root, env=environment, stdout=stdout, stderr=stderr)
                    # Keep ownership until this same child exits; never terminate or relaunch it.
                    while original_rc is None:
                        try:
                            original_rc = child.wait()
                        except BaseException as error:
                            wait_interruptions.append({"observed_utc": _utc(), "type": type(error).__name__,
                                "message": str(error), "traceback": traceback.format_exc()})
            except BaseException as error:
                runner_error = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
            finally:
                finished_utc = _utc()
                post = _post_source_guards(root, environment=environment, directory=run_controls,
                    expected_commit=args.expected_source_commit, reviewed_wrapper_sha256=args.reviewed_wrapper_sha256)
            if original_rc is not None:
                _fresh_bytes(run_controls / "original-exit-code.txt", (str(original_rc) + "\n").encode("ascii"))
            expected_state = {key: value.decode("ascii") for key, value in before.items()}
            initial_state = {key: value.decode("ascii") for key, value in initial.items()}
            result = {"name": name, "started_utc": started_utc, "finished_utc": finished_utc,
                      "elapsed_seconds": (time.monotonic_ns() - started_ns) / 1_000_000_000,
                      "original_exit_code": original_rc, "child_process_created": child is not None,
                      "samples_per_branch": samples, "expected_measured_sample_count": 32 * 4 * samples,
                      "complete_consumer_positive_asserted": False,
                      "source_state_unchanged": post["state"] == expected_state == initial_state,
                      "recipe_unchanged": post["recipe"] == before_recipe == initial_recipe,
                      "raw_source_before": child_before_raw, "raw_source_after": post["raw_source"],
                      "post_source_guards": post, "runner_error": runner_error, "wait_interruptions": wait_interruptions}
            for filename in ("stdout.raw", "stderr.raw"):
                path = run_controls / filename
                payload = path.read_bytes() if path.is_file() else None
                result[filename] = {"available": payload is not None,
                    "size_bytes": len(payload) if payload is not None else None,
                    "sha256": hashlib.sha256(payload).hexdigest() if payload is not None else None}
            eligible = (original_rc == 0 and runner_error is None and not wait_interruptions and post["passed"]
                        and result["source_state_unchanged"] and result["recipe_unchanged"])
            if eligible:
                try:
                    report_path = base / name / "producer-stage-report.v2.json"
                    report = json.loads(report_path.read_bytes())
                    fresh = report["consumers"]["fresh_interpreter_guardian_cold_reader"]
                    module_sha = initial_recipe["default_guardian_module_sha256"]
                    if (report.get("complete_consumer_positive_asserted") is not True
                            or report.get("source_commit") != args.expected_source_commit
                            or report.get("expected_measured_sample_count") != 32 * 4 * samples
                            or report["consumers"]["assessment"]["coverage"]["accepted_sample_count"] != 32 * 4 * samples
                            or fresh.get("original_exit_code") != 0 or fresh.get("standalone_guardian_cold_reader_passed") is not True
                            or fresh.get("expected_default_module_sha256") != module_sha
                            or fresh["proof"]["default_module_sha256"] != module_sha
                            or fresh["proof"]["default_module_path"] != initial_recipe["default_guardian_module_path"]
                            or fresh["proof"]["preprocessing_contract_content_sha256"] != report["consumers"]["guardian"]["preprocessing_contract_sha256"]):
                        raise ValueError("zero-exit producer lacks exact complete/fresh-standalone proof")
                    result["complete_consumer_positive_asserted"] = True
                    result["producer_report"] = {"path": str(report_path), "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()}
                except Exception as error:
                    result["runner_validation_error"] = {"type": type(error).__name__, "message": str(error)}
            _fresh_json(run_controls / "finished.v4.json", result)
            results.append(result)
            print(json.dumps({"fixture_finished": name, "original_exit_code": original_rc,
                              "complete_consumer_positive_asserted": result["complete_consumer_positive_asserted"],
                              "finished_utc": finished_utc}, sort_keys=True), flush=True)
            if not result["complete_consumer_positive_asserted"]:
                exit_code = original_rc if original_rc is not None and 0 < original_rc < 256 else 1
    except BaseException as error:
        outer_error = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        exit_code = 1
    finally:
        final = _post_source_guards(root, environment=environment, directory=controls,
            expected_commit=args.expected_source_commit, reviewed_wrapper_sha256=args.reviewed_wrapper_sha256)
        state_unchanged = final["state"] == {key: value.decode("ascii") for key, value in initial.items()}
        if not final["passed"] or not state_unchanged or final["recipe"] != initial_recipe:
            exit_code = 1
            for result in results:
                result["complete_consumer_positive_asserted"] = False
        _fresh_json(controls / "run-result.v4.json", {"schema_version": 4, "source_commit": args.expected_source_commit,
                    "finished_utc": _utc(), "exit_code": exit_code, "runs": results, "runner_error": outer_error,
                    "source_state_unchanged": state_unchanged, "recipe_unchanged": final["recipe"] == initial_recipe,
                    "raw_source_before": before_raw, "raw_source_after": final["raw_source"], "post_source_guards": final,
                    "both_complete_consumers_passed": exit_code == 0 and outer_error is None
                        and len(results) == len(RUNS) and all(row["complete_consumer_positive_asserted"] for row in results),
                    "campaign_authority": False})
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
