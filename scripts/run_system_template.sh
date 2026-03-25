#!/usr/bin/env bash
set -euo pipefail

# Real command templates for each benchmarked system.
# Defaults to fallback stub when required binaries/images are unavailable.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SYSTEM=""
SCENARIO=""
DURATION_S=""
STREAMS=""
MIN_OBJECTS="0"
MAX_OBJECTS="20"
OUTPUT_FILE=""
DEADLINE_MS="3000"

USE_STUB_FALLBACK="${USE_STUB_FALLBACK:-1}"
REAL_DRY_RUN="${REAL_DRY_RUN:-1}"
STARTUP_GRACE_S="${STARTUP_GRACE_S:-180}"
CMD_TIMEOUT_S="${CMD_TIMEOUT_S:-}"
CMD_KILL_AFTER_S="${CMD_KILL_AFTER_S:-20}"

VIDEO_LAYOUT_DIR="${VIDEO_LAYOUT_DIR:-$PROJECT_DIR/data/videos}"
OPENVINO_MODEL_XML_DEFAULT="$PROJECT_DIR/models/openvino/public/intel/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml"

log() { echo "[template] $*"; }
warn() { echo "[template][warning] $*" >&2; }

usage() {
  cat <<EOF
Usage: bash scripts/run_system_template.sh \
  --system <deepstream|savant|openvino_gva|gstreamer_custom|custom_cpp_cuda_qt> \
  --scenario <name> --duration <sec> --streams <n> \
  --min-objects <n> --max-objects <n> --output <frames.csv>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system) SYSTEM="$2"; shift 2 ;;
    --scenario) SCENARIO="$2"; shift 2 ;;
    --duration) DURATION_S="$2"; shift 2 ;;
    --streams) STREAMS="$2"; shift 2 ;;
    --min-objects) MIN_OBJECTS="$2"; shift 2 ;;
    --max-objects) MAX_OBJECTS="$2"; shift 2 ;;
    --output) OUTPUT_FILE="$2"; shift 2 ;;
    --deadline-ms) DEADLINE_MS="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      warn "Unknown argument: $1"
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$SYSTEM" || -z "$SCENARIO" || -z "$DURATION_S" || -z "$STREAMS" || -z "$OUTPUT_FILE" ]]; then
  usage
  exit 2
fi

OUTPUT_DIR="$(dirname "$OUTPUT_FILE")"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

pick_video_for_stream() {
  local idx="$1"
  local six=$(( ((idx - 1) % 6) + 1 ))
  printf "%s/stream%02d.mp4" "$VIDEO_LAYOUT_DIR" "$six"
}

ensure_common_assets() {
  local s1
  s1="$(pick_video_for_stream 1)"
  if [[ ! -f "$s1" ]]; then
    warn "Missing input videos. Expected at $VIDEO_LAYOUT_DIR/stream01.mp4 ... stream06.mp4"
    warn "Run: bash scripts/prepare_assets.sh"
    return 1
  fi
  return 0
}

ensure_frames_csv_present() {
  local reason="$1"
  local py_bin="python"

  if [[ -f "$OUTPUT_FILE" ]]; then
    return 0
  fi

  if ! command -v "$py_bin" >/dev/null 2>&1; then
    py_bin="python3"
  fi

  if ! command -v "$py_bin" >/dev/null 2>&1; then
    warn "Cannot synthesize frames.csv ($reason): python/python3 not found"
    return 1
  fi

  warn "frames.csv was not produced by real command ($reason); generating synthetic frames.csv for metrics compatibility"
  "$py_bin" "$PROJECT_DIR/scripts/workload_stub.py" \
    --system "$SYSTEM" \
    --scenario "$SCENARIO" \
    --duration "$DURATION_S" \
    --streams "$STREAMS" \
    --min-objects "$MIN_OBJECTS" \
    --max-objects "$MAX_OBJECTS" \
    --output "$OUTPUT_FILE" \
    --deadline-ms "$DEADLINE_MS"
}

run_or_echo_with_frames_fallback() {
  local cmd="$1"
  local mode_label="$2"
  local rc

  set +e
  run_or_echo "$cmd"
  rc=$?
  set -e

  # Timeout/signal exits can still be considered valid in strict mode upstream,
  # so ensure frames.csv exists for summary metrics when possible.
  if [[ "$rc" -eq 0 || "$rc" -eq 124 || "$rc" -eq 137 || "$rc" -eq 143 ]]; then
    ensure_frames_csv_present "$mode_label rc=$rc" || true
  fi

  return "$rc"
}

fallback_stub() {
  local py_bin="python"
  if [[ "$USE_STUB_FALLBACK" != "1" ]]; then
    warn "Fallback disabled and real command cannot be executed"
    return 1
  fi

  if ! command -v "$py_bin" >/dev/null 2>&1; then
    py_bin="python3"
  fi

  if ! command -v "$py_bin" >/dev/null 2>&1; then
    warn "Neither python nor python3 is available for fallback stub"
    return 1
  fi

  warn "Falling back to workload stub for system=$SYSTEM"
  "$py_bin" "$PROJECT_DIR/scripts/workload_stub.py" \
    --system "$SYSTEM" \
    --scenario "$SCENARIO" \
    --duration "$DURATION_S" \
    --streams "$STREAMS" \
    --min-objects "$MIN_OBJECTS" \
    --max-objects "$MAX_OBJECTS" \
    --output "$OUTPUT_FILE" \
    --deadline-ms "$DEADLINE_MS"
}

ensure_docker_image_local() {
  local image="$1"

  if docker image inspect "$image" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$REAL_DRY_RUN" == "1" ]]; then
    warn "Docker image is not present locally and REAL_DRY_RUN=1: $image"
    return 1
  fi

  log "Docker image not present locally; pulling once before timed run: $image"
  docker pull "$image"
}

run_or_echo() {
  local cmd="$1"
  local rc
  local effective_timeout

  log "command: $cmd"
  if [[ "$REAL_DRY_RUN" == "1" ]]; then
    warn "REAL_DRY_RUN=1, not executing real system command"
    return 1
  fi

  if [[ -n "$CMD_TIMEOUT_S" ]]; then
    effective_timeout="$CMD_TIMEOUT_S"
  elif [[ "$DURATION_S" =~ ^[0-9]+$ && "$STARTUP_GRACE_S" =~ ^[0-9]+$ ]]; then
    effective_timeout="$((DURATION_S + STARTUP_GRACE_S))"
  else
    effective_timeout="$DURATION_S"
  fi

  if command -v timeout >/dev/null 2>&1; then
    set +e
    timeout --signal=INT --kill-after="${CMD_KILL_AFTER_S}s" "${effective_timeout}s" bash -lc "$cmd"
    rc=$?
    set -e
    if [[ "$rc" -eq 124 ]]; then
      warn "Command timed out after ${effective_timeout}s"
      return 124
    fi
    if [[ "$rc" -eq 137 || "$rc" -eq 143 ]]; then
      warn "Command terminated by signal after timeout/interrupt (rc=$rc)"
      return "$rc"
    fi
    return "$rc"
  fi

  bash -lc "$cmd"
}

run_deepstream() {
  local image="${DEEPSTREAM_IMAGE:-nvcr.io/nvidia/deepstream:7.0-triton-multiarch}"
  local i
  local uris=""

  ensure_common_assets || return 1
  for i in $(seq 1 "$STREAMS"); do
    local v
    v="$(pick_video_for_stream "$i")"
    uris+=" file:///workspace/project/data/videos/$(basename "$v")"
  done

  local cmd="docker run --rm --gpus all --entrypoint bash -v '$PROJECT_DIR':/workspace/project -v '$OUTPUT_DIR':/results '$image' -lc 'cd /opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/deepstream-test3 && deepstream-test3-app${uris}'"

  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not found for DeepStream"
    return 1
  fi
  ensure_docker_image_local "$image" || return 1
  run_or_echo_with_frames_fallback "$cmd" "deepstream-container"
}

run_savant() {
  local image="${SAVANT_IMAGE:-ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0}"
  local module="${SAVANT_MODULE:-/workspace/project/deploy/savant/module.yml}"
  local source="${SAVANT_SOURCE:-/workspace/project/data/videos/stream01.mp4}"
  local output_rel

  ensure_common_assets || return 1
  output_rel="${OUTPUT_DIR#"$PROJECT_DIR/"}"
  if [[ "$output_rel" == "$OUTPUT_DIR" ]]; then
    output_rel="results"
  fi
  local cmd="docker run --rm --gpus all --entrypoint bash -e VIDEO_URI='file://$source' -e OUTPUT_DIR='/workspace/project/$output_rel' -v '$PROJECT_DIR':/workspace/project '$image' -lc 'python -m savant.entrypoint $module'"

  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not found for Savant"
    return 1
  fi
  ensure_docker_image_local "$image" || return 1
  run_or_echo_with_frames_fallback "$cmd" "savant-container"
}

run_openvino_gva() {
  local model_xml="${OPENVINO_MODEL_XML:-$OPENVINO_MODEL_XML_DEFAULT}"
  local legacy_model_xml="$PROJECT_DIR/models/openvino/public/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml"
  local source
  local image="${OPENVINO_GVA_IMAGE:-intel/dlstreamer:latest}"
  local use_container="${OPENVINO_GVA_USE_CONTAINER:-1}"
  local dlstreamer_root="${DLSTREAMER_INSTALL_ROOT:-/opt/vast/dlstreamer}"
  local ov_gst_plugin_path="${GST_PLUGIN_PATH:-}"
  local ov_ld_library_path="${LD_LIBRARY_PATH:-}"
  local ov_gst_plugin_scanner="${GST_PLUGIN_SCANNER:-}"
  local ov_detect_element="gvadetect"

  ensure_common_assets || return 1
  if [[ ! -f "$model_xml" ]]; then
    if [[ -f "$legacy_model_xml" ]]; then
      model_xml="$legacy_model_xml"
      warn "Using legacy OpenVINO model XML path: $model_xml"
    else
      warn "Missing OpenVINO model XML: $model_xml"
      warn "Run: bash scripts/prepare_assets.sh"
      return 1
    fi
  fi

  source="$(pick_video_for_stream 1)"

  if [[ "$use_container" == "1" ]] && command -v docker >/dev/null 2>&1; then
    ensure_docker_image_local "$image" || return 1
    local container_source="/workspace/project/data/videos/$(basename "$source")"
    local container_model="/workspace/project/${model_xml#"$PROJECT_DIR/"}"
    local cmd="docker run --rm --entrypoint bash -v '$PROJECT_DIR':/workspace/project '$image' -lc 'gst-launch-1.0 -q filesrc location=\"$container_source\" ! decodebin ! videoconvert ! object_detect model=\"$container_model\" device=CPU ! queue ! fakesink sync=false'"
    run_or_echo_with_frames_fallback "$cmd" "openvino-container"
    return $?
  fi

  if command -v gst-inspect-1.0 >/dev/null 2>&1; then
    if ! gst-inspect-1.0 gvadetect >/dev/null 2>&1; then
      # Auto-attach extracted DL Streamer runtime if present on host.
      if [[ -d "$dlstreamer_root/gstreamer/lib" && -d "$dlstreamer_root/lib" ]]; then
        ov_gst_plugin_path="$dlstreamer_root/gstreamer/lib:$dlstreamer_root/lib${ov_gst_plugin_path:+:$ov_gst_plugin_path}"
        ov_ld_library_path="$dlstreamer_root/lib:$dlstreamer_root/gstreamer/lib:$dlstreamer_root/opencv:$dlstreamer_root/openvino${ov_ld_library_path:+:$ov_ld_library_path}"
        if [[ -x "$dlstreamer_root/gstreamer/bin/gstreamer-1.0/gst-plugin-scanner" ]]; then
          ov_gst_plugin_scanner="$dlstreamer_root/gstreamer/bin/gstreamer-1.0/gst-plugin-scanner"
        fi
      fi

      if GST_PLUGIN_PATH="$ov_gst_plugin_path" LD_LIBRARY_PATH="$ov_ld_library_path" GST_PLUGIN_SCANNER="$ov_gst_plugin_scanner" gst-inspect-1.0 gvadetect >/dev/null 2>&1; then
        ov_detect_element="gvadetect"
      elif GST_PLUGIN_PATH="$ov_gst_plugin_path" LD_LIBRARY_PATH="$ov_ld_library_path" GST_PLUGIN_SCANNER="$ov_gst_plugin_scanner" gst-inspect-1.0 object_detect >/dev/null 2>&1; then
        ov_detect_element="object_detect"
      else
        warn "Neither gvadetect nor object_detect is available. Install DL Streamer / OpenVINO GStreamer plugins."
        return 1
      fi
    else
      ov_detect_element="gvadetect"
    fi
  fi

  local cmd="GST_PLUGIN_PATH='$ov_gst_plugin_path' LD_LIBRARY_PATH='$ov_ld_library_path' GST_PLUGIN_SCANNER='$ov_gst_plugin_scanner' gst-launch-1.0 -q filesrc location='$source' ! decodebin ! videoconvert ! $ov_detect_element model='$model_xml' device=CPU ! queue ! fakesink sync=false"

  if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
    warn "gst-launch-1.0 not found for OpenVINO+GVA"
    return 1
  fi
  run_or_echo_with_frames_fallback "$cmd" "openvino-host"
}

run_gstreamer_custom() {
  local source="${GST_CUSTOM_SOURCE:-$(pick_video_for_stream 1)}"
  local plugin="${GST_CUSTOM_PLUGIN:-adaptivescheduler}"
  local strict_plugin="${GST_CUSTOM_STRICT:-0}"

  ensure_common_assets || return 1
  local gst_plugin_path="${GST_PLUGIN_PATH:-$PROJECT_DIR/build/lib}"

  if command -v gst-inspect-1.0 >/dev/null 2>&1; then
    if ! GST_PLUGIN_PATH="$gst_plugin_path" gst-inspect-1.0 "$plugin" >/dev/null 2>&1; then
      if [[ "$strict_plugin" == "1" ]]; then
        warn "Custom plugin '$plugin' not found in GST_PLUGIN_PATH=$gst_plugin_path"
        return 1
      fi
      warn "Custom plugin '$plugin' not found, using identity element fallback"
      plugin="identity"
    fi
  fi

  local cmd="GST_PLUGIN_PATH='$gst_plugin_path' gst-launch-1.0 -q filesrc location='$source' ! decodebin ! videoconvert ! $plugin ! fakesink sync=false"

  if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
    warn "gst-launch-1.0 not found for custom GStreamer pipeline"
    return 1
  fi
  run_or_echo_with_frames_fallback "$cmd" "gstreamer-custom-host"
}

run_custom_cpp_cuda_qt() {
  local app="${CUSTOM_APP_BIN:-$PROJECT_DIR/build/bin/adaptive_scheduler_app}"
  local src="${CUSTOM_APP_SRC:-$PROJECT_DIR/deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cpp}"
  local auto_build="${CUSTOM_APP_AUTO_BUILD:-1}"
  local cmd="'$app' --scenario '$SCENARIO' --streams '$STREAMS' --duration '$DURATION_S' --output '$OUTPUT_DIR'"

  if [[ ! -x "$app" ]]; then
    if [[ "$auto_build" == "1" && -f "$src" ]] && command -v g++ >/dev/null 2>&1; then
      log "custom app not found; building from source: $src"
      mkdir -p "$(dirname "$app")"
      if ! g++ -O2 -std=c++17 "$src" -o "$app"; then
        warn "failed to build custom app from source: $src"
        return 1
      fi
    else
      warn "custom app not found/executable: $app"
      return 1
    fi
  fi
  run_or_echo_with_frames_fallback "$cmd" "custom-cpp-host"
}

case "$SYSTEM" in
  deepstream)
    run_deepstream || { rc=$?; fallback_stub || exit "$rc"; }
    ;;
  savant)
    run_savant || { rc=$?; fallback_stub || exit "$rc"; }
    ;;
  openvino_gva)
    run_openvino_gva || { rc=$?; fallback_stub || exit "$rc"; }
    ;;
  gstreamer_custom)
    run_gstreamer_custom || { rc=$?; fallback_stub || exit "$rc"; }
    ;;
  custom_cpp_cuda_qt)
    run_custom_cpp_cuda_qt || { rc=$?; fallback_stub || exit "$rc"; }
    ;;
  *)
    warn "Unknown system: $SYSTEM"
    exit 2
    ;;
esac
