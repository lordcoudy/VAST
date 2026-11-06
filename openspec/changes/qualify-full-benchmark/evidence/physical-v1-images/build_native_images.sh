#!/usr/bin/env bash
set -euo pipefail

label="${1:?expected a or b}"
[[ "$label" == a || "$label" == b ]] || exit 2
root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
base="$root/artifacts/qualify_full_benchmark_20261007a"
dest="$base/native-$label"
[[ "$(realpath -e "$root")" == "$root" ]]
[[ ! -e "$dest" ]]
mkdir -m 700 "$dest"
export VAST_PUBLICATION_PYTHON=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
export VAST_PUBLICATION_IMAGE_ARTIFACT_DIR="$dest"
export VAST_NATIVE_PROBE_FREEZE_RECEIPT="$dest/native_probe.freeze.json"
"$root/scripts/build_native_probe_images_publication_v1.sh" >"$dest/stdout.log" 2>"$dest/stderr.log"
sha256sum "$dest/native_probe.freeze.json" >"$dest/receipt-file.sha256"
