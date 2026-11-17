#!/usr/bin/env python3
"""Two authorized postmortem ELF probes, not original custody or qualification."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


COMMIT = "a16f243e7e80f093342ccdddf717d59d6d46f0a8"
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + COMMIT)
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
ENGINE = BASE / "consumer-fixture-08-minimum30/command-boundary/immutable/engine"
SOCKET = Path("/var/tmp/apf08-u4vbgm5h/runtime/engine.sock")
OUT = Path(__file__).absolute().parent / "probe-boundary-diagnosis-01"
PINS = {
    ROOT / "scripts/publication_policy_qualification_runtime_inputs_v2.py": "a4358e759a24cbf49652cecbbb7a30199476d0c3539be5e1c9dd87b972aeb2f8",
    ROOT / "tests/fixtures/accepted_policy_physical_fixture_v2.py": "39c12abb6315a6117d4b238f354b605108df1a4c0d34b0b7a45f5e0f3d5817d2",
    ROOT / "tests/fixtures/accepted_policy_original_custody_fixture_v1.py": "f1b37fa796714770443d79da89e70d4b5a017b279a9591791439f2e5d2b5fd28",
    ENGINE: "9b0d7ea41df75ccfd227e48a8c4d2572a2a95cad64b33932c9ac2a1582def510",
    ENGINE.parent / "engine.c": "2d8f1df1ff855a7cc514b579c32d9f3700573a4e6e2ee5b77e82a6e274c4444a",
    BASE / "consumer-runtime-observations-02/image-inspect-map.json": "890fecbd90e5f9c7af3ceecd0500e06e2d9fde8dc1ec38324f9d66de2335ecdb",
    BASE / "consumer-runtime-observations-02/device-probe-map.json": "5253f71f50662019e3543ac8338d2ef7ac09c9a26a25132f4af45564bdaf4921",
}
CASES = (
    ("openvino_gva", "sha256:61bfedeb4f6e74dfde3650375fb3f048c5ded32b5b252497394c44f098afd2ce"),
    ("gstreamer_custom", "sha256:8208fb4ee35f14cfc1d191baf5c9b35b213fdfbc955697b6d6b6cdd9b304d60e"),
)


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_bytes(path, value):
    with path.open("xb") as stream:
        stream.write(value)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii"))


def hashes():
    result = []
    for path, expected in PINS.items():
        if path.resolve(strict=True) != path:
            raise ValueError("diagnostic input path is aliased: " + str(path))
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError("diagnostic input bytes drifted: " + str(path))
        result.append({"path": str(path), "sha256": actual, "size_bytes": len(raw)})
    return result


def state():
    result = {}
    for name, arguments in (
        ("head", ("rev-parse", "HEAD")),
        ("tracked_status", ("status", "--porcelain=v1", "--untracked-files=no")),
    ):
        value = subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), *arguments], check=True, capture_output=True)
        result[name] = value.stdout.decode("ascii")
    if result["head"].strip() != COMMIT or result["tracked_status"]:
        raise ValueError("exact frozen tracked source state drifted")
    return result


def capture(name, command, environment):
    write_json(OUT / (name + ".started.v1.json"), {
        "started_utc": utc(), "command": command, "cwd": str(ROOT),
        "environment": {key: environment.get(key) for key in ("HOME", "TMPDIR", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH")},
    })
    started = utc()
    child = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=180.0)
    write_bytes(OUT / (name + ".stdout.raw"), child.stdout)
    write_bytes(OUT / (name + ".stderr.raw"), child.stderr)
    result = {
        "command": command, "cwd": str(ROOT), "started_utc": started, "finished_utc": utc(),
        "original_exit_code": child.returncode,
        "stdout_size_bytes": len(child.stdout), "stderr_size_bytes": len(child.stderr),
        "stdout_sha256": hashlib.sha256(child.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(child.stderr).hexdigest(),
    }
    write_json(OUT / (name + ".finished.v1.json"), result)
    return child, result


def raw_proof(name, environment):
    program = (
        "import json,sys; from pathlib import Path; root=Path(" + repr(str(ROOT)) + "); "
        "sys.path.insert(0,str(root/'scripts')); import run_ci_checks as ci; "
        "paths=ci.tracked_paths(root); ci.verify_committed_bytes(root,paths); "
        "print(json.dumps({'raw_committed_bytes_verified':True,'tracked_path_count':len(paths),"
        "'verifier_path':ci.__file__},sort_keys=True))"
    )
    child, result = capture("raw-source-" + name, [str(PYTHON), "-B", "-c", program], environment)
    if child.returncode != 0 or child.stderr:
        raise ValueError("stock raw source verifier failed closed")
    proof = json.loads(child.stdout)
    if proof != {"raw_committed_bytes_verified": True, "tracked_path_count": 12115,
                 "verifier_path": str(ROOT / "scripts/run_ci_checks.py")}:
        raise ValueError("stock raw source proof identity/count drifted")
    return {"capture": result, "proof": proof}


def command(system, image):
    extra = ("--env", "GST_REGISTRY=/opt/vast/share/gstreamer-registry.bin",
             "--env", "GST_REGISTRY_UPDATE=no") if system == "gstreamer_custom" else ()
    return [str(ENGINE), "--host=unix://" + str(SOCKET),
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128", "--ipc", "none",
        "--gpus", "all", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=268435456",
        "--mount", "type=bind,src=" + str(ROOT) + ",dst=/workspace/project,readonly",
        "--env", "HOME=/tmp", "--env", "XDG_CACHE_HOME=/tmp", *extra,
        "--workdir", "/workspace/project", "--entrypoint", "/usr/bin/python3", image,
        "-B", "/workspace/project/deploy/openvino/checkpoint/probe_openvino_devices.py"]


def main():
    if Path(sys.executable).resolve() != PYTHON.resolve() or not sys.dont_write_bytecode:
        raise ValueError("canonical Python -B is mandatory")
    if ROOT.resolve(strict=True) != ROOT or OUT.is_relative_to(ROOT) or os.path.lexists(OUT):
        raise ValueError("fixed fresh diagnostic namespace is invalid or occupied")
    before_hashes, before_state = hashes(), state()
    OUT.mkdir(mode=0o700)
    environment = dict(os.environ, TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    result = {
        "source_commit": COMMIT, "source_root": str(ROOT), "started_utc": utc(),
        "input_hashes_before": before_hashes, "source_state_before": before_state,
        "diagnostic_not_original_invocation": True,
        "path_substitution": "closed held /proc/self/fd path replaced by its retained byte-identical physical ELF",
        "original_engine_socket_path": str(SOCKET), "probes": [],
        "qualification_executed": False, "campaign_authority": False,
    }
    exit_code = 1
    try:
        result["raw_source_before"] = raw_proof("before", environment)
        for system, image in CASES:
            child, observed = capture(system, command(system, image), environment)
            observed["system"] = system
            observed["image_id"] = image
            result["probes"].append(observed)
            if child.returncode != 52 or child.stdout or child.stderr:
                raise ValueError("probe result differs from missing exact image-ID reply hypothesis")
        exit_code = 0
    except Exception as error:
        result["diagnostic_error"] = repr(error)
    finally:
        result["input_hashes_after"] = hashes()
        result["source_state_after"] = state()
        result["raw_source_after"] = raw_proof("after", environment)
        result["finished_utc"] = utc()
        result["diagnostic_exit_code"] = exit_code
        write_json(OUT / "diagnostic-result.v1.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
