#!/usr/bin/env bash
set -euo pipefail
[[ "$#" == 6 && "$(id -u)" == 0 ]] || exit 64
CLONE="$1"
OUT="$2"
SHA="$3"
PARENT_NAMESPACE="$4"
START_NS="$5"
OBSERVED_NOFILE_SOFT="$6"
[[ "$SHA" =~ ^[0-9a-f]{40}$ && "$START_NS" =~ ^[0-9]+$ ]]
[[ "$OBSERVED_NOFILE_SOFT" == 10240 ]]
[[ "$(readlink /proc/self/ns/mnt)" != "$PARENT_NAMESPACE" ]]
[[ "$(findmnt -rn -T / -o PROPAGATION)" == private ]]
printf '%s\n' "$(readlink /proc/self/ns/mnt)" > "$OUT/private-mount-namespace.txt"
[[ "$(realpath -e "$CLONE")" == "$CLONE" ]]
[[ "$CLONE" == /home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-"$SHA" ]]
[[ "$(git -c safe.directory="$CLONE" -C "$CLONE" rev-parse HEAD)" == "$SHA" ]]
RUNTIME=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1
bash "$CLONE/scripts/mount_publication_runtime_wsl.sh" --source-runtime "$RUNTIME" \
  --project-root "$CLONE" --project-runtime-mount .publication-runtime/full-publication-cp312-v1 \
  > "$OUT/runtime-mount.materialization.json"
bash "$CLONE/scripts/mount_publication_runtime_wsl.sh" --source-runtime "$RUNTIME" \
  --project-root "$CLONE" --project-runtime-mount .publication-runtime/full-publication-cp312-v1 \
  --check-only > "$OUT/runtime-mount.check.json"
findmnt -rn -T "$RUNTIME" -o TARGET,FSTYPE,OPTIONS,PROPAGATION > "$OUT/runtime-source.mount.txt"
findmnt -rn -T "$CLONE/.publication-runtime/full-publication-cp312-v1" \
  -o TARGET,FSTYPE,OPTIONS,PROPAGATION > "$OUT/runtime-target.mount.txt"
cd "$CLONE"
[[ "$(realpath -e /tmp)" == /tmp && -d /tmp ]]
[[ "$(findmnt -rn -T /tmp -o FSTYPE)" == ext4 ]]
findmnt -rn -T /tmp -o TARGET,FSTYPE,OPTIONS,PROPAGATION > "$OUT/test-temporary-base.mount.txt"
stat -c '%a:%u:%g:%d:%i' /tmp > "$OUT/test-temporary-base.stat.txt"
# Mount privilege ends before the CI parent or any tests are launched.
[[ "$(id -u s-a-balashov)" == 1000 ]]
exec runuser -u s-a-balashov -- env HOME=/home/s-a-balashov USER=s-a-balashov \
  LOGNAME=s-a-balashov TMPDIR=/tmp \
  "$RUNTIME/bin/python" -B - "$OUT" "$SHA" "$START_NS" "$OBSERVED_NOFILE_SOFT" <<'PY'
import json
import os
from pathlib import Path
import resource
import sys

out, sha, started, observed_soft = sys.argv[1:]
assert observed_soft == "10240"
assert os.getuid() == os.getgid() == 1000
assert os.environ["HOME"] == "/home/s-a-balashov" and os.environ["TMPDIR"] == "/tmp"

def identity():
    fields = {}
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        key, _, value = line.partition(":")
        if key in {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs"}:
            fields[key] = value.strip()
    return {"uid": os.getuid(), "gid": os.getgid(), "nofile": list(resource.getrlimit(resource.RLIMIT_NOFILE)),
            "process_status": fields}

before = identity()
with (Path(out) / "ci-user-limits.before.json").open("x", encoding="ascii") as stream:
    json.dump(before, stream, sort_keys=True)
    stream.write("\n")
assert before["nofile"][1] == 1048576
assert all(before["process_status"][key] == "0000000000000000" for key in ("CapInh", "CapPrm", "CapEff", "CapAmb"))
# Restore only the observed ordinary-user soft limit after runuser's reset.
resource.setrlimit(resource.RLIMIT_NOFILE, (int(observed_soft), before["nofile"][1]))
after = identity()
with (Path(out) / "ci-user-limits.after.json").open("x", encoding="ascii") as stream:
    json.dump(after, stream, sort_keys=True)
    stream.write("\n")
assert after["nofile"] == [10240, 1048576]
assert after["uid"] == before["uid"] == 1000 and after["gid"] == before["gid"] == 1000
assert after["process_status"] == before["process_status"]
os.execv(sys.executable, [sys.executable, "-B", "scripts/run_ci_checks.py", "--expected-commit", sha,
    "--output-dir", str(Path(out) / "original"), "--job-started-monotonic-ns", started])
PY
