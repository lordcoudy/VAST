#!/usr/bin/env bash
# Amendment 7, 6D.4: refreeze (recipe capture_image_patch.sh, diff vs 20261008d).
set -euo pipefail
E=$(cd "$(dirname "$0")" && pwd)
base=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008e
cp "$E/capture_image_patch.sh" "$E/capture_image_patch.sh.recipe-diff.txt" "$base/"
date -u +%FT%TZ > "$base/capture.started.txt"
set +e
bash "$base/capture_image_patch.sh"
rc=$?
set -e
echo "$rc" > "$base/capture.rc"; date -u +%FT%TZ > "$base/capture.finished.txt"
python3 "$E/engine_snapshot.py" "$E/build_prep/engine.after-refreeze.v1.json"
echo "capture rc=$rc"; exit "$rc"
