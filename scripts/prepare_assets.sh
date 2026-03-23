#!/usr/bin/env bash
set -euo pipefail

# Prepares deterministic input assets used by real command templates:
# - data/videos/stream01.mp4 ... stream06.mp4
# - models/openvino/public/person-vehicle-bike-detection-crossroad-0078/FP16/*.xml|*.bin

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO_DIR="$PROJECT_DIR/data/videos"
MODEL_ROOT="$PROJECT_DIR/models/openvino"
OMZ_MODEL_NAME="person-vehicle-bike-detection-crossroad-0078"
OMZ_DOWNLOAD_RETRIES="${OMZ_DOWNLOAD_RETRIES:-4}"
OMZ_RETRY_SLEEP_S="${OMZ_RETRY_SLEEP_S:-15}"

resolve_model_xml_path() {
  local candidate
  for candidate in \
    "$MODEL_ROOT/public/intel/$OMZ_MODEL_NAME/FP16/$OMZ_MODEL_NAME.xml" \
    "$MODEL_ROOT/public/$OMZ_MODEL_NAME/FP16/$OMZ_MODEL_NAME.xml"; do
    if [[ -f "$candidate" ]]; then
      printf "%s" "$candidate"
      return 0
    fi
  done
  return 1
}

VIDEO_DURATION_S="${VIDEO_DURATION_S:-300}"
VIDEO_WIDTH="${VIDEO_WIDTH:-1920}"
VIDEO_HEIGHT="${VIDEO_HEIGHT:-1080}"
VIDEO_FPS="${VIDEO_FPS:-30}"

log() { echo "[assets] $*"; }
warn() { echo "[assets][warning] $*" >&2; }

ensure_video_layout() {
  mkdir -p "$VIDEO_DIR"

  local s1="$VIDEO_DIR/stream01.mp4"
  if [[ ! -f "$s1" ]]; then
    if ! command -v ffmpeg >/dev/null 2>&1; then
      warn "ffmpeg not found, cannot auto-generate videos"
      return 1
    fi

    log "Generating $s1 (${VIDEO_WIDTH}x${VIDEO_HEIGHT}@${VIDEO_FPS}, ${VIDEO_DURATION_S}s)"
    ffmpeg -y \
      -f lavfi -i "testsrc2=size=${VIDEO_WIDTH}x${VIDEO_HEIGHT}:rate=${VIDEO_FPS}" \
      -t "$VIDEO_DURATION_S" \
      -c:v libx264 -preset veryfast -pix_fmt yuv420p \
      "$s1"
  fi

  local i
  for i in 2 3 4 5 6; do
    local dst
    dst=$(printf "%s/stream%02d.mp4" "$VIDEO_DIR" "$i")
    if [[ -f "$dst" ]]; then
      continue
    fi

    if ln "$s1" "$dst" 2>/dev/null; then
      :
    else
      cp "$s1" "$dst"
    fi
  done

  cat >"$VIDEO_DIR/layout.txt" <<EOF
$VIDEO_DIR/stream01.mp4
$VIDEO_DIR/stream02.mp4
$VIDEO_DIR/stream03.mp4
$VIDEO_DIR/stream04.mp4
$VIDEO_DIR/stream05.mp4
$VIDEO_DIR/stream06.mp4
EOF

  log "Video layout ready at $VIDEO_DIR"
}

ensure_openvino_model() {
  local model_xml=""

  if model_xml="$(resolve_model_xml_path)"; then
    log "OpenVINO model already present: $model_xml"
    return 0
  fi

  if ! command -v omz_downloader >/dev/null 2>&1; then
    warn "omz_downloader not found. Install openvino-dev in the active environment first."
    return 1
  fi

  mkdir -p "$MODEL_ROOT/public" "$MODEL_ROOT/cache"
  local attempt=1
  local ok=0
  while [[ "$attempt" -le "$OMZ_DOWNLOAD_RETRIES" ]]; do
    log "Downloading Open Model Zoo model: $OMZ_MODEL_NAME (attempt ${attempt}/${OMZ_DOWNLOAD_RETRIES})"
    if omz_downloader \
      --name "$OMZ_MODEL_NAME" \
      --output_dir "$MODEL_ROOT/public" \
      --cache_dir "$MODEL_ROOT/cache"; then
      ok=1
      break
    fi

    if [[ "$attempt" -lt "$OMZ_DOWNLOAD_RETRIES" ]]; then
      warn "Download attempt ${attempt}/${OMZ_DOWNLOAD_RETRIES} failed; retrying in ${OMZ_RETRY_SLEEP_S}s"
      sleep "$OMZ_RETRY_SLEEP_S"
    fi
    attempt=$((attempt + 1))
  done

  if [[ "$ok" -ne 1 ]]; then
    warn "Failed to download $OMZ_MODEL_NAME after ${OMZ_DOWNLOAD_RETRIES} attempts"
    return 1
  fi

  if model_xml="$(resolve_model_xml_path)"; then
    log "OpenVINO model ready: $model_xml"
  else
    warn "Model download finished but expected XML is missing in both canonical and legacy paths"
    return 1
  fi
}

main() {
  local model_xml=""
  ensure_video_layout
  ensure_openvino_model

  if ! model_xml="$(resolve_model_xml_path)"; then
    warn "Unable to resolve OpenVINO model XML path after preparation"
    return 1
  fi

  cat <<EOF

Prepared assets:
- Video layout: $VIDEO_DIR/layout.txt
- OpenVINO model: $model_xml

EOF
}

main "$@"
