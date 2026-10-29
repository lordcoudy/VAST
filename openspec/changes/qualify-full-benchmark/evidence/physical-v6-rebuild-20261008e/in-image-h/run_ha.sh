#!/bin/bash
# H(a) driver (Amendment 7): a_in_image_check.py inside the rebuilt DeepStream runtime image.
# Executed in WSL as uid 1000. Scratch: /var/tmp/claude-inimage-diag-h (own, removed after).
set -u
EV=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/openspec/changes/qualify-full-benchmark/evidence/physical-v6-rebuild-20261008e/in-image-h
S=/var/tmp/claude-inimage-diag-h
ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
declare -A IMG=(
  [deepstream]=sha256:3a9aa20a8efb722e89865e73aaa9d29ec6ce6ae4e806f485887a9a032bebb984
)
mkdir -p -m 700 "$S/tools"
cp "$EV/a_in_image_check.py" "$S/tools/"
for sys in deepstream; do
  cmd=(/usr/bin/docker run --rm --network none --name "claude-inimage-diag-ha-$sys"
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
