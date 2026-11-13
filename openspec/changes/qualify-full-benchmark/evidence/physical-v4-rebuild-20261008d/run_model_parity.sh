#!/usr/bin/env bash
set -euo pipefail

root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
base="$root/artifacts/qualify_full_benchmark_20261008d"
parity="$base/model_parity_v4"
control="$base/model_parity_control"
python=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
namespace=qfb-20261008d
[[ "$(realpath -e "$root")" == "$root" ]]
[[ -f "$base/qualification_image_identity_patch.json" && ! -e "$parity" && ! -e "$control" ]]
[[ ! -e /var/tmp/vast-parity-qfb-20261008d ]]
mkdir -m 700 "$parity" "$control"
mkdir -m 700 /var/tmp/vast-parity-qfb-20261008d

"$python" -B "$root/scripts/checkpoint_model_parity_materializer_v4.py" \
  --project-root "$root" \
  --image-patch "$base/qualification_image_identity_patch.json" \
  --source-execution-config "$root/configs/analytics_execution_layer.yaml" \
  --source-manifest "$root/configs/checkpoint_analytics_model_parity.yaml" \
  --datasets "$root/configs/datasets.yaml" \
  --runtime-probe-dir "$parity/runtime_probes" \
  --versioned-execution-config "$root/configs/analytics_execution_layer.refreshed.v4.$namespace.json" \
  --base-v4-manifest "$root/configs/checkpoint_analytics_model_parity.refreshed.v4.$namespace.yaml" \
  --binding-set "$parity/bindings" \
  --materialization-dir "$parity/materialization" \
  --accepted-manifest "$root/configs/checkpoint_analytics_model_parity.refreshed.v4.$namespace.accepted.yaml" \
  --accepted-assessment "$root/configs/checkpoint_analytics_model_parity.refreshed.v4.$namespace.accepted.assessment.json" \
  --acceptance-receipt "$root/configs/checkpoint_analytics_model_parity.refreshed.v4.$namespace.accepted.acceptance_receipt.json" \
  --acceptance-binding "$parity/acceptance_binding.v4.json" \
  --ffmpeg /usr/bin/ffmpeg \
  --socket-dir /var/tmp/vast-parity-qfb-20261008d \
  >"$control/stdout.log" 2>"$control/stderr.log"
