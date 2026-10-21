#!/usr/bin/env python3
"""Replay the 23 packaged regression commands of 20260926d against this chain's exact images.

Adaptation versus the 20260928g replay (recorded in the summary):
* image IDs map 20260926d -> this chain exactly as before (9 distinct identities);
* host paths of the old review root are rewritten to this exact-commit root, so the
  current tests/configs are mounted (the old test files no longer match current code);
* 20260926d helper inputs are copied into this chain with SHA256 equality checks;
* ``expected_packaged_sha256`` is the SHA256 of the current repository source with the
  same basename, which must be listed in that runtime image source allowlist;
* ``tests_run`` is the count the host loader discovers in the same mounted test file.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
BASE = ROOT / "artifacts/qualify_full_benchmark_20261008c"
OLD_ROOT = "/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec"
OLD = Path(OLD_ROOT) / "artifacts/fix_benchmark_preparations_20260926d"
INPUTS = BASE / "packaged_inputs_20260926d"
DEST = BASE / "packaged_regressions"
PYTHON = "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python"
ALLOWLISTS = {"openvino_gva": "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
              "gstreamer_custom": "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"}


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def write(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def image_map() -> dict[str, str]:
    result: dict[str, str] = {}
    for group, leaf in (("native-a", "native_probe.freeze.json"), ("worker_images", "analytics-worker.freeze.json")):
        left = {row["name"]: row["image_id"] for row in read(OLD / group / leaf)["images"]}
        right = {row["name"]: row["image_id"] for row in read(BASE / group / leaf)["images"]}
        assert left.keys() == right.keys()
        result.update({left[name]: right[name] for name in left})
    for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
        old = read(OLD / "runtime_images" / f"{system}.runtime.freeze.json")
        new = read(BASE / "runtime_images" / f"{system}.runtime.freeze.json")
        assert old["system"] == new["system"] == system
        result[old["physical_identity"]["image_id"]] = new["physical_identity"]["image_id"]
    assert len(result) == 9 and len(set(result.values())) == 9
    return result


def copy_inputs() -> list[dict]:
    rows = []
    INPUTS.mkdir(mode=0o700)
    for name in ("check_packaged_external_manifest.py", "external-manifest-cases.json"):
        source = OLD / "packaged_historical_regressions" / name
        target = INPUTS / name
        shutil.copyfile(source, target)
        left, right = digest(source.read_bytes()), digest(target.read_bytes())
        assert left == right and not source.is_symlink()
        rows.append({"source": str(source), "target": str(target), "sha256": right, "size_bytes": target.stat().st_size})
    return rows


def rewrite(token: str) -> str:
    old_helpers = str(OLD / "packaged_historical_regressions") + "/"
    if old_helpers in token:
        token = token.replace(old_helpers, str(INPUTS) + "/")
    if OLD_ROOT in token:
        token = token.replace(OLD_ROOT, str(ROOT))
    return token


def discovered_tests(test_file: Path) -> int:
    import importlib.util
    for entry in (str(ROOT), str(ROOT / "tests"), str(ROOT / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(f"packaged_count_{test_file.stem}", test_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    count = unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases()
    assert count > 0, test_file
    return count


def current_packaged_sha(name: str, packaged: str) -> str:
    system = name.split(".", 1)[0]
    source = f"scripts/{Path(packaged).name}"
    allow = (ROOT / ALLOWLISTS[system]).read_text().split()
    assert source in allow, (name, source)
    return digest((ROOT / source).read_bytes())


def main() -> None:
    if sys.flags.optimize != 0:
        raise RuntimeError("packaged regression replay requires unoptimized Python")
    assert ROOT.resolve(strict=True) == ROOT and not DEST.exists() and not INPUTS.exists()
    replacements = image_map()
    copied = copy_inputs()
    cases: list[tuple[str, dict]] = []
    for file in sorted((OLD / "packaged_historical_regressions").glob("*.result.json")):
        cases.append((file.name.removesuffix(".result.json"), read(file)))
    for record in read(OLD / "packaged_analytics_regressions/summary.json")["checks"]:
        cases.append((record["name"], record))
    assert len(cases) == 23 and len({name for name, _ in cases}) == 23
    DEST.mkdir(mode=0o700)
    results = []
    for name, template in cases:
        old_images = [token for token in template["argv"] if token in replacements]
        assert len(old_images) == (0 if name == "native-cuda-transfer" else 1), name
        argv = [rewrite(replacements.get(token, token)) for token in template["argv"]]
        assert not any(OLD_ROOT in token for token in argv), name
        if argv[0].endswith("python") and argv[0] != PYTHON:
            raise RuntimeError(f"unexpected host interpreter for {name}")
        expected = template.get("expected_packaged_sha256")
        if expected is not None:
            expected = current_packaged_sha(name, argv[-1])
        tests_run = template.get("tests_run")
        if tests_run is not None:
            mounted = [token.split(":", 1)[0] for token in argv if token.endswith(".py:ro") or ".py:/tmp/" in token]
            test_files = [Path(path) for path in mounted if Path(path).name.startswith("test_")]
            assert len(test_files) == 1, (name, test_files)
            tests_run = discovered_tests(test_files[0])
        started = time.time_ns()
        try:
            completed = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=180)
            exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as error:
            exit_code, stdout, stderr = 124, error.stdout or b"", error.stderr or b""
        write(DEST / f"{name}.stdout", stdout)
        write(DEST / f"{name}.stderr", stderr)
        passed = exit_code == 0
        if expected is not None:
            words = stdout.split()
            passed = passed and bool(words) and words[0] == expected.encode("ascii")
        if tests_run is not None:
            actual = re.search(rb"Ran (\d+) tests?", stderr)
            passed = passed and actual is not None and int(actual.group(1)) == tests_run
        result = {"name": name, "argv": argv, "started_unix_ns": started, "finished_unix_ns": time.time_ns(),
                  "exit_code": exit_code, "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr),
                  "expected_packaged_sha256": expected, "template_expected_packaged_sha256": template.get("expected_packaged_sha256"),
                  "tests_run_expected": tests_run, "template_tests_run": template.get("tests_run"), "passed": passed}
        write(DEST / f"{name}.result.json", (json.dumps(result, sort_keys=True) + "\n").encode())
        results.append(result)
        if not passed:
            break
    summary = {"artifact_kind": "vast_packaged_regression_replay_v1", "source_attempt": "20260926d",
               "target_attempt": "qualify_full_benchmark_20261008c", "expected_count": 23,
               "completed_count": len(results), "copied_inputs": copied,
               "adaptation": "current-root mounts; expected packaged sha = current allowlisted source; tests_run = host discovery of the mounted file",
               "all_passed": len(results) == 23 and all(row["passed"] for row in results), "results": results}
    write(DEST / "summary.json", (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode())
    if not summary["all_passed"]:
        raise SystemExit(1)
    print(json.dumps({"status": "passed", "checks": len(results)}, sort_keys=True))


if __name__ == "__main__":
    main()
