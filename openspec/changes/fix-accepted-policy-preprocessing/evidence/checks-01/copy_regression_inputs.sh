#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/recipe_common.sh"
[[ "$#" == 2 ]] || exit 64
SHA="$1"
CATALOG_SHA="$2"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
OUT="$CHECK_BASE/regression-copy-$SHA"
[[ ! -e "$OUT" ]]
mkdir -p -- "$CHECK_BASE"
mkdir -m 700 -- "$OUT"
"$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" regression "$SHA" "$CATALOG_SHA" \
  "$OLD_ROOT" "$ROOT" "$OUT/copy.report.json" > "$OUT/stdout.log" 2> "$OUT/stderr.log"
assert_frozen_root "$SHA"
