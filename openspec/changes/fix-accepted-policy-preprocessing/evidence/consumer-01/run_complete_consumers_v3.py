#!/usr/bin/env python3
"""One reviewed exact-source sequential 08/09 consumer run, without retries."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


SOURCE_PREFIX = "/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-"
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
BASE_RELATIVE = Path("artifacts/accepted_policy_repair_20261011a")
ENTRYPOINT_RELATIVE = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py")
CONTROLS_NAME = "consumer-complete-08-controls"
RUNS = ((30, "consumer-fixture-08-minimum30", ".apf08"),
        (31, "consumer-fixture-09-larger31", ".apf09"))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_bytes(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)


def _fresh_json(path: Path, value: object) -> None:
    _fresh_bytes(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))


def _git(root: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, check=True).stdout


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
    if child.returncode == 0:
        try:
            result["proof"] = json.loads(child.stdout)
            result["proof_validated"] = (type(result["proof"]) is dict
                and result["proof"].get("raw_committed_bytes_verified") is True
                and result["proof"].get("verifier_path") == str(root / "scripts/run_ci_checks.py"))
        except (ValueError, UnicodeError) as error:
            result["verifier_validation_error"] = str(error)
    if directory is not None:
        _fresh_json(directory / ("raw-source-" + name + ".result.v1.json"), result)
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
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--orchestration-clearance-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.check_only and not args.orchestration_clearance_confirmed:
        parser.error("execution requires explicit selected-root writer scheduling clearance")
    root, base, controls, initial = _preflight(args.expected_source_commit)
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
        print(json.dumps({"preflight_passed": raw["proof_validated"],
                          "source_commit": args.expected_source_commit, "project_root": str(root),
                          "controls_dir": str(controls), "commands": commands, "raw_source_proof": raw}, sort_keys=True), flush=True)
        return 0 if raw["proof_validated"] else 1
    controls.mkdir(mode=0o700)
    _save_state(controls, "before", initial)
    _fresh_json(controls / "run-plan.v3.json", {"schema_version": 3, "started_utc": _utc(),
        "source_commit": args.expected_source_commit, "project_root": str(root), "commands": commands,
        "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "entrypoint_sha256": hashlib.sha256((root / ENTRYPOINT_RELATIVE).read_bytes()).hexdigest(),
        "environment": {"TMPDIR": "/var/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
        "orchestration_clearance_confirmed": args.orchestration_clearance_confirmed,
        "campaign_authority": False, "physical_inference_observed": False,
        "limits": ["All earlier source591 fixtures, wrappers and original failures remain preserved.",
                   "The two new positive fixtures use one exact reviewed source and no validator substitutes.",
                   "Original failure stops the sequence; no automatic retry or new output suffix is chosen.",
                   "Scheduling clearance is orchestration evidence, not production qualification authority.",
                   "Artificial observations are not Q1 or a126016-sample pilot replay."]})
    before_raw = _raw_source_proof(root, environment=environment, directory=controls, name="before")
    results, exit_code = [], 0 if before_raw["proof_validated"] else 1
    for (samples, name, _), command in zip(RUNS, commands):
        if exit_code:
            break
        run_controls = controls / name
        run_controls.mkdir(mode=0o700)
        before = _source_state(root)
        _save_state(run_controls, "before", before)
        _require_clean_source_state(before, args.expected_source_commit)
        child_before_raw = _raw_source_proof(root, environment=environment, directory=run_controls, name="before")
        if not child_before_raw["proof_validated"]:
            exit_code = 1
            results.append({"name": name, "child_not_started": True, "raw_source_before": child_before_raw})
            break
        started_utc, started_ns = _utc(), time.monotonic_ns()
        _fresh_json(run_controls / "started.v3.json", {"started_utc": started_utc, "command": command,
                    "samples_per_branch": samples, "expected_measured_sample_count": 32 * 4 * samples,
                    "source_commit": args.expected_source_commit, "orchestration_clearance_confirmed": True,
                    "campaign_authority": False})
        print(json.dumps({"fixture_started": name, "started_utc": started_utc,
                          "stdout_path": str(run_controls / "stdout.raw"),
                          "stderr_path": str(run_controls / "stderr.raw")}, sort_keys=True), flush=True)
        with (run_controls / "stdout.raw").open("xb") as stdout, (run_controls / "stderr.raw").open("xb") as stderr:
            child = subprocess.run(command, cwd=root, env=environment, stdout=stdout, stderr=stderr, check=False)
        finished_utc = _utc()
        _fresh_bytes(run_controls / "original-exit-code.txt", (str(child.returncode) + "\n").encode("ascii"))
        after = _source_state(root)
        _save_state(run_controls, "after", after)
        child_after_raw = _raw_source_proof(root, environment=environment, directory=run_controls, name="after")
        result = {"name": name, "started_utc": started_utc, "finished_utc": finished_utc,
                  "elapsed_seconds": (time.monotonic_ns() - started_ns) / 1_000_000_000,
                  "original_exit_code": child.returncode, "samples_per_branch": samples,
                  "expected_measured_sample_count": 32 * 4 * samples,
                  "complete_consumer_positive_asserted": False, "source_state_unchanged": after == before == initial,
                  "raw_source_before": child_before_raw, "raw_source_after": child_after_raw}
        for filename in ("stdout.raw", "stderr.raw"):
            payload = (run_controls / filename).read_bytes()
            result[filename] = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        if child.returncode == 0:
            try:
                report_path = base / name / "producer-stage-report.v2.json"
                report = json.loads(report_path.read_bytes())
                fresh = report["consumers"]["fresh_interpreter_guardian_cold_reader"]
                module_sha = hashlib.sha256((root / "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py").read_bytes()).hexdigest()
                if (report.get("complete_consumer_positive_asserted") is not True
                        or report.get("source_commit") != args.expected_source_commit
                        or report.get("expected_measured_sample_count") != 32 * 4 * samples
                        or report["consumers"]["assessment"]["coverage"]["accepted_sample_count"] != 32 * 4 * samples
                        or fresh.get("original_exit_code") != 0 or fresh.get("standalone_guardian_cold_reader_passed") is not True
                        or fresh.get("expected_default_module_sha256") != module_sha
                        or fresh["proof"]["preprocessing_contract_content_sha256"] != report["consumers"]["guardian"]["preprocessing_contract_sha256"]):
                    raise ValueError("zero-exit producer lacks exact complete/fresh-standalone proof")
                result["complete_consumer_positive_asserted"] = True
                result["producer_report"] = {"path": str(report_path), "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()}
            except Exception as error:
                result["runner_validation_error"] = {"type": type(error).__name__, "message": str(error)}
                exit_code = 1
        if not result["source_state_unchanged"] or not child_after_raw["proof_validated"]:
            result["runner_source_error"] = "exact Git state or stock raw committed bytes changed during child"
            result["complete_consumer_positive_asserted"] = False
            exit_code = 1
        _fresh_json(run_controls / "finished.v3.json", result)
        results.append(result)
        print(json.dumps({"fixture_finished": name, "original_exit_code": child.returncode,
                          "complete_consumer_positive_asserted": result["complete_consumer_positive_asserted"],
                          "finished_utc": finished_utc}, sort_keys=True), flush=True)
        if child.returncode:
            exit_code = child.returncode if 0 < child.returncode < 256 else 1
    final = _source_state(root)
    _save_state(controls, "after", final)
    after_raw = _raw_source_proof(root, environment=environment, directory=controls, name="after")
    if final != initial or not after_raw["proof_validated"]:
        exit_code = 1
    _fresh_json(controls / "run-result.v3.json", {"schema_version": 3, "source_commit": args.expected_source_commit,
                "finished_utc": _utc(), "exit_code": exit_code, "runs": results,
                "source_state_unchanged": final == initial, "raw_source_before": before_raw, "raw_source_after": after_raw,
                "both_complete_consumers_passed": exit_code == 0 and len(results) == len(RUNS) and all(
                    row["complete_consumer_positive_asserted"] for row in results), "campaign_authority": False})
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
