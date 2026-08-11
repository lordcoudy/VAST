#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OPENVINO_BASE_IMAGE="${OPENVINO_BASE_IMAGE:-intel/dlstreamer@sha256:355435d2bdb986fe1d51f443d366da3ac1eb0c7175aa03ce2b31e4485f36b3bd}"
DEEPSTREAM_BASE_IMAGE="${DEEPSTREAM_BASE_IMAGE:-nvcr.io/nvidia/deepstream:7.0-triton-multiarch}"
SAVANT_BASE_IMAGE="${SAVANT_BASE_IMAGE:-ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0}"
OPENVINO_NATIVE_PROBE_IMAGE="${OPENVINO_NATIVE_PROBE_IMAGE:-vast/openvino-native-probe:dlstreamer-2026.1}"
DEEPSTREAM_NATIVE_PROBE_IMAGE="${DEEPSTREAM_NATIVE_PROBE_IMAGE:-vast/deepstream-native-probe:7.0}"
SAVANT_NATIVE_PROBE_IMAGE="${SAVANT_NATIVE_PROBE_IMAGE:-vast/savant-native-probe:0.5.17-7.0}"
BUILD_OPENVINO="${BUILD_OPENVINO:-1}"
BUILD_DEEPSTREAM="${BUILD_DEEPSTREAM:-1}"
BUILD_SAVANT="${BUILD_SAVANT:-1}"
SOURCE_LABEL="org.vast.native_probe.source_sha"

log() { echo "[native-probe-images] $*"; }

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
  else
    shasum -a 256 "$1"
  fi
}

sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum
  else
    shasum -a 256
  fi
}

source_sha() {
  local include_savant="$1"
  local include_analytics="$2"
  (
    cd "$PROJECT_DIR"
    printf "CMakeLists.txt\n"
    find deploy/native_gst_probe -type f -print | LC_ALL=C sort
    if [[ "$include_savant" == "1" ]]; then
      find deploy/savant -type f -print | LC_ALL=C sort
    fi
    if [[ "$include_analytics" == "1" ]]; then
      find deploy/gstreamer_adaptivescheduler deploy/gstreamer_analytics_terminal -type f -print | LC_ALL=C sort
    fi
  ) | while IFS= read -r path; do
    digest="$(sha256_file "$PROJECT_DIR/$path" | awk '{print $1}')"
    printf "%s  %s\n" "$digest" "$path"
  done | sha256_stream | awk '{print $1}'
}

if ! command -v docker >/dev/null 2>&1; then
  echo "[native-probe-images][error] docker is required" >&2
  exit 1
fi

if [[ "$BUILD_OPENVINO" == "1" ]]; then
  openvino_source_sha="$(source_sha 0 1)"
  log "building OpenVINO native probe image: $OPENVINO_NATIVE_PROBE_IMAGE"
  log "source sha: $openvino_source_sha"
  docker build \
    --build-arg BASE_IMAGE="$OPENVINO_BASE_IMAGE" \
    --build-arg VAST_NATIVE_PROBE_SOURCE_SHA="$openvino_source_sha" \
    --label "$SOURCE_LABEL=$openvino_source_sha" \
    -f "$PROJECT_DIR/deploy/native_gst_probe/Dockerfile.openvino" \
    -t "$OPENVINO_NATIVE_PROBE_IMAGE" \
    "$PROJECT_DIR"
fi

if [[ "$BUILD_DEEPSTREAM" == "1" ]]; then
  deepstream_source_sha="$(source_sha 0 0)"
  log "building DeepStream native probe image: $DEEPSTREAM_NATIVE_PROBE_IMAGE"
  log "source sha: $deepstream_source_sha"
  docker build \
    --build-arg BASE_IMAGE="$DEEPSTREAM_BASE_IMAGE" \
    --build-arg VAST_NATIVE_PROBE_SOURCE_SHA="$deepstream_source_sha" \
    --label "$SOURCE_LABEL=$deepstream_source_sha" \
    -f "$PROJECT_DIR/deploy/native_gst_probe/Dockerfile.deepstream" \
    -t "$DEEPSTREAM_NATIVE_PROBE_IMAGE" \
    "$PROJECT_DIR"
fi

if [[ "$BUILD_SAVANT" == "1" ]]; then
  savant_source_sha="$(source_sha 1 0)"
  log "building Savant native probe image: $SAVANT_NATIVE_PROBE_IMAGE"
  log "source sha: $savant_source_sha"
  docker build \
    --build-arg BASE_IMAGE="$SAVANT_BASE_IMAGE" \
    --build-arg VAST_NATIVE_PROBE_SOURCE_SHA="$savant_source_sha" \
    --label "$SOURCE_LABEL=$savant_source_sha" \
    -f "$PROJECT_DIR/deploy/native_gst_probe/Dockerfile.savant" \
    -t "$SAVANT_NATIVE_PROBE_IMAGE" \
    "$PROJECT_DIR"
fi
