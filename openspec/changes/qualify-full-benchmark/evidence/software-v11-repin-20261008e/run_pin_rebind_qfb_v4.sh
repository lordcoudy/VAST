#!/usr/bin/env bash
# Run from WSL as uid 1000. MODE: inventory | plan | render | apply
# QFB_TRACKED_FILES must name a NUL-separated `git ls-files -z` listing of the PR worktree
# (WSL git cannot open the Windows worktree).
set -euo pipefail
test "$(id -u)" = 1000
mode=$1
root=/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST
evidence=$root/openspec/changes/qualify-full-benchmark/evidence/software-v11-repin-20261008e
python=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
test "$(realpath -e "$root")" = "$root"
test -s "${QFB_TRACKED_FILES:?}"
cd "$root"
set -o noclobber
case "$mode" in
  inventory) exec "$python" -B "$evidence/rebind_host_identity_pins_qfb_v4.py" inventory >"$evidence/inventory.v1.json" ;;
  plan) exec "$python" -B "$evidence/rebind_host_identity_pins_qfb_v4.py" plan >"$evidence/host-pin-rebind.plan.v1.json" ;;
  render) exec "$python" -B "$evidence/render_plan_review_qfb_v4.py" >"$evidence/host-pin-rebind.plan-review.v1.json" ;;
  apply)
    plan_sha=$(sha256sum "$evidence/host-pin-rebind.plan.v1.json" | cut -d ' ' -f 1)
    test "$plan_sha" = "${2:?reviewed plan sha256 required}"
    exec "$python" -B "$evidence/rebind_host_identity_pins_qfb_v4.py" apply "$plan_sha" >"$evidence/host-pin-rebind.applied.v1.json" ;;
  *) exit 64 ;;
esac
