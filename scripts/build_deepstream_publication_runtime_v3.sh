#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
base_image="nvcr.io/nvidia/deepstream@sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
expected_base_id="${VAST_DEEPSTREAM_BASE_IMAGE_ID:-sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759}"
image_ref="${VAST_DEEPSTREAM_RUNTIME_IMAGE:-vast/deepstream-publication-runtime-v3:materialized}"
first_ref="${image_ref}-determinism-a"
second_ref="${image_ref}-determinism-b"
source_date_epoch="1722470400"
source_allowlist="deploy/deepstream/checkpoint/runtime-source-allowlist.txt"
dependency_allowlist="deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt"

cd "$project_root"
/usr/bin/python3 -B deploy/deepstream/checkpoint/validate_runtime_source_closure_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist"
mapfile -t runtime_sources < "$source_allowlist"
mapfile -t runtime_dependencies < "$dependency_allowlist"

assert_exact_base_image() {
  local observed_base_id
  observed_base_id="$(docker image inspect "$base_image" --format '{{.Id}}')"
  if [[ "$observed_base_id" != "$expected_base_id" ]]; then
    echo "pinned DeepStream base image ID drifted" >&2
    exit 2
  fi
}
assert_exact_base_image

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

build_context="$(mktemp -d /tmp/vast-deepstream-publication-v3.XXXXXXXX)"
readonly build_context
cleanup_build_context() {
  if [[ "$(dirname -- "$build_context")" != /tmp \
     || "$(basename -- "$build_context")" != vast-deepstream-publication-v3.* ]]; then
    echo "refusing unsafe DeepStream build-context cleanup" >&2
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
  "$build_context/deploy/deepstream/checkpoint/validate_runtime_source_closure_v3.py" \
  --project-root "$build_context" \
  --manifest "$build_context/$source_allowlist"
context_source_sha256="$(compute_runtime_source_sha256 "$build_context")"
context_bundle_sha256="$(compute_runtime_bundle_sha256 "$build_context")"
if [[ "$context_source_sha256" != "$runtime_source_sha256" \
   || "$context_bundle_sha256" != "$runtime_bundle_sha256" ]]; then
  echo "DeepStream exact build-context identity drifted" >&2
  exit 2
fi

build_one() {
  local target="$1"
  assert_exact_base_image
  DOCKER_BUILDKIT=1 SOURCE_DATE_EPOCH="$source_date_epoch" \
    docker buildx build \
      --no-cache \
      --pull=false \
      --network=none \
      --provenance=false \
      --sbom=false \
      --output "type=docker,rewrite-timestamp=true,unpack=false" \
      --build-arg "BASE_IMAGE=$base_image" \
      --build-arg "SOURCE_DATE_EPOCH=$source_date_epoch" \
      --build-arg "VAST_RUNTIME_SOURCE_SHA256=$runtime_source_sha256" \
      --build-arg "VAST_RUNTIME_BUNDLE_SHA256=$runtime_bundle_sha256" \
      --tag "$target" \
      --file "$build_context/deploy/deepstream/checkpoint/Dockerfile.runtime" \
      "$build_context"
  assert_exact_base_image
}

build_one "$first_ref"
build_one "$second_ref"

/usr/bin/python3 -B deploy/deepstream/checkpoint/validate_runtime_source_closure_v3.py \
  --project-root "$project_root" \
  --manifest "$project_root/$source_allowlist"
post_build_source_sha256="$(compute_runtime_source_sha256 "$project_root")"
post_build_bundle_sha256="$(compute_runtime_bundle_sha256 "$project_root")"
if [[ "$post_build_source_sha256" != "$runtime_source_sha256" ]]; then
  echo "DeepStream runtime source changed during build" >&2
  exit 2
fi
if [[ "$post_build_bundle_sha256" != "$runtime_bundle_sha256" ]]; then
  echo "DeepStream runtime bundle changed during build" >&2
  exit 2
fi
if [[ "$(compute_runtime_source_sha256 "$build_context")" != "$runtime_source_sha256" \
   || "$(compute_runtime_bundle_sha256 "$build_context")" != "$runtime_bundle_sha256" ]]; then
  echo "DeepStream exact build context changed during build" >&2
  exit 2
fi

first_id="$(docker image inspect "$first_ref" --format '{{.Id}}')"
second_id="$(docker image inspect "$second_ref" --format '{{.Id}}')"
if [[ "$first_id" != "$second_id" ]]; then
  echo "deterministic DeepStream image IDs differ: $first_id != $second_id" >&2
  exit 2
fi
docker tag "$first_id" "$image_ref"
image_id="$first_id"
entrypoint="$(docker image inspect "$image_id" --format '{{json .Config.Entrypoint}}')"
abi="$(docker image inspect "$image_id" --format '{{index .Config.Labels "org.vast.publication-runtime-abi"}}')"
source_label="$(docker image inspect "$image_id" --format '{{index .Config.Labels "org.vast.runtime-source-sha256"}}')"
bundle_label="$(docker image inspect "$image_id" --format '{{index .Config.Labels "org.vast.runtime-dependency-set-sha256"}}')"
created="$(docker image inspect "$image_id" --format '{{.Created}}')"
created_epoch="$(date -u -d "$created" +%s)"
if [[ "$entrypoint" != '["/usr/local/bin/vast_deepstream_publication_runtime_v3"]' \
   || "$abi" != '3' \
   || "$source_label" != "$runtime_source_sha256" \
   || "$bundle_label" != "$runtime_bundle_sha256" \
   || "$created_epoch" != "$source_date_epoch" ]]; then
  echo "materialized DeepStream runtime image identity validation failed" >&2
  exit 2
fi

docker run --rm --network none \
  --entrypoint /usr/local/bin/vast_deepstream_publication_runtime_v3 \
  "$image_id" --help >/dev/null

repo_digests="$(docker image inspect "$image_id" --format '{{json .RepoDigests}}')"
printf 'image_ref=%s\nimage_id=%s\nruntime_source_sha256=%s\n' \
  "$image_ref" "$image_id" "$runtime_source_sha256"
printf 'runtime_bundle_sha256=%s\nrepo_digests=%s\n' \
  "$runtime_bundle_sha256" "$repo_digests"
