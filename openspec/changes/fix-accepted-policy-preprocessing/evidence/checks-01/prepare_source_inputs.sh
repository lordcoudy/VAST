#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/recipe_common.sh"
[[ "$#" == 4 ]] || exit 64
SHA="$1"
CATALOG_SHA="$2"
ASSET_SHA="$3"
FRESH_SHA="$4"
assert_frozen_root "$SHA"
[[ "$ROOT" != "$PHYSICAL_ROOT" ]]
[[ "$(git -C "$PHYSICAL_ROOT" rev-parse HEAD)" == "$PHYSICAL_BUILD_COMMIT" ]]
[[ -z "$(git -C "$PHYSICAL_ROOT" status --porcelain --untracked-files=no)" ]]
assert_committed_bytes "$ROOT"
assert_committed_bytes "$PHYSICAL_ROOT"
OUT="$CHECK_BASE/source-input-copy-$SHA"
[[ ! -e "$OUT" ]]
mkdir -p -- "$CHECK_BASE"
mkdir -m 700 -- "$OUT"
"$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" regression "$SHA" "$CATALOG_SHA" \
  "$OLD_ROOT" "$ROOT" "$OUT/regression-copy.report.json" \
  > "$OUT/regression-copy.stdout.log" 2> "$OUT/regression-copy.stderr.log"
"$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" assets "$SHA" "$CATALOG_SHA" \
  "$PHYSICAL_ROOT" "$ROOT" "$OUT/asset-copy.report.json" "$ASSET_SHA" "$PHYSICAL_BUILD_COMMIT" \
  > "$OUT/asset-copy.stdout.log" 2> "$OUT/asset-copy.stderr.log"
"$PY" -B "$CHECK_RECIPE_DIR/copy_fresh_check_inputs.py" "$PHYSICAL_BUILD_COMMIT" "$SHA" "$FRESH_SHA" \
  "$PHYSICAL_ROOT" "$ROOT" "$OUT/fresh-copy.report.json" \
  > "$OUT/fresh-copy.stdout.log" 2> "$OUT/fresh-copy.stderr.log"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
[[ "$(git -C "$PHYSICAL_ROOT" rev-parse HEAD)" == "$PHYSICAL_BUILD_COMMIT" ]]
assert_committed_bytes "$PHYSICAL_ROOT"
