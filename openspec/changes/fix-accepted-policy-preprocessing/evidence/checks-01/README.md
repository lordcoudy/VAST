# Prepared Check Recipes, Not Execution Evidence

These recipes were initially prepared without cloning, copying, running tests,
or invoking Docker. Subsequent originals and their boundaries are catalogued in
`completed-check-results.v1.json` and `execution-review.md`; preparation alone
does not establish success. By default they use the new repair
root `/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a`. Alternatively set
`VAST_REPAIR_CHECK_ROOT` to the exact canonical ext4 source clone
`/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$FROZEN_COMMIT`.
No other override is accepted. The recipe must reside beneath the selected root;
its HEAD, raw tracked bytes, UID/HOME, and canonical path are checked. Outputs go
only beneath that root's `artifacts/accepted_policy_repair_20261011a/checks-01/`.
The historical `/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a` is read-only input and
is never checked out, retagged, promoted, or materialized by these recipes.

## Exact Frozen Inputs

The root owner must review the 31-row `regression-inputs.sha256-size-path.tsv`
and its SHA-256 before copying. All 31 historical files were read and rehashed
against existing accepted receipts or physical integration fixture inventories:

- 19 unchanged files under `artifacts/qualify_full_benchmark_20261008e/`, from
  `physical-v12-ci-c5/receipts.list` and the original copied-receipt hash list.
- 12 unchanged files under `artifacts/deepstream_publication_v3/`, from
  `physical-v1-integration/input_copies/artifacts__deepstream_publication_v3.source-manifest.v1.json`.

These files are **regression-only historical immutable inputs**, not renewed
parity/runtime/transaction authority. The historical DeepStream fragment is used
only by its unchanged explicitly declared integration test. It is never admitted
to a new promoter, transaction builder, or materializer. Failed Q1/G9 raw data,
attempt directories, historical pilots, and promoted policy packages are absent.

The seven DeepStream dependency wheels are already tracked, with unchanged
receipt hashes; a normal clone provides them. The ext4 clone additionally copies
exactly 24 model files and 10 corpus files from the independently reviewed
`physical-01/asset-copy.inventory.v1.json`, whose preparation-time SHA-256 is
`b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d`.
It excludes that inventory's three remapped repair base receipts. The clone
therefore receives 65 historical/model/corpus inputs at unchanged relative paths.
Both catalogs require explicitly supplied reviewed digests and complete copy
preflight; tracked paths and existing destinations cannot be overwritten.

## Additive Fresh Catalog

The separate `prepare_fresh_check_catalog.py` recipe renders the complete fresh
accepted-v4 graph from the exact passed independent physical parity audit:
480 executions, 960 individual tensor files, 1920 execution members, and 2478
unique physical descriptors. Its reviewed audit SHA-256 is
`75922812dde1281dc57f7969d5cd5bd3d32fa6cd10e34a6638b8e54ce51fb95b`.
The physical build commit remains `aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`;
the final host-only pin/config source commit is distinct and explicitly checked.

The additive catalog has 2473 fresh ignored files: 2466 audit-listed files,
the separately bound acceptance binding, and six immutable fresh receipt files.
It also has eight destination-only tracked byte cross-checks (seven configs and
the exact selected-original GStreamer receipt copy), and five corpus byte
cross-checks already supplied by the 34-file asset subset. Tracked inputs must
arrive through the source commit, never through this copier.

Two additional `consumer-runtime-observations-02` maps are listed separately as
fixture-only inputs, not independently parity-audited authority:
`image-inspect-map.json` (48042 bytes, SHA-256
`890fecbd90e5f9c7af3ceecd0500e06e2d9fde8dc1ec38324f9d66de2335ecdb`) and
`device-probe-map.json` (2153 bytes, SHA-256
`5253f71f50662019e3543ac8338d2ef7ac09c9a26a25132f4af45564bdaf4921`).
They contain the captured raw inspect/probe JSON needed by the artificial
custody boundary. `observations-01` and policy attempt outputs are excluded.
Original command captures remain separate evidence. Total ignored copies for a
fully prepared clone are 2540: 31 historical, 34 model/corpus, 2473 fresh, two
fixture observations. Neither copying nor fixture playback renews authority.

Before freezing, root renders and reviews the actual catalog, then commits it as
`fresh-inputs.catalog.v1.json` in this evidence directory. For example:

```bash
"$PY" -B "$HOST_E/prepare_fresh_check_catalog.py" "$PHYSICAL_ROOT" "$HOST_ROOT" \
  "$EXACT_PHYSICAL_SOURCE_COMMIT" "$REVIEWED_PARITY_AUDIT_SHA256"
```

Save the generated JSON as evidence, review all descriptors and its actual
SHA-256, and supply that exact digest to the copy recipe. No catalog has been
rendered or copied during preparation. The copier verifies every source byte
before its first write, uses independent ordinary files rather than hard links,
and rechecks hashes and raw tracked commit bytes afterward. No root/path
metadata, receipt, epoch, or authority document is rebound. A genuine stock
reader refusal in the destination is preserved and reported, not repaired by
editing metadata.

## Commands For The Root Owner

First freeze and commit the complete repair sources and these recipes. Use the
exact 40-character lowercase frozen commit, not a short SHA or branch name.
The sources must be raw-byte-identical to that commit and tracked-clean.
Run as UID 1000 with `HOME=/home/s-a-balashov`; no recipe expands or coerces SHA.

To leave the active physical build root at its original ACA commit, root may
create a fresh ordinary ext4 clone of the final repair source, then run:

```bash
export VAST_REPAIR_CHECK_ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$FROZEN_COMMIT
E=$VAST_REPAIR_CHECK_ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
bash "$E/prepare_source_inputs.sh" "$FROZEN_COMMIT" "$REVIEWED_REGRESSION_CATALOG_SHA256" \
  "$REVIEWED_ASSET_INVENTORY_SHA256" "$REVIEWED_FRESH_CATALOG_SHA256"
bash "$E/run_focused_suite.sh" "$FROZEN_COMMIT"
bash "$E/run_final_source_inputs_v2.sh" "$FROZEN_COMMIT"
# Supply the separately reviewed exact reconstruction corpus before this lane.
bash "$E/run_integration_lane.sh" "$FROZEN_COMMIT"
bash "$E/run_ext4_suite.sh" "$FROZEN_COMMIT" "$REVIEWED_REGRESSION_CATALOG_SHA256" \
  "$REVIEWED_ASSET_INVENTORY_SHA256" "$REVIEWED_FRESH_CATALOG_SHA256"
```

The preparation wrapper copies the 31 regressions from the unchanged old root,
34 models/corpus files and 2475 fresh/fixture files from the unchanged physical
ACA root, verifying the distinct input and destination commits. It changes no
tracked source. The full suite then clones the final source into a separate
`ci-$FROZEN_COMMIT` root. It does not check out or restart an existing worker.
For the original physical-root option, the same inputs must already be present
and that root must be at the supplied final source commit; the suite never
silently upgrades it.

Complete the focused, source-comparison, input-copy and physical integration
writers before starting complete consumers. Start the full ext4 suite only
after the physical integration lane finishes: Docker Desktop may create
global bind rows during the live held-FD test, even after its containers exit,
and such an overlap invalidates the suite's exact global mount-table check.
The full suite uses a distinct clone; any parallel consumer requires explicit
review proving all remaining outer writes stay within already created deep
output directories and cannot mutate its guarded ancestors.

Do not execute the integration lane while a runtime-image build or other live
Docker check, full-suite wrapper or fixture engine child is active. The nine test identities are
unchanged; their approved literal runtime/parity pins are the paired fresh pins
where applicable. Both those fresh images and the one declared historical
DeepStream fixture image must be locally available. A missing image, pin mismatch, or
live preflight failure is a failed prerequisite/check, not permission to patch
constants, replace receipts, retag an image, mock a validator, or waive the test.

`integration-test-ids.txt` preserves exactly the nine existing manifest IDs in
sorted order. The runner checks that equality before starting. Each original
test runs in a fresh Python interpreter with the existing live opt-in flags and
`TMPDIR=/var/tmp`. All nine must actually execute once, succeed, and have zero
skips/expected failures. Original stdout, stderr, exact outcome, timestamps, and
the supplied commit are retained. This lane does not by itself qualify newly
rebuilt repair runtime images or establish new accepted-policy authority.

## Full Ext4 Suite And The Bind Prerequisite

The full suite creates a fresh detached ext4 clone at
`/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-$FROZEN_COMMIT`.
Both that path and its new output directory must be absent. The unchanged
`scripts/run_ci_checks.py` supplies complete discovery, the declared nine-case
exclusion, original observer/namespace diagnostics, six CPU build targets,
source-byte checks, and the original 90-minute deadline. Output is outside that
clone. A failed original parent command is returned as failure, not just logged.

To satisfy the actual canonical copied-Python bind test, the recipe uses:

```bash
sudo -n unshare --mount --fork --propagation private /bin/bash \
  "$E/private_runtime_namespace.sh" "$EXT4_CLONE" "$FRESH_OUTPUT" \
  "$FROZEN_COMMIT" "$ORIGINAL_MOUNT_NAMESPACE" "$JOB_STARTED_MONOTONIC_NS" "$OBSERVED_NOFILE_SOFT"
```

The wrapper first records `sudo -n true`. If passwordless sudo is unavailable,
it instead invokes the supported WSL root entry point with the same explicit
arguments, still immediately entering an isolated private mount namespace:

```bash
/mnt/c/Windows/System32/wsl.exe --distribution Ubuntu --user root --exec \
  unshare --mount --fork --propagation private /bin/bash \
  "$E/private_runtime_namespace.sh" "$EXT4_CLONE" "$FRESH_OUTPUT" \
  "$FROZEN_COMMIT" "$ORIGINAL_MOUNT_NAMESPACE" "$JOB_STARTED_MONOTONIC_NS" "$OBSERVED_NOFILE_SOFT"
```

This fallback is not a global root mount operation and does not change any
skip declaration. The launcher choice, original/private namespace identities,
and byte-identical before/after caller `/proc/self/mountinfo` are retained.
Any changed global mount table blocks success. No launcher has been executed
during preparation.

This privileged helper checks that its mount namespace differs from its caller
and that root propagation is private. Only inside it, the existing supported
`scripts/mount_publication_runtime_wsl.sh` self-binds the canonical ext4 runtime
read-only and binds the same runtime at the clone's exact project-relative path.
It uses explicit source/root arguments and `--check-only` verification. It then
drops privilege with `runuser` and correct HOME/USER/LOGNAME/TMPDIR before CI.
The outer UID1000 caller must actually observe soft/hard NOFILE 10240/1048576.
After `runuser`, the child records its identity, capabilities and limits,
restores only that observed ordinary-user soft limit while preserving the hard
limit, records the result, and refuses any mismatch before launching stock CI.
The test temporary base is verified canonical ext4 `/tmp`; no production
socket-length bound, test assertion, system limit or CI skip policy is changed.
Mounts disappear with the private namespace; no global remount/unmount or old
root mount is touched. Original mount descriptions and namespace identity are
retained. Both privileged launchers being unavailable, mount privilege, copied single-link Python, or
required namespace support being unavailable blocks the recipe; it does not
authorize an additional skip. No mount command has been executed during
preparation.

## Skip Review And CI Dispatch Gap

The unchanged committed `.ci/integration-test-selection.v1.json` has preparation
SHA-256 `09e9268069e88b957f9ae54a827960bc18ee13a00d4319994d108d3cb81a0805`.
It contains the exact nine integration declarations and 88 allowed portable
skip **identity/reason pairs**: 78 platform/explicit physical prerequisites and
10 existing schema-v1 migration tombstones. Their existing reasons and
`acceptance_claim=false` remain authoritative; an allowed skip is nonexecution,
not a successful test. The machine harness must produce a valid
`portable_skip_audit` for the actual skip set. A new ID or changed reason fails.

The prior `physical-v12-ci-c5/ext4-suite.report.json` ran 3244 portable cases,
reported 88 skips, raw-byte equality and no tracked mutation, but was **not
machine-green**: 87 skips matched declarations; one did not. The exact difference:

`test_backend_publication_output_transaction_production_v3.BackendPublicationOutputTransactionProductionV3Tests.test_canonical_wsl_venv_requires_plain_copied_python`

Declared reason: `canonical WSL publication venv is not installed`.
Actual unapproved reason: `canonical WSL publication venv bind is not mounted`.
The original report contains the corresponding `ValueError` and overall
`successful=false`. Historical human disposition does not change the manifest
or make that machine run green. The private bind recipe requires this canonical
test to be in `successful_test_ids` and absent from the actual skip set.

`.github/workflows/ci.yml` automatically dispatches pull requests only against
`master` (and pushes to `master`). The repair Draft PR targets the retained
`codex/qualify-full-benchmark` branch, so no automatic PR dispatch is promised.
Root must explicitly dispatch the existing workflow at the frozen repair branch
and verify that both CPU and host-diagnostic jobs actually checked its exact
latest commit. These local recipes are not a successful GitHub CI run. Workflow
changes and skip-whitelist changes are outside this repair/evidence scope.
