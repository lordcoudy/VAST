"""Capture bounded test-only reference TDD in fresh ext4 overlays; no producer."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
SOURCE = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-d725413ef086f3550dcafd6bc8233982f35cab14")
BASE = Path("/mnt/e/STUDY/VAST/tmp/host-cache-cleanup-20261012/stock-sample-reference-tdd-02")
OVERLAYS = Path("/var/tmp/vast-stock-sample-reference-tdd-20261013b")
PYTHON = "/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python"
FILES = ("tests/fixtures/accepted_policy_stock_sample_reference_v1.py",
         "tests/test_accepted_policy_f5_real_refusals.py",
         "tests/test_accepted_policy_stock_sample_reference_v1.py")
PRODUCTION = {
    "scripts/publication_policy_qualification.py": "f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde",
    "scripts/publication_policy_qualification_pilot_validation_v2.py": "48fbc62494cdc40bd5f925cee6ff16dad02269feacf1803d263a9d165523f246",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    result = {"authored_files": {name: sha(ROOT / name) for name in FILES},
              "managed_production": {name: sha(ROOT / name) for name in PRODUCTION},
              "frozen_production": {name: sha(SOURCE / name) for name in PRODUCTION},
              "capturer_sha256": sha(Path(__file__))}
    if result["managed_production"] != PRODUCTION or result["frozen_production"] != PRODUCTION:
        raise RuntimeError("original stock/F5 production bytes differ from reviewed pins")
    return result


def fresh_json(path, value):
    with path.open("x", encoding="ascii") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("red", "green"), required=True)
    args = parser.parse_args()
    if (sys.executable != PYTHON or sys.version_info[:3] != (3, 12, 3)
            or sys.flags.optimize != 0 or os.getuid() != 1000 or os.getgid() != 1000
            or os.environ.get("HOME") != "/home/s-a-balashov" or os.environ.get("TMPDIR") != "/var/tmp"):
        raise RuntimeError("canonical ordinary unoptimized test runtime required")
    before = snapshot()
    if args.phase == "red":
        BASE.mkdir(exist_ok=False)
        OVERLAYS.mkdir(exist_ok=False)
    else:
        red = json.loads((BASE / "red/result.v1.json").read_bytes())
        if red["original_exit_code"] != 1 or red["source_hashes_unchanged"] is not True:
            raise RuntimeError("retained original RED1 with unchanged sources required")
    directory = BASE / args.phase
    overlay = OVERLAYS / args.phase
    directory.mkdir(exist_ok=False)
    overlay.mkdir(exist_ok=False)
    (overlay / "scripts").symlink_to(SOURCE / "scripts", target_is_directory=True)
    for name in FILES:
        destination = overlay / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        raw = (ROOT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != before["authored_files"][name]:
            raise RuntimeError("authored source drift before overlay copy")
        with destination.open("xb") as stream:
            stream.write(raw)
    targets = ["tests.test_accepted_policy_stock_sample_reference_v1"]
    if args.phase == "red":
        targets[0] += ".AcceptedPolicyStockSampleReferenceV1Tests.test_reference_passes_real_six_stream_reset_to_dataset_gate"
    else:
        targets += ["tests.test_accepted_policy_f5_real_refusals",
                    "tests.test_publication_qualification_policy_pilot_validator_v2"]
    bootstrap = "\n".join((
        "import importlib,json,sys",
        "from pathlib import Path",
        "sys.path[:0]=" + repr([str(SOURCE), str(SOURCE / "scripts")]),
        "import tests",
        "tests.__path__=[" + repr(str(overlay / "tests")) + ",*tests.__path__]",
        "import tests.fixtures",
        "tests.fixtures.__path__=[" + repr(str(overlay / "tests/fixtures")) + ",*tests.fixtures.__path__]",
        "owned=" + repr({name[:-3].replace("/", "."): str(overlay / name) for name in FILES}),
        "loaded={name:Path(importlib.import_module(name).__file__).resolve() for name in owned}",
        "assert all(loaded[name] == Path(path).resolve() for name,path in owned.items()), loaded",
        "print(json.dumps({'owned_import_paths':{name:str(path) for name,path in loaded.items()}},sort_keys=True),flush=True)",
        "import unittest",
        "unittest.main(module=None,argv=" + repr(["unittest", *targets, "-v"]) + ")",
    ))
    command = [PYTHON, "-B", "-c", bootstrap]
    started = datetime.now(timezone.utc).isoformat()
    fresh_json(directory / "command.v1.json", {"argv": command, "cwd": str(overlay), "started_utc": started,
               "uid": os.getuid(), "gid": os.getgid(), "python_version": sys.version,
               "approved_design_commit": "67b1362fde9463a1e983b49dbc0ee545a5095231",
               "read_only_dependency_source_commit": "d725413ef086f3550dcafd6bc8233982f35cab14",
               "overlay_files": list(FILES), "no_complete_consumer_or_campaign": True})
    fresh_json(directory / "source-hashes.before.json", before)
    with (directory / "stdout.raw").open("xb") as stdout, (directory / "stderr.raw").open("xb") as stderr:
        child = subprocess.Popen(command, cwd=overlay, stdout=stdout, stderr=stderr)
        original_rc = child.wait()
    after = snapshot()
    overlay_unchanged = all(sha(overlay / name) == before["authored_files"][name] for name in FILES)
    fresh_json(directory / "source-hashes.after.json", after)
    result = {"phase": args.phase, "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
              "original_exit_code": original_rc, "source_hashes_unchanged": before == after,
              "overlay_bytes_unchanged": overlay_unchanged,
              "stdout": {"bytes": (directory / "stdout.raw").stat().st_size, "sha256": sha(directory / "stdout.raw")},
              "stderr": {"bytes": (directory / "stderr.raw").stat().st_size, "sha256": sha(directory / "stderr.raw")},
              "no_complete_consumer_or_campaign": True}
    fresh_json(directory / "result.v1.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    if before != after or not overlay_unchanged:
        raise RuntimeError("authored/production/capturer/overlay bytes changed during original run")
    return original_rc


if __name__ == "__main__":
    sys.exit(main())
