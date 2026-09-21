#!/usr/bin/env bash
set -euo pipefail
umask 022

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
registry="$project_root/configs/publication_qualification_image_refreeze_v1.json"
python_bin="${VAST_PUBLICATION_PYTHON:-$project_root/.publication-runtime/full-publication-cp312-v1/bin/python3.12}"
artifact_dir="${VAST_PUBLICATION_IMAGE_ARTIFACT_DIR:-$project_root/artifacts/publication_image_build_v1}"
native_receipt="${VAST_NATIVE_PROBE_FREEZE_RECEIPT:-$artifact_dir/native_probe.freeze.json}"
worker_receipt="${VAST_ANALYTICS_WORKER_FREEZE_RECEIPT:-$artifact_dir/analytics_worker.freeze.json}"
patch_output="${VAST_QUALIFICATION_IMAGE_IDENTITY_PATCH:-$artifact_dir/qualification_image_identity_patch.v1.json}"
docker_bin="${VAST_DOCKER_BIN:-docker}"

[[ -x "$python_bin" && -f "$registry" && ! -L "$registry" ]] || {
  echo "pinned publication Python or refreeze registry is unavailable" >&2
  exit 2
}

if [[ "${VAST_PUBLICATION_IMAGE_PLAN_ONLY:-0}" == "1" ]]; then
  exec "$python_bin" -B \
    "$project_root/scripts/publication_qualification_image_refreeze_v1.py" plan \
    --project-root "$project_root" \
    --registry "$registry"
fi

case "$artifact_dir" in
  "$project_root"/*) ;;
  *)
    echo "qualification image artifact directory must remain under project_root" >&2
    exit 2
    ;;
esac
[[ "$artifact_dir" != *"/../"* && "$artifact_dir" != *"/./"* ]] || {
  echo "qualification image artifact directory is not canonical" >&2
  exit 2
}
if [[ -e "$artifact_dir" ]]; then
  [[ -d "$artifact_dir" && ! -L "$artifact_dir" ]] || {
    echo "qualification image artifact directory is unsafe" >&2
    exit 2
  }
else
  install -d -m 0755 -- "$artifact_dir"
fi
[[ "$(cd "$artifact_dir" && pwd -P)" == "$artifact_dir" ]] || {
  echo "qualification image artifact directory is aliased" >&2
  exit 2
}
[[ -f "$native_receipt" && ! -L "$native_receipt" \
   && -f "$worker_receipt" && ! -L "$worker_receipt" ]] || {
  echo "native-probe and analytics-worker freeze receipts are required" >&2
  exit 2
}

systems=(deepstream savant openvino_gva gstreamer_custom)
runtime_arguments=()
for system in "${systems[@]}"; do
  receipt="$artifact_dir/${system}.runtime.freeze.json"
  "$python_bin" -B \
    "$project_root/scripts/publication_qualification_image_refreeze_v1.py" capture \
    --project-root "$project_root" \
    --registry "$registry" \
    --system "$system" \
    --native-receipt "$native_receipt" \
    --receipt-output "$receipt" \
    --docker "$docker_bin" >/dev/null
  runtime_arguments+=(--runtime-receipt "${system}=$receipt")
done

exec "$python_bin" -B \
  "$project_root/scripts/publication_qualification_image_refreeze_v1.py" assemble \
  --project-root "$project_root" \
  --registry "$registry" \
  --native-receipt "$native_receipt" \
  --worker-receipt "$worker_receipt" \
  "${runtime_arguments[@]}" \
  --output "$patch_output"
