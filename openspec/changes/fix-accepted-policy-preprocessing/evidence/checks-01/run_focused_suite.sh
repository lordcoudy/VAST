#!/usr/bin/env bash
set -euo pipefail
source "${VAST_REPAIR_CHECK_ROOT:-$(cd "$(dirname "$0")/../../../../.." && pwd -P)}/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/recipe_common.sh"
[[ "$#" == 1 ]] || exit 64
SHA="$1"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
RUN_SUFFIX="${VAST_REPAIR_FOCUSED_RUN_SUFFIX:-01}"
[[ "$RUN_SUFFIX" =~ ^[0-9]{2}$ ]]
OUT="$CHECK_BASE/focused-$SHA-$RUN_SUFFIX"
[[ ! -e "$OUT" ]]
mkdir -p -- "$CHECK_BASE"
mkdir -m 700 -- "$OUT"
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
printf '%s\n' "$SHA" > "$OUT/commit.txt"
printf '%s\n' "${MODULES[@]}" > "$OUT/test-modules.txt"
date -u +%FT%TZ > "$OUT/started.txt"
cd "$ROOT"
set +e
TMPDIR=/var/tmp PYTHONPATH="$ROOT/tests" "$PY" -B -m unittest -v "${MODULES[@]}" \
  > "$OUT/original.stdout.log" 2> "$OUT/original.stderr.log"
RC="$?"
set -e
printf '%s\n' "$RC" > "$OUT/original.rc.txt"
date -u +%FT%TZ > "$OUT/finished.txt"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
exit "$RC"
