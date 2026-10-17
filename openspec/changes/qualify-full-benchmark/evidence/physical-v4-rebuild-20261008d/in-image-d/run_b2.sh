#!/bin/bash
# D(b) rerun of modules whose first-pass failures were environment-only.
# Changes vs run_b.sh: /tmp tmpfs explicitly "exec" (Docker tmpfs defaults to
# noexec; fixture ELF engines are executed from /tmp), interpreter invoked as
# its canonical file /usr/bin/python3.10 (the /usr/bin/python3 symlink is
# rejected by execution_code_closure's canonical-interpreter check), and psutil
# 7.2.2 (cp36-abi3 wheel, copied from the host publication venv) on PYTHONPATH.
set -u
EV=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/openspec/changes/qualify-full-benchmark/evidence/physical-v4-rebuild-20261008d/in-image-d
S=/var/tmp/claude-inimage-diag-d
ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
MODULES=${MODULES:-test_checkpoint_runtime,test_publication_operational_container_custody_v1,test_publication_operational_process_custody_v1,test_publication_policy_qualification_execution_closure_v1}
declare -A IMG=(
  [deepstream]=sha256:b236e0f4024f5b6566ca1c724dc1c48a118d10c51ce7df4f97bc0d425ead4157
  [savant]=sha256:045ccc3527dac40959706a678480f1145a3c7de609a9262365f5787911f667a7
)
mkdir -p -m 700 "$S/tools" "$S/out"
cp "$EV/b2_in_image_tests.py" "$S/tools/"
for sys in deepstream savant; do
  cmd=(/usr/bin/docker run --rm --network none --name "claude-inimage-diag-b2-$sys"
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
  printf '%q ' "${cmd[@]}" > "$EV/b2_$sys.command.txt"; echo >> "$EV/b2_$sys.command.txt"
  start=$(date +%s.%N)
  "${cmd[@]}" > "$EV/b2_$sys.summary.json" 2> "$EV/b2_$sys.runner.stderr.log"
  rc=$?
  end=$(date +%s.%N)
  echo "rc=$rc duration_s=$(echo "$end - $start" | bc)" > "$EV/b2_$sys.rc.txt"
  mkdir -p "$EV/b2_$sys"
  cp "$S/out/$sys-b2"/*.log "$EV/b2_$sys/" 2>/dev/null
  (cd "$EV/b2_$sys" && sha256sum *.log) > "$EV/b2_$sys.logs.sha256"
done
