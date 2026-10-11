#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/recipe_common.sh"
[[ "$#" == 4 ]] || exit 64
SHA="$1"
CATALOG_SHA="$2"
ASSET_SHA="$3"
FRESH_SHA="$4"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
assert_nine_ids
CLONE=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-"$SHA"
OUT="$CHECK_BASE/ext4-$SHA"
[[ ! -e "$CLONE" && ! -e "$OUT" ]]
[[ "$(findmnt -rn -T /home/s-a-balashov/work -o FSTYPE)" == ext4 ]]
mkdir -p -- "$CHECK_BASE"
mkdir -m 700 -- "$OUT"
date -u +%FT%TZ > "$OUT/started.txt"
printf '%s\n' "$SHA" > "$OUT/commit.txt"
git -c core.autocrlf=false clone --no-hardlinks --no-checkout "$ROOT" "$CLONE" \
  > "$OUT/clone.stdout.log" 2> "$OUT/clone.stderr.log"
git -C "$CLONE" -c core.autocrlf=false checkout --detach "$SHA" \
  > "$OUT/checkout.stdout.log" 2> "$OUT/checkout.stderr.log"
[[ "$(git -C "$CLONE" rev-parse HEAD)" == "$SHA" ]]
assert_committed_bytes "$CLONE"
"$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" ext4 "$SHA" "$CATALOG_SHA" \
  "$ROOT" "$CLONE" "$OUT/input-copy.report.json" "$ASSET_SHA" \
  > "$OUT/input-copy.stdout.log" 2> "$OUT/input-copy.stderr.log"
"$PY" -B "$CHECK_RECIPE_DIR/copy_fresh_check_inputs.py" "$SHA" "$SHA" "$FRESH_SHA" \
  "$ROOT" "$CLONE" "$OUT/fresh-input-copy.report.json" \
  > "$OUT/fresh-input-copy.stdout.log" 2> "$OUT/fresh-input-copy.stderr.log"
START_NS="$("$PY" -B -c 'import time; print(time.monotonic_ns())')"
PARENT_NAMESPACE="$(readlink /proc/self/ns/mnt)"
printf '%s\n' "$PARENT_NAMESPACE" > "$OUT/original-mount-namespace.txt"
cp -- /proc/self/mountinfo "$OUT/global-mountinfo.before.txt"
set +e
if sudo -n true > "$OUT/sudo-prerequisite.stdout.log" 2> "$OUT/sudo-prerequisite.stderr.log"; then
  printf '%s\n' sudo-private-unshare > "$OUT/privileged-launcher.txt"
  sudo -n unshare --mount --fork --propagation private /bin/bash \
    "$CHECK_RECIPE_DIR/private_runtime_namespace.sh" "$CLONE" "$OUT" "$SHA" \
    "$PARENT_NAMESPACE" "$START_NS" > "$OUT/parent.stdout.log" 2> "$OUT/parent.stderr.log"
  RC="$?"
else
  WSL_EXE=/mnt/c/Windows/System32/wsl.exe
  if [[ -x "$WSL_EXE" ]]; then
    printf '%s\n' wsl-root-private-unshare > "$OUT/privileged-launcher.txt"
    "$WSL_EXE" --distribution Ubuntu --user root --exec unshare --mount --fork \
      --propagation private /bin/bash "$CHECK_RECIPE_DIR/private_runtime_namespace.sh" \
      "$CLONE" "$OUT" "$SHA" "$PARENT_NAMESPACE" "$START_NS" \
      > "$OUT/parent.stdout.log" 2> "$OUT/parent.stderr.log"
    RC="$?"
  else
    printf '%s\n' unavailable > "$OUT/privileged-launcher.txt"
    printf '%s\n' 'Neither noninteractive sudo nor the WSL root entry point is available.' > "$OUT/parent.stderr.log"
    RC=77
  fi
fi
set -e
printf '%s\n' "$RC" > "$OUT/parent.rc"
date -u +%FT%TZ > "$OUT/finished.txt"
cp -- /proc/self/mountinfo "$OUT/global-mountinfo.after.txt"
[[ "$(readlink /proc/self/ns/mnt)" == "$PARENT_NAMESPACE" ]]
cmp -- "$OUT/global-mountinfo.before.txt" "$OUT/global-mountinfo.after.txt"
sha256sum -- "$OUT/global-mountinfo.before.txt" "$OUT/global-mountinfo.after.txt" > "$OUT/global-mountinfo.sha256.txt"
assert_frozen_root "$SHA"
[[ "$(git -C "$CLONE" rev-parse HEAD)" == "$SHA" ]]
assert_committed_bytes "$CLONE"
[[ "$RC" == 0 ]] || exit "$RC"
"$PY" -B - "$OUT/original/report.json" "$SHA" "$ROOT/.ci/integration-test-selection.v1.json" <<'PY'
import json
import sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_bytes())
manifest = json.loads(Path(sys.argv[3]).read_bytes())
suite = report["unittest"]
assert report["commit"] == sys.argv[2] and report["successful"] is True
assert report["raw_checkout_bytes_match_commit"] is True and report["changed_tracked_paths"] == []
assert suite["successful"] is True and suite["tests_run"] > 0
assert all(not suite[key] for key in ("errors", "failures", "missing_required_successes", "unexpected_successes"))
allowed = {row["test_id"]: row for row in manifest["allowed_portable_skips"]}
actual = suite["skips"]
assert len({row["test_id"] for row in actual}) == len(actual)
assert all(row["test_id"] in allowed and row["reason"] == allowed[row["test_id"]]["reason"] for row in actual)
assert suite["portable_skip_audit"] == sorted([allowed[row["test_id"]] for row in actual], key=lambda row: row["test_id"])
canonical = "test_backend_publication_output_transaction_production_v3.BackendPublicationOutputTransactionProductionV3Tests.test_canonical_wsl_venv_requires_plain_copied_python"
assert canonical in suite["successful_test_ids"]
assert all(row["test_id"] != canonical for row in actual)
print(json.dumps({"full_ext4_regression_checks": "passed", "commit": report["commit"],
    "tests_run": suite["tests_run"], "approved_nonexecution_count": len(actual),
    "new_runtime_qualification": False}))
PY
