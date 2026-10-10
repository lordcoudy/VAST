#!/usr/bin/env bash
set -euo pipefail

kind="${1:?expected worker or runtime}"
[[ "$kind" == worker || "$kind" == runtime ]] || exit 2
root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
base="$root/artifacts/qualify_full_benchmark_20261008e"
native="$base/native-a/native_probe.freeze.json"
native_b="$base/native-b/native_probe.freeze.json"
python=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
[[ "$(realpath -e "$root")" == "$root" ]]
[[ -f "$native" && -f "$native_b" && -x "$python" ]]
cmp "$native" "$native_b"

if [[ "$kind" == worker ]]; then
  dest="$base/worker_images"
  [[ ! -e "$dest" ]]
  mkdir -m 700 "$dest"
  work="$(mktemp -d /tmp/vast-benchmark-worker-qfb-20261008e.XXXXXXXX)"
  "$python" -B "$root/scripts/publication_image_build_v1.py" build \
    --project-root "$root" \
    --registry "$root/configs/publication_image_build_v1.json" \
    --group analytics_worker \
    --work-root "$work" \
    --receipt-output "$dest/analytics-worker.freeze.json" \
    --producer-receipt "$native" >"$dest/stdout.log" 2>"$dest/stderr.log"
  sha256sum "$dest/analytics-worker.freeze.json" >"$dest/receipt-file.sha256"
else
  [[ -f "$base/worker_images/analytics-worker.freeze.json" ]]
  dest="$base/runtime_images"
  [[ ! -e "$dest" ]]
  mkdir -m 700 "$dest"
  "$python" -B "$root/scripts/build_publication_runtime_images_after_refreeze_v1.py" build \
    --project-root "$root" \
    --native-receipt "$native" \
    --artifact-dir "$dest" >"$dest/stdout.log" 2>"$dest/stderr.log"
fi
