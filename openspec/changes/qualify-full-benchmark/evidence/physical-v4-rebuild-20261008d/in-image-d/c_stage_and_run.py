"""D(c): non-qualifying arm reproduction in the rebuilt runtime image.

Run in WSL as uid 1000 with the host publication python:
  python -B c_stage_and_run.py <deepstream|savant> <scratch_dir> <evidence_dir>

Stages copies of the attempt-2 (20261008c) materialized runtime inputs for the
cpu/h264/independent_processes cell into <scratch_dir>/inputs exactly as
checkpoint_<system>_publication_runtime_v3._materialize_inputs does (container
paths, 0400 files, 0700 dirs), builds the container argv exactly as
_container_argv does, substitutes only the new image ID, the scratch mount
sources and a scratch endpoint socket, and runs the container once.

The endpoint socket is a bound-then-closed UNIX socket file (no listener): the
guardian is intentionally absent, so any analytics connect is refused.
Nothing under the qfb root is written.
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

SYSTEM, SCRATCH, EVIDENCE = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
BUNDLES = ROOT / "artifacts/publication_policy_qualification_v2_qfb_20261008c/bootstrap/qualification-runtime-inputs-v2"
CAPTURE = ROOT / "artifacts/publication_operational_capture_v1_qfb_20261008c"
NEW_IMAGES = {
    "deepstream": "sha256:b236e0f4024f5b6566ca1c724dc1c48a118d10c51ce7df4f97bc0d425ead4157",
    "savant": "sha256:045ccc3527dac40959706a678480f1145a3c7de609a9262365f5787911f667a7",
}
# Operational context used by attempt 2 for the Savant original op (engine_02
# launch, sha 2d3eee...); DeepStream uses the bundle's own context (05).
CONTEXT_OVERRIDE = {"savant": "native_context_04.v1.json"}
PIDS = {"deepstream": "512", "savant": "4096"}
ARM_SUBCOMMAND = {"deepstream": [], "savant": ["arm"]}
KEY = {"deepstream": "deepstream_publication_runtime_v3", "savant": "savant_publication_runtime_v3"}
IN, OUT, OP = "/opt/vast/input", "/opt/vast/output", "/opt/vast/operational"
THREAD_ENV = ["OPENBLAS_NUM_THREADS=1", "OMP_NUM_THREADS=1", "MKL_NUM_THREADS=1", "NUMEXPR_NUM_THREADS=1"]


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


bundle_path = BUNDLES / SYSTEM / "cpu/h264/independent_processes.json"
bundle = json.loads(bundle_path.read_text())
runtime = bundle["runtime_inputs"]
raw = runtime["dataset"][KEY[SYSTEM]]
record = {"system": SYSTEM, "bundle": str(bundle_path), "bundle_sha256": sha(bundle_path),
          "old_image": raw["container_image"]["image_id"], "new_image": NEW_IMAGES[SYSTEM],
          "substitutions": [], "pins": []}

roles = {role: dict(value) for role, value in raw["files"].items()}
if SYSTEM in CONTEXT_OVERRIDE:
    path = CAPTURE / "capture-plan" / CONTEXT_OVERRIDE[SYSTEM]
    old = dict(roles["operational_request_context"])
    roles["operational_request_context"].update(
        path=str(path.relative_to(ROOT)), sha256=sha(path), size_bytes=path.stat().st_size)
    record["substitutions"].append({"role": "operational_request_context", "reason":
        "attempt-2 Savant original op used native_context_04 (engine_02 launch); bundle names 13",
        "from": old, "to": roles["operational_request_context"]})
sources = [dict(v) for v in raw["source_files"]]
models = [dict(v) for v in raw["model_files"]]
support = [dict(v) for v in raw["support_files"]]
materialized = [(r, v) for r, v in sorted(roles.items()) if r != "container_engine"]
materialized += [(f"source_files:{i}", v) for i, v in enumerate(sources)]
materialized += [(f"model_files:{i}", v) for i, v in enumerate(models)]
materialized += [(f"support_files:{i}", v) for i, v in enumerate(support)]

inputs = SCRATCH / "inputs"
inputs.mkdir(mode=0o700)
for role, pin in materialized:
    source = ROOT / pin["path"]
    actual = sha(source)
    if actual != pin["sha256"] or source.stat().st_size != pin["size_bytes"]:
        # Substitute the root's current bytes and record it.
        record["substitutions"].append({"role": role, "reason": "root bytes differ from bundle",
            "path": pin["path"], "bundle_sha256": pin["sha256"], "root_sha256": actual})
        pin["sha256"], pin["size_bytes"] = actual, source.stat().st_size
    relative = PurePosixPath(pin["container_path"]).relative_to(IN)
    target = inputs.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(source, "rb") as src, open(target, "xb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
    if sha(target) != pin["sha256"]:
        raise SystemExit(f"copy drift: {role}")
    target.chmod(0o400)
    record["pins"].append({"role": role, "path": pin["path"], "container_path": pin["container_path"],
                           "sha256": pin["sha256"], "size_bytes": pin["size_bytes"]})

output = SCRATCH / "output"
output.mkdir(mode=0o700)
operational = SCRATCH / "operational"
operational.mkdir(mode=0o700)
(SCRATCH / "r").mkdir(mode=0o700)
endpoint = SCRATCH / "r" / "a.sock"
holder = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
holder.bind(str(endpoint))
holder.close()  # socket inode stays; no listener -> connect is refused

argv = ["/usr/bin/docker", "run", "--name", f"claude-inimage-diag-c-{SYSTEM}", "--label", "claude-diag=1",
        "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "--gpus", "all", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--pids-limit", PIDS[SYSTEM]]
for item in THREAD_ENV:
    argv += ["--env", item]
argv += ["--mount", f"type=bind,src={inputs},dst={IN},readonly",
         "--mount", f"type=bind,src={output},dst={OUT}",
         "--mount", f"type=bind,src={operational},dst={OP}"]
for socket_binding in raw["endpoint_sockets"]:
    argv += ["--mount", f"type=bind,src={endpoint},dst={socket_binding['container_path']},readonly"]
argv += ["--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=1073741824", NEW_IMAGES[SYSTEM],
         *ARM_SUBCOMMAND[SYSTEM],
         "--config", roles["experiments_config"]["container_path"],
         "--datasets", roles["datasets_config"]["container_path"],
         "--adapter-config", roles["adapter_config"]["container_path"],
         "--analytics-model-manifest", roles["analytics_model_manifest"]["container_path"],
         "--policy-capability-manifest", roles["policy_capability_manifest"]["container_path"],
         "--policy-calibration", roles["policy_calibration"]["container_path"],
         "--scenario", runtime["scenario"], "--topology-kind", runtime["topology_kind"],
         "--codec", str(runtime["codec"]), "--policy", str(runtime["policy"]),
         "--deadline-ms", str(float(runtime["deadline_ms"])), "--output-dir", OUT,
         "--run-id", bundle["run_id"], "--arm-id", bundle["arm_id"],
         "--duration", str(int(runtime["duration_s"])),
         "--ready-timeout", str(float(raw["ready_timeout_s"])),
         "--drain-timeout", str(float(raw["drain_timeout_s"])),
         "--start-lead-ms", str(int(raw["start_lead_ms"]))]
for value in sources:
    argv += ["--source-binding", f"{value['sha256']}={value['container_path']}"]
for value in models:
    argv += ["--model-binding", f"{value['sha256']}={value['container_path']}"]
for value in support:
    argv += ["--support-binding", f"{value['sha256']}={value['container_path']}"]
if raw["static_hybrid_map"] is not None:
    raise SystemExit("static map not expected for cpu_only")
if raw["defer_full_resource_acceptance"]:
    argv.append("--defer-full-resource-acceptance")
if "operational_capture" in raw:
    argv += ["--operational-request-context", roles["operational_request_context"]["container_path"],
             "--operational-output-dir", OP]
record["argv"] = argv

if SYSTEM == "savant":
    # Self-check: same container arguments as attempt-2 engine_02 apart from
    # cidfile/name/label, image and scratch paths.
    launch = json.loads((CAPTURE / "process-captures/savant-original-savant-cpu-h264-independent-processes/engine_02.launch.v1.json").read_text())["argv"]
    old_scratch = "/var/tmp/vqfb1008c/s/vast-savant-v3-qualification-arm-v2-savant-cpu-h264-independent-processes-q4gntr2i"

    def normalize(values, scratch, image, sock):
        result, index = [], 1
        while index < len(values):
            item = values[index]
            if item in ("--cidfile", "--name", "--label"):
                index += 2
                continue
            result.append(item.replace(scratch, "<S>").replace(image, "<IMG>").replace(sock, "<SOCK>"))
            index += 1
        return result
    record["argv_matches_attempt2_engine02"] = normalize(
        launch, old_scratch, raw["container_image"]["image_id"], "/var/tmp/vqfb1008c/r/a.sock"
    ) == normalize(argv, str(SCRATCH), NEW_IMAGES[SYSTEM], str(endpoint))

started = time.monotonic()
try:
    completed = subprocess.run(argv, capture_output=True, timeout=1200)
    returncode, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
except subprocess.TimeoutExpired as error:
    returncode, stdout, stderr = "host_timeout_1200s", error.stdout or b"", error.stderr or b""
record["returncode"] = returncode
record["duration_s"] = round(time.monotonic() - started, 3)
record["stdout_bytes"], record["stderr_bytes"] = len(stdout), len(stderr)
record["stdout_sha256"] = hashlib.sha256(stdout).hexdigest()
record["stderr_sha256"] = hashlib.sha256(stderr).hexdigest()
record["output_tree"] = sorted(
    f"{p.relative_to(SCRATCH)}\t{p.stat().st_size if p.is_file() else 'dir'}"
    for base in (output, operational) for p in base.rglob("*")
)
prefix = EVIDENCE / f"c_{SYSTEM}"
(prefix.parent / f"{prefix.name}.stdout.raw").write_bytes(stdout)
(prefix.parent / f"{prefix.name}.stderr.raw").write_bytes(stderr)
(prefix.parent / f"{prefix.name}.record.json").write_text(json.dumps(record, indent=1) + "\n")
# Keep small native diagnostics (logs/json/csv <= 2 MiB) from the scratch output.
keep = EVIDENCE / f"c_{SYSTEM}_output"
for base in (output, operational):
    for path in base.rglob("*"):
        if path.is_file() and path.stat().st_size <= 2 * 1024 * 1024:
            destination = keep / path.relative_to(SCRATCH)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
print(json.dumps({k: record[k] for k in ("system", "returncode", "duration_s", "stderr_bytes",
                  "stderr_sha256", "substitutions") if k in record}, indent=1))
print("argv_matches_attempt2_engine02:", record.get("argv_matches_attempt2_engine02"))
print(stderr.decode("utf-8", "replace")[-8000:])
