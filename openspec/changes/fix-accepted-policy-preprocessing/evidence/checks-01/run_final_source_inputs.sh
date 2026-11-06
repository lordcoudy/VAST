#!/usr/bin/env bash
set -euo pipefail
SHA=591a93e778a9a7839da6278326d215e24e91ea45
ROOT="/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA"
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
HELPER="$(cd -- "$(dirname -- "$0")" && pwd -P)/compare_final_source_inputs.py"
export VAST_REPAIR_CHECK_ROOT="$ROOT"
source "$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/recipe_common.sh"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
OUT="$CHECK_BASE/final-source-inputs-$SHA"
[[ ! -e "$OUT" ]]
mkdir -m 700 -- "$OUT"
date -u +%FT%TZ > "$OUT/started.txt"
printf '%s\n' "$SHA" > "$OUT/source-commit.txt"
sha256sum -- "$HELPER" "$(realpath -e "$0")" > "$OUT/external-helpers.sha256.txt"
cd "$ROOT"
set +e
{
  "$PY" -B "$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/physical-01/derive_packaged_closure_inventory.py" \
    "$ROOT" "$SHA" > "$OUT/fresh-packaged-closure.inventory.v1.json" &&
  "$PY" -B "$ROOT/scripts/publication_image_build_v1.py" plan \
    --project-root "$ROOT" --registry "$ROOT/configs/publication_image_build_v1.json" > "$OUT/native-worker.plan.json" &&
  "$PY" -B "$HELPER" --project-root "$ROOT" --fresh-inventory "$OUT/fresh-packaged-closure.inventory.v1.json" \
    --native-worker-plan "$OUT/native-worker.plan.json" > "$OUT/source-comparison.v1.json" &&
  "$PY" -B "$ROOT/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
    --project-root "$ROOT" --receipt "$OUT/execution-code-closure.v1.json" > "$OUT/code-closure-materialize.stdout.json" &&
  "$PY" -B "$ROOT/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
    --project-root "$ROOT" --receipt "$OUT/execution-code-closure.v1.json" --validate-only > "$OUT/code-closure-cold.stdout.json"
} > "$OUT/original.stdout.log" 2> "$OUT/original.stderr.log"
RC="$?"
set -e
printf '%s\n' "$RC" > "$OUT/original.rc.txt"
date -u +%FT%TZ > "$OUT/finished.txt"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
exit "$RC"
