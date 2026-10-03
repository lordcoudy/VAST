#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
python_bin="${VAST_PUBLICATION_PYTHON:-$project_root/.publication-runtime/full-publication-cp312-v1/bin/python3.12}"
registry="$project_root/configs/publication_image_build_v1.json"
artifact_dir="${VAST_PUBLICATION_IMAGE_ARTIFACT_DIR:-$project_root/artifacts/publication_image_build_v1}"
receipt_output="${VAST_NATIVE_PROBE_FREEZE_RECEIPT:-$artifact_dir/native_probe.freeze.json}"

[[ -x "$python_bin" ]] || {
  echo "canonical publication Python is unavailable: $python_bin" >&2
  exit 2
}

if [[ "${VAST_PUBLICATION_IMAGE_PLAN_ONLY:-0}" == "1" ]]; then
  exec "$python_bin" -B "$project_root/scripts/publication_image_build_v1.py" plan \
    --project-root "$project_root" \
    --registry "$registry"
fi

mkdir -p -- "$artifact_dir"
work_root="$(mktemp -d /tmp/vast-publication-native-images-v1.XXXXXXXX)"
readonly work_root
cleanup() {
  local resolved
  resolved="$(realpath -e -- "$work_root")" || return 2
  if [[ "$(dirname -- "$resolved")" != /tmp \
     || "$(basename -- "$resolved")" != vast-publication-native-images-v1.* ]]; then
    echo "refusing unsafe native-image work-root cleanup" >&2
    return 2
  fi
  rm -rf -- "$resolved"
}
trap cleanup EXIT

"$python_bin" -B "$project_root/scripts/publication_image_build_v1.py" build \
  --project-root "$project_root" \
  --registry "$registry" \
  --group native_probe \
  --work-root "$work_root" \
  --receipt-output "$receipt_output"
