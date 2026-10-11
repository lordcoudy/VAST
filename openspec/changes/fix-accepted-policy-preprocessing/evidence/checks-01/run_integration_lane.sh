#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/recipe_common.sh"
[[ "$#" == 1 ]] || exit 64
SHA="$1"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
assert_nine_ids
OUT="$CHECK_BASE/integration-$SHA"
[[ ! -e "$OUT" ]]
mkdir -p -- "$CHECK_BASE"
mkdir -m 700 -- "$OUT"
printf '%s\n' "$SHA" > "$OUT/commit.txt"
date -u +%FT%TZ > "$OUT/started.txt"
cp --no-clobber "$CHECK_RECIPE_DIR/integration-test-ids.txt" "$OUT/integration-test-ids.txt"
cd "$ROOT"
FAIL=0
while IFS= read -r ID; do
  set +e
  VAST_LIVE_PREFLIGHT=1 VAST_RUN_OPENVINO_LIVE_DOCKER_TEST=1 TMPDIR=/var/tmp \
    "$PY" -B "$CHECK_RECIPE_DIR/run_integration_case.py" "$ID" "$OUT/$ID.outcome.json" \
    > "$OUT/$ID.stdout.log" 2> "$OUT/$ID.stderr.log"
  RC="$?"
  set -e
  printf '%s %s\n' "$RC" "$ID" >> "$OUT/results.txt"
  [[ "$RC" == 0 ]] || FAIL=1
done < "$CHECK_RECIPE_DIR/integration-test-ids.txt"
date -u +%FT%TZ > "$OUT/finished.txt"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
[[ "$FAIL" == 0 ]] || exit 1
[[ "$(wc -l < "$OUT/results.txt")" == 9 ]]
printf '%s\n' 'Nine original integration cases executed successfully, with zero skips.'
