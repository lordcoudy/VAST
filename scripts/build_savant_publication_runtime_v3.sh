#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
base_image="ghcr.io/insight-platform/savant-deepstream@sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
expected_base_id="sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
base_build_ref="ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0"
native_builder="vast/savant-native-probe@sha256:ef70f6fae0558d1d90ae32fc931256bc71169749c15ae00b70a8ca00c0b70513"
expected_native_builder_id="sha256:ef70f6fae0558d1d90ae32fc931256bc71169749c15ae00b70a8ca00c0b70513"
native_builder_build_ref="vast/savant-native-probe:0.5.17-7.0"
image_ref="${VAST_SAVANT_RUNTIME_IMAGE:-vast/savant-publication-runtime-v3:materialized}"
image_manifest="${VAST_SAVANT_RUNTIME_IMAGE_MANIFEST:-$project_root/artifacts/savant_publication_v3/qualification/runtime_image.materialized.json}"
first_ref="${image_ref}-determinism-a"
second_ref="${image_ref}-determinism-b"
source_date_epoch="1722470400"
source_allowlist="deploy/savant/publication/runtime-source-allowlist.txt"
dependency_allowlist="deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt"

cd "$project_root"
/usr/bin/python3 deploy/savant/publication/validate_runtime_source_closure_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist"
mapfile -t runtime_sources < "$source_allowlist"
mapfile -t runtime_dependencies < "$dependency_allowlist"

assert_exact_input_images() {
  local observed_base_digest_id observed_base_tag_id
  local observed_builder_digest_id observed_builder_tag_id
  observed_base_digest_id="$(docker image inspect "$base_image" --format '{{.Id}}')"
  observed_base_tag_id="$(docker image inspect "$base_build_ref" --format '{{.Id}}')"
  observed_builder_digest_id="$(
    docker image inspect "$native_builder" --format '{{.Id}}'
  )"
  observed_builder_tag_id="$(
    docker image inspect "$native_builder_build_ref" --format '{{.Id}}'
  )"
  if [[ "$observed_base_digest_id" != "$expected_base_id" \
     || "$observed_base_tag_id" != "$expected_base_id" ]]; then
    echo "pinned Savant base image/tag ID drifted" >&2
    exit 2
  fi
  if [[ "$observed_builder_digest_id" != "$expected_native_builder_id" \
     || "$observed_builder_tag_id" != "$expected_native_builder_id" ]]; then
    echo "pinned Savant native-builder image/tag ID drifted" >&2
    exit 2
  fi
}
assert_exact_input_images

compute_runtime_source_sha256() {
  local root="$1"
  (cd "$root" && sha256sum "${runtime_sources[@]}" | sha256sum | cut -d' ' -f1)
}

compute_runtime_bundle_sha256() {
  local root="$1"
  (cd "$root" && sha256sum "${runtime_dependencies[@]}" | sha256sum | cut -d' ' -f1)
}

runtime_source_sha256="$(compute_runtime_source_sha256 "$project_root")"
runtime_bundle_sha256="$(compute_runtime_bundle_sha256 "$project_root")"

build_context="$(mktemp -d /tmp/vast-savant-publication-v3.XXXXXXXX)"
readonly build_context
cleanup_build_context() {
  if [[ "$(dirname -- "$build_context")" != /tmp \
     || "$(basename -- "$build_context")" != vast-savant-publication-v3.* ]]; then
    echo "refusing unsafe Savant build-context cleanup" >&2
    return 2
  fi
  rm -rf -- "$build_context"
}
trap cleanup_build_context EXIT

/usr/bin/python3 -B scripts/materialize_runtime_build_context_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist" \
  --manifest "$project_root/$dependency_allowlist" \
  --source-date-epoch "$source_date_epoch" \
  --output-dir "$build_context" >/dev/null
/usr/bin/python3 -B \
  "$build_context/deploy/savant/publication/validate_runtime_source_closure_v3.py" \
  --project-root "$build_context" \
  --manifest "$build_context/$source_allowlist"
context_source_sha256="$(compute_runtime_source_sha256 "$build_context")"
context_bundle_sha256="$(compute_runtime_bundle_sha256 "$build_context")"
if [[ "$context_source_sha256" != "$runtime_source_sha256" \
   || "$context_bundle_sha256" != "$runtime_bundle_sha256" ]]; then
  echo "Savant exact build-context identity drifted" >&2
  exit 2
fi

build_one() {
  local target="$1"
  assert_exact_input_images
  DOCKER_BUILDKIT=1 SOURCE_DATE_EPOCH="$source_date_epoch" \
    docker buildx build \
      --no-cache \
      --network=none \
      --pull=false \
      --provenance=false \
      --output "type=docker,rewrite-timestamp=true,unpack=false" \
      --build-arg "SOURCE_DATE_EPOCH=$source_date_epoch" \
      --build-arg "SAVANT_BASE_IMAGE=$base_build_ref" \
      --build-arg "NATIVE_BUILDER_IMAGE=$native_builder_build_ref" \
      --build-arg "VAST_SAVANT_RUNTIME_SOURCE_SHA256=$runtime_source_sha256" \
      --build-arg "VAST_SAVANT_RUNTIME_BUNDLE_SHA256=$runtime_bundle_sha256" \
      --tag "$target" \
      --file "$build_context/deploy/savant/publication/Dockerfile" \
      "$build_context"
  assert_exact_input_images
}

build_one "$first_ref"
build_one "$second_ref"

/usr/bin/python3 deploy/savant/publication/validate_runtime_source_closure_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist"
post_build_source_sha256="$(compute_runtime_source_sha256 "$project_root")"
post_build_bundle_sha256="$(compute_runtime_bundle_sha256 "$project_root")"
if [[ "$post_build_source_sha256" != "$runtime_source_sha256" ]]; then
  echo "Savant runtime source changed during build" >&2
  exit 2
fi
if [[ "$post_build_bundle_sha256" != "$runtime_bundle_sha256" ]]; then
  echo "Savant runtime bundle changed during build" >&2
  exit 2
fi
if [[ "$(compute_runtime_source_sha256 "$build_context")" != "$runtime_source_sha256" \
   || "$(compute_runtime_bundle_sha256 "$build_context")" != "$runtime_bundle_sha256" ]]; then
  echo "Savant exact build context changed during build" >&2
  exit 2
fi

first_id="$(docker image inspect "$first_ref" --format '{{.Id}}')"
second_id="$(docker image inspect "$second_ref" --format '{{.Id}}')"
if [[ "$first_id" != "$second_id" ]]; then
  echo "deterministic Savant image IDs differ: $first_id != $second_id" >&2
  exit 2
fi
docker tag "$first_id" "$image_ref"
image_id="$first_id"
entrypoint="$(
  docker image inspect "$image_id" --format '{{json .Config.Entrypoint}}'
)"
abi="$(
  docker image inspect "$image_id" \
    --format '{{index .Config.Labels "org.vast.publication-runtime-abi"}}'
)"
source_label="$(
  docker image inspect "$image_id" \
    --format '{{index .Config.Labels "org.vast.savant.runtime-source-sha256"}}'
)"
bundle_label="$(
  docker image inspect "$image_id" \
    --format '{{index .Config.Labels "org.vast.savant.runtime-bundle-sha256"}}'
)"
if [[ "$entrypoint" != '["/usr/local/bin/vast_savant_checkpoint_runtime"]' \
   || "$abi" != 3 \
   || "$source_label" != "$runtime_source_sha256" \
   || "$bundle_label" != "$runtime_bundle_sha256" ]]; then
  echo "materialized Savant runtime image identity validation failed" >&2
  exit 2
fi

docker run --rm --network none "$image_id" arm --help >/dev/null
mkdir -p "$(dirname "$image_manifest")"
python3 -B scripts/checkpoint_savant_runtime_image_materialization_v3.py \
  --image-id "$image_id" \
  --runtime-source-sha256 "$runtime_source_sha256" \
  --runtime-bundle-sha256 "$runtime_bundle_sha256" \
  --output "$image_manifest" >/dev/null
repo_digests="$(
  docker image inspect "$image_id" --format '{{json .RepoDigests}}'
)"
printf 'image_ref=%s\nimage_id=%s\nruntime_source_sha256=%s\n' \
  "$image_ref" "$image_id" "$runtime_source_sha256"
printf 'runtime_bundle_sha256=%s\nrepo_digests=%s\n' \
  "$runtime_bundle_sha256" "$repo_digests"
printf 'runtime_image_manifest=%s\n' "$image_manifest"
