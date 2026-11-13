#!/usr/bin/env bash
# Operator-run only after runtime build/capture and competing parity work ends.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/recipe_common.sh"
expected_commit="${1:?exact frozen repair build commit required}"
[[ "$expected_commit" == aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795 ]]
assert_frozen_root "$expected_commit"
inventory="$RECIPE_DIR/packaged-closure.aca94dd0.inventory.v1.json"
checker="$RECIPE_DIR/verify_packaged_readers.py"
fixture="$RECIPE_DIR/cold-descriptor-fixture"
assert_plain_file "$inventory"
assert_plain_file "$checker"
assert_plain_file "$fixture/fixture.inventory.v1.json"
[[ "$(sha256sum "$inventory" | cut -d ' ' -f 1)" == f395d0dd84be03232939f8aeb5c927d51b2e5a3aedaaea8836b05f0b83bd9bcc ]]
[[ "$(sha256sum "$fixture/fixture.inventory.v1.json" | cut -d ' ' -f 1)" == 065c45da24c2390da58af2db4f0d727793198e1a414f4b9341e942481fa694ba ]]
[[ "$(realpath -e "$fixture")" == "$fixture" && ! -L "$fixture" ]]
[[ -z "$(docker ps -q)" ]]
[[ "$(cat "$BASE/runtime-build-control/rc.txt")" == 0 ]]
control="$BASE/packaged-reader-control"
[[ ! -e "$control" ]]
mkdir -m 700 "$control"
set -o noclobber
printf '%s\n' "$expected_commit" > "$control/expected-commit.txt"
sha256sum "$checker" "$inventory" "$fixture/fixture.inventory.v1.json" > "$control/helpers.before.sha256"
date -u +%FT%TZ > "$control/started.txt"
for system in deepstream savant openvino_gva gstreamer_custom; do
  ref="$(runtime_reference "$system")"
  receipt="$BASE/runtime_images/$system.runtime.freeze.json"
  assert_plain_file "$receipt"
  "$PY" -B - "$ROOT" "$receipt" "$ref" > "$control/$system.receipt-binding.json" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1] + "/scripts")
from publication_qualification_image_refreeze_v1 import load_runtime_image_receipt
receipt = load_runtime_image_receipt(sys.argv[2])
assert receipt["candidate_binding_eligible"] is True and receipt["blockers"] == []
physical = receipt["physical_identity"]
assert physical["final_reference"] == sys.argv[3]
print(json.dumps({"reference": physical["final_reference"], "image_id": physical["image_id"],
                  "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
PY
  image_id="$($PY -B -c 'import json,sys;print(json.load(open(sys.argv[1]))["image_id"])' "$control/$system.receipt-binding.json")"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]
  for suffix in '' -determinism-a -determinism-b; do
    [[ "$(docker image inspect "$ref$suffix" --format '{{.Id}}')" == "$image_id" ]]
  done
  docker image inspect "$image_id" > "$control/$system.image-inspect.before.json"
  command=(docker run --rm --network none --read-only --cap-drop ALL
    --security-opt no-new-privileges --entrypoint python3
    --mount "type=bind,source=$checker,target=/repair-check/check.py,readonly"
    --mount "type=bind,source=$inventory,target=/repair-check/closure.inventory.v1.json,readonly"
    --mount "type=bind,source=$fixture,target=/repair-fixture,readonly"
    "$image_id" -B /repair-check/check.py
    --inventory /repair-check/closure.inventory.v1.json
    --fixture /repair-fixture --runtime "$system" --mode all)
  printf '%q ' "${command[@]}" > "$control/$system.command.txt"
  printf '\n' >> "$control/$system.command.txt"
  set +e
  "${command[@]}" > "$control/$system.stdout.json" 2> "$control/$system.stderr.log"
  rc=$?
  set -e
  printf '%s\n' "$rc" > "$control/$system.rc.txt"
  [[ "$rc" == 0 ]]
  "$PY" -B - "$control/$system.stdout.json" "$system" <<'PY'
import json, sys
row = json.load(open(sys.argv[1], encoding="utf-8"))
assert row["passed"] is True and row["runtime"] == sys.argv[2]
assert row["source_commit"] == "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
assert row["fresh_interpreter_count"] == 7 and len(row["runs"]) == 7
assert all(run["passed"] is True for run in row["runs"])
assert row["host_production_scripts_mounted"] is False
assert row["promotion_first_actual_image_check"] == "unsupported_by_approved_host_only_F1_scope"
PY
  docker image inspect "$image_id" > "$control/$system.image-inspect.after.json"
  cmp "$control/$system.image-inspect.before.json" "$control/$system.image-inspect.after.json"
  for suffix in '' -determinism-a -determinism-b; do
    [[ "$(docker image inspect "$ref$suffix" --format '{{.Id}}')" == "$image_id" ]]
  done
done
sha256sum "$checker" "$inventory" "$fixture/fixture.inventory.v1.json" > "$control/helpers.after.sha256"
cmp "$control/helpers.before.sha256" "$control/helpers.after.sha256"
date -u +%FT%TZ > "$control/finished.txt"
assert_frozen_root "$expected_commit"
