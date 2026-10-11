#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/recipe_common.sh"
expected_commit="${1:?exact frozen repair build commit required}"
assert_frozen_root "$expected_commit"
assert_plain_file "$NATIVE"
assert_plain_file "$WORKER"
control="$BASE/image-capture-control"
runtime="$BASE/runtime_images"
patch="$BASE/qualification_image_identity_patch.json"
[[ -d "$runtime" && ! -e "$control" && ! -e "$patch" ]]
assert_plain_file "$runtime/savant.runtime_image.materialized.v3.json"
mkdir -m 700 "$control"
set -o noclobber
printf '%s\n' "$expected_commit" > "$control/expected-commit.txt"
date -u +%FT%TZ > "$control/started.txt"
for system in deepstream savant openvino_gva gstreamer_custom; do
  "$PY" -B "$ROOT/scripts/publication_qualification_image_refreeze_v1.py" capture \
    --project-root "$ROOT" --registry "$REGISTRY" --system "$system" \
    --native-receipt "$NATIVE" --receipt-output "$runtime/$system.runtime.freeze.json" \
    --candidate-final-reference "$(runtime_reference "$system")" --docker /usr/bin/docker \
    > "$control/$system.stdout.log" 2> "$control/$system.stderr.log"
done
"$PY" -B "$ROOT/scripts/publication_qualification_image_refreeze_v1.py" assemble \
  --project-root "$ROOT" --registry "$REGISTRY" \
  --native-receipt "$NATIVE" --worker-receipt "$WORKER" \
  --runtime-receipt "deepstream=$runtime/deepstream.runtime.freeze.json" \
  --runtime-receipt "savant=$runtime/savant.runtime.freeze.json" \
  --runtime-receipt "openvino_gva=$runtime/openvino_gva.runtime.freeze.json" \
  --runtime-receipt "gstreamer_custom=$runtime/gstreamer_custom.runtime.freeze.json" \
  --output "$patch" > "$control/assemble.stdout.log" 2> "$control/assemble.stderr.log"
"$PY" -B "$ROOT/scripts/publication_qualification_image_refreeze_v1.py" verify-patch \
  --project-root "$ROOT" --patch "$patch" \
  > "$control/verify.stdout.log" 2> "$control/verify.stderr.log"
"$PY" -B - "$patch" "$runtime" > "$control/parity-refresh-required.json" <<'PY'
import json, sys
from pathlib import Path
patch = json.load(open(sys.argv[1], encoding="utf-8"))
expected = ["analytics_worker:cpu_identity_changed_requires_parity_refresh",
            "analytics_worker:gpu_identity_changed_requires_parity_refresh"]
assert patch["blockers"] == expected and patch["candidate_binding_eligible"] is False
for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
    row = json.loads((Path(sys.argv[2]) / (system + ".runtime.freeze.json")).read_bytes())
    assert row["candidate_binding_eligible"] is True and row["blockers"] == []
print(json.dumps({"parity_refresh_required": True, "blockers": expected}, sort_keys=True))
PY
sha256sum "$patch" > "$control/patch-file.sha256"
date -u +%FT%TZ > "$control/finished.txt"
assert_frozen_root "$expected_commit"
