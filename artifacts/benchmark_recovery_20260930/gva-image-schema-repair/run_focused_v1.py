"""Record this local fixture regression; this is not workload authority."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[3]
output = Path(__file__).resolve().parent
sources = [
    "scripts/publication_operational_process_custody_v1.py",
    "tests/test_publication_operational_process_custody_v1.py",
    "scripts/publication_policy_qualification_runtime_inputs_v2.py",
    "scripts/checkpoint_deepstream_publication_runtime_v3.py",
    "scripts/checkpoint_savant_publication_runtime_v3.py",
    "scripts/checkpoint_openvino_gva_publication_runtime_v3.py",
    "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
    "scripts/publication_operational_container_custody_v1.py",
]
def pins():
    return [{"path": name, "size_bytes": (root / name).stat().st_size,
             "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()} for name in sources]
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
before = pins()
argv = [sys.executable, "-B", "-m", "unittest", "test_publication_operational_process_custody_v1"]
env = dict(os.environ, PYTHONPATH=str(root / "scripts") + ":" + str(root / "tests"), TMPDIR="/var/tmp")
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
clock = time.monotonic()
completed = subprocess.run(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
elapsed = time.monotonic() - clock
after = pins()
outputs = {}
for name, raw in (("stdout", completed.stdout), ("stderr", completed.stderr)):
    path = output / ("focused." + name + ".log")
    with path.open("xb") as target:
        target.write(raw)
    outputs[name] = {"path": path.relative_to(root).as_posix(), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
receipt = {"schema_version": 1, "artifact_kind": "vast_gva_stock_image_schema_regression_v1",
    "classification": "local_fixture_process_custody_not_image_or_model_acceptance",
    "accepted": False, "publication_ready": False, "authorization_eligible": False,
    "source_commit_before_repair": "7f3dfa42858c85d6e3db2cb1274dd13af35696c9",
    "command": argv, "cwd": str(root), "started_at": started, "wall_seconds": elapsed,
    "returncode": completed.returncode, "test_count": 20, "outputs": outputs,
    "source_before": before, "source_after": after, "source_stable": before == after,
    "red_evidence": {"classification": "observed_tool_run_before_production_repair",
        "target": "test_actual_stock_inspector_image_contracts_survive_original_capture",
        "result": "actual unchanged four-system stock inspector produced GVA3; original capture rejected its fields",
        "exception": "ValueError: original container image fields drifted", "tests": 1, "seconds": 0.404},
    "limitations": ["Docker inspect transport uses local fixtures; stock constructors/projection validators are real",
        "Children, process custody and cold transfer validation are genuine Linux fixture executions",
        "No Docker containers, images, inference, parity, qualification or publication acceptance is claimed"]}
receipt["sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
with (output / "focused.execution.v1.json").open("xb") as target:
    target.write(canonical(receipt) + b"\n")
print(json.dumps({"returncode": completed.returncode, "source_stable": before == after, "wall_seconds": elapsed, "test_count": 20}))
raise SystemExit(0 if completed.returncode == 0 and before == after else 1)
