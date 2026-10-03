"""Bounded original unit execution; no image/source/inference workload."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
PINS = ("scripts/publication_policy_qualification_runtime_inputs_v2.py",
        "scripts/publication_gstreamer_component_authority_v1.py",
        "scripts/publication_gstreamer_component_inputs_v1.py",
        "tests/test_publication_gstreamer_component_inputs_v1.py")
def snapshot():
    return {name: {"size_bytes": (ROOT / name).stat().st_size,
                   "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
            for name in PINS if (ROOT / name).is_file()}

output = Path(sys.argv[1])
output.mkdir(parents=False, exist_ok=False)
before = snapshot()
code = "import sys,unittest;sys.path.insert(0,'" + str(ROOT / 'tests') + "');suite=unittest.defaultTestLoader.loadTestsFromName('test_publication_gstreamer_component_inputs_v1');r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(not r.wasSuccessful())"
argv = [sys.executable, "-I", "-B", "-c", code]
start = time.monotonic()
with (output / "stdout.bin").open("xb") as stdout, (output / "stderr.bin").open("xb") as stderr:
    process = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr, start_new_session=True)
    dispatch = {"argv": argv, "pid": process.pid, "group": os.getpgid(process.pid),
                "before": before, "scope": "local_metadata_unit_only", "timeout_s": 60}
    (output / "dispatch.json").write_text(json.dumps(dispatch, sort_keys=True) + "\n")
    timed_out = False
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
result = {"dispatch": dispatch, "returncode": process.returncode, "timed_out": timed_out,
          "elapsed_s": time.monotonic() - start, "after": snapshot(), "accepted": False,
          "outputs": {name: {"size_bytes": (output / name).stat().st_size,
                              "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest()}
                      for name in ("stdout.bin", "stderr.bin")}}
with (output / "execution.json").open("x") as stream:
    json.dump(result, stream, sort_keys=True)
    stream.write("\n")
print(json.dumps({"returncode": process.returncode, "timed_out": timed_out, "elapsed_s": result["elapsed_s"]}))
