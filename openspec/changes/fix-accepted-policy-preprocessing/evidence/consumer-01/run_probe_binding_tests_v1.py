#!/usr/bin/env python3
"""Original bounded fixture probe RED/GREEN capture, never a consumer run."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
OUT = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/probe-boundary-diagnosis-01"
SOURCES = (
    "tests/test_accepted_policy_fixture_probe_binding_v2.py",
    "tests/fixtures/accepted_policy_physical_fixture_v2.py",
    "tests/fixtures/accepted_policy_original_custody_fixture_v1.py",
    "scripts/publication_policy_qualification_runtime_inputs_v2.py",
)


def utc():
    return datetime.now(timezone.utc).isoformat()


def hashes():
    return [{"path": str(ROOT / name), "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
            for name in SOURCES]


def write(path, value):
    with path.open("xb") as stream:
        stream.write(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("red", "green"))
    args = parser.parse_args()
    if Path(sys.executable).resolve() != PYTHON.resolve() or not sys.dont_write_bytecode:
        raise ValueError("canonical Python -B is required")
    directory = OUT / ("focused-" + args.stage)
    directory.mkdir(mode=0o700, exist_ok=False)
    tests = ["tests.test_accepted_policy_fixture_probe_binding_v2.AcceptedPolicyFixtureProbeBindingV2Tests."
             "test_prepared_context_binds_system_probes_to_exact_patch_image_ids"] if args.stage == "red" else [
                 "tests.test_accepted_policy_fixture_probe_binding_v2",
                 "tests.test_accepted_policy_fixture_transport_v2",
                 "tests.test_accepted_policy_original_custody_fixture_v1",
             ]
    command = [str(PYTHON), "-B", "-m", "unittest", "-v", *tests]
    before = hashes()
    started = utc()
    environment = dict(os.environ, TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    child = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=180)
    finished = utc()
    write(directory / "stdout.raw", child.stdout)
    write(directory / "stderr.raw", child.stderr)
    result = {"stage": args.stage, "command": command, "cwd": str(ROOT), "started_utc": started,
        "finished_utc": finished, "original_exit_code": child.returncode,
        "stdout_bytes": len(child.stdout), "stderr_bytes": len(child.stderr),
        "stdout_sha256": hashlib.sha256(child.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(child.stderr).hexdigest(),
        "sources_before": before, "sources_after": hashes(),
        "scope": "bounded actual ELF/default-probe setup; expensive upstream setup providers are spies",
        "full_consumer_acceptance": False}
    write(directory / "result.v1.json", (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii"))
    sys.stdout.buffer.write(child.stdout)
    sys.stderr.buffer.write(child.stderr)
    print(json.dumps(result, sort_keys=True), flush=True)
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
