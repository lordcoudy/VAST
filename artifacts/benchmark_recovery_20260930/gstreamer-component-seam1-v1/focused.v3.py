"""Finite original metadata units; no image/model/source/inference work."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PINS = (
    "scripts/publication_policy_qualification_runtime_inputs_v2.py",
    "scripts/publication_gstreamer_component_authority_v1.py",
    "scripts/publication_gstreamer_component_inputs_v1.py",
    "scripts/checkpoint_model_parity_acceptance_v4.py",
    "scripts/publication_policy_qualification_bootstrap_v2.py",
    "tests/test_publication_gstreamer_component_inputs_v1.py",
    "scripts/publication_guardian_runtime_expectations_v1.py",
    "scripts/checkpoint_gstreamer_analytics_sidecar.py",
)
MODULES = ("test_publication_gstreamer_component_inputs_v1",
           "test_checkpoint_model_parity_acceptance_v4",
           "test_publication_policy_qualification_bootstrap_v2",
           "test_publication_policy_qualification_runtime_inputs_v2")


def facts(path):
    raw = path.read_bytes()
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def snapshot():
    return {name: facts(ROOT / name) for name in PINS}


output = Path(sys.argv[1])
output.mkdir(parents=False, exist_ok=False)
before = snapshot()
code = ("import sys,unittest;sys.path.insert(0," + repr(str(ROOT)) + ");sys.path.insert(0," + repr(str(ROOT / "tests")) + ");"
        "suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in " + repr(MODULES) + ");"
        "r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(not r.wasSuccessful())")
argv = [sys.executable, "-I", "-B", "-c", code]
start = time.monotonic()
with (output / "stdout.bin").open("xb") as stdout, (output / "stderr.bin").open("xb") as stderr:
    process = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
    pid, group = process.pid, os.getpgid(process.pid)
    stat_before = Path("/proc", str(pid), "stat").read_text()
    dispatch = {"argv": argv, "pid": pid, "group": group, "proc_stat": stat_before,
                "before": before, "controller": facts(Path(__file__)),
                "scope": "local_metadata_units_only", "timeout_s": 90, "teardown_s": 10}
    with (output / "dispatch.json").open("x") as stream:
        json.dump(dispatch, stream, sort_keys=True); stream.write("\n")
    timed_out = False
    try:
        process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(group, signal.SIGKILL)
        process.wait(timeout=10)
try:
    os.killpg(group, 0)
    group_absent = False
except ProcessLookupError:
    group_absent = True
result = {"dispatch": dispatch, "returncode": process.returncode, "timed_out": timed_out,
          "elapsed_s": time.monotonic() - start, "after": snapshot(), "accepted": False,
          "quiescence": {"original_pid_absent": not Path("/proc", str(pid)).exists(), "original_group_absent": group_absent},
          "outputs": {name: facts(output / name) for name in ("stdout.bin", "stderr.bin")}}
with (output / "execution.json").open("x") as stream:
    json.dump(result, stream, sort_keys=True); stream.write("\n")
print(json.dumps({key: result[key] for key in ("returncode", "timed_out", "elapsed_s", "quiescence")}))
