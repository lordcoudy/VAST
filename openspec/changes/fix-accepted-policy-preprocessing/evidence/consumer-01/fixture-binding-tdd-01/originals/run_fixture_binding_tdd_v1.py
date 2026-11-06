"""Capture one bounded fixture-binding unittest run; never run a producer."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
BASE = Path("/mnt/e/STUDY/VAST/tmp/host-cache-cleanup-20261012/fixture-binding-tdd-01")
PYTHON = "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python"
SOURCES = ("tests/fixtures/accepted_policy_consumer_fixture_v2.py",
           "tests/test_accepted_policy_fixture_binding_v2.py")


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def fresh_json(path, value):
    with path.open("x", encoding="ascii") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("red", "green"), required=True)
    args = parser.parse_args()
    if (sys.executable != PYTHON or sys.version_info[:3] != (3, 12, 3)
            or sys.flags.optimize != 0 or os.getuid() != 1000 or os.getgid() != 1000
            or os.environ.get("HOME") != "/home/s-a-balashov" or os.environ.get("TMPDIR") != "/var/tmp"):
        raise RuntimeError("canonical ordinary unoptimized fixture-test runtime required")
    directory = BASE / args.phase
    directory.mkdir(parents=True, exist_ok=False)
    target = "tests.test_accepted_policy_fixture_binding_v2"
    if args.phase == "red":
        target += ".AcceptedPolicyFixtureBindingV2Tests.test_complete_fixture_binding_uses_absolute_stock_output_contract"
    command = [PYTHON, "-B", "-m", "unittest", target, "-v"]
    before = hashes()
    started = datetime.now(timezone.utc).isoformat()
    fresh_json(directory / "command.v1.json", {"argv": command, "cwd": str(ROOT), "started_utc": started,
               "uid": os.getuid(), "gid": os.getgid(), "python_version": sys.version,
               "no_complete_consumer_or_campaign": True})
    fresh_json(directory / "source-hashes.before.json", before)
    with (directory / "stdout.raw").open("xb") as stdout, (directory / "stderr.raw").open("xb") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        original_rc = child.wait()
    after = hashes()
    fresh_json(directory / "source-hashes.after.json", after)
    result = {"argv": command, "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
              "original_exit_code": original_rc, "source_hashes_unchanged": before == after,
              "phase": args.phase, "no_complete_consumer_or_campaign": True}
    fresh_json(directory / "result.v1.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    if before != after:
        raise RuntimeError("managed fixture/test source bytes changed during original run")
    return original_rc


if __name__ == "__main__":
    sys.exit(main())
