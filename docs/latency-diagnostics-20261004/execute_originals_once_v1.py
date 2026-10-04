"""Root-owned one-shot offline invocation; no benchmark acceptance authority.

Run with the recorded canonical CPython after the CLI source/test review.
An existing execution directory consumes this invocation; no retry/resume.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "scripts/analyze_component_latency_v1.py"
MATH = HERE / "raw-independent-review/calculation.v2.json"
OUT = HERE / "original-cli-execution-v1"
NAMES = ("cpu-baseline", "cpu-shared", "gpu-baseline", "gpu-shared")


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def identity(path):
    data = path.read_bytes()
    return {"path": str(path), "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def main():
    if sys.version_info[:3] != (3, 12, 3):
        raise RuntimeError("canonical CPython3.12.3 is required for this invocation")
    OUT.mkdir(mode=0o700)  # No replacement, cleanup, retry or resume.
    original_math = json.loads(MATH.read_text(encoding="utf-8"))
    if len(original_math["arms"]) != len(NAMES):
        raise RuntimeError("the independently retained four original arms are required")
    source_before = identity(SOURCE)
    save(OUT / "invocation-start.v1.json", {
        "kind": "offline_diagnostic_invocation", "python": sys.version,
        "executable": sys.executable, "source": source_before,
        "independent_math": identity(MATH), "deadline_ms": 100,
        "acceptance_authority": False, "benchmark_rerun": False,
    })
    held = []
    terminals = []
    before_after = []
    primary_failure = None
    try:
        for name, arm in zip(NAMES, original_math["arms"], strict=True):
            for leaf, pin in sorted(arm["inputs"].items()):
                path = Path(arm["evidence_directory"]) / leaf
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                    raise RuntimeError(f"nonregular original input: {path}")
                handle = path.open("rb")
                held.append((handle, path, epoch(info), pin, name))
                if epoch(os.fstat(handle.fileno())) != epoch(info):
                    raise RuntimeError(f"original open identity changed: {path}")
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
                if digest != pin["sha256"] or info.st_size != pin["size_bytes"]:
                    raise RuntimeError(f"original input differs from independent calculation: {path}")
        for name, arm in zip(NAMES, original_math["arms"], strict=True):
            argv = [sys.executable, "-I", "-B", str(SOURCE), "--evidence-dir",
                    arm["evidence_directory"], "--deadline-ms", "100",
                    "--native-policy-evidence", str(Path(arm["evidence_directory"]) /
                                                    "publication_policy_decisions.jsonl"),
                    "--output-dir", str(OUT / name)]
            started = time.monotonic_ns()
            with (OUT / f"{name}.stdout.txt").open("xb") as stdout, \
                    (OUT / f"{name}.stderr.txt").open("xb") as stderr:
                result = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr,
                                        check=False)
            terminal = {"argv": argv, "exit_code": result.returncode,
                        "elapsed_s": (time.monotonic_ns() - started) / 1e9,
                        "stdout": identity(OUT / f"{name}.stdout.txt"),
                        "stderr": identity(OUT / f"{name}.stderr.txt")}
            save(OUT / f"{name}.terminal.v1.json", terminal)
            terminals.append(terminal)
            print(f"{name}: exit={result.returncode}; elapsed={terminal['elapsed_s']:.3f}s",
                  flush=True)
            if result.returncode != 0:
                raise RuntimeError(f"original diagnostic failed: {name}")
    except BaseException as error:
        primary_failure = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        stability_errors = []
        for handle, path, before, pin, name in held:
            try:
                handle.seek(0)
                after_hash = hashlib.file_digest(handle, "sha256").hexdigest()
                opened_after = epoch(os.fstat(handle.fileno()))
                named_after = epoch(path.lstat())
                unchanged = (before == opened_after == named_after and
                             after_hash == pin["sha256"])
                before_after.append({"arm": name, "path": str(path),
                                     "before": before, "opened_after": opened_after,
                                     "named_after": named_after, "sha256": after_hash,
                                     "unchanged": unchanged})
                if not unchanged:
                    stability_errors.append(str(path))
            except BaseException as error:
                stability_errors.append(f"{path}: {type(error).__name__}: {error}")
            finally:
                handle.close()
        source_after = identity(SOURCE)
        if source_before != source_after:
            stability_errors.append("diagnostic source changed during invocation")
        save(OUT / "invocation-terminal.v1.json", {
            "kind": "offline_diagnostic_invocation", "terminals": terminals,
            "source_before": source_before, "source_after": source_after,
            "input_stability": before_after, "stability_errors": stability_errors,
            "primary_failure": primary_failure, "leaf_handles_closed": True,
            "four_original_cli_successes": len(terminals) == 4 and
                all(t["exit_code"] == 0 for t in terminals) and
                primary_failure is None and not stability_errors,
            "acceptance_authority": False, "benchmark_rerun": False,
            "limits": ["Leaf hash/epoch stability only; no ancestor-custody, hardware",
                       "or original acceptance reattestation by this diagnostic."],
        })
        if stability_errors and primary_failure is None:
            raise RuntimeError("offline input/source stability failed")


if __name__ == "__main__":
    main()
