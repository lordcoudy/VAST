#!/usr/bin/env bash
set -euo pipefail
[[ "$#" == 5 && "$(id -u)" == 0 ]] || exit 64
CLONE="$1"
OUT="$2"
SHA="$3"
PARENT_NAMESPACE="$4"
START_NS="$5"
[[ "$SHA" =~ ^[0-9a-f]{40}$ && "$START_NS" =~ ^[0-9]+$ ]]
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
# Mount privilege ends before the CI parent or any tests are launched.
[[ "$(id -u s-a-balashov)" == 1000 ]]
exec runuser -u s-a-balashov -- env HOME=/home/s-a-balashov USER=s-a-balashov \
  LOGNAME=s-a-balashov TMPDIR=/var/tmp \
  "$RUNTIME/bin/python" -B scripts/run_ci_checks.py --expected-commit "$SHA" \
  --output-dir "$OUT/original" --job-started-monotonic-ns "$START_NS"
