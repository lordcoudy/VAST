#!/usr/bin/env python3
"""One authorized unchanged A16 full dispatch, with literal outer controls."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys


SHA = "a16f243e7e80f093342ccdddf717d59d6d46f0a8"
ROOT = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-" + SHA)
CI = Path("/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-" + SHA)
RELATIVE = "openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/run_ext4_suite.sh"
RECIPE = ROOT / RELATIVE
CONTROL = Path(__file__).parent / "full-a16-control-01"
DEEP_OUT = ROOT / "artifacts/accepted_policy_repair_20261011a/checks-01" / ("ext4-" + SHA)
CATALOGS = ["8b9111ab5855bf73b0bac2532599b1a77d36235e05a544d0a08c47cdbcaac0e7",
            "b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d",
            "9b38ca696ee662bcd26f78a293f899fb6333b581670f486a5c9cfae4f9e48d45"]


def utc():
    return datetime.now(timezone.utc).isoformat() + "\n"


def output(*args):
    return subprocess.check_output(args, text=True).strip()


if __name__ == "__main__":
    assert sys.argv[1:] == [] and sys.flags.optimize == 0
    assert os.getuid() == os.getgid() == 1000 and os.environ["HOME"] == "/home/s-a-balashov"
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == (10240, 1048576)
    assert ROOT.resolve(strict=True) == ROOT and output("findmnt", "-rn", "-T", str(ROOT), "-o", "FSTYPE") == "ext4"
    assert output("git", "-C", str(ROOT), "rev-parse", "HEAD") == SHA
    assert output("git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no") == ""
    assert not CI.exists() and not CI.is_symlink() and not DEEP_OUT.exists() and not DEEP_OUT.is_symlink()
    assert RECIPE.resolve(strict=True) == RECIPE
    recipe_bytes = RECIPE.read_bytes()
    assert hashlib.sha256(recipe_bytes).hexdigest() == "045cdded701dfb59100ce600344079f615a7be5991778befa4123eb209cb106d"
    assert subprocess.check_output(["git", "-C", str(ROOT), "show", SHA + ":" + RELATIVE]) == recipe_bytes
    containers = output("/usr/bin/docker", "ps", "--all", "--format", "{{.ID}} {{.Names}} {{.Status}}")
    gpu = output("/usr/lib/wsl/lib/nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")
    assert containers == gpu == ""
    actors = [line for line in output("ps", "-eo", "pid,ppid,user,comm,args").splitlines()
              if str(ROOT) in line and int(line.split()[0]) != os.getpid()]
    assert not actors, "selected SOURCE actor exists before dispatch"
    assert CONTROL.resolve(strict=False) == CONTROL and not CONTROL.exists() and not CONTROL.is_symlink()
    CONTROL.mkdir(mode=0o700)
    command = ["/bin/bash", str(RECIPE), SHA, *CATALOGS]
    environment = os.environ.copy()
    environment.update({"VAST_REPAIR_CHECK_ROOT": str(ROOT), "HOME": "/home/s-a-balashov",
                        "USER": "s-a-balashov", "LOGNAME": "s-a-balashov"})
    (CONTROL / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="ascii")
    (CONTROL / "environment.json").write_text(json.dumps({key: environment[key] for key in
        ("VAST_REPAIR_CHECK_ROOT", "HOME", "USER", "LOGNAME")}, sort_keys=True, indent=2) + "\n", encoding="ascii")
    (CONTROL / "preflight.json").write_text(json.dumps({"source_commit": SHA, "uid": os.getuid(),
        "gid": os.getgid(), "nofile": list(resource.getrlimit(resource.RLIMIT_NOFILE)),
        "docker": containers, "gpu": gpu, "source_actors": actors, "ci_absent": True,
        "deep_out_absent": True, "unchanged_recipe_sha256": hashlib.sha256(recipe_bytes).hexdigest()},
        sort_keys=True, indent=2) + "\n", encoding="ascii")
    (CONTROL / "started.txt").write_text(utc(), encoding="ascii")
    print(json.dumps({"dispatch": "started", "source_commit": SHA, "control": str(CONTROL), "deep_out": str(DEEP_OUT)}), flush=True)
    with (CONTROL / "original.stdout.log").open("xb") as stdout, (CONTROL / "original.stderr.log").open("xb") as stderr:
        child = subprocess.run(command, env=environment, stdout=stdout, stderr=stderr, check=False)
    (CONTROL / "original.rc.txt").write_text(str(child.returncode) + "\n", encoding="ascii")
    (CONTROL / "finished.txt").write_text(utc(), encoding="ascii")
    print(json.dumps({"dispatch": "finished", "original_rc": child.returncode, "control": str(CONTROL)}), flush=True)
    raise SystemExit(child.returncode)
