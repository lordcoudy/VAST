#!/usr/bin/env python3
"""Audited sequential artificial-observation consumer runs; not Q1 authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


EXPECTED_COMMIT = "591a93e778a9a7839da6278326d215e24e91ea45"
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + EXPECTED_COMMIT)
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
BASE_RELATIVE = Path("artifacts/accepted_policy_repair_20261011a")
ENTRYPOINT_RELATIVE = Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py")
CONTROLS_NAME = "consumer-complete-04-controls"
RUNS = ((30, "consumer-fixture-04-minimum30", ".apf04"),
        (31, "consumer-fixture-05-larger31", ".apf05"))


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_bytes(path: Path, value: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(value)


def _fresh_json(path: Path, value: object) -> None:
    _fresh_bytes(path, (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))


def _git(*arguments: str) -> bytes:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, check=True)
    return result.stdout


def _source_state() -> dict[str, bytes]:
    return {"head": _git("rev-parse", "HEAD"),
            "tracked_status": _git("status", "--porcelain=v1", "--untracked-files=no")}


def _require_clean_source_state(state: dict[str, bytes]) -> None:
    if state["head"].decode("ascii").strip() != EXPECTED_COMMIT:
        raise ValueError("frozen clone HEAD differs from the reviewed source commit")
    if state["tracked_status"]:
        raise ValueError("frozen clone has tracked source changes")


def _save_state(directory: Path, name: str, state: dict[str, bytes]) -> None:
    for kind, value in state.items():
        _fresh_bytes(directory / ("source-" + kind.replace("_", "-") + "." + name + ".txt"), value)


def _preflight() -> tuple[Path, Path, dict[str, bytes]]:
    if ROOT.resolve(strict=True) != ROOT or not ROOT.is_dir():
        raise ValueError("frozen clone root is missing or aliased")
    base = ROOT / BASE_RELATIVE
    if base.resolve(strict=True) != base or not base.is_dir():
        raise ValueError("fixture base is missing or aliased")
    if not PYTHON.is_file() or not (ROOT / ENTRYPOINT_RELATIVE).is_file():
        raise ValueError("canonical runtime or frozen entrypoint is missing")
    controls = base / CONTROLS_NAME
    for path in (controls, *(base / name for _, name, _ in RUNS)):
        if os.path.lexists(path):
            raise ValueError("exclusive output already exists: " + str(path))
    state = _source_state()
    _require_clean_source_state(state)
    return base, controls, state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    base, controls, initial_state = _preflight()
    commands = [[str(PYTHON), "-B", str(ROOT / ENTRYPOINT_RELATIVE),
                 "--project-root", str(ROOT), "--expected-source-commit", EXPECTED_COMMIT,
                 "--artifact-base", BASE_RELATIVE.as_posix(), "--namespace", "accepted-policy-repair-20261011a",
                 "--output-dir", (BASE_RELATIVE / name).as_posix(), "--socket-prefix", prefix,
                 "--samples-per-branch", str(samples), "--stage", "complete"]
                for samples, name, prefix in RUNS]
    if args.check_only:
        print(json.dumps({"preflight_passed": True, "source_commit": EXPECTED_COMMIT,
                          "controls_dir": str(controls), "commands": commands}, sort_keys=True), flush=True)
        return 0
    controls.mkdir()
    _save_state(controls, "before", initial_state)
    plan = {"schema_version": 1, "started_utc": _utc(), "source_commit": EXPECTED_COMMIT,
            "project_root": str(ROOT), "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "entrypoint_sha256": hashlib.sha256((ROOT / ENTRYPOINT_RELATIVE).read_bytes()).hexdigest(),
            "commands": commands, "environment": {"TMPDIR": "/var/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
            "campaign_authority": False, "physical_inference_observed": False,
            "limitations": ["Fresh original observations and front peers are artificial.",
                            "Real acceptance, F1, F5, closure and default guardian consumers are not substituted.",
                            "Measured fixture counts do not claim a Q1 campaign or a 126016-sample pilot replay."]}
    _fresh_json(controls / "run-plan.v1.json", plan)
    environment = dict(os.environ, TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    results = []
    exit_code = 0
    for (samples, name, _), command in zip(RUNS, commands):
        run_controls = controls / name
        run_controls.mkdir()
        before = _source_state()
        _save_state(run_controls, "before", before)
        _require_clean_source_state(before)
        started_utc, started_ns = _utc(), time.monotonic_ns()
        _fresh_json(run_controls / "started.v1.json", {"started_utc": started_utc, "command": command,
                    "samples_per_branch": samples, "expected_measured_sample_count": 32 * 4 * samples,
                    "source_commit": EXPECTED_COMMIT, "campaign_authority": False})
        print(json.dumps({"fixture_started": name, "started_utc": started_utc,
                          "stdout_path": str(run_controls / "stdout.raw"),
                          "stderr_path": str(run_controls / "stderr.raw")}, sort_keys=True), flush=True)
        with (run_controls / "stdout.raw").open("xb") as stdout, (run_controls / "stderr.raw").open("xb") as stderr:
            child = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr, check=False)
        finished_utc = _utc()
        _fresh_bytes(run_controls / "original-exit-code.txt", (str(child.returncode) + "\n").encode("ascii"))
        after = _source_state()
        _save_state(run_controls, "after", after)
        result = {"name": name, "started_utc": started_utc, "finished_utc": finished_utc,
                  "elapsed_seconds": (time.monotonic_ns() - started_ns) / 1_000_000_000,
                  "original_exit_code": child.returncode, "samples_per_branch": samples,
                  "expected_measured_sample_count": 32 * 4 * samples, "complete_consumer_positive_asserted": False,
                  "source_state_unchanged": after == before == initial_state}
        for filename in ("stdout.raw", "stderr.raw"):
            payload = (run_controls / filename).read_bytes()
            result[filename] = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        if child.returncode == 0:
            try:
                report_path = base / name / "producer-stage-report.v2.json"
                report = json.loads(report_path.read_bytes())
                if (report.get("complete_consumer_positive_asserted") is not True or
                        report.get("source_commit") != EXPECTED_COMMIT or
                        report.get("expected_measured_sample_count") != 32 * 4 * samples or
                        report["consumers"]["assessment"]["coverage"]["accepted_sample_count"] != 32 * 4 * samples):
                    raise ValueError("zero-exit producer lacks the expected complete consumer proof")
                result["complete_consumer_positive_asserted"] = True
                result["producer_report"] = {"path": str(report_path),
                                             "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()}
            except Exception as error:
                result["runner_validation_error"] = {"type": type(error).__name__, "message": str(error)}
                exit_code = 1
        if not result["source_state_unchanged"]:
            result["runner_source_error"] = "source HEAD or tracked status changed during the child"
            exit_code = 1
        _fresh_json(run_controls / "finished.v1.json", result)
        results.append(result)
        print(json.dumps({"fixture_finished": name, "original_exit_code": child.returncode,
                          "complete_consumer_positive_asserted": result["complete_consumer_positive_asserted"],
                          "finished_utc": finished_utc}, sort_keys=True), flush=True)
        if child.returncode:
            exit_code = child.returncode if 0 < child.returncode < 256 else 1
        if exit_code:
            break
    final_state = _source_state()
    _save_state(controls, "after", final_state)
    if final_state != initial_state:
        exit_code = 1
    _fresh_json(controls / "run-result.v1.json", {"schema_version": 1, "source_commit": EXPECTED_COMMIT,
                "finished_utc": _utc(), "exit_code": exit_code, "runs": results,
                "source_state_unchanged": final_state == initial_state,
                "both_complete_consumers_passed": exit_code == 0 and len(results) == len(RUNS) and all(
                    row["complete_consumer_positive_asserted"] for row in results), "campaign_authority": False})
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
