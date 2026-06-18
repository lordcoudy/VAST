#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEEPSTREAM_BASE_IMAGE="${DEEPSTREAM_BASE_IMAGE:-nvcr.io/nvidia/deepstream:7.0-triton-multiarch}"
SAVANT_BASE_IMAGE="${SAVANT_BASE_IMAGE:-ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0}"
DEEPSTREAM_NATIVE_PROBE_IMAGE="${DEEPSTREAM_NATIVE_PROBE_IMAGE:-vast/deepstream-native-probe:7.0}"
SAVANT_NATIVE_PROBE_IMAGE="${SAVANT_NATIVE_PROBE_IMAGE:-vast/savant-native-probe:0.5.17-7.0}"
BUILD_DEEPSTREAM="${BUILD_DEEPSTREAM:-1}"
BUILD_SAVANT="${BUILD_SAVANT:-1}"

log() { echo "[native-probe-images] $*"; }

if ! command -v docker >/dev/null 2>&1; then
  echo "[native-probe-images][error] docker is required" >&2
  exit 1
fi

if [[ "$BUILD_DEEPSTREAM" == "1" ]]; then
  log "building DeepStream native probe image: $DEEPSTREAM_NATIVE_PROBE_IMAGE"
  docker build \
    --build-arg BASE_IMAGE="$DEEPSTREAM_BASE_IMAGE" \
    -f "$PROJECT_DIR/deploy/native_gst_probe/Dockerfile.deepstream" \
    -t "$DEEPSTREAM_NATIVE_PROBE_IMAGE" \
    "$PROJECT_DIR"
fi

if [[ "$BUILD_SAVANT" == "1" ]]; then
  log "building Savant native probe image: $SAVANT_NATIVE_PROBE_IMAGE"
  docker build \
    --build-arg BASE_IMAGE="$SAVANT_BASE_IMAGE" \
    -f "$PROJECT_DIR/deploy/native_gst_probe/Dockerfile.savant" \
    -t "$SAVANT_NATIVE_PROBE_IMAGE" \
    "$PROJECT_DIR"
fi

