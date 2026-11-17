#!/usr/bin/env bash
set -euo pipefail
# Distinct post-archive controls. Sealed pre-archive recipes remain untouched.
[[ "$#" == 5 && "$2" =~ ^[0-9a-f]{40}$ ]] || exit 64
MODE="$1"
SHA="$2"
CATALOG_SHA="$3"
ASSET_SHA="$4"
FRESH_SHA="$5"
[[ "$MODE" == prepare || "$MODE" == focus || "$MODE" == sourcecompare || "$MODE" == integration || "$MODE" == full ]] || exit 64
[[ "$CATALOG_SHA" == 8b9111ab5855bf73b0bac2532599b1a77d36235e05a544d0a08c47cdbcaac0e7 ]]
[[ "$ASSET_SHA" == b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d ]]
[[ "$FRESH_SHA" == 9b38ca696ee662bcd26f78a293f899fb6333b581670f486a5c9cfae4f9e48d45 ]]
ROOT="/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA"
PHYSICAL_ROOT=/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a
PHYSICAL_BUILD_COMMIT=aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795
OLD_ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
SELF="${BASH_SOURCE[0]}"
[[ "$SELF" == /* && "$(realpath -e "$SELF")" == "$SELF" ]]
CHECK_RECIPE_DIR="$(dirname -- "$SELF")"
CHECK_BASE="$ROOT/artifacts/accepted_policy_repair_20261011a/checks-01"

assert_committed_bytes() {
  "$PY" -B - "$1" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(root / "scripts"))
import run_ci_checks
run_ci_checks.verify_committed_bytes(root, run_ci_checks.tracked_paths(root))
PY
}

assert_frozen_root() {
  [[ "$(id -u)" == 1000 && "$HOME" == /home/s-a-balashov ]]
  [[ "$(realpath -e "$ROOT")" == "$ROOT" && -x "$PY" ]]
  [[ "$(findmnt -rn -T "$ROOT" -o FSTYPE)" == ext4 ]]
  [[ "$(git -C "$ROOT" rev-parse HEAD)" == "$SHA" ]]
  [[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]
  assert_committed_bytes "$ROOT"
  "$PY" -B - "$ROOT" "$SHA" "$SELF" <<'PY'
import sys
from pathlib import Path
root, sha, self_value = sys.argv[1:]
self_path = Path(self_value)
sys.path.insert(0, str(self_path.parent))
from copy_fresh_check_inputs_v2 import recipe_origin
origin = recipe_origin(Path(root), sha, self_path)
assert self_path.name == "run_archive_checks_v1.sh"
assert Path(origin["change_relative"]).parts[:3] == ("openspec", "changes", "archive")
assert not (Path(root) / "openspec/changes/fix-accepted-policy-preprocessing").exists()
archives = list((Path(root) / "openspec/changes/archive").glob("*-fix-accepted-policy-preprocessing"))
assert archives == [Path(root) / origin["change_relative"]]
PY
}

assert_nine_ids() {
  "$PY" -B - "$ROOT" "$CHECK_RECIPE_DIR/integration-test-ids.txt" <<'PY'
import json
import sys
from pathlib import Path
root, ids_path = map(Path, sys.argv[1:])
ids = ids_path.read_text(encoding="ascii").splitlines()
document = json.loads((root / ".ci/integration-test-selection.v1.json").read_bytes())
declared = sorted(row["test_id"] for row in document["integration_declarations"])
if len(ids) != 9 or len(set(ids)) != 9 or ids != declared:
    raise RuntimeError("nine integration IDs differ from the committed CI selection")
PY
}

assert_idle() {
  "/usr/bin/docker" ps --all --format '{{.ID}} {{.Names}} {{.Status}}' > "$OUT/containers.$1.txt"
  "/usr/lib/wsl/lib/nvidia-smi" --query-compute-apps=pid,process_name,used_memory --format=csv,noheader > "$OUT/gpu-compute.$1.txt"
  [[ ! -s "$OUT/containers.$1.txt" && ! -s "$OUT/gpu-compute.$1.txt" ]]
}

assert_frozen_root
assert_nine_ids
OUT="$CHECK_BASE/archive-$MODE-$SHA"
[[ ! -e "$OUT" ]]
mkdir -p -- "$CHECK_BASE"
mkdir -m 700 -- "$OUT"
date -u +%FT%TZ > "$OUT/started.txt"
printf '%s\n' "$SHA" > "$OUT/source-commit.txt"
printf '%s\n' "$MODE" > "$OUT/mode.txt"
sha256sum -- "$SELF" "$CHECK_RECIPE_DIR/copy_fresh_check_inputs_v2.py" \
  "$CHECK_RECIPE_DIR/compare_final_source_inputs_v3.py" \
  "$CHECK_RECIPE_DIR/copy_check_inputs.py" "$CHECK_RECIPE_DIR/run_integration_case.py" \
  "$CHECK_RECIPE_DIR/private_runtime_namespace.sh" > "$OUT/helpers.sha256.txt"
cd "$ROOT"
RESULT_RC=0

case "$MODE" in
prepare)
  [[ "$(git -C "$PHYSICAL_ROOT" rev-parse HEAD)" == "$PHYSICAL_BUILD_COMMIT" ]]
  [[ -z "$(git -C "$PHYSICAL_ROOT" status --porcelain --untracked-files=no)" ]]
  assert_committed_bytes "$PHYSICAL_ROOT"
  "$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" regression "$SHA" "$CATALOG_SHA" \
    "$OLD_ROOT" "$ROOT" "$OUT/regression-copy.report.json" \
    > "$OUT/regression-copy.stdout.log" 2> "$OUT/regression-copy.stderr.log"
  "$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" assets "$SHA" "$CATALOG_SHA" \
    "$PHYSICAL_ROOT" "$ROOT" "$OUT/asset-copy.report.json" "$ASSET_SHA" "$PHYSICAL_BUILD_COMMIT" \
    > "$OUT/asset-copy.stdout.log" 2> "$OUT/asset-copy.stderr.log"
  "$PY" -B "$CHECK_RECIPE_DIR/copy_fresh_check_inputs_v2.py" "$PHYSICAL_BUILD_COMMIT" "$SHA" "$FRESH_SHA" \
    "$PHYSICAL_ROOT" "$ROOT" "$OUT/fresh-copy.report.json" \
    > "$OUT/fresh-copy.stdout.log" 2> "$OUT/fresh-copy.stderr.log"
  [[ "$(git -C "$PHYSICAL_ROOT" rev-parse HEAD)" == "$PHYSICAL_BUILD_COMMIT" ]]
  assert_committed_bytes "$PHYSICAL_ROOT"
  ;;
focus)
  MODULES=(
    tests.test_publication_guardian_accepted_policy_preprocessing_contract_v1
    tests.test_accepted_policy_guardian_transaction_lineage
    tests.test_full_publication_identity_artifacts
    tests.test_full_publication_identity_policy_coverage
    tests.test_publication_qualification_policy_pilot_validator_v2
    tests.test_publication_policy_qualification_validation_leaves_v2
    tests.test_publication_qualification_promotion_v2
    tests.test_publication_policy_qualification_transaction_v2
    tests.test_publication_policy_qualification_fragments_from_authority_v2
    tests.test_publication_policy_qualification_execution_code_closure_v1
    tests.test_publication_policy_qualification_execution_closure_v1
    tests.test_publication_guardian_preprocessing_contract_v1
    tests.test_checkpoint_deepstream_runtime_source_closure_v3
    tests.test_checkpoint_savant_runtime_source_closure_v3
    tests.test_checkpoint_openvino_gva_runtime_source_closure_v3
    tests.test_checkpoint_gstreamer_custom_runtime_source_closure_v3
    tests.test_publication_runtime_source_closure_guardian_v1
    tests.test_runtime_image_python310_compat_v1
    tests.test_publication_runtime_frozen_identity_constants_v1
    tests.test_checkpoint_gstreamer_custom_publication_runtime_v3
    tests.test_checkpoint_gstreamer_custom_qualification_fragment_v3
    tests.test_publication_gstreamer_component_inputs_v1
    tests.test_accepted_policy_original_custody_fixture_v1
    tests.test_accepted_policy_guardian_lifecycle_fixture_v1
    tests.test_accepted_policy_checkpoint_fixture_v1
    tests.test_accepted_policy_production_validation
    tests.test_accepted_policy_native_fixture_v2
    tests.test_accepted_policy_change_paths_v1
    tests.test_accepted_policy_fixture_sample_counts_v2
    tests.test_accepted_policy_fixture_transport_v2
    tests.test_accepted_policy_standalone_reader_fixture_v2
    tests.test_accepted_policy_f5_real_refusals
    tests.test_image_input_eol_rules_v1
  )
  "$PY" -B - "$CHECK_RECIPE_DIR/run_focused_suite.sh" "${MODULES[@]}" <<'PY'
import re
import sys
from pathlib import Path
body = Path(sys.argv[1]).read_text(encoding="ascii")
matched = re.search(r"(?m)^MODULES=\(\n((?:  tests\.[a-zA-Z0-9_]+\n)+)\)$", body)
assert matched is not None and matched[1].split() == sys.argv[2:]
PY
  printf '%s\n' "${MODULES[@]}" > "$OUT/test-modules.txt"
  set +e
  TMPDIR=/var/tmp PYTHONPATH="$ROOT/tests" "$PY" -B -m unittest -v "${MODULES[@]}" \
    > "$OUT/original.stdout.log" 2> "$OUT/original.stderr.log"
  RC="$?"
  set -e
  printf '%s\n' "$RC" > "$OUT/original.rc.txt"
  RESULT_RC="$RC"
  ;;
sourcecompare)
  PHYSICAL_EVIDENCE="$(dirname -- "$CHECK_RECIPE_DIR")/physical-01"
  set +e
  {
    "$PY" -B "$PHYSICAL_EVIDENCE/derive_packaged_closure_inventory.py" "$ROOT" "$SHA" \
      > "$OUT/fresh-packaged-closure.inventory.v1.json" &&
    "$PY" -B "$ROOT/scripts/publication_image_build_v1.py" plan \
      --project-root "$ROOT" --registry "$ROOT/configs/publication_image_build_v1.json" \
      > "$OUT/native-worker.plan.json" &&
    "$PY" -B "$CHECK_RECIPE_DIR/compare_final_source_inputs_v3.py" \
      --source-commit "$SHA" --project-root "$ROOT" \
      --fresh-inventory "$OUT/fresh-packaged-closure.inventory.v1.json" \
      --native-worker-plan "$OUT/native-worker.plan.json" > "$OUT/source-comparison.v3.json" &&
    "$PY" -B "$ROOT/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
      --project-root "$ROOT" --receipt "$OUT/execution-code-closure.v1.json" > "$OUT/code-closure-materialize.stdout.json" &&
    "$PY" -B "$ROOT/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
      --project-root "$ROOT" --receipt "$OUT/execution-code-closure.v1.json" --validate-only > "$OUT/code-closure-cold.stdout.json"
  } > "$OUT/original.stdout.log" 2> "$OUT/original.stderr.log"
  RC="$?"
  set -e
  printf '%s\n' "$RC" > "$OUT/original.rc.txt"
  RESULT_RC="$RC"
  ;;
integration)
  # Reconstruction12 is separately reviewed/copied into SOURCE before this lane.
  assert_idle before
  "/usr/bin/docker" info --format '{{.ID}}' > "$OUT/docker-engine-id.txt"
  df -Pk "$ROOT" /var/tmp /mnt/c /mnt/e > "$OUT/disk.before.txt"
  cp --no-clobber "$CHECK_RECIPE_DIR/integration-test-ids.txt" "$OUT/integration-test-ids.txt"
  FAIL=0
  while IFS= read -r ID; do
    set +e
    VAST_LIVE_PREFLIGHT=1 VAST_RUN_OPENVINO_LIVE_DOCKER_TEST=1 TMPDIR=/var/tmp \
      "$PY" -B "$CHECK_RECIPE_DIR/run_integration_case.py" "$ID" "$OUT/$ID.outcome.json" \
      > "$OUT/$ID.stdout.log" 2> "$OUT/$ID.stderr.log"
    RC="$?"
    set -e
    printf '%s %s\n' "$RC" "$ID" >> "$OUT/results.txt"
    [[ "$RC" == 0 ]] || FAIL=1
  done < "$CHECK_RECIPE_DIR/integration-test-ids.txt"
  assert_idle after
  [[ "$(wc -l < "$OUT/results.txt")" == 9 ]]
  RESULT_RC="$FAIL"
  ;;
full)
  INTEGRATION_OUT="$CHECK_BASE/archive-integration-$SHA"
  # The portable lane excludes these9; actual physical outcomes must precede its mount baseline.
  "$PY" -B - "$INTEGRATION_OUT" "$CHECK_RECIPE_DIR/integration-test-ids.txt" "$SHA" <<'PY'
import json
import sys
from pathlib import Path
out, ids_path = map(Path, sys.argv[1:3])
sha = sys.argv[3]
ids = ids_path.read_text(encoding="ascii").splitlines()
assert (out / "passed.txt").read_text(encoding="ascii") == sha + "\n"
assert (out / "source-commit.txt").read_text(encoding="ascii") == sha + "\n"
assert (out / "results.txt").read_text(encoding="ascii").splitlines() == ["0 " + name for name in ids]
for name in ids:
    row = json.loads((out / (name + ".outcome.json")).read_bytes())
    assert row["test_id"] == name and row["successful"] is True
    assert row["successful_test_ids"] == [name]
    assert row["tests_run"] == 1 and not row["skips"] and not row["errors"] and not row["failures"]
PY
  assert_idle before
  ORDINARY_NOFILE_SOFT="$(ulimit -Sn)"
  ORDINARY_NOFILE_HARD="$(ulimit -Hn)"
  [[ "$ORDINARY_NOFILE_SOFT" == 10240 && "$ORDINARY_NOFILE_HARD" == 1048576 ]]
  CLONE=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-"$SHA"
  [[ ! -e "$CLONE" ]]
  [[ "$(findmnt -rn -T /home/s-a-balashov/work -o FSTYPE)" == ext4 ]]
  "$PY" -B - "$ORDINARY_NOFILE_SOFT" "$ORDINARY_NOFILE_HARD" > "$OUT/ordinary-user-limits.json" <<'PY'
import json
import os
import resource
import sys
assert os.getuid() == 1000 and os.getgid() == 1000
expected = (int(sys.argv[1]), int(sys.argv[2]))
assert expected == (10240, 1048576)
assert resource.getrlimit(resource.RLIMIT_NOFILE) == expected
print(json.dumps({"uid": os.getuid(), "gid": os.getgid(), "nofile": list(expected),
    "source": "observed ordinary UID1000 caller, not a requested increase"}, sort_keys=True))
PY
  git -c core.autocrlf=false clone --no-hardlinks --no-checkout "$ROOT" "$CLONE" \
    > "$OUT/clone.stdout.log" 2> "$OUT/clone.stderr.log"
  git -C "$CLONE" -c core.autocrlf=false checkout --detach "$SHA" \
    > "$OUT/checkout.stdout.log" 2> "$OUT/checkout.stderr.log"
  [[ "$(git -C "$CLONE" rev-parse HEAD)" == "$SHA" ]]
  assert_committed_bytes "$CLONE"
  # Preserve the sealed portable input set: old31+assets34+fresh2473+2fixturemaps, not reconstruction12.
  "$PY" -B "$CHECK_RECIPE_DIR/copy_check_inputs.py" ext4 "$SHA" "$CATALOG_SHA" \
    "$ROOT" "$CLONE" "$OUT/input-copy.report.json" "$ASSET_SHA" \
    > "$OUT/input-copy.stdout.log" 2> "$OUT/input-copy.stderr.log"
  "$PY" -B "$CHECK_RECIPE_DIR/copy_fresh_check_inputs_v2.py" "$SHA" "$SHA" "$FRESH_SHA" \
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
      "$PARENT_NAMESPACE" "$START_NS" "$ORDINARY_NOFILE_SOFT" \
      > "$OUT/parent.stdout.log" 2> "$OUT/parent.stderr.log"
    RC="$?"
  else
    WSL_EXE=/mnt/c/Windows/System32/wsl.exe
    if [[ -x "$WSL_EXE" ]]; then
      printf '%s\n' wsl-root-private-unshare > "$OUT/privileged-launcher.txt"
      "$WSL_EXE" --distribution Ubuntu --user root --exec unshare --mount --fork \
        --propagation private /bin/bash "$CHECK_RECIPE_DIR/private_runtime_namespace.sh" \
        "$CLONE" "$OUT" "$SHA" "$PARENT_NAMESPACE" "$START_NS" "$ORDINARY_NOFILE_SOFT" \
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
  date -u +%FT%TZ > "$OUT/ci-finished.txt"
  cp -- /proc/self/mountinfo "$OUT/global-mountinfo.after.txt"
  [[ "$(readlink /proc/self/ns/mnt)" == "$PARENT_NAMESPACE" ]]
  cmp -- "$OUT/global-mountinfo.before.txt" "$OUT/global-mountinfo.after.txt"
  sha256sum -- "$OUT/global-mountinfo.before.txt" "$OUT/global-mountinfo.after.txt" > "$OUT/global-mountinfo.sha256.txt"
  assert_frozen_root
  [[ "$(git -C "$CLONE" rev-parse HEAD)" == "$SHA" ]]
  assert_committed_bytes "$CLONE"
  RESULT_RC="$RC"
  if [[ "$RC" == 0 ]]; then
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
  fi
  assert_idle after
  ;;
esac
assert_frozen_root
date -u +%FT%TZ > "$OUT/finished.txt"
printf '%s\n' "$RESULT_RC" > "$OUT/launcher-result.rc.txt"
[[ "$RESULT_RC" == 0 ]] || exit "$RESULT_RC"
printf '%s\n' "$SHA" > "$OUT/passed.txt"
