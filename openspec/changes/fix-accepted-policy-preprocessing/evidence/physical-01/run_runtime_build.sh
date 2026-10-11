#!/usr/bin/env bash
# Rebuild only runtime x4 on fresh tags; retain canonical images and base producers.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/recipe_common.sh"
expected_commit="${1:?exact frozen repair build commit required}"
assert_frozen_root "$expected_commit"
assert_plain_file "$NATIVE"
assert_plain_file "$BASE/native-b/native_probe.freeze.json"
assert_plain_file "$WORKER"
cmp "$NATIVE" "$BASE/native-b/native_probe.freeze.json"
[[ "$(sha256sum "$NATIVE" | cut -d ' ' -f 1)" == 57f1a9f30c345c930a1ddff06dc51fdfebfa570c1651971d468d115d91d6ece0 ]]
[[ "$(sha256sum "$WORKER" | cut -d ' ' -f 1)" == 5509b370821e8881f65f78dd1f61714fd908780eb50220a1d32c2d8936f5b554 ]]
control="$BASE/runtime-build-control"
runtime="$BASE/runtime_images"
[[ ! -e "$control" && ! -e "$runtime" ]]
mkdir -m 700 "$control" "$runtime"
set -o noclobber
printf '%s\n' "$expected_commit" > "$control/expected-commit.txt"
docker ps --no-trunc > "$control/containers.before.txt"
[[ -z "$(docker ps -q)" ]]
gpu_query="$(command -v nvidia-smi)"
[[ -x "$gpu_query" ]]
"$gpu_query" --query-compute-apps=pid --format=csv,noheader > "$control/gpu-compute-pids.before.txt"
[[ ! -s "$control/gpu-compute-pids.before.txt" ]]
"$PY" -B - > "$control/worker-process-preflight.json" <<'PY'
import json, re, subprocess
output = subprocess.run(["/usr/bin/ps", "-eo", "pid=,args="], check=True,
                        capture_output=True, text=True).stdout
pattern = re.compile(
    r"(?:^|/)(?:run_ci_checks|checkpoint_[A-Za-z0-9_]*(?:pilot|runtime)[A-Za-z0-9_]*|"
    r"publication_qualification_operational_owner[A-Za-z0-9_]*|"
    r"publication_policy_qualification_pilot_executor[A-Za-z0-9_]*|"
    r"publication_guardian[A-Za-z0-9_]*|"
    r"full_publication_[A-Za-z0-9_]*(?:orchestrator|guardian|verifier)[A-Za-z0-9_]*)\.py(?:\s|$)|"
    r"(?:^|[/\s])vast_[A-Za-z0-9_]*(?:runtime|worker)(?:\s|$)"
)
active = [line.strip() for line in output.splitlines() if pattern.search(line)]
print(json.dumps({"competing_worker_or_verifier_processes": active, "passed": not active}, sort_keys=True))
assert not active, "competing worker/verifier process is active"
PY
"$PY" -B "$ROOT/scripts/publication_image_build_v1.py" plan \
  --project-root "$ROOT" --registry "$ROOT/configs/publication_image_build_v1.json" \
  > "$control/native-worker.plan.json"
"$PY" -B - "$ROOT" "$NATIVE" "$WORKER" "$control/native-worker.plan.json" \
  > "$control/native-worker.compare.json" <<'PY'
import json, subprocess, sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from publication_image_build_v1 import load_publication_image_freeze_receipt
native = load_publication_image_freeze_receipt(sys.argv[2])
worker = load_publication_image_freeze_receipt(sys.argv[3])
plan = json.load(open(sys.argv[4], encoding="utf-8"))
assert native["registry_sha256"] == worker["registry_sha256"] == plan["registry_sha256"]
rows = native["images"] + worker["images"]
assert {row["name"] for row in rows} == {row["name"] for row in plan["images"]}
fields = ("source_set_sha256", "dependency_set_sha256", "build_context_sha256")
for row in rows:
    expected = next(value for value in plan["images"] if value["name"] == row["name"])
    assert all(row[key] == expected[key] for key in fields), row["name"]
images = sorted({row[key] for row in rows for key in ("image_id", "base_image_id", "build_image_id")})
live = []
for image in images:
    observed = subprocess.run(["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", image],
                              check=True, capture_output=True, text=True).stdout.strip()
    assert observed == image
    live.append({"image_id": image, "live_image_id": observed})
print(json.dumps({"all_five_source_dependency_context_hashes_equal": True,
                  "registry_sha256": plan["registry_sha256"], "live_images": live}, sort_keys=True))
PY

canonical_snapshot() {
  local system ref suffix
  for system in deepstream savant openvino_gva gstreamer_custom; do
    ref="$(runtime_reference "$system")"
    ref="${ref%:*}:materialized"
    for suffix in '' -determinism-a -determinism-b; do
      printf '%s ' "$ref$suffix"
      docker image inspect "$ref$suffix" --format '{{.Id}}' 2>/dev/null || printf 'MISSING\n'
    done
  done
}
canonical_snapshot > "$control/canonical-tags.before.txt"
for system in deepstream savant openvino_gva gstreamer_custom; do
  ref="$(runtime_reference "$system")"
  for suffix in '' -determinism-a -determinism-b; do
    if docker image inspect "$ref$suffix" >/dev/null 2>&1; then
      printf 'fresh runtime tag already exists: %s\n' "$ref$suffix" >&2
      exit 3
    fi
  done
done
docker info --format '{{json .}}' > "$control/docker-info.before.json"
docker version --format '{{json .}}' > "$control/docker-version.before.json"
df -B1 --output=target,avail / /mnt/c /mnt/e /var/tmp > "$control/disk.before.txt"
date -u +%FT%TZ > "$control/started.txt"
set +e
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy \
  VAST_DEEPSTREAM_RUNTIME_IMAGE="$(runtime_reference deepstream)" \
  VAST_SAVANT_RUNTIME_IMAGE="$(runtime_reference savant)" \
  VAST_OPENVINO_GVA_RUNTIME_IMAGE="$(runtime_reference openvino_gva)" \
  VAST_GSTREAMER_RUNTIME_IMAGE="$(runtime_reference gstreamer_custom)" \
  "$PY" -B "$ROOT/scripts/build_publication_runtime_images_after_refreeze_v1.py" build \
    --project-root "$ROOT" --native-receipt "$NATIVE" --artifact-dir "$runtime" \
    > "$control/stdout.log" 2> "$control/stderr.log"
rc=$?
set -e
printf '%s\n' "$rc" > "$control/rc.txt"
date -u +%FT%TZ > "$control/finished.txt"
canonical_snapshot > "$control/canonical-tags.after.txt"
cmp "$control/canonical-tags.before.txt" "$control/canonical-tags.after.txt"
docker info --format '{{json .}}' > "$control/docker-info.after.json"
docker version --format '{{json .}}' > "$control/docker-version.after.json"
df -B1 --output=target,avail / /mnt/c /mnt/e /var/tmp > "$control/disk.after.txt"
assert_frozen_root "$expected_commit"
exit "$rc"
