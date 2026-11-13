#!/bin/bash
# D(b) rerun of modules whose first-pass failures were environment-only.
# Changes vs run_b.sh: /tmp tmpfs explicitly "exec" (Docker tmpfs defaults to
# noexec; fixture ELF engines are executed from /tmp), interpreter invoked as
# its canonical file /usr/bin/python3.10 (the /usr/bin/python3 symlink is
# rejected by execution_code_closure's canonical-interpreter check), and psutil
# 7.2.2 (cp36-abi3 wheel, copied from the host publication venv) on PYTHONPATH.
set -u
EV=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/openspec/changes/qualify-full-benchmark/evidence/physical-v6-rebuild-20261008e/in-image-h
S=/var/tmp/claude-inimage-diag-h
ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
MODULES=${MODULES:-test_operational_identifier_domain_v1,test_checkpoint_deepstream_runtime}
declare -A IMG=(
  [deepstream]=sha256:3a9aa20a8efb722e89865e73aaa9d29ec6ce6ae4e806f485887a9a032bebb984
)
mkdir -p -m 700 "$S/tools" "$S/out"
cp "$EV/b2_in_image_tests.py" "$S/tools/"
for sys in deepstream; do
  cmd=(/usr/bin/docker run --rm --network none --name "claude-inimage-diag-hb-$sys"
    --user 1000:1000 --gpus all --read-only --cap-drop ALL
    --security-opt no-new-privileges:true
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=4294967296 --env HOME=/tmp
    --env VAST_DIAG_PYTHON=/usr/bin/python3.10
    --env VAST_DIAG_EXTRA_PATH=/work/pydeps
    --env "VAST_DIAG_MODULES=$MODULES"
    --mount "type=bind,src=$S/tools,dst=/work/tools,readonly"
    --mount "type=bind,src=$S/pydeps,dst=/work/pydeps,readonly"
    --mount "type=bind,src=$S/out,dst=/work/out"
    --mount "type=bind,src=$ROOT,dst=/work/root,readonly"
    --entrypoint /usr/bin/python3.10 "${IMG[$sys]}" -B /work/tools/b2_in_image_tests.py "$sys")
  printf '%q ' "${cmd[@]}" > "$EV/hb_$sys.command.txt"; echo >> "$EV/hb_$sys.command.txt"
  start=$(date +%s.%N)
  "${cmd[@]}" > "$EV/hb_$sys.summary.json" 2> "$EV/hb_$sys.runner.stderr.log"
  rc=$?
  end=$(date +%s.%N)
  echo "rc=$rc duration_s=$(echo "$end - $start" | bc)" > "$EV/hb_$sys.rc.txt"
  mkdir -p "$EV/hb_$sys"
  cp "$S/out/$sys-b2"/*.log "$EV/hb_$sys/" 2>/dev/null
  (cd "$EV/hb_$sys" && sha256sum *.log) > "$EV/hb_$sys.logs.sha256"
done
