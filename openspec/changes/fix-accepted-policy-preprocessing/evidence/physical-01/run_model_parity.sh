#!/usr/bin/env bash
# Fresh physical parity authority, never historical Q1/G9 data.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/recipe_common.sh"
expected_commit="${1:?exact frozen repair build commit required}"
assert_frozen_root "$expected_commit"
parity="$BASE/model_parity_v4"
control="$BASE/model-parity-control"
socket="/var/tmp/vast-parity-$NAMESPACE"
patch="$BASE/qualification_image_identity_patch.json"
assert_plain_file "$patch"
[[ ! -e "$parity" && ! -e "$control" && ! -e "$socket" && ! -L "$socket" ]]
mkdir -m 700 "$parity" "$control" "$socket"
set -o noclobber
printf '%s\n' "$expected_commit" > "$control/expected-commit.txt"
date -u +%FT%TZ > "$control/started.txt"
set +e
"$PY" -B "$ROOT/scripts/checkpoint_model_parity_materializer_v4.py" \
  --project-root "$ROOT" --image-patch "$patch" \
  --source-execution-config "$ROOT/configs/analytics_execution_layer.yaml" \
  --source-manifest "$ROOT/configs/checkpoint_analytics_model_parity.yaml" \
  --datasets "$ROOT/configs/datasets.yaml" \
  --runtime-probe-dir "$parity/runtime_probes" \
  --versioned-execution-config "$ROOT/configs/analytics_execution_layer.refreshed.v4.$NAMESPACE.json" \
  --base-v4-manifest "$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.$NAMESPACE.yaml" \
  --binding-set "$parity/bindings" --materialization-dir "$parity/materialization" \
  --accepted-manifest "$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.$NAMESPACE.accepted.yaml" \
  --accepted-assessment "$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.$NAMESPACE.accepted.assessment.json" \
  --acceptance-receipt "$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.$NAMESPACE.accepted.acceptance_receipt.json" \
  --acceptance-binding "$parity/acceptance_binding.v4.json" \
  --ffmpeg /usr/bin/ffmpeg --socket-dir "$socket" \
  > "$control/stdout.log" 2> "$control/stderr.log"
rc=$?
set -e
printf '%s\n' "$rc" > "$control/rc.txt"
date -u +%FT%TZ > "$control/finished.txt"
assert_frozen_root "$expected_commit"
exit "$rc"
