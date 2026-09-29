"""Exclusive immutable local fixture logs; does not run a benchmark."""
from pathlib import Path
import datetime
import hashlib
import json
import subprocess
import sys
import time

root = Path.cwd()
old = json.loads((root / "artifacts/benchmark_recovery_20260929/operational-execution-binding/attempt-01.execution.v1.json").read_bytes())
names = [row["path"] for row in old["source_files"]]

def pins():
    return [{"path": name, "size_bytes": len((raw := (root / name).read_bytes())),
             "sha256": hashlib.sha256(raw).hexdigest()} for name in names]

prefix = Path(__file__).parent / sys.argv[1]
if any(Path(str(prefix) + suffix).exists() for suffix in (".execution.v1.json", ".stdout.log", ".stderr.log")):
    raise SystemExit("This attempt already exists; preserve its original evidence.")
before = pins()
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
start = time.monotonic()
result = subprocess.run(old["argv"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
after = pins()
logs = {}
for name, data in (("stdout", result.stdout), ("stderr", result.stderr)):
    path = Path(str(prefix) + "." + name + ".log")
    with path.open("xb") as stream:
        stream.write(data)
    logs[name] = {"path": str(path.relative_to(root)), "size_bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest()}
replace = {"started_at_utc", "ended_at_utc", "elapsed_s", "original_exit_code",
           "source_files", "source_files_after", "source_files_stable_during_test", "stdout", "stderr"}
document = {**{key: value for key, value in old.items() if key not in replace},
    "started_at_utc": started, "ended_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "elapsed_s": time.monotonic() - start, "original_exit_code": result.returncode,
    "source_files": before, "source_files_after": after, "source_files_stable_during_test": before == after, **logs}
raw = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
path = Path(str(prefix) + ".execution.v1.json")
with path.open("xb") as stream:
    stream.write(raw)
print(json.dumps({"receipt": str(path.relative_to(root)), "sha256": hashlib.sha256(raw).hexdigest(),
                  "exit_code": result.returncode, "source_stable": before == after}))
print(result.stderr.decode()[-12000:])
