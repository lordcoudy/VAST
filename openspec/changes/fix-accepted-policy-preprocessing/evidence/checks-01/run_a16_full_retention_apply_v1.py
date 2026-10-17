#!/usr/bin/env python3
"""Capture the one explicitly authorized finite A16 evidence retention apply."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


HERE = Path(__file__).resolve().parent
PYTHON = "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python"
CONTROL = HERE / "a16-full-apply-control-01"
PLAN = HERE / "a16-full-originals.retention-plan.v1.json"
HELPER = HERE / "retain_a16_full_originals.py"
COMMON = HERE / "retain_a16_completed_originals.py"
EXPECTED = {
    str(HELPER): "ad27c8fdbd8823b20ba363bfbbe9dab1d4805e3d3b3c0508d4e300adc9fc742d",
    str(PLAN): "e7ed026de152f1e2f3e2472669c87db66eaa937e5b970909a82d8c846a66ee19",
    str(COMMON): "65fb7ef980246e1fd5b8054a4eaad6c04e6015928523532420c9f5e37bc68941",
}


def hashes():
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in EXPECTED}


def write(name, value):
    with (CONTROL / name).open("xb") as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    if sys.argv[1:] or sys.flags.optimize or sys.executable != PYTHON or sys.version_info[:3] != (3, 12, 3):
        raise ValueError("exact canonical capture interpreter/argv required")
    if os.getuid() != 1000 or os.getgid() != 1000 or os.environ["HOME"] != "/home/s-a-balashov":
        raise ValueError("ordinary UID/GID1000/HOME required")
    if hashes() != EXPECTED or CONTROL.resolve(strict=False) != CONTROL or os.path.lexists(CONTROL):
        raise ValueError("reviewed bytes or fresh capture boundary differs")
    CONTROL.mkdir(mode=0o700)
    command = [PYTHON, "-B", str(HELPER), "apply", "--plan", str(PLAN),
               "--reviewed-plan-sha256", EXPECTED[str(PLAN)]]
    write("command.json", command)
    write("hashes.before.json", hashes())
    started = datetime.now(timezone.utc).isoformat()
    interruptions = []
    with (CONTROL / "original.stdout.raw").open("xb") as stdout, (CONTROL / "original.stderr.raw").open("xb") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        while True:
            try:
                actual_rc = child.wait()
                break
            except BaseException as error:
                interruptions.append({"utc": datetime.now(timezone.utc).isoformat(), "type": type(error).__name__,
                                      "message": str(error), "traceback": traceback.format_exc()})
    finished = datetime.now(timezone.utc).isoformat()
    write("original.result.json", {"started_utc": started, "finished_utc": finished, "original_exit_code": actual_rc,
          "command": command, "interruptions": interruptions,
          "streams": {name: {"size_bytes": (CONTROL / name).stat().st_size,
                     "sha256": hashlib.sha256((CONTROL / name).read_bytes()).hexdigest()}
                     for name in ("original.stdout.raw", "original.stderr.raw")}})
    after = hashes()
    write("hashes.after.json", after)
    if actual_rc != 0 or interruptions or after != EXPECTED:
        raise ValueError("original retention failed or capture guards differ; originals preserved, no retry")
    print(json.dumps({"status": "closed", "original_exit_code": actual_rc, "control": str(CONTROL),
                      "helper_plan_common_hashes_unchanged": True, "new_qualification_authority": False}))
