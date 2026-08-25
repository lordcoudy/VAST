#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
base_image="vast/openvino-native-probe@sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1"
expected_base_id="sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1"
image_ref="${VAST_GSTREAMER_RUNTIME_IMAGE:-vast/gstreamer-custom-publication-runtime-v3:materialized}"
first_ref="${image_ref}-determinism-a"
second_ref="${image_ref}-determinism-b"
source_date_epoch="0"

cd "$project_root"
source_allowlist="deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"
dependency_allowlist="deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt"
build_context_allowlist="deploy/gstreamer_custom/publication/runtime-build-context-allowlist.txt"
/usr/bin/python3 \
  deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist"
mapfile -t runtime_sources < "$source_allowlist"
mapfile -t runtime_dependencies < "$dependency_allowlist"
mapfile -t build_context_sources < "$build_context_allowlist"
native_probe_sources=()
for source in "${runtime_sources[@]}"; do
  if [[ "$source" == deploy/native_gst_probe/* ]]; then
    native_probe_sources+=("$source")
  fi
done

observed_base_id="$(docker image inspect "$base_image" --format '{{.Id}}')"
[[ "$observed_base_id" == "$expected_base_id" ]] || {
  echo "pinned GStreamer Custom base image ID drifted" >&2
  exit 2
}

compute_runtime_source_sha256() {
  local root="$1"
  (cd "$root" && sha256sum "${runtime_sources[@]}" | sha256sum | cut -d' ' -f1)
}

compute_native_source_sha256() {
  local root="$1"
  (cd "$root" && sha256sum "${native_probe_sources[@]}" | sha256sum | cut -d' ' -f1)
}

compute_dependency_set_sha256() {
  local root="$1"
  (cd "$root" && sha256sum "${runtime_dependencies[@]}" | sha256sum | cut -d' ' -f1)
}

compute_build_context_inputs_sha256() {
  local root="$1"
  (cd "$root" && sha256sum "${build_context_sources[@]}" | sha256sum | cut -d' ' -f1)
}

runtime_source_sha256="$(compute_runtime_source_sha256 "$project_root")"
native_probe_source_sha256="$(compute_native_source_sha256 "$project_root")"
dependency_set_sha256="$(compute_dependency_set_sha256 "$project_root")"
build_context_inputs_sha256="$(compute_build_context_inputs_sha256 "$project_root")"

build_context="$(mktemp -d /tmp/vast-gstreamer-custom-publication-v3.XXXXXXXX)"
readonly build_context
cleanup_build_context() {
  if [[ "$(dirname -- "$build_context")" != /tmp \
     || "$(basename -- "$build_context")" != vast-gstreamer-custom-publication-v3.* ]]; then
    echo "refusing unsafe GStreamer Custom build-context cleanup" >&2
    return 2
  fi
  rm -rf -- "$build_context"
}
trap cleanup_build_context EXIT

context_materialization="$(
  /usr/bin/python3 -B scripts/materialize_runtime_build_context_v3.py \
    --project-root "$project_root" \
    --manifest "$project_root/$source_allowlist" \
    --manifest "$project_root/$dependency_allowlist" \
    --manifest "$project_root/$build_context_allowlist" \
    --source-date-epoch "$source_date_epoch" \
    --output-dir "$build_context"
)"
/usr/bin/python3 -B \
  "$build_context/deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py" \
  --project-root "$build_context" \
  --manifest "$build_context/$source_allowlist"
context_source_sha256="$(compute_runtime_source_sha256 "$build_context")"
context_native_sha256="$(compute_native_source_sha256 "$build_context")"
context_dependency_sha256="$(compute_dependency_set_sha256 "$build_context")"
context_inputs_sha256="$(compute_build_context_inputs_sha256 "$build_context")"
if [[ "$context_source_sha256" != "$runtime_source_sha256" \
   || "$context_native_sha256" != "$native_probe_source_sha256" \
   || "$context_dependency_sha256" != "$dependency_set_sha256" \
   || "$context_inputs_sha256" != "$build_context_inputs_sha256" ]]; then
  echo "GStreamer Custom exact build-context identity drifted" >&2
  exit 2
fi

build_one() {
  local target="$1"
  DOCKER_BUILDKIT=1 SOURCE_DATE_EPOCH="$source_date_epoch" docker build \
    --no-cache \
    --pull=false \
    --network=none \
    --provenance=false \
    --sbom=false \
    --build-arg "BASE_IMAGE=$base_image" \
    --build-arg "SOURCE_DATE_EPOCH=$source_date_epoch" \
    --build-arg "VAST_RUNTIME_SOURCE_SHA256=$runtime_source_sha256" \
    --build-arg "VAST_NATIVE_PROBE_SOURCE_SHA256=$native_probe_source_sha256" \
    --build-arg "VAST_DEPENDENCY_SET_SHA256=$dependency_set_sha256" \
    --tag "$target" \
    --file "$build_context/deploy/gstreamer_custom/publication/Dockerfile" \
    "$build_context"
}

build_one "$first_ref"
build_one "$second_ref"
/usr/bin/python3 -B deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist"
if [[ "$(compute_runtime_source_sha256 "$project_root")" != "$runtime_source_sha256" \
   || "$(compute_native_source_sha256 "$project_root")" != "$native_probe_source_sha256" \
   || "$(compute_dependency_set_sha256 "$project_root")" != "$dependency_set_sha256" \
   || "$(compute_build_context_inputs_sha256 "$project_root")" != "$build_context_inputs_sha256" ]]; then
  echo "GStreamer Custom workspace inputs changed during build" >&2
  exit 2
fi
if [[ "$(compute_runtime_source_sha256 "$build_context")" != "$runtime_source_sha256" \
   || "$(compute_native_source_sha256 "$build_context")" != "$native_probe_source_sha256" \
   || "$(compute_dependency_set_sha256 "$build_context")" != "$dependency_set_sha256" \
   || "$(compute_build_context_inputs_sha256 "$build_context")" != "$build_context_inputs_sha256" ]]; then
  echo "GStreamer Custom exact build context changed during build" >&2
  exit 2
fi
first_id="$(docker image inspect "$first_ref" --format '{{.Id}}')"
second_id="$(docker image inspect "$second_ref" --format '{{.Id}}')"
[[ "$first_id" == "$second_id" ]] || {
  echo "deterministic image IDs differ: $first_id != $second_id" >&2
  exit 2
}
docker tag "$first_id" "$image_ref"

entrypoint="$(docker image inspect "$first_id" --format '{{json .Config.Entrypoint}}')"
user="$(docker image inspect "$first_id" --format '{{.Config.User}}')"
abi="$(docker image inspect "$first_id" --format '{{index .Config.Labels "org.vast.publication-runtime-abi"}}')"
source_label="$(docker image inspect "$first_id" --format '{{index .Config.Labels "org.vast.runtime-source-sha256"}}')"
native_source_label="$(docker image inspect "$first_id" --format '{{index .Config.Labels "org.vast.native_probe.source_sha"}}')"
dependency_label="$(docker image inspect "$first_id" --format '{{index .Config.Labels "org.vast.runtime-dependency-set-sha256"}}')"
created="$(docker image inspect "$first_id" --format '{{.Created}}')"
[[ "$entrypoint" == '["/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3"]' \
   && "$user" == 'dlstreamer' \
   && "$abi" == '3' \
   && "$source_label" == "$runtime_source_sha256" \
   && "$native_source_label" == "$native_probe_source_sha256" \
   && "$dependency_label" == "$dependency_set_sha256" \
   && "$created" == '1970-01-01T00:00:00Z' ]] || {
  echo "materialized GStreamer Custom image projection is invalid" >&2
  exit 2
}

embedded_paths=(
  /usr/local/bin/vast_native_gst_probe
  /usr/local/bin/vast_checkpoint_source
  /opt/vast/share/gstreamer-registry.bin
  /opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so
  /opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so
  /opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so
  /opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so
  /opt/vast/checkpoint/checkpoint_gstreamer_runtime.py
  /opt/vast/checkpoint/checkpoint_gstreamer_custom_container_coordinator_v3.py
  /opt/vast/runtime-source-allowlist.txt
)
embedded_sha256="$(docker run --rm --network none --entrypoint /usr/bin/sha256sum \
  "$first_id" "${embedded_paths[@]}" | sha256sum | cut -d' ' -f1)"
docker run --rm --network none "$first_id" --help >/dev/null

printf 'image_ref=%s\nimage_id=%s\nbase_image_id=%s\nruntime_source_sha256=%s\nnative_probe_source_sha256=%s\ndependency_set_sha256=%s\nembedded_set_sha256=%s\n' \
  "$image_ref" "$first_id" "$expected_base_id" "$runtime_source_sha256" \
  "$native_probe_source_sha256" "$dependency_set_sha256" "$embedded_sha256"
printf 'build_context_materialization=%s\n' "$context_materialization"
printf 'build_context_inputs_sha256=%s\n' "$build_context_inputs_sha256"
