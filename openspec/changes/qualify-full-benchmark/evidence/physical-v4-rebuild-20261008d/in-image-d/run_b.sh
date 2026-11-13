#!/bin/bash
# D(b) driver: run b_in_image_tests.py inside the DeepStream and Savant runtime images.
# Root mounted read-only; logs written to own scratch, then copied to evidence.
set -u
EV=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/openspec/changes/qualify-full-benchmark/evidence/physical-v4-rebuild-20261008d/in-image-d
S=/var/tmp/claude-inimage-diag-d
ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
declare -A IMG=(
  [deepstream]=sha256:b236e0f4024f5b6566ca1c724dc1c48a118d10c51ce7df4f97bc0d425ead4157
  [savant]=sha256:045ccc3527dac40959706a678480f1145a3c7de609a9262365f5787911f667a7
)
mkdir -p -m 700 "$S/tools" "$S/out"
cp "$EV/b_in_image_tests.py" "$S/tools/"
for sys in deepstream savant; do
  cmd=(/usr/bin/docker run --rm --network none --name "claude-inimage-diag-b-$sys"
    --user 1000:1000 --gpus all --read-only --cap-drop ALL
    --security-opt no-new-privileges:true
    --tmpfs /tmp:rw,nosuid,nodev,size=4294967296 --env HOME=/tmp
    --mount "type=bind,src=$S/tools,dst=/work/tools,readonly"
    --mount "type=bind,src=$S/out,dst=/work/out"
    --mount "type=bind,src=$ROOT,dst=/work/root,readonly"
    --entrypoint python3 "${IMG[$sys]}" -B /work/tools/b_in_image_tests.py "$sys")
  printf '%q ' "${cmd[@]}" > "$EV/b_$sys.command.txt"; echo >> "$EV/b_$sys.command.txt"
  start=$(date +%s.%N)
  "${cmd[@]}" > "$EV/b_$sys.summary.json" 2> "$EV/b_$sys.runner.stderr.log"
  rc=$?
  end=$(date +%s.%N)
  echo "rc=$rc duration_s=$(echo "$end - $start" | bc)" > "$EV/b_$sys.rc.txt"
  mkdir -p "$EV/b_$sys"
  cp "$S/out/$sys"/*.log "$EV/b_$sys/" 2>/dev/null
  (cd "$EV/b_$sys" && sha256sum *.log) > "$EV/b_$sys.logs.sha256"
done
