#!/usr/bin/env bash
set -euo pipefail

# Prepares deterministic input assets used by real command templates:
# - data/videos/stream01.mp4 ... stream06.mp4
# - models/openvino/public/person-vehicle-bike-detection-crossroad-0078/FP16/*.xml|*.bin

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIDEO_DIR="$PROJECT_DIR/data/videos"
MODEL_ROOT="$PROJECT_DIR/models/openvino"
OMZ_MODEL_NAME="person-vehicle-bike-detection-crossroad-0078"

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
  local model_xml="$MODEL_ROOT/public/$OMZ_MODEL_NAME/FP16/$OMZ_MODEL_NAME.xml"

  if [[ -f "$model_xml" ]]; then
    log "OpenVINO model already present: $model_xml"
    return 0
  fi

  if ! command -v omz_downloader >/dev/null 2>&1; then
    warn "omz_downloader not found. Install openvino-dev in the active environment first."
    return 1
  fi

  mkdir -p "$MODEL_ROOT/public" "$MODEL_ROOT/cache"
  log "Downloading Open Model Zoo model: $OMZ_MODEL_NAME"
  omz_downloader \
    --name "$OMZ_MODEL_NAME" \
    --output_dir "$MODEL_ROOT/public" \
    --cache_dir "$MODEL_ROOT/cache"

  if [[ -f "$model_xml" ]]; then
    log "OpenVINO model ready: $model_xml"
  else
    warn "Model download finished but expected XML is missing: $model_xml"
    return 1
  fi
}

main() {
  ensure_video_layout
  ensure_openvino_model

  cat <<EOF

Prepared assets:
- Video layout: $VIDEO_DIR/layout.txt
- OpenVINO model: $MODEL_ROOT/public/$OMZ_MODEL_NAME/FP16/$OMZ_MODEL_NAME.xml

EOF
}

main "$@"
