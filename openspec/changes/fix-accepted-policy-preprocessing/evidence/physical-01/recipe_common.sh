#!/usr/bin/env bash
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT=/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a
SOURCE_ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
NAMESPACE=accepted-policy-repair-20261011a
BASE="$ROOT/artifacts/accepted_policy_repair_20261011a"
REGISTRY="$ROOT/configs/publication_qualification_image_refreeze_v1.json"
NATIVE="$BASE/native-a/native_probe.freeze.json"
WORKER="$BASE/worker_images/analytics-worker.freeze.json"

assert_frozen_root() {
  local expected="$1"
  [[ "$expected" =~ ^[0-9a-f]{40}$ ]]
  [[ "$(realpath -e "$ROOT")" == "$ROOT" && -x "$PY" ]]
  [[ "$(git -C "$ROOT" rev-parse HEAD)" == "$expected" ]]
  [[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]
}

assert_plain_file() {
  local file="$1"
  [[ -f "$file" && ! -L "$file" && "$(realpath -e "$file")" == "$file" ]]
  [[ "$(stat -c %h "$file")" == 1 ]]
}

runtime_reference() {
  case "$1" in
    deepstream) printf 'vast/deepstream-publication-runtime-v3:%s\n' "$NAMESPACE" ;;
    savant) printf 'vast/savant-publication-runtime-v3:%s\n' "$NAMESPACE" ;;
    openvino_gva) printf 'vast/openvino-gva-publication-runtime-v3:%s\n' "$NAMESPACE" ;;
    gstreamer_custom) printf 'vast/gstreamer-custom-publication-runtime-v3:%s\n' "$NAMESPACE" ;;
    *) return 64 ;;
  esac
}
