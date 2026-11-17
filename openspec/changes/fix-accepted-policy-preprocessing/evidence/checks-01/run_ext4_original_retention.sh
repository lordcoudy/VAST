#!/usr/bin/env bash
set -eu
umask 077

HERE=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
HELPER=$HERE/retain_ext4_original_results.py
PLAN=$HERE/ext4-original-results.plan.v1.json
CONTROL=$HERE/ext4-original-retention-control
PLAN_SHA=ecd8bfddc9df5b5ca07457a8698165cef0ad867df5c3cb19f91f2da1bc898928
HELPER_SHA=bb012e68ad3928229f08238870c9c206b8ec5e41e8c618960a21b0c8c80928b2

test "$(realpath -e "$HERE")" = "$HERE"
test "$(sha256sum "$HELPER" | cut -d ' ' -f 1)" = "$HELPER_SHA"
test "$(sha256sum "$PLAN" | cut -d ' ' -f 1)" = "$PLAN_SHA"
test ! -e "$CONTROL"
test ! -L "$CONTROL"
mkdir "$CONTROL"
date -u +%Y-%m-%dT%H:%M:%SZ > "$CONTROL/started.txt"
sha256sum "$HELPER" "$PLAN" "$HERE/run_ext4_original_retention.sh" > "$CONTROL/external-helper-plan-wrapper.sha256"

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
