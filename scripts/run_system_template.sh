#!/usr/bin/env bash
set -euo pipefail

# Real command templates for each benchmarked system.

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
HOST_ROLE="${EXPERIMENT_HOST_ROLE:-local}"
PIPELINE_STAGES="${EXPERIMENT_PIPELINE_STAGES:-}"
SCENARIO_JSON="${EXPERIMENT_SCENARIO_JSON:-}"
BENCHMARK_MODE="${BENCHMARK_MODE:-benchmark}"
RUN_ID="${EXPERIMENT_RUN_ID:-unassigned}"
DETECTOR="${ADAPTER_DETECTOR:-$SYSTEM}"
BACKEND="${ADAPTER_BACKEND:-$SYSTEM}"
SCHEDULER_POLICY="${SCHEDULER_POLICY:-static_hybrid}"
QL_HEFT_POLICY_ARTIFACT="${QL_HEFT_POLICY_ARTIFACT:-$PROJECT_DIR/policies/ql_heft_frozen.policy}"
EXPERIMENT_DISTRIBUTED="${EXPERIMENT_DISTRIBUTED:-0}"
RTP_INPUT_PORT="${EXPERIMENT_RTP_INPUT_PORT:-}"
RTP_OUTPUT_HOST="${EXPERIMENT_RTP_OUTPUT_HOST:-}"
RTP_OUTPUT_PORT="${EXPERIMENT_RTP_OUTPUT_PORT:-}"
RTP_PORT_STRIDE="${EXPERIMENT_RTP_PORT_STRIDE:-1}"

REAL_DRY_RUN="${REAL_DRY_RUN:-0}"
STARTUP_GRACE_S="${STARTUP_GRACE_S:-180}"
CMD_TIMEOUT_S="${CMD_TIMEOUT_S:-}"
CMD_KILL_AFTER_S="${CMD_KILL_AFTER_S:-20}"
EXPERIMENT_RUN_SEED="${EXPERIMENT_RUN_SEED:-$RANDOM}"

VIDEO_LAYOUT_DIR="${VIDEO_LAYOUT_DIR:-$PROJECT_DIR/data/videos}"
DATASET_STREAMS_JSON="${DATASET_STREAMS_JSON:-}"
OPENVINO_MODEL_XML_DEFAULT="$PROJECT_DIR/models/openvino/public/intel/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml"
NATIVE_PROBE_BIN="${NATIVE_PROBE_BIN:-$PROJECT_DIR/build/bin/vast_native_gst_probe}"
DEEPSTREAM_NATIVE_PROBE_IMAGE="${DEEPSTREAM_NATIVE_PROBE_IMAGE:-vast/deepstream-native-probe:7.0}"
SAVANT_NATIVE_PROBE_IMAGE="${SAVANT_NATIVE_PROBE_IMAGE:-vast/savant-native-probe:0.5.17-7.0}"
SAVANT_LOCAL_MODULE_DEFAULT="$PROJECT_DIR/deploy/savant/canonical_heterogeneous_module.yml"

log() { echo "[template] $*"; }
warn() { echo "[template][warning] $*" >&2; }

now_ms() {
  local raw
  raw="$(date +%s%3N 2>/dev/null || true)"
  if [[ "$raw" =~ ^[0-9]+$ ]]; then
    printf "%s" "$raw"
    return 0
  fi
  python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

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
    --host-role) HOST_ROLE="$2"; shift 2 ;;
    --pipeline-stages) PIPELINE_STAGES="$2"; shift 2 ;;
    --scenario-json) SCENARIO_JSON="$2"; shift 2 ;;
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

DETECTOR="${ADAPTER_DETECTOR:-$SYSTEM}"
BACKEND="${ADAPTER_BACKEND:-$SYSTEM}"

OUTPUT_DIR="$(dirname "$OUTPUT_FILE")"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
OUTPUT_FILE="$OUTPUT_DIR/$(basename "$OUTPUT_FILE")"

export EXPERIMENT_HOST_ROLE="$HOST_ROLE"
export EXPERIMENT_PIPELINE_STAGES="$PIPELINE_STAGES"
export EXPERIMENT_SCENARIO_JSON="$SCENARIO_JSON"
export MIN_OBJECTS="$MIN_OBJECTS"
export MAX_OBJECTS="$MAX_OBJECTS"
export DEADLINE_MS="$DEADLINE_MS"

log "mode=$BENCHMARK_MODE scenario=$SCENARIO role=$HOST_ROLE stages=${PIPELINE_STAGES:-all} streams=$STREAMS objects=${MIN_OBJECTS}-${MAX_OBJECTS}"

pick_video_for_stream() {
  local idx="$1"
  if [[ -n "$DATASET_STREAMS_JSON" ]]; then
    local py_bin="python3"
    local selected=""
    if ! command -v "$py_bin" >/dev/null 2>&1; then
      py_bin="python"
    fi
    if command -v "$py_bin" >/dev/null 2>&1; then
      selected="$(STREAM_INDEX="$idx" DATASET_STREAMS_JSON="$DATASET_STREAMS_JSON" PROJECT_DIR="$PROJECT_DIR" "$py_bin" -c 'import json, os, pathlib
streams = json.loads(os.environ.get("DATASET_STREAMS_JSON", "[]") or "[]")
if streams:
    idx = max(1, int(os.environ.get("STREAM_INDEX", "1")))
    raw = str(streams[(idx - 1) % len(streams)])
    path = pathlib.Path(raw)
    print(path if path.is_absolute() else pathlib.Path(os.environ["PROJECT_DIR"]) / path)
' 2>/dev/null || true)"
      if [[ -n "$selected" ]]; then
        printf "%s" "$selected"
        return 0
      fi
    fi
  fi
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

ensure_frames_csv_from_runtime() {
  local elapsed_ms="$1"
  local source_video="$2"
  local py_bin="python3"

  if [[ -s "$OUTPUT_FILE" ]]; then
    return 0
  fi

  if [[ "$BENCHMARK_MODE" != "smoke" ]]; then
    warn "Native frames.csv telemetry is required in benchmark mode: $OUTPUT_FILE"
    return 1
  fi

  if ! command -v "$py_bin" >/dev/null 2>&1; then
    py_bin="python"
  fi
  if ! command -v "$py_bin" >/dev/null 2>&1; then
    warn "frames.csv export failed: python runtime is unavailable"
    return 1
  fi

  log "Exporting synthetic smoke-only frame metrics to $OUTPUT_FILE (elapsed=${elapsed_ms}ms, source=$source_video)"
  "$py_bin" "$PROJECT_DIR/scripts/emit_runtime_frames_csv.py" \
    --output "$OUTPUT_FILE" \
    --duration-s "$DURATION_S" \
    --streams "$STREAMS" \
    --elapsed-ms "$elapsed_ms" \
    --source-video "$source_video" \
    --min-objects "$MIN_OBJECTS" \
    --max-objects "$MAX_OBJECTS" \
    --deadline-ms "$DEADLINE_MS" \
    --run-id "$RUN_ID" \
    --detector "$DETECTOR" \
    --backend "$BACKEND"
}

run_with_frames_export() {
  local cmd="$1"
  local source_video="$2"
  local start_ms
  local end_ms
  local elapsed_ms
  local rc

  start_ms="$(now_ms)"
  set +e
  run_or_echo "$cmd"
  rc=$?
  set -e
  end_ms="$(now_ms)"
  elapsed_ms="$((end_ms - start_ms))"

  # Accept controlled timeout/signal exits; run_experiments.py validates those conditions.
  if [[ "$rc" -eq 0 || "$rc" -eq 124 || "$rc" -eq 137 || "$rc" -eq 143 ]]; then
    set +e
    ensure_frames_csv_from_runtime "$elapsed_ms" "$source_video"
    local export_rc=$?
    set -e
    if [[ "$export_rc" -ne 0 ]]; then
      warn "Runtime frame metrics export failed (rc=$export_rc)"
    fi
  fi

  return "$rc"
}

run_deepstream() {
  local image="${DEEPSTREAM_IMAGE:-nvcr.io/nvidia/deepstream:7.0-triton-multiarch}"
  local i
  local uris=""
  local source

  ensure_common_assets || return 1
  source="$(pick_video_for_stream 1)"
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
  run_with_frames_export "$cmd" "$source"
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
  local cmd=""
  local i
  for i in $(seq 1 "$STREAMS"); do
    local stream_source
    stream_source="/workspace/project/data/videos/$(basename "$(pick_video_for_stream "$i")")"
    cmd+="docker run --rm --gpus all --entrypoint bash -e VIDEO_URI='file://$stream_source' -e OUTPUT_DIR='/workspace/project/$output_rel/stream_$i' -v '$PROJECT_DIR':/workspace/project '$image' -lc 'python -m savant.entrypoint $module' & "
  done
  cmd+="wait"

  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not found for Savant"
    return 1
  fi
  ensure_docker_image_local "$image" || return 1
  run_with_frames_export "$cmd" "$source"
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
    local branches=""
    local i
    for i in $(seq 1 "$STREAMS"); do
      container_source="/workspace/project/data/videos/$(basename "$(pick_video_for_stream "$i")")"
      branches+=" filesrc location=\"$container_source\" ! decodebin ! videoconvert ! object_detect model=\"$container_model\" device=CPU ! queue ! fakesink sync=false "
    done
    local cmd="docker run --rm --entrypoint bash -v '$PROJECT_DIR':/workspace/project '$image' -lc 'gst-launch-1.0 -q $branches'"
    run_with_frames_export "$cmd" "$source"
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

  local host_branches=""
  local i
  for i in $(seq 1 "$STREAMS"); do
    host_branches+=" filesrc location='$(pick_video_for_stream "$i")' ! decodebin ! videoconvert ! $ov_detect_element model='$model_xml' device=CPU ! queue ! fakesink sync=false "
  done
  local cmd="GST_PLUGIN_PATH='$ov_gst_plugin_path' LD_LIBRARY_PATH='$ov_ld_library_path' GST_PLUGIN_SCANNER='$ov_gst_plugin_scanner' gst-launch-1.0 -q $host_branches"

  if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
    warn "gst-launch-1.0 not found for OpenVINO+GVA"
    return 1
  fi
  run_with_frames_export "$cmd" "$source"
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

  local branches=""
  local i
  for i in $(seq 1 "$STREAMS"); do
    branches+=" filesrc location='$(pick_video_for_stream "$i")' ! decodebin ! videoconvert ! $plugin ! fakesink sync=false "
  done
  local cmd="GST_PLUGIN_PATH='$gst_plugin_path' gst-launch-1.0 -q $branches"

  if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
    warn "gst-launch-1.0 not found for custom GStreamer pipeline"
    return 1
  fi
  run_with_frames_export "$cmd" "$source"
}

run_custom_cpp_cuda_qt() {
  local app="${CUSTOM_APP_BIN:-$PROJECT_DIR/build/bin/adaptive_scheduler_app}"
  local cmd="QT_QPA_PLATFORM=offscreen '$app' --scenario '$SCENARIO' --streams '$STREAMS' --duration '$DURATION_S' --output '$OUTPUT_DIR' --policy '$SCHEDULER_POLICY' --policy-artifact '$QL_HEFT_POLICY_ARTIFACT' --run-id '$RUN_ID' --detector '$DETECTOR' --backend '$BACKEND' --min-objects '$MIN_OBJECTS' --max-objects '$MAX_OBJECTS' --deadline-ms '$DEADLINE_MS'"
  local source
  source="$(pick_video_for_stream 1)"

  if [[ "$BENCHMARK_MODE" == "smoke" && "${CUSTOM_SMOKE_USE_BINARY:-0}" != "1" ]]; then
    log "Using explicit synthetic custom adapter for smoke mode"
    python3 "$PROJECT_DIR/scripts/custom_app_emitter.py" \
      --scenario "$SCENARIO" \
      --streams "$STREAMS" \
      --duration "$DURATION_S" \
      --output "$OUTPUT_DIR" \
      --run-id "$RUN_ID" \
      --detector "$DETECTOR" \
      --backend "$BACKEND"
    return $?
  fi

  if [[ ! -x "$app" ]]; then
    warn "custom app not found/executable: $app"
    warn "Provide a real implementation via CUSTOM_APP_BIN."
    return 1
  fi
  run_with_frames_export "$cmd" "$source"
}

shell_quote() {
  printf "%q" "$1"
}

project_path_for_runtime() {
  local path="$1"
  if [[ "${NATIVE_PROBE_CONTAINERIZED:-0}" == "1" && "$path" == "$PROJECT_DIR"/* ]]; then
    printf "/workspace/project/%s" "${path#"$PROJECT_DIR/"}"
  else
    printf "%s" "$path"
  fi
}

native_probe_detect_bin() {
  case "$SYSTEM" in
    openvino_gva)
      local model_xml
      model_xml="$(project_path_for_runtime "${OPENVINO_MODEL_XML:-$OPENVINO_MODEL_XML_DEFAULT}")"
      local element="${OPENVINO_GVA_DETECT_ELEMENT:-}"
      if [[ "$REAL_DRY_RUN" != "1" && "${NATIVE_PROBE_CONTAINERIZED:-0}" != "1" && ! -f "$model_xml" ]]; then
        warn "Missing OpenVINO model XML: $model_xml"
        return 1
      fi
      if [[ -z "$element" ]]; then
        if [[ "$REAL_DRY_RUN" == "1" ]]; then
          element="gvadetect"
        elif ! command -v gst-inspect-1.0 >/dev/null 2>&1; then
          warn "OpenVINO strict distributed benchmark requires gst-inspect-1.0 and DL Streamer plugins"
          return 1
        fi
        if [[ "$element" == "gvadetect" ]]; then
          :
        elif gst-inspect-1.0 gvadetect >/dev/null 2>&1; then
          element="gvadetect"
        elif gst-inspect-1.0 object_detect >/dev/null 2>&1; then
          element="object_detect"
        else
          warn "OpenVINO strict distributed benchmark requires gvadetect or object_detect"
          return 1
        fi
      fi
      printf "%s model=%s device=CPU" "$element" "$(shell_quote "$model_xml")"
      ;;
    gstreamer_custom)
      local plugin="${GST_CUSTOM_PLUGIN:-adaptivescheduler}"
      local gst_plugin_path="${GST_PLUGIN_PATH:-$PROJECT_DIR/build/lib}"
      if [[ "$REAL_DRY_RUN" == "1" ]]; then
        printf "%s" "$plugin"
        return 0
      fi
      if ! command -v gst-inspect-1.0 >/dev/null 2>&1; then
        warn "Strict distributed benchmark requires gst-inspect-1.0 for custom GStreamer plugin validation"
        return 1
      fi
      if ! GST_PLUGIN_PATH="$gst_plugin_path" GST_CUSTOM_STRICT=1 gst-inspect-1.0 "$plugin" >/dev/null 2>&1; then
        warn "Strict distributed benchmark requires custom GStreamer plugin '$plugin' in GST_PLUGIN_PATH=$gst_plugin_path"
        return 1
      fi
      printf "%s" "$plugin"
      ;;
    deepstream)
      local config
      config="$(project_path_for_runtime "${DEEPSTREAM_PGIE_CONFIG:-/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_infer_primary.txt}")"
      printf "nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12 ! nvinfer config-file-path=%s ! nvvideoconvert ! video/x-raw" "$(shell_quote "$config")"
      ;;
    savant)
      # The Savant derived image provides a framework module that exposes a GStreamer-compatible detector hook.
      printf "%s" "${SAVANT_CANONICAL_DETECT_BIN:-vast_savant_detect}"
      ;;
    *)
      printf "identity"
      ;;
  esac
}

native_probe_args() {
  local output_dir="$1"
  local detect_bin="$2"
  local runtime_video_layout
  runtime_video_layout="$(project_path_for_runtime "$VIDEO_LAYOUT_DIR")"
  local args=(
    --system "$SYSTEM"
    --role "$HOST_ROLE"
    --stages "$PIPELINE_STAGES"
    --run-id "$RUN_ID"
    --detector "$DETECTOR"
    --backend "$BACKEND"
    --output-dir "$output_dir"
    --duration "$DURATION_S"
    --streams "$STREAMS"
    --video-layout-dir "$runtime_video_layout"
    --detect-bin "$detect_bin"
    --min-objects "$MIN_OBJECTS"
    --max-objects "$MAX_OBJECTS"
  )
  if [[ -n "$RTP_INPUT_PORT" ]]; then
    args+=(--input-port-base "$RTP_INPUT_PORT")
  fi
  if [[ -n "$RTP_OUTPUT_HOST" ]]; then
    args+=(--output-host "$RTP_OUTPUT_HOST")
  fi
  if [[ -n "$RTP_OUTPUT_PORT" ]]; then
    args+=(--output-port-base "$RTP_OUTPUT_PORT")
  fi
  args+=(--port-stride "$RTP_PORT_STRIDE")
  printf " %q" "${args[@]}"
}

native_probe_env_prefix() {
  local env_args=()
  if [[ "$SYSTEM" == "gstreamer_custom" ]]; then
    env_args+=("GST_PLUGIN_PATH=${GST_PLUGIN_PATH:-$PROJECT_DIR/build/lib}" "GST_CUSTOM_STRICT=1")
  fi
  if [[ ${#env_args[@]} -eq 0 ]]; then
    return 0
  fi
  printf "%q " "${env_args[@]}"
}

container_output_dir() {
  if [[ "$OUTPUT_DIR" == "$PROJECT_DIR" ]]; then
    printf "/workspace/project"
  elif [[ "$OUTPUT_DIR" == "$PROJECT_DIR"/* ]]; then
    printf "/workspace/project/%s" "${OUTPUT_DIR#"$PROJECT_DIR/"}"
  else
    warn "Containerized strict probes require OUTPUT_DIR under PROJECT_DIR; using /workspace/project/runs/container_external"
    printf "/workspace/project/runs/container_external"
  fi
}

run_host_native_probe() {
  local detect_bin
  detect_bin="$(native_probe_detect_bin)" || return 1
  if [[ "$REAL_DRY_RUN" != "1" && ! -x "$NATIVE_PROBE_BIN" ]]; then
    warn "Strict native benchmark requires native probe binary: $NATIVE_PROBE_BIN"
    warn "Build it with: cmake -S . -B build/cmake && cmake --build build/cmake --target vast_native_gst_probe"
    return 1
  fi
  local cmd
  cmd="$(native_probe_env_prefix)$(shell_quote "$NATIVE_PROBE_BIN")$(native_probe_args "$OUTPUT_DIR" "$detect_bin")"
  run_or_echo "$cmd"
}

run_container_native_probe() {
  local image="$1"
  local detect_bin
  if [[ "$REAL_DRY_RUN" != "1" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
      warn "docker not found for strict native $SYSTEM probe"
      return 1
    fi
  fi
  if [[ "$REAL_DRY_RUN" != "1" ]] && ! docker image inspect "$image" >/dev/null 2>&1; then
    warn "Strict native $SYSTEM benchmark requires derived native probe image: $image"
    warn "Build images with: bash scripts/build_native_probe_images.sh"
    return 1
  fi
  local container_output
  container_output="$(container_output_dir)"
  local cmd
  local prev_containerized="${NATIVE_PROBE_CONTAINERIZED:-0}"
  NATIVE_PROBE_CONTAINERIZED=1
  if ! detect_bin="$(native_probe_detect_bin)"; then
    NATIVE_PROBE_CONTAINERIZED="$prev_containerized"
    return 1
  fi
  cmd="docker run --rm --network host --gpus all \
    -e EXPERIMENT_RTP_INPUT_PORT='${RTP_INPUT_PORT}' \
    -e EXPERIMENT_RTP_OUTPUT_HOST='${RTP_OUTPUT_HOST}' \
    -e EXPERIMENT_RTP_OUTPUT_PORT='${RTP_OUTPUT_PORT}' \
    -e EXPERIMENT_RTP_PORT_STRIDE='${RTP_PORT_STRIDE}' \
    -e EXPERIMENT_RUN_ID='${RUN_ID}' \
    -e EXPERIMENT_HOST_ROLE='${HOST_ROLE}' \
    -e EXPERIMENT_PIPELINE_STAGES='${PIPELINE_STAGES}' \
    -e ADAPTER_DETECTOR='${DETECTOR}' \
    -e ADAPTER_BACKEND='${BACKEND}' \
    -e DATASET_STREAMS_JSON='${DATASET_STREAMS_JSON}' \
    -e GST_CUSTOM_STRICT='1' \
    -v '$PROJECT_DIR':/workspace/project \
    -w /workspace/project '$image' \
    /usr/local/bin/vast_native_gst_probe$(native_probe_args "$container_output" "$detect_bin")"
  NATIVE_PROBE_CONTAINERIZED="$prev_containerized"
  run_or_echo "$cmd"
}

merge_savant_local_outputs() {
  local py_bin="python3"
  if ! command -v "$py_bin" >/dev/null 2>&1; then
    py_bin="python"
  fi
  if ! command -v "$py_bin" >/dev/null 2>&1; then
    warn "Savant local telemetry merge failed: python runtime is unavailable"
    return 1
  fi
  "$py_bin" "$PROJECT_DIR/deploy/savant/native_probe.py" \
    --merge-local \
    --output-dir "$OUTPUT_DIR" \
    --streams "$STREAMS"
}

run_savant_local_native_probe() {
  local image="${SAVANT_IMAGE:-ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0}"
  local module
  local container_output
  local output_mount=""
  local cmd=""
  local i
  local rc
  local prev_containerized="${NATIVE_PROBE_CONTAINERIZED:-0}"

  if [[ "$OUTPUT_DIR" == "$PROJECT_DIR" ]]; then
    container_output="/workspace/project"
  elif [[ "$OUTPUT_DIR" == "$PROJECT_DIR"/* ]]; then
    container_output="/workspace/project/${OUTPUT_DIR#"$PROJECT_DIR/"}"
  else
    container_output="/results"
    output_mount="-v '$OUTPUT_DIR':/results"
  fi

  NATIVE_PROBE_CONTAINERIZED=1
  module="$(project_path_for_runtime "${SAVANT_LOCAL_MODULE:-$SAVANT_LOCAL_MODULE_DEFAULT}")"
  NATIVE_PROBE_CONTAINERIZED="$prev_containerized"

  if [[ "$REAL_DRY_RUN" != "1" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
      warn "docker not found for strict local Savant probe"
      return 1
    fi
    ensure_docker_image_local "$image" || return 1
  fi

  cmd="set -e; pids=''; "
  for i in $(seq 0 $((STREAMS - 1))); do
    local idx=$((i + 1))
    local stream_source="/workspace/project/data/videos/$(basename "$(pick_video_for_stream "$idx")")"
    cmd+="docker run --rm --gpus all --entrypoint bash \
      -e VIDEO_URI='file://$stream_source' \
      -e VAST_STREAM_ID='$i' \
      -e VAST_NATIVE_OUTPUT_DIR='${container_output}/streams/stream_$i' \
      -e EXPERIMENT_RUN_ID='${RUN_ID}' \
      -e ADAPTER_DETECTOR='${DETECTOR}' \
      -e ADAPTER_BACKEND='${BACKEND}' \
      -e MIN_OBJECTS='${MIN_OBJECTS}' \
      -e MAX_OBJECTS='${MAX_OBJECTS}' \
      -v '$PROJECT_DIR':/workspace/project ${output_mount} \
      -w /workspace/project '$image' \
      -lc 'python -m savant.entrypoint $module' & pids=\"\$pids \$!\"; "
  done
  cmd+="sleep ${DURATION_S}; for pid in \$pids; do kill -INT \$pid >/dev/null 2>&1 || true; done; wait || true"

  set +e
  run_or_echo "$cmd"
  rc=$?
  set -e

  if [[ "$REAL_DRY_RUN" == "1" ]]; then
    return "$rc"
  fi

  if [[ "$rc" -eq 0 || "$rc" -eq 124 || "$rc" -eq 137 || "$rc" -eq 143 ]]; then
    merge_savant_local_outputs || return 1
  fi

  return "$rc"
}

run_savant_framework_native_probe() {
  if [[ "$HOST_ROLE" != "gpu_worker" ]]; then
    run_container_native_probe "$SAVANT_NATIVE_PROBE_IMAGE"
    return $?
  fi
  if [[ "$REAL_DRY_RUN" != "1" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
      warn "docker not found for strict distributed Savant probe"
      return 1
    fi
    if ! docker image inspect "$SAVANT_NATIVE_PROBE_IMAGE" >/dev/null 2>&1; then
      warn "Strict distributed Savant benchmark requires derived native probe image: $SAVANT_NATIVE_PROBE_IMAGE"
      warn "Build images with: bash scripts/build_native_probe_images.sh"
      return 1
    fi
  fi
  local container_output
  local module
  local inner
  local prev_containerized="${NATIVE_PROBE_CONTAINERIZED:-0}"
  container_output="$(container_output_dir)"
  NATIVE_PROBE_CONTAINERIZED=1
  module="$(project_path_for_runtime "${SAVANT_CANONICAL_MODULE:-$PROJECT_DIR/deploy/savant/canonical_distributed_module.yml}")"
  NATIVE_PROBE_CONTAINERIZED="$prev_containerized"
  inner="set -e; pids=''; for i in \$(seq 0 $((STREAMS - 1))); do in_port=\$(( ${RTP_INPUT_PORT:-5600} + i * ${RTP_PORT_STRIDE} )); out_port=\$(( ${RTP_OUTPUT_PORT:-5700} + i * ${RTP_PORT_STRIDE} )); VAST_STREAM_ID=\$i EXPERIMENT_RTP_INPUT_PORT=\$in_port EXPERIMENT_RTP_OUTPUT_PORT=\$out_port VAST_NATIVE_OUTPUT_DIR='${container_output}/streams/stream_'\$i python -m savant.entrypoint ${module} & pids=\"\$pids \$!\"; done; sleep ${DURATION_S}; for pid in \$pids; do kill -INT \$pid >/dev/null 2>&1 || true; done; wait || true"
  local cmd
  cmd="docker run --rm --network host --gpus all \
    -e BENCHMARK_MODE='${BENCHMARK_MODE}' \
    -e DATASET_NAME='${DATASET_NAME:-}' \
    -e DATASET_STREAMS_JSON='${DATASET_STREAMS_JSON}' \
    -e EXPERIMENT_RUN_ID='${RUN_ID}' \
    -e EXPERIMENT_HOST_ROLE='${HOST_ROLE}' \
    -e EXPERIMENT_PIPELINE_STAGES='${PIPELINE_STAGES}' \
    -e EXPERIMENT_RTP_INPUT_PORT='${RTP_INPUT_PORT}' \
    -e EXPERIMENT_RTP_OUTPUT_HOST='${RTP_OUTPUT_HOST}' \
    -e EXPERIMENT_RTP_OUTPUT_PORT='${RTP_OUTPUT_PORT}' \
    -e EXPERIMENT_RTP_PORT_STRIDE='${RTP_PORT_STRIDE}' \
    -e ADAPTER_DETECTOR='${DETECTOR}' \
    -e ADAPTER_BACKEND='${BACKEND}' \
    -e VAST_NATIVE_OUTPUT_DIR='${container_output}' \
    -e VAST_TRACE_EXTENSION_ID='1' \
    -e MIN_OBJECTS='${MIN_OBJECTS}' \
    -e MAX_OBJECTS='${MAX_OBJECTS}' \
    -v '$PROJECT_DIR':/workspace/project \
    -w /workspace/project '$SAVANT_NATIVE_PROBE_IMAGE' \
    bash -lc $(shell_quote "$inner")"
  run_or_echo "$cmd"
}

run_builtin_strict_distributed_adapter() {
  if [[ "$SCENARIO" != "canonical_distributed" ]]; then
    warn "Built-in strict distributed adapters currently support only canonical_distributed"
    return 1
  fi
  case "$SYSTEM" in
    openvino_gva|gstreamer_custom)
      run_host_native_probe
      ;;
    deepstream)
      run_container_native_probe "$DEEPSTREAM_NATIVE_PROBE_IMAGE"
      ;;
    savant)
      run_savant_framework_native_probe
      ;;
    custom_cpp_cuda_qt)
      run_custom_cpp_cuda_qt
      ;;
    *)
      warn "No built-in strict distributed adapter for system=$SYSTEM"
      return 1
      ;;
  esac
}

run_builtin_strict_local_adapter() {
  if [[ "$SCENARIO" != "canonical_heterogeneous" ]]; then
    warn "Built-in strict local benchmark adapters currently support only canonical_heterogeneous"
    return 1
  fi
  case "$SYSTEM" in
    openvino_gva|gstreamer_custom)
      run_host_native_probe
      ;;
    deepstream)
      run_container_native_probe "$DEEPSTREAM_NATIVE_PROBE_IMAGE"
      ;;
    savant)
      run_savant_local_native_probe
      ;;
    custom_cpp_cuda_qt)
      run_custom_cpp_cuda_qt
      ;;
    *)
      warn "No built-in strict local adapter for system=$SYSTEM"
      return 1
      ;;
  esac
}

run_distributed_rtp_smoke() {
  local source
  source="$(pick_video_for_stream 1)"
  ensure_common_assets || return 1
  if ! command -v gst-launch-1.0 >/dev/null 2>&1; then
    warn "gst-launch-1.0 is required for RTP smoke transport"
    return 1
  fi

  case "$HOST_ROLE" in
    edge)
      [[ -n "$RTP_OUTPUT_HOST" && -n "$RTP_OUTPUT_PORT" ]] || return 2
      run_with_frames_export "gst-launch-1.0 -q -e filesrc location='$source' ! qtdemux ! h264parse ! rtph264pay pt=96 config-interval=1 ! udpsink host='$RTP_OUTPUT_HOST' port='$RTP_OUTPUT_PORT'" "$source"
      ;;
    gpu_worker)
      [[ -n "$RTP_INPUT_PORT" && -n "$RTP_OUTPUT_HOST" && -n "$RTP_OUTPUT_PORT" ]] || return 2
      run_with_frames_export "gst-launch-1.0 -q -e udpsrc port='$RTP_INPUT_PORT' caps='application/x-rtp,media=video,encoding-name=H264,payload=96' ! rtph264depay ! h264parse ! rtph264pay pt=96 config-interval=1 ! udpsink host='$RTP_OUTPUT_HOST' port='$RTP_OUTPUT_PORT'" "$source"
      ;;
    aggregator)
      [[ -n "$RTP_INPUT_PORT" ]] || return 2
      run_with_frames_export "gst-launch-1.0 -q -e udpsrc port='$RTP_INPUT_PORT' caps='application/x-rtp,media=video,encoding-name=H264,payload=96' ! rtph264depay ! decodebin ! fakesink sync=false" "$source"
      ;;
    *)
      warn "Unsupported distributed role: $HOST_ROLE"
      return 2
      ;;
  esac
}

run_distributed_adapter() {
  local normalized_system
  local normalized_role
  normalized_system="$(printf "%s" "$SYSTEM" | tr '[:lower:]' '[:upper:]')"
  normalized_role="$(printf "%s" "$HOST_ROLE" | tr '[:lower:]' '[:upper:]')"
  local role_cmd_var="DISTRIBUTED_NATIVE_CMD_${normalized_system}_${normalized_role}"
  local native_cmd="${!role_cmd_var:-${DISTRIBUTED_NATIVE_CMD:-}}"
  if [[ -n "$native_cmd" ]]; then
    run_with_frames_export "$native_cmd" "$(pick_video_for_stream 1)"
    return $?
  fi
  if [[ "$BENCHMARK_MODE" == "benchmark" ]]; then
    run_builtin_strict_distributed_adapter
    return $?
  fi
  warn "Using RTP smoke bridge for system=$SYSTEM role=$HOST_ROLE"
  run_distributed_rtp_smoke
}

if [[ "$EXPERIMENT_DISTRIBUTED" == "1" ]]; then
  run_distributed_adapter
  exit $?
fi

if [[ "$BENCHMARK_MODE" == "benchmark" ]]; then
  run_builtin_strict_local_adapter
  exit $?
fi

case "$SYSTEM" in
  deepstream)
    run_deepstream
    ;;
  savant)
    run_savant
    ;;
  openvino_gva)
    run_openvino_gva
    ;;
  gstreamer_custom)
    run_gstreamer_custom
    ;;
  custom_cpp_cuda_qt)
    run_custom_cpp_cuda_qt
    ;;
  *)
    warn "Unknown system: $SYSTEM"
    exit 2
    ;;
esac
