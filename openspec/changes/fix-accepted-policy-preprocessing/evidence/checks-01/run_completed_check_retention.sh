#!/usr/bin/env bash
set -eu
umask 077

HERE=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
HELPER=$HERE/retain_completed_check_results.py
PLAN=$HERE/completed-check-results.plan.v1.json
CONTROL=$HERE/completed-check-retention-control
PLAN_SHA=58baf5eab3eda7c4d589b161b7b7c2f9b57af6d896475c036416eb9b22206625
HELPER_SHA=01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed

test "$(realpath -e "$HERE")" = "$HERE"
test "$(sha256sum "$HELPER" | cut -d ' ' -f 1)" = "$HELPER_SHA"
test "$(sha256sum "$PLAN" | cut -d ' ' -f 1)" = "$PLAN_SHA"
test ! -e "$CONTROL"
test ! -L "$CONTROL"
mkdir "$CONTROL"
date -u +%Y-%m-%dT%H:%M:%SZ > "$CONTROL/started.txt"
sha256sum "$HELPER" "$PLAN" "$HERE/run_completed_check_retention.sh" > "$CONTROL/external-helper-plan-wrapper.sha256"

set +e
env TMPDIR=/var/tmp PYTHONDONTWRITEBYTECODE=1 "$PY" -B "$HELPER" apply \
  --plan "$PLAN" --reviewed-plan-sha256 "$PLAN_SHA" \
  > "$CONTROL/original.stdout.json" 2> "$CONTROL/original.stderr.log"
RC=$?
set -e
printf '%s\n' "$RC" > "$CONTROL/original.rc.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$CONTROL/finished.txt"
cat "$CONTROL/original.stdout.json"
cat "$CONTROL/original.stderr.log" >&2
exit "$RC"
