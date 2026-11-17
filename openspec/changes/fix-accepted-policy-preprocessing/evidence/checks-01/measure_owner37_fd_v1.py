"""Bounded FD diagnosis of one unchanged frozen-source unittest, not acceptance.

Parent-side /proc sampling observes a fresh child. The child's only hooks are
unittest result start/stop events; no production validator or provider changes.
Each limit is local to that child, and all outputs stay outside the source root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import unittest


SHA = "591a93e778a9a7839da6278326d215e24e91ea45"
SOURCE = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + SHA)
PYTHON = Path("/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python")
TEST = ("tests.test_publication_qualification_operational_owner_v1.QualificationOwner37Tests."
        "test_owner_executes_exact_37_and_binding_passes_cold_closure_with_real_validators")
OUTPUT_PARENT = Path("/var/tmp")
OUTPUT_PREFIX = "vast-repair-owner37-fd-"


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _exclusive_json(path, value):
    with path.open("xb") as stream:
        stream.write(_json_bytes(value))


def _identity():
    return {"pid": os.getpid(), "uid": os.getuid(), "gid": os.getgid(),
            "executable": sys.executable, "cwd": str(Path.cwd()),
            "nofile": list(resource.getrlimit(resource.RLIMIT_NOFILE)),
            "tmpdir": os.environ.get("TMPDIR"), "monotonic_ns": time.monotonic_ns()}


def _fd_snapshot(pid):
    directory = Path("/proc") / str(pid) / "fd"
    rows = []
    try:
        names = os.listdir(directory)
    except OSError as error:
        return {"unavailable": type(error).__name__ + ": " + str(error)}
    for name in names:
        try:
            target = os.readlink(directory / name)
        except OSError:
            continue
        rows.append({"fd": int(name), "target": target})
    rows.sort(key=lambda row: row["fd"])
    return {"count": len(rows), "rows": rows}


def _source_proof():
    head = subprocess.run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                          check=True, capture_output=True).stdout.decode("ascii").strip()
    status = subprocess.run(["git", "-C", str(SOURCE), "status", "--porcelain", "--untracked-files=no"],
                            check=True, capture_output=True).stdout
    if head != SHA or status:
        raise RuntimeError("frozen source commit or tracked status drifted")
    sys.path.insert(0, str(SOURCE / "scripts"))
    import run_ci_checks
    paths = run_ci_checks.tracked_paths(SOURCE)
    run_ci_checks.verify_committed_bytes(SOURCE, paths)
    return {"commit": head, "tracked_status": status.decode("ascii"),
            "tracked_paths_count": len(paths), "stock_raw_byte_verifier_passed": True}


def _child(output, limit):
    os.chdir(SOURCE)
    if resource.getrlimit(resource.RLIMIT_NOFILE)[1] != 1048576:
        raise RuntimeError("inherited hard RLIMIT_NOFILE is not the reviewed 1048576")
    resource.setrlimit(resource.RLIMIT_NOFILE, (limit, 1048576))
    sys.path.insert(0, str(SOURCE))
    before = {"identity": _identity(), "fds": _fd_snapshot(os.getpid())}
    _exclusive_json(output / "child-before-import.json", before)
    events = []

    class ObservedResult(unittest.TextTestResult):
        def startTest(self, test):
            events.append({"event": "startTest", "test_id": test.id(),
                           "identity": _identity(), "fds": _fd_snapshot(os.getpid())})
            super().startTest(test)

        def stopTest(self, test):
            events.append({"event": "stopTest", "test_id": test.id(),
                           "identity": _identity(), "fds": _fd_snapshot(os.getpid())})
            super().stopTest(test)

    suite = unittest.defaultTestLoader.loadTestsFromName(TEST)
    result = unittest.TextTestRunner(verbosity=2, resultclass=ObservedResult).run(suite)
    after = {"identity": _identity(), "fds": _fd_snapshot(os.getpid())}
    value = {"test_id": TEST, "tests_run": result.testsRun,
             "successful": result.wasSuccessful(),
             "failures": [{"test_id": test.id(), "traceback": trace} for test, trace in result.failures],
             "errors": [{"test_id": test.id(), "traceback": trace} for test, trace in result.errors],
             "skips": [{"test_id": test.id(), "reason": reason} for test, reason in result.skipped],
             "events": events, "after_runner_and_class_cleanup": after,
             "qualification_authority": False, "production_overrides": False}
    _exclusive_json(output / "child-result.json", value)
    return 0 if result.wasSuccessful() else 1


def _parent(output):
    if os.getuid() != 1000 or SOURCE.resolve(strict=True) != SOURCE:
        raise RuntimeError("expected UID1000 and exact physical frozen source")
    if output.parent != OUTPUT_PARENT or not output.name.startswith(OUTPUT_PREFIX):
        raise RuntimeError("output must be one new reviewed /var/tmp sibling namespace")
    if OUTPUT_PARENT.resolve(strict=True) != OUTPUT_PARENT:
        raise RuntimeError("output parent is not canonical")
    output.mkdir(mode=0o700)
    source_before = _source_proof()
    _exclusive_json(output / "source-before.json", source_before)
    helper = Path(__file__).resolve(strict=True)
    summary = {"schema_version": 1, "source_root": str(SOURCE), "commit": SHA,
               "helper_path": str(helper), "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
               "test_id": TEST, "sampling_interval_seconds": 0.01, "cases": [],
               "qualification_authority": False, "source_mutations": False}
    for limit in (1024, 10240):
        case = output / ("soft-" + str(limit))
        case.mkdir(mode=0o700)
        env = dict(os.environ, HOME="/home/s-a-balashov", USER="s-a-balashov",
                   LOGNAME="s-a-balashov", TMPDIR="/var/tmp", PYTHONDONTWRITEBYTECODE="1")
        command = [str(PYTHON), "-B", str(helper), "--child", "--output", str(case),
                   "--soft-limit", str(limit)]
        peak = {"count": -1, "rows": []}
        samples = 0
        first = None
        started = time.monotonic_ns()
        with (case / "stdout.log").open("xb") as stdout, (case / "stderr.log").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=SOURCE, env=env, stdout=stdout, stderr=stderr,
                                     close_fds=True, start_new_session=True)
            with (case / "fd-counts.jsonl").open("xb") as counts:
                while child.poll() is None:
                    snapshot = _fd_snapshot(child.pid)
                    row = {"monotonic_ns": time.monotonic_ns(), "count": snapshot.get("count"),
                           "unavailable": snapshot.get("unavailable")}
                    counts.write(json.dumps(row, sort_keys=True).encode("ascii") + b"\n")
                    samples += 1
                    if first is None and "count" in snapshot:
                        first = snapshot
                    if snapshot.get("count", -1) > peak["count"]:
                        peak = snapshot
                        peak["monotonic_ns"] = row["monotonic_ns"]
                    time.sleep(0.01)
            rc = child.wait()
        record = {"requested_soft_limit": limit, "original_returncode": rc, "pid": child.pid,
                  "command": command, "started_monotonic_ns": started,
                  "finished_monotonic_ns": time.monotonic_ns(), "sample_count": samples,
                  "first_observed": first, "peak_observed": peak,
                  "sampling_limit": "Observed peak is a lower bound; no prior suite process is instrumented."}
        _exclusive_json(case / "parent-observation.json", record)
        summary["cases"].append({key: record[key] for key in
                                 ("requested_soft_limit", "original_returncode", "pid", "sample_count")})
    summary["source_after"] = _source_proof()
    if summary["source_after"] != source_before:
        raise RuntimeError("before/after source proof differs")
    _exclusive_json(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--soft-limit", type=int, choices=(1024, 10240))
    args = parser.parse_args()
    if args.child:
        if args.soft_limit is None or args.output.parent.parent != OUTPUT_PARENT:
            parser.error("child requires a reviewed limit and /var/tmp case path")
        return _child(args.output, args.soft_limit)
    if args.soft_limit is not None:
        parser.error("the parent always performs the two reviewed limits sequentially")
    return _parent(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
