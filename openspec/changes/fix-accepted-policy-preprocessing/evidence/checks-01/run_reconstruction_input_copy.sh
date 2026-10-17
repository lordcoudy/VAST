#!/usr/bin/env bash
set -euo pipefail
SHA=591a93e778a9a7839da6278326d215e24e91ea45
ROOT="/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA"
MANAGED="$(cd -- "$(dirname -- "$0")" && pwd -P)"
HELPER="$MANAGED/copy_reconstruction_inputs_v1.py"
PLAN="$MANAGED/reconstruction-inputs.copy-plan.v1.json"
PLAN_SHA=e097ad424cb80a87b1a80d7166236ef5a364faab438c9a14751f5f600535d838
HELPER_SHA=f6fc58865cbebb67bb55c1677673a8dd24ea4f8ca44314f749acdc0f69095474
[[ "$(sha256sum "$HELPER" | cut -d ' ' -f1)" == "$HELPER_SHA" ]]
[[ "$(sha256sum "$PLAN" | cut -d ' ' -f1)" == "$PLAN_SHA" ]]
export VAST_REPAIR_CHECK_ROOT="$ROOT"
source "$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/recipe_common.sh"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
OUT="$CHECK_BASE/reconstruction-inputs-copy-$SHA"
[[ ! -e "$OUT" && ! -L "$OUT" ]]
mkdir -m 700 -- "$OUT"
date -u +%FT%TZ > "$OUT/started.txt"
printf '%s\n' "$SHA" > "$OUT/source-commit.txt"
sha256sum "$HELPER" "$PLAN" "$0" > "$OUT/external-helper-plan.sha256"
cd "$ROOT"
set +e
"$PY" -B "$HELPER" apply --plan "$PLAN" --reviewed-plan-sha256 "$PLAN_SHA" \
  > "$OUT/original.stdout.json" 2> "$OUT/original.stderr.log"
RC="$?"
set -e
printf '%s\n' "$RC" > "$OUT/original.rc.txt"
date -u +%FT%TZ > "$OUT/finished.txt"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
printf '%s\n' "$OUT"
exit "$RC"
