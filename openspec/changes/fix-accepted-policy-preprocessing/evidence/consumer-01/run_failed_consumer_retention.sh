#!/usr/bin/env bash
set -eu
umask 077

HERE=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
HELPER=$HERE/retain_failed_consumer_results.py
PLAN=$HERE/failed-consumer-results.plan.v1.json
CONTROL=$HERE/failed-consumer-retention-control
PLAN_SHA=8da8e787cb0958629be105c5454602db19b2b93dfe2dbcca61c9fd5905415378
HELPER_SHA=50e7555f763ba94be32605930bb8402d69ab120350267310ec4e65cd606be915

test "$(realpath -e "$HERE")" = "$HERE"
test "$(sha256sum "$HELPER" | cut -d ' ' -f 1)" = "$HELPER_SHA"
test "$(sha256sum "$PLAN" | cut -d ' ' -f 1)" = "$PLAN_SHA"
test ! -e "$CONTROL"
test ! -L "$CONTROL"
mkdir "$CONTROL"
date -u +%Y-%m-%dT%H:%M:%SZ > "$CONTROL/started.txt"
sha256sum "$HELPER" "$PLAN" "$HERE/run_failed_consumer_retention.sh" > "$CONTROL/external-helper-plan-wrapper.sha256"

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
