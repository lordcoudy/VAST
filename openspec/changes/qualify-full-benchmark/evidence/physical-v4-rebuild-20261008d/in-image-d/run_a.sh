#!/bin/bash
# D(a) driver: run a_in_image_check.py inside the DeepStream and Savant runtime images.
# Executed in WSL as uid 1000. Scratch: /var/tmp/claude-inimage-diag-d (own, removed after).
set -u
EV=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/openspec/changes/qualify-full-benchmark/evidence/physical-v4-rebuild-20261008d/in-image-d
S=/var/tmp/claude-inimage-diag-d
ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
declare -A IMG=(
  [deepstream]=sha256:b236e0f4024f5b6566ca1c724dc1c48a118d10c51ce7df4f97bc0d425ead4157
  [savant]=sha256:045ccc3527dac40959706a678480f1145a3c7de609a9262365f5787911f667a7
)
mkdir -p -m 700 "$S/tools"
cp "$EV/a_in_image_check.py" "$S/tools/"
for sys in deepstream savant; do
  cmd=(/usr/bin/docker run --rm --network none --name "claude-inimage-diag-a-$sys"
    --user 1000:1000 --gpus all --read-only --cap-drop ALL
    --security-opt no-new-privileges:true
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=1073741824 --env HOME=/tmp
    --mount "type=bind,src=$S/tools,dst=/work/tools,readonly"
    --mount "type=bind,src=$ROOT,dst=/work/root,readonly"
    --entrypoint python3 "${IMG[$sys]}" -B /work/tools/a_in_image_check.py "$sys")
  printf '%q ' "${cmd[@]}" > "$EV/a_$sys.command.txt"; echo >> "$EV/a_$sys.command.txt"
  start=$(date +%s.%N)
  "${cmd[@]}" > "$EV/a_$sys.report.json" 2> "$EV/a_$sys.stderr.log"
  rc=$?
  end=$(date +%s.%N)
  echo "rc=$rc duration_s=$(echo "$end - $start" | bc)" > "$EV/a_$sys.rc.txt"
  sha256sum "$EV/a_$sys.stderr.log" "$EV/a_$sys.report.json" >> "$EV/a_$sys.rc.txt"
done
