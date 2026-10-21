#!/usr/bin/env bash
# Amendment 8, 6E.2: focused GREEN run of new + dependent test modules on ext4.
# Fresh clone of the branch head from the local repository, the uncommitted worktree
# changes overlaid byte-for-byte, OMZ models copied from the frozen root (read-only).
set -euo pipefail
W=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST
R=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
E=/mnt/e/STUDY/VAST/tmp/claude-a8
head=$1; label=$2; log=$3; shift 3
C=/home/s-a-balashov/work/vast-a8-green-$(date -u +%Y%m%dT%H%M%S)
[[ ! -e "$C" ]]
git clone -q --depth 1 --branch codex/qualify-full-benchmark file:///mnt/e/STUDY/VAST "$C"
[[ "$(git -C "$C" rev-parse HEAD)" == "$head" ]]
: > "$E/overlay.files"
while read -r rel; do
  mkdir -p "$(dirname "$C/$rel")"; cp "$W/$rel" "$C/$rel"; echo "$rel" >> "$E/overlay.files"
done < "$E/overlay.list"
(cd "$C" && sha256sum $(cat "$E/overlay.files")) > "$E/overlay.sha256"
(cd "$W" && sha256sum $(cat "$E/overlay.files")) | cmp - "$E/overlay.sha256"
for d in vehicle-license-plate-detection-barrier-0106 vehicle-detection-0202 person-vehicle-bike-detection-2002 person-vehicle-bike-detection-crossroad-1016; do
  rel=models/openvino/public/intel/$d/FP16; mkdir -p "$C/$rel"; cp "$R/$rel/$d.xml" "$R/$rel/$d.bin" "$C/$rel/"
done
cd "$C/tests"
{
  echo "head=$label"
  echo "clone=$C overlay=$(wc -l < "$E/overlay.files") files (overlay.sha256)"
  echo "python=$($PY -c 'import platform;print(platform.python_version())') platform=$(uname -sr) cwd=$PWD PYTHONPATH=$C TMPDIR=${TMPDIR:-unset}"
  echo "command=python -B -m unittest -v $*"
  set +e
  PYTHONPATH=$C $PY -B -m unittest -v "$@" 2>&1
  echo "exit=$?"
} > "$log" 2>&1
tail -n 4 "$log"
