#!/usr/bin/env bash
set -euo pipefail
[[ "$#" == 8 && "$1" == --source-commit && "$3" == --plan \
   && "$5" == --reviewed-plan-sha256 && "$7" == --reviewed-helper-sha256 ]] || exit 64
SHA="$2"
PLAN="$4"
PLAN_SHA="$6"
HELPER_SHA="$8"
[[ "$SHA" =~ ^[0-9a-f]{40}$ && "$PLAN_SHA" =~ ^[0-9a-f]{64}$ \
   && "$HELPER_SHA" =~ ^[0-9a-f]{64}$ ]]
ROOT="/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA"
MANAGED="$(cd -- "$(dirname -- "$0")" && pwd -P)"
HELPER="$MANAGED/copy_reconstruction_inputs_v2.py"
[[ "$PLAN" == /* && -f "$PLAN" && ! -L "$PLAN" \
   && "$(realpath -e "$PLAN")" == "$PLAN" ]]
[[ "$(sha256sum "$HELPER" | cut -d ' ' -f1)" == "$HELPER_SHA" ]]
[[ "$(sha256sum "$PLAN" | cut -d ' ' -f1)" == "$PLAN_SHA" ]]
export VAST_REPAIR_CHECK_ROOT="$ROOT"
source "$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/recipe_common.sh"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
[[ -d "$CHECK_BASE" && "$(realpath -e "$CHECK_BASE")" == "$CHECK_BASE" ]]
OUT="$CHECK_BASE/reconstruction-inputs-copy-v2-$SHA"
[[ ! -e "$OUT" && ! -L "$OUT" ]]
mkdir -m 700 -- "$OUT"
date -u +%FT%TZ > "$OUT/started.txt"
printf '%s\n' "$SHA" > "$OUT/source-commit.txt"
sha256sum "$HELPER" "$PLAN" "$0" > "$OUT/external-helper-plan-wrapper.sha256"
cd "$ROOT"
set +e
"$PY" -B "$HELPER" --source-commit "$SHA" apply \
  --plan "$PLAN" --reviewed-plan-sha256 "$PLAN_SHA" \
  > "$OUT/original.stdout.json" 2> "$OUT/original.stderr.log"
RC="$?"
set -e
printf '%s\n' "$RC" > "$OUT/original.rc.txt"
date -u +%FT%TZ > "$OUT/finished.txt"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
printf '%s\n' "$OUT"
exit "$RC"
