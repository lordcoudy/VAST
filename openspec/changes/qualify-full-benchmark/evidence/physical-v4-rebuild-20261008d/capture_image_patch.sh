#!/usr/bin/env bash
set -euo pipefail

root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
base="$root/artifacts/qualify_full_benchmark_20261008d"
capture="$base/image_capture"
runtime="$base/runtime_images"
python=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
registry="$root/configs/publication_qualification_image_refreeze_v1.json"
native="$base/native-a/native_probe.freeze.json"
worker="$base/worker_images/analytics-worker.freeze.json"
[[ "$(realpath -e "$root")" == "$root" && ! -e "$capture" ]]
[[ -f "$native" && -f "$worker" && -f "$runtime/savant.runtime_image.materialized.v3.json" ]]
mkdir -m 700 "$capture"

for system in deepstream savant openvino_gva gstreamer_custom; do
  "$python" -B "$root/scripts/publication_qualification_image_refreeze_v1.py" capture \
    --project-root "$root" --registry "$registry" --system "$system" \
    --native-receipt "$native" \
    --receipt-output "$runtime/$system.runtime.freeze.json" \
    --docker /usr/bin/docker \
    >"$capture/$system.stdout" 2>"$capture/$system.stderr"
done

"$python" -B "$root/scripts/publication_qualification_image_refreeze_v1.py" assemble \
  --project-root "$root" --registry "$registry" \
  --native-receipt "$native" --worker-receipt "$worker" \
  --runtime-receipt "deepstream=$runtime/deepstream.runtime.freeze.json" \
  --runtime-receipt "savant=$runtime/savant.runtime.freeze.json" \
  --runtime-receipt "openvino_gva=$runtime/openvino_gva.runtime.freeze.json" \
  --runtime-receipt "gstreamer_custom=$runtime/gstreamer_custom.runtime.freeze.json" \
  --output "$base/qualification_image_identity_patch.json" \
  >"$capture/assemble.stdout" 2>"$capture/assemble.stderr"

"$python" -B "$root/scripts/publication_qualification_image_refreeze_v1.py" verify-patch \
  --project-root "$root" --patch "$base/qualification_image_identity_patch.json" \
  >"$capture/verify-patch.stdout" 2>"$capture/verify-patch.stderr"
sha256sum "$base/qualification_image_identity_patch.json" >"$capture/patch-file.sha256"
