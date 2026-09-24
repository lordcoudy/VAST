# Preparation plan and operating boundary

Status: proposed instructions for the later approved apply phase. No runtime test, qualification, Q4 or full-run workload has been executed by this proposal. Completion means ready for a later launch request, with an unstarted package. No process can be guaranteed error-free; gates must fail closed and preserve useful evidence.

## Frozen downstream experiment

Preserve deepstream, savant, openvino_gva and gstreamer_custom; h264/h265; checkpoint_independent_processes_baseline and checkpoint_video_dag_shared; cpu_only, gpu_only, static_hybrid, heft, deadline_aware_heft, queue_aware_edf and adaptive_weights; deadlines 16.7, 33.3, 50, 100 and 500 ms. The 280 system/codec/policy/deadline groups have ten paired repeats: 2,800 pairs and 5,600 arms. Each arm uses six streams, seed 20260323, 30-second warmup and 180-second measurement.

Frozen matrix v4 SHA-256: `a1115ea9fa5f496f45d75636b8376366a48413cdc4c9787cb7ca4baac04b230e`.

Frozen policy v1 SHA-256: `4168818527ced4b3611c9aeabff6b04a7962314f4d80beb3da9dc814ba369016`.

Keep primary-contrast 5/5 counterbalance, deterministic remaining within-pair order and seeded pair shuffle. Paired arms share ingress schedule/run_seed, model/preprocessing identities and resource attribution. Preserve paired-percentile bootstrap median, 95% confidence, 10,000 resamples, seed 20260323, and existing coprimary/quality claim rules. Keep valid negative results. Deterministic plan/analysis replay must agree; separate live measurements need not have identical timings.

Q4 measurement windows alone require 1,120 x 210 seconds, approximately 2.72 days. Qualification, diagnostics, builds/tests, parity and I/O add time. The later full matrix requires at least 13.61 additional days of windows and is excluded from this change. The 280 sizing pairs derive from phase B and add no measured arms.

## Gate 0: approval and exact baseline

Require this change's exact planning commit approved in its Draft PR, then a separate apply request. Reconcile the dirty runtime before implementation: review-context.json lists inspected bytes, not a complete executable closure. A clean checkout at the parent commit is insufficient. Do not include unrelated changes, alter historical receipts or apply the overlapping older proposal in parallel.

Inspect process and invocation identities before operating. Reuse an active stage's supported owner/checkpoint; do not start duplicate workers/verifiers. Keep failed A269 and its helpers retired. Its eight historical cells cannot count toward the new qualification.

Record source/fixture/config manifests, data/model/image/receipt descriptors and actual environment inventory. Verify the accepted frozen Python runtime, previously recorded at /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python, rather than assuming the path alone proves identity. Preserve WSL Ubuntu UID 1000 and the accepted memory=24GB setting; record actual OS/kernel/WSL, Docker/containerd, CPU/GPU/drivers/libraries, package versions, thread/resource/power settings and storage/memory headroom. Do not reinstall unconstrained dependencies or tune after results.

## Gate 1: repairs and renewed evidence

Implement design decisions 1-3 and tasks 2-4: immutable native snapshot/hash binding with pre-allocation bounds, attributable guardian failure accounting with bounded diagnostics, and zero unexpected retries in all four interfaces. Preserve strict rejection and supported transient recovery. Verification-plan.md names the positive, negative and compatibility cases.

Renew affected native foundations and publication image closures, deterministic image receipts and packaged tests. A shared-protocol edit also requires checking worker image closures. Renew dependent physical parity (480 executions/32 groups where required) and identity fixtures. Reuse accepted evidence only when its complete dependency graph is unchanged.

Run the final full suite from the ext4 runtime checkout after the final source/fixture/mirror bytes are in place. Retain before/after manifests and original terminal evidence. Historical 2,493 tests/87 skips are comparison data, not fixed new totals; explain every changed skip identity. Run affected native builds/tests and project-required checks, explicitly identifying unavailable lint/type/CI targets. Any later source change invalidates affected evidence.

## Gate 2: one fresh qualification

Produce new input/preprocessing receipts, validate the three canonical mounts and runtime identities with existing helpers, start one new guardian and authenticate all eight workers. Materialize 32 bundles/four assets with the existing producer. Perform the gated 180-second Savant video diagnostic, then all 32 system/resource/codec/topology qualification cells in one fresh attempt.

Require physical receipt validation, original successful terminal results, authenticated guardian stop, valid lifecycle/closure and policy/resource qualification/promotion. A failed diagnostic or cell blocks dependents; retain evidence and diagnose before a fresh or explicitly supported resume. Do not merge partial attempts or treat a successful diagnostic as qualification.

## Gate 3: Q4 with one owned checkpoint

Start a fresh guardian bound to accepted policy/preprocessing; retired socket-bound qualification bundles are not live authority. Feed the exact returned paths and physical/semantic hashes through:

1. scripts/publication_q4_authority_source_request_v1.py: accepted parity, policy/resource, guardian, preprocessing, dataset and qualification-runtime receipts plus future output paths.
2. scripts/publication_q4_authority_source_material_v1.py: validated request and its file/semantic hashes.
3. scripts/publication_q4_authority_plan_pipeline_v1.py: source-spec, then phase1.
4. scripts/publication_q4_runtime_registry_materializer_v4.py: candidate registry and materialization result.
5. The pipeline's phase2, then scripts/backend_q4_two_phase_source_registry_v1.py.
6. scripts/backend_q4_two_phase_executor_v1.py: phase_a (560), boundary (identities/grants), phase_b (560 and 280 derived sizing pairs).

The executor requires this ordered option sequence. Generate/review argv with current source interfaces and accepted values; never copy old attempt-specific examples:

```text
--project-root --source-registry --work-dir --identity-manifest-output
--phase1-receipt --phase1-receipt-file-sha256 --phase1-receipt-sha256
--phase2-receipt --phase2-receipt-file-sha256 --phase2-receipt-sha256
--source-materialization-result --source-materialization-result-file-sha256
--source-materialization-result-sha256 --through-phase
```

Keep one work directory/checkpoint and original invocation evidence across the three stages. Record start/observe as separate operator steps for these long operations. Passing source-registry validation alone does not complete Q4. Require every record, physical descriptor, boundary and persisted backend binding.

## Gate 4: actual capacity and live preflight

Obtain an explicit current operator lower-bound guarantee in bytes, UTC confirmation timestamp, reference and statement for the existing destination. An undated 1,500-GB note or old 500-GiB estimate is not confirmation. For conversion only: 1,500 GB = 1,500,000,000,000 bytes; 500 GiB = 536,870,912,000 bytes.

Materialize with scripts/seafile_operator_capacity_attestation_v2.py materialize and its --project-root, --sizing-index, --output, --destination-id, --operator-lower-bound-bytes, --confirmed-at-utc, --observed-at-utc, --confirmation-reference, --confirmation-statement and --links-file options. Run it in WSL with the verified frozen Python executable and the private ignored seafile.txt; the link-file custody check depends on consistent lstat/fstat metadata. Bind the actual 280-pair sizing index. Require max(500 GiB, ceil(projected_remote_bytes * 1.25) + 5 GiB), with ten repeats, plus successful live upload/readback and stock validation. Keep private capability URLs out of logs/review documents; no new destination or quota-query substitute is proposed.

Complete the accepted identity manifest and current plan/preflight. Require the stock 20-GiB reserve on all required results/scratch/temp/host volumes, memory headroom, canonical identities and current guardian/backend bindings. Missing capacity blocks readiness, not independent qualification/Q4. Transient transport/low-storage failures retain exit 75 and supported same-checkpoint recovery; integrity/identity failures remain permanent 78. Never remeasure accepted pairs just to finish offload.

## Gate 5: plan, preflight and unstarted package

These WSL Bash templates are for the approved apply phase after gates 0-4. Supply values only from accepted records. They deliberately fail on unset inputs. No preparation command installs, enables, starts or launches the service.

The project root must be canonical. Its runs/full_publication namespace must already exist and satisfy the stock real-path checks. Choose a new one-component attempt ID. The run root is exactly its child, state has the fixed basename below, and service output is a fresh direct child of artifacts. Do not use symlink aliases or overwrite earlier evidence. The service receipt path must come from materialize's returned payload.

```bash
set -euo pipefail
: "${PROJECT_ROOT:?canonical accepted runtime checkout}"
: "${PYTHON:?verified frozen Python executable}"
: "${ATTEMPT_ID:?fresh single-component full-run attempt ID}"
: "${IDENTITY:?accepted identity manifest path}"
: "${CAPACITY:?accepted dated capacity attestation path}"
: "${LINKS_FILE:?existing private capability file path}"
: "${DESTINATION_ID:?existing accepted destination}"
: "${SERVICE_DIR:?fresh direct child of PROJECT_ROOT/artifacts}"
RUN_ROOT="$PROJECT_ROOT/runs/full_publication/$ATTEMPT_ID"
STATE_PATH="$RUN_ROOT/full_publication_supervisor_state.v1.json"
MATRIX_SHA=a1115ea9fa5f496f45d75636b8376366a48413cdc4c9787cb7ca4baac04b230e
POLICY_SHA=4168818527ced4b3611c9aeabff6b04a7962314f4d80beb3da9dc814ba369016
cd "$PROJECT_ROOT"
ENTRY_ARGS=(
  --project-root "$PROJECT_ROOT" --run-root "$RUN_ROOT"
  --config "$PROJECT_ROOT/configs/experiments.yaml"
  --datasets "$PROJECT_ROOT/configs/datasets.yaml"
  --models "$PROJECT_ROOT/configs/checkpoint_analytics_models_openvino.yaml"
  --identity-artifacts "$IDENTITY" --capacity-attestation "$CAPACITY"
  --cloud-links-file "$LINKS_FILE" --cloud-destination-id "$DESTINATION_ID"
  --expected-matrix-sha256 "$MATRIX_SHA"
  --expected-policy-contract-sha256 "$POLICY_SHA"
  --minimum-free-gib 20 --cloud-timeout-s 120
)
"$PYTHON" scripts/full_publication_entrypoint.py "${ENTRY_ARGS[@]}" plan
"$PYTHON" scripts/full_publication_entrypoint.py "${ENTRY_ARGS[@]}" preflight
"$PYTHON" scripts/full_publication_wsl_user_service_v1.py materialize \
  --project-root "$PROJECT_ROOT" --attempt-id "$ATTEMPT_ID" \
  --run-root "$RUN_ROOT" --state-path "$STATE_PATH" \
  --output-dir "$SERVICE_DIR" --python-executable "$PYTHON" \
  --config "$PROJECT_ROOT/configs/experiments.yaml" \
  --datasets "$PROJECT_ROOT/configs/datasets.yaml" \
  --models "$PROJECT_ROOT/configs/checkpoint_analytics_models_openvino.yaml" \
  --identity-artifacts "$IDENTITY" --capacity-attestation "$CAPACITY" \
  --cloud-links-file "$LINKS_FILE" --cloud-destination-id "$DESTINATION_ID" \
  --expected-matrix-sha256 "$MATRIX_SHA" \
  --expected-policy-contract-sha256 "$POLICY_SHA" \
  --minimum-free-gib 20 --cloud-timeout-s 120 --preflight-timeout-s 900 \
  --max-unexpected-retries 0
```

After reading the successful returned materialization receipt path, run only non-installed validation:

```bash
set -euo pipefail
: "${PROJECT_ROOT:?same accepted runtime checkout}"
: "${PYTHON:?same verified frozen interpreter}"
: "${SERVICE_RECEIPT:?exact receipt path returned by materialize}"
cd "$PROJECT_ROOT"
"$PYTHON" scripts/full_publication_wsl_user_service_v1.py validate \
  --receipt "$SERVICE_RECEIPT"
```

Allowed shell variables are PROJECT_ROOT, PYTHON, ATTEMPT_ID, IDENTITY, CAPACITY, LINKS_FILE, DESTINATION_ID, SERVICE_DIR, RUN_ROOT, STATE_PATH, MATRIX_SHA, POLICY_SHA, ENTRY_ARGS and SERVICE_RECEIPT. Validate syntax and this exact set, plus options against current parsers. Save sanitized argv, receipt descriptors, original exit codes and observation times; do not print secret-bearing inputs. Templates do not replace stock path/identity/capacity validation.

## Gate 6: stop and hand off

Deliver the design.md preparation packet, a requirement/scenario conformance record and explicit remaining limitations. preparation_ready=true is allowed only with every current gate accepted; full_run_started=false and publication_ready=false are mandatory. Record zero full-run launch invocations/arms. A generated offline plan or valid service bundle cannot alone grant readiness.

Bind observation time and invalidation conditions. Guardian restart, changed source/image/config/data/model, capacity change or failed live checks invalidates the dependent gates. If prerequisites expire while awaiting execution, re-preflight and renew required bindings. Do not claim indefinite readiness or infer successful launch from a process that merely exists.

A later execution request must separately authorize installation/start, repeat current live preflight, and use the exact prepared service receipt with the stock install/start interfaces. During that later run, retain supported same-checkpoint recovery, original terminal outcomes, all 2,800 accepted pairs and verified offload ledgers. Only then run stock verify, finalize and finalized-only export and reconcile final manifest/table/plot claims. These later operating steps remain outside this preparation change.

After preparation implementation passes, follow repository conformance, sync/archive and final-review requirements in the same branch/PR. Missing CI or final approval remains a merge blocker even if local runtime readiness has been demonstrated.
