"""Bounded original unit process capture; no workload beyond selected broker fixtures."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / sys.argv[1]
OUT.mkdir(mode=0o700)
registry = json.loads((ROOT / "artifacts/benchmark_recovery_20260930/packaging-source-rollforward.v4.json").read_bytes())
sources = {e["path"] for e in registry["final_actual_source_manifest"]["project_sources"]} | {
    "scripts/backend_publication_process_supervisor_v3.py",
    "tests/test_backend_publication_broker_terminal_v3.py",
    "tests/test_backend_publication_process_supervisor_v3.py",
    "tests/fixtures/backend_publication_v3_process_fixture.py",
}

limits = {e["path"]: int(e["size_bytes"]) for e in registry["final_actual_source_manifest"]["project_sources"]}
def snapshot():
    result = {}
    for name in sorted(sources):
        path = ROOT / name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            digest = hashlib.sha256()
            count = 0
            while block := os.read(fd, 65536):
                count += len(block)
                digest.update(block)
                assert count <= limits.get(name, 16 * 1024 * 1024), name
            names = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
            epoch = [int(getattr(before, k)) for k in names]
            assert epoch == [int(getattr(os.fstat(fd), k)) for k in names]
            assert epoch == [int(getattr(path.lstat(), k)) for k in names]
            assert count == before.st_size
            result[name] = {"size_bytes": count, "sha256": digest.hexdigest(), "epoch": epoch}
        finally:
            os.close(fd)
    return result

def write(name, value):
    with (OUT / name).open("xb") as output:
        output.write((json.dumps(value, sort_keys=True) + "\n").encode())
        output.flush()
        os.fsync(output.fileno())

before = snapshot()
write("source-before.json", before)
fixtures = OUT / "original-fixtures"
fixtures.mkdir(mode=0o700)
code = f"""
import pathlib,sys,unittest
sys.path.insert(0,{str(ROOT / 'tests')!r})
import test_backend_publication_broker_terminal_v3 as tests
tests.EVIDENCE_DIR=pathlib.Path({str(fixtures)!r})
suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
"""
argv = [sys.executable, "-I", "-B", "-c", code]
write("dispatch.json", {"argv": argv, "cwd": str(ROOT), "timeout_s": 60, "teardown_s": 10,
      "reviewed_planning_commit": "9c514a60d644c8c3ecd637eb83185a59aa2a5e01",
      "review_reference": "https://github.com/lordcoudy/VAST/pull/2#issuecomment-5906191857",
      "scope": "eight broker terminal units; real journal/child fixtures, no models/Docker/source/GPU; no full CI claim"})
begun = time.monotonic()
with (OUT / "stdout").open("xb") as stdout, (OUT / "stderr").open("xb") as stderr:
    process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                               stdout=stdout, stderr=stderr, start_new_session=True)
    original_stat = Path(f"/proc/{process.pid}/stat").read_text()
    timed_out = False
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
after = snapshot()
write("source-after.json", after)
assert after == before
files = {name: {"size_bytes": (OUT / name).stat().st_size,
                "sha256": hashlib.sha256((OUT / name).read_bytes()).hexdigest()}
         for name in ("stdout", "stderr", "dispatch.json", "source-before.json", "source-after.json")}
assert all(files[name]["size_bytes"] <= 1024 * 1024 for name in ("stdout", "stderr"))
write("execution.json", {"original_pid": process.pid, "original_proc_stat": original_stat,
      "returncode": process.returncode, "timed_out": timed_out, "elapsed_s": time.monotonic() - begun,
      "original_process_absent": not Path(f"/proc/{process.pid}").exists(),
      "source_before_after_equal": True, "source_count": len(sources), "files": files,
      "classification": "original focused unit prefix/result only; no full CI/hardware/publication acceptance"})
print(json.dumps({"returncode": process.returncode, "elapsed_s": time.monotonic() - begun,
                  "execution_path": str((OUT / "execution.json").relative_to(ROOT)),
                  "execution_sha256": hashlib.sha256((OUT / "execution.json").read_bytes()).hexdigest()}))
