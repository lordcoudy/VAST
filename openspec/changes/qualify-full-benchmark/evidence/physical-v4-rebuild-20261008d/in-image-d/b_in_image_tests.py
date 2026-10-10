"""D(b): run the test modules covering the Amendment 6 fixed files inside a
runtime image with its own python3.  Root is mounted read-only at /work/root;
scripts and tests are imported from there.  Per-module logs go to /work/out.

Run inside the image: python3 -B /work/tools/b_in_image_tests.py <system>
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SYSTEM = sys.argv[1]
ROOT = Path("/work/root")
OUT = Path("/work/out") / SYSTEM
MODULES = (
    "test_runtime_image_python310_compat_v1",
    "test_checkpoint_runtime",
    "test_checkpoint_runtime_inherited_fds",
    "test_checkpoint_model_parity",
    "test_checkpoint_gstreamer_analytics_bridge",
    "test_checkpoint_publication_runtime",
    "test_checkpoint_native_policy_runtime",
    "test_publication_operational_container_custody_v1",
    "test_publication_operational_process_custody_v1",
    "test_publication_operational_runtime_context_v1",
    "test_extract_kpp_legacy_iss",
    "test_full_resource_qualification",
    "test_full_resource_qualification_index_v1",
    "test_publication_policy_qualification",
    "test_publication_policy_qualification_execution_closure_v1",
    "test_checkpoint_savant_container_runtime_v3",
    "test_checkpoint_deepstream_container_runtime_v3",
)

OUT.mkdir(parents=True, exist_ok=True)
image_path = [item for item in os.environ.get("PYTHONPATH", "").split(":") if item]
environment = os.environ.copy()
# Root scripts/tests first (code under test), then the image's own path
# entries (e.g. /opt/savant) for SDK packages.
environment["PYTHONPATH"] = ":".join(
    [str(ROOT / "scripts"), str(ROOT / "tests"), str(ROOT)]
    + [item for item in image_path if item != "/opt/vast/checkpoint"]
)
environment["PYTHONDONTWRITEBYTECODE"] = "1"
environment["TMPDIR"] = "/tmp"
summary = {"system": SYSTEM, "python": sys.version, "pythonpath": environment["PYTHONPATH"],
           "cwd": str(ROOT), "modules": {}}
for module in MODULES:
    if not (ROOT / "tests" / f"{module}.py").is_file():
        summary["modules"][module] = {"status": "missing"}
        continue
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "-v", module],
            cwd=str(ROOT), env=environment, capture_output=True, timeout=1500,
        )
        returncode, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as error:
        returncode, stdout, stderr = "timeout", error.stdout or b"", error.stderr or b""
    elapsed = round(time.monotonic() - started, 2)
    (OUT / f"{module}.stdout.log").write_bytes(stdout)
    (OUT / f"{module}.stderr.log").write_bytes(stderr)
    tail = [line for line in stderr.decode("utf-8", "replace").splitlines() if line.strip()][-3:]
    summary["modules"][module] = {"returncode": returncode, "elapsed_s": elapsed, "tail": tail}
(OUT / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
print(json.dumps(summary, indent=1, sort_keys=True))
