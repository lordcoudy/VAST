#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
image_id="${1:?usage: run_deepstream_kpp_sdk_pilot_v3.sh sha256:IMAGE_ID}"
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "DeepStream pilot requires an exact image ID" >&2
  exit 2
fi

pilot_dir="$(mktemp -d /tmp/vast-deepstream-kpp-pilot.XXXXXX)"
cleanup() {
  rm -f -- "$pilot_dir/first.h264" "$pilot_dir/first.h265"
  rmdir -- "$pilot_dir"
}
trap cleanup EXIT

cd "$project_root"
ffmpeg -hide_banner -loglevel error \
  -i data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_front_gate.mp4 \
  -map 0:v:0 -frames:v 1 -c:v copy -bsf:v h264_mp4toannexb \
  -f h264 "$pilot_dir/first.h264"
ffmpeg -hide_banner -loglevel error \
  -i data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_front_gate.mp4 \
  -map 0:v:0 -frames:v 1 -c:v copy -bsf:v hevc_mp4toannexb \
  -f hevc "$pilot_dir/first.h265"

sha256sum "$pilot_dir/first.h264" "$pilot_dir/first.h265"
for codec in h264 h265; do
  for topology in independent_processes shared_video_dag; do
    if [[ "$topology" == independent_processes ]]; then
      branches="damage"
    else
      branches="plate_number,vehicle_type,damage,foreign_object"
    fi
    printf 'pilot codec=%s topology=%s\n' "$codec" "$topology"
    docker run --rm --gpus all --network none \
      --mount "type=bind,src=$pilot_dir,dst=/pilot,readonly" \
      --entrypoint /usr/local/bin/vast_deepstream_checkpoint_runtime \
      "$image_id" pilot \
      --input "/pilot/first.$codec" \
      --codec "$codec" \
      --topology-kind "$topology" \
      --stream-id 0 \
      --branches "$branches" \
      --timeout-s 30
  done
done
