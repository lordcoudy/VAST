"""CPU repository checks. GPU/model acceptance requires separate physical evidence."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "vast_native_gst_probe", "vast_checkpoint_source", "gstadaptivescheduler",
    "gstvastanalyticsterminal", "gstvastanalyticsqueue", "gstvastcheckpointprefixqueue",
)
REQUIRED_TESTS = frozenset(
    "test_checkpoint_analytics_execution_client_cpp."
    "CheckpointAnalyticsExecutionClientCppTest." + name
    for name in (
        "test_native_client_regression", "test_native_policy_topology_regression",
        "test_native_reset_queue_level_regression",
    )
)
HARDWARE_GAPS = (
    "Hosted CPU tests do not execute NVIDIA decode or the packaged SDK runtimes.",
    "Skipped hardware/data tests do not prove model parity, native paired execution, "
    "qualification, Q4, storage or the full benchmark.",
    "Final scientific conformance and archived completion require separately reviewed "
    "physical evidence bound to the actual source closure.",
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True,
        timeout=30,
    )
    return [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]


def manifest(root: Path, paths: list[str]) -> dict[str, dict[str, object]]:
    result = {}
    for relative in paths:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"tracked path is not a regular file: {relative}")
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise RuntimeError(f"tracked path changed while hashing: {relative}")
        result[relative] = {"size_bytes": before.st_size, "sha256": digest.hexdigest()}
    return result


def source_changes(before: dict, after: dict) -> list[str]:
    return sorted(path for path in before.keys() | after.keys()
                  if before.get(path) != after.get(path))


def verify_committed_bytes(root: Path, paths: list[str]) -> None:
    """Check raw checkout bytes against HEAD, independently of Git's stat cache."""
    object_format = subprocess.run(
        ["git", "rev-parse", "--show-object-format"], cwd=root, check=True,
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    if object_format not in ("sha1", "sha256"):
        raise RuntimeError("unsupported Git object hash format")
    tree = subprocess.run(["git", "ls-tree", "-rz", "HEAD"], cwd=root,
                          check=True, capture_output=True, timeout=30).stdout
    expected = {}
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise RuntimeError("CI source tree contains a nonregular tracked object")
        expected[os.fsdecode(name)] = oid.decode("ascii")
    if set(expected) != set(paths):
        raise RuntimeError("tracked path inventory differs from HEAD")
    for relative, oid in expected.items():
        path = root / relative
        size = path.stat().st_size
        digest = hashlib.new(object_format)
        digest.update(f"blob {size}\0".encode("ascii"))
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != oid:
            raise RuntimeError(f"raw checkout bytes differ from HEAD: {relative}")


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successes: list[str] = []

    def addSuccess(self, test):
        self.successes.append(test.id())
        super().addSuccess(test)


def suite_report(result: RecordedResult) -> dict:
    return {
        "tests_run": result.testsRun,
        "successful_test_ids": result.successes,
        "skips": [{"test_id": test.id(), "reason": reason}
                  for test, reason in result.skipped],
        "failures": [{"test_id": test.id(), "traceback": trace}
                     for test, trace in result.failures],
        "errors": [{"test_id": test.id(), "traceback": trace}
                   for test, trace in result.errors],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "missing_required_successes": sorted(REQUIRED_TESTS - set(result.successes)),
        "successful": result.wasSuccessful() and result.testsRun > 0
                      and REQUIRED_TESTS <= set(result.successes),
    }


def command(argv: list[str], output: Path, name: str, timeout: int) -> dict:
    began = time.monotonic()
    with (output / (name + ".stdout")).open("wb") as stdout, (
        output / (name + ".stderr")
    ).open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
    observation = {"argv": argv, "returncode": process.returncode, "timed_out": timed_out,
                   "elapsed_s": time.monotonic() - began}
    write_json(output / (name + ".json"), observation)
    if timed_out or process.returncode:
        raise RuntimeError(f"{name} failed: see its original stdout/stderr")
    return observation


def specification_inventory(root: Path) -> dict:
    inventories = []
    for path in sorted((root / "openspec").rglob("spec.md")):
        requirements = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("### Requirement: "):
                requirements.append({"name": line.removeprefix("### Requirement: "),
                                     "scenarios": []})
            elif line.startswith("#### Scenario: "):
                if not requirements:
                    raise RuntimeError(f"scenario precedes a requirement in {path}")
                requirements[-1]["scenarios"].append(line.removeprefix("#### Scenario: "))
        inventories.append({"path": path.relative_to(root).as_posix(),
                            "requirements": requirements})
    return {"inventory": inventories, "behavior_conformance": "requires reviewed evidence map",
            "hardware_gaps": HARDWARE_GAPS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output == ROOT or ROOT in output.parents:
        raise RuntimeError("CI outputs must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    report = {"kind": "vast_cpu_ci_checks_v1", "successful": False,
              "hardware_acceptance": False, "hardware_gaps": HARDWARE_GAPS}
    before = None
    paths = []
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        report["commit"] = commit
        if commit != args.expected_commit:
            raise RuntimeError("checked-out commit differs from the requested PR/push commit")
        paths = tracked_paths(ROOT)
        before = manifest(ROOT, paths)
        verify_committed_bytes(ROOT, paths)
        write_json(output / "tracked-source.before.json", before)
        report["raw_checkout_bytes_match_commit"] = True
        report["python"] = sys.version
        report["packages"] = sorted(
            [{"name": dist.metadata["Name"], "version": dist.version}
             for dist in importlib.metadata.distributions()],
            key=lambda row: row["name"].casefold(),
        )
        write_json(output / "specification-inventory.json", specification_inventory(ROOT))
        checked_python = []
        checked_bash = []
        for relative in paths:
            if not relative.startswith(("scripts/", "tests/", "deploy/")):
                continue
            if relative.endswith(".py"):
                ast.parse((ROOT / relative).read_bytes(), filename=relative)
                checked_python.append(relative)
            elif relative.endswith(".sh"):
                subprocess.run(["bash", "-n", str(ROOT / relative)], check=True, timeout=15)
                checked_bash.append(relative)
        report["python_syntax"] = checked_python
        report["bash_syntax"] = checked_bash
        build = output / "build"
        command(["cmake", "-S", str(ROOT), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DVAST_BUILD_CUSTOM_CUDA_QT=OFF",
                 "-DCMAKE_RUNTIME_OUTPUT_DIRECTORY=" + str(build / "bin"),
                 "-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=" + str(build / "lib")],
                output, "native-configure", 120)
        command(["cmake", "--build", str(build), "--parallel", "2", "--target", *TARGETS],
                output, "native-build", 600)
        report["built_targets"] = TARGETS
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
        with (output / "unittest.original.log").open("w", encoding="utf-8") as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                            resultclass=RecordedResult).run(suite)
        report["unittest"] = suite_report(result)
        if not report["unittest"]["successful"]:
            raise RuntimeError("test discovery failed or a required native regression did not pass")
        report["successful"] = True
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if before is not None:
                after = manifest(ROOT, tracked_paths(ROOT))
                write_json(output / "tracked-source.after.json", after)
                report["changed_tracked_paths"] = source_changes(before, after)
                if report["changed_tracked_paths"]:
                    report["successful"] = False
                    report["source_integrity_failure"] = "tracked files changed during CPU checks"
        except Exception as exc:
            report["successful"] = False
            report["source_integrity_failure"] = f"{type(exc).__name__}: {exc}"
        report["elapsed_s"] = time.monotonic() - began
        write_json(output / "report.json", report)
    print(json.dumps({"successful": report["successful"], "report": str(output / "report.json")}))
    return 0 if report["successful"] else 1


if __name__ == "__main__":
    sys.exit(main())
