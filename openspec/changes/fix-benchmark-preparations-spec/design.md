## Context

The supplied benchmark plan, fix guide and review findings describe the failed A269 attempt and the full-run methodology. The user selected a narrower endpoint for this new change: finish preparation through qualification, Q4, capacity and preflight, then hand off without starting the full matrix.

Read-only checks found the prior 44-file runtime baseline unchanged. The native client still trusts a separately supplied digest; sidecar verification still precedes request attribution/accounting; supervisor/service defaults remain 3. A269's specific triggering request remains unconfirmed. Its failed receipts and eight historical DeepStream cells cannot satisfy fresh qualification.

Main OpenSpec specs are absent. The old prepare-repeatable-full-benchmark change is an unimplemented reference, not an approved prerequisite. Keep it unchanged; reconcile overlapping work before anyone later applies it. This change's artifacts are self-contained because the reference branch has not been published.

## Goals / Non-Goals

**Goals:** close demonstrated defects, prove the repaired runtime through current evidence, preserve repeatable experimental inputs, and supply a validated unstarted launch package.

**Non-goals:** guarantee that future hardware/network faults cannot occur; rerun A269; start full-matrix execution; install/enable its service; complete final publication; introduce new benchmark estimands, relaxed thresholds, dependencies or CI configuration.

## Decisions

### 1. Repair the native trust boundary

In deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp:192-222 and 281-313, validate the envelope and payload size before copying. The shared protocol limit is 67,108,864 bytes. Copy once into an owned vector, compute SHA-256 via the existing GLib facility, compare with raw_input_sha256 and create the sealed descriptor from that snapshot. Wrong hashes fail locally before exchange; do not silently replace an incorrect expected hash.

The existing Python worker client provides the corresponding copy/check/send pattern. Reuse existing GStreamer/GLib tooling and wire the standalone C++ test into normal Linux discovery; its existence without a discovered runner is insufficient. Test size 0/limit/limit+1, correct payload, valid-format wrong digest with no datagram/FD, synchronized post-capture buffer reuse, and exception cleanup. Caller mutation during capture remains prohibited; an owned copy cannot legalize a C++ data race.

Alternatives rejected: trusting caller hash retains F1; changing it silently masks upstream bugs; new cryptography dependencies are unnecessary. Hash/copy overhead is part of measured service work, not subtracted from results.

### 2. Attribute before reservation and retain bounded diagnostics

In scripts/checkpoint_gstreamer_analytics_sidecar.py, validate the pre-payload control envelope before reservation: stable IDs, frame/branch, decision resource or negotiated worker route, type, descriptor count and payload syntax/binding. Reuse/expose the GStreamer bridge control validator and worker inference-request validator. Check route against the expected mode/worker set, reserve once, then verify the memfd.

A post-attribution integrity failure counts started/failed exactly once and never invokes inference; earlier failures remain connection-only. These checks do not add or claim per-connection front-client authentication. Existing peer/control/worker checks remain unchanged.

Preserve lifecycle v1 and its exact failure object {type,message}. Write an additive immutable sibling, kind vast_gstreamer_analytics_protocol_failure_diagnostic_v1, schema_version=1, with lifecycle_id, service_authority_sha256, observed_at_utc, protocol_mode, attribution, validated request_id/branch/resource or null, expected/observed byte length/digest/seal mask or null, failure_stage and canonical self SHA. Maximum size 8192 bytes; exclude raw payload, request dumps, credentials and capability URLs.

Capture safe observations before descriptor closure. Keep the shared protocol validator unchanged where possible: a failure-only sealed-FD inspection can compute the observed digest without successful-path overhead. Never read unbounded/unsafe descriptors for diagnostics. Serialize first-failure selection, persist using existing owned immutable output mechanisms, and bind relative diagnostic path/hash in the lifecycle failure message and evidence snapshot. Persistence failure must not hide the original failure or produce a success claim. Preserve descriptor cleanup in all paths.

Rejected alternatives: adding fields to lifecycle v1 breaks historical exact schemas; suppressing hash errors or reconnecting undermines acceptance; recording full frames is unnecessary.

### 3. Align defaults and preserve recovery

Change all four supervisor/service API and CLI defaults from 3 to 0. Keep explicit `--max-unexpected-retries 0` in the prepared command. Generic explicit nonzero budgets may remain supported but are ineligible for this benchmark package.

Inject launcher exceptions and unknown exits with the option omitted: one invocation, no retry sleep, failed_permanent (exit 78). Preserve transient exit 75 backoff and same-checkpoint recovery, per-pair reserve checks, accepted-pair offload bypass, and upload/readback/receipt-ledger/raw-cleanup order. These are existing safeguards, not new implementations to duplicate.

### 4. Renew the actual dependency closure

Record the implementation baseline explicitly before edits. The dirty source tree is not represented by its parent Git commit; reconcile required source into this branch without sweeping unrelated edits into a commit. Preserve old bytes, fixtures and receipts.

Map changed files through native foundations and all publication-image source allowlists. Header and sidecar edits are packaged, so this is not the host-only A267 case. Rebuild affected images deterministically, run packaged regressions, refresh changed image/source identities, rerun dependent physical parity (480 executions in 32 groups when required), and update host fixtures by accepted receipts. If the shared protocol module changes, renew affected analytics worker images too.

Finish with one final full ext4 suite on the final source/fixture/mirror bytes, checking before/after hashes. Compare actual skip identities with the historical 87; adding tests means 2,493 is not a fixed required count. Build affected native targets, execute their tests, and report absent lint/type/CI targets honestly.

### 5. Complete prerequisites using existing authorities

Follow preparation-plan.md in order: new input/preprocessing receipts, canonical checks, one guardian with eight authenticated workers, 32 bundles/four assets, one gated video diagnostic, 32 complete qualification cells, successful authenticated stop/lifecycle/closure and policy/resource promotion. Failed A269 cannot resume or contribute cells.

Start a fresh accepted-policy guardian for Q4. Produce source request/material, phase1 runtime plan/registry, phase2 source registry, then execute 560 phase-A records, identity/grant boundary, 560 phase-B records and 280 derived sizing pairs in the same Q4 work/checkpoint. Use exact returned receipt paths/file hashes/semantic hashes and the current ordered CLI interface.

Only actual sizing plus dated operator confirmation and live upload/readback can admit cloud capacity. Keep existing private capability links/destination. Do not use undated capacity notes or a quota-query substitute.

### 6. Define a preparation handoff rather than another authority

Create an operator evidence packet, kind vast_benchmark_preparation_handoff_v1, with:

- schema_version=1, change name, approved planning commit, implementation commit and exact source manifest;
- observed_at_utc, attempt IDs, environment inventory and bound data/model/image/config identities;
- gates, each containing id, state (missing/failed/historical/accepted), observation time, descriptors {path,size_bytes,sha256}, blocker and verification method;
- frozen matrix/policy identities, full-matrix expected counts, sanitized exact argv, run root, state path and unstarted service receipt;
- preparation_ready, full_run_started, publication_ready and outstanding merge/CI limitations.

This packet summarizes stock validator results; it is not a new grant and manual editing cannot grant execution. preparation_ready=true requires every preparation gate accepted at observation time; full_run_started=false and publication_ready=false remain mandatory. Record zero full-run launch invocations/arms for this change. Missing CI can still block merge; report that separately from tested runtime preparation, without claiming CI passed.

Service paths must be PROJECT_ROOT/runs/full_publication/ATTEMPT_ID, its full_publication_supervisor_state.v1.json, and a materialization directory directly under PROJECT_ROOT/artifacts. Plan/preflight/materialize/validate are in scope. Install/enable/start/launch are deferred. A later execution request must repeat live preflight: guardian sockets, capacity and host conditions are not permanent attestations.

Keep WSL Ubuntu UID 1000 and accepted memory=24GB setting. Capture actual frozen interpreter/package versions, OS/WSL/kernel, Docker/containerd, GPU/CPU/driver/runtime libraries, resource/thread/power settings and reserve observations. Do not reinstall unconstrained requirements.txt ranges or tune after seeing outcomes.

### 7. Correct and check operational guidance

Write clean templates in this change's preparation-plan.md rather than applying blanket character substitutions to corrupted input. On implementation, publish docs/benchmark-preparation-runbook.md and point README/PLAN/progress to it, preserving historical data and PLAN numbered obligations.

Validate Bash fences with syntax-only parsing, inspect the variable-name set against an explicit allowlist, and compare each CLI flag and path constraint with current parser source. Syntax alone cannot catch a consistently misspelled variable. The reference typo issue affects documentation, not the 44 verified runtime files.

### 8. Integrate the native-probe qualification path

Qualification runs and nonpromoting pre-checks showed that the OpenVINO GVA and GStreamer Custom native-probe path has never completed a cell, and each repair exposed the next latent defect. The first three are implemented under the operator's scope decisions: a type-safe reset queue-level read (`c61328db`), a 4096-task container ceiling matching Savant's (`0f25cb41`), and decode-stage artifacts limited to loaded factories (`0f25cb41`).

The policy client SHALL validate identifiers by the manifest grammar (non-empty, at most 4096 bytes, no controls) plus exact membership of the frozen branch set, instead of an 8-byte minimum that rejects `damage`.

The probe currently binds CPU paths to the pre-qualification v1 scheme (`gstreamer-custom-openvino-cpu-v1`, `vast-native-gst-policy-path-v1`, the probe executable hash). The qualification-v2 manifest instead selects `<system>-qualification-authority-v2` / `<system>-native-policy-emitter-v2` identities with the fragment implementation hash, and names an analytics-execution backend. No runtime injects the GPU identities the probe reads. Recommended option: the runtime injects each branch's CPU and GPU `implementation_id`, `emitter_id` and `emitter_sha256` from the frozen manifest as analytics bindings. The probe uses them for both resources and verifies the loaded analytics path against the manifest's `terminal_backend` before measurement. The v1 compiled scheme is removed from qualification. Alternative: if review determines that in-process `gvadetect` is the intended CPU path, correct the manifest producer rather than the probe. Either choice needs positive and fail-closed regressions.

The GStreamer Custom runtime SHALL accept the bundle's project-relative copied container-engine client under the same size, SHA-256 and containment checks the OpenVINO runtime applies, instead of requiring an absolute host path.

Pre-check replays use the stock runtime with engine-output capture only, run against the live nonpromoting guardian, and never promote evidence. Each native-source change renews the image chain, parity, final suite and qualification chain.

## Risks / Trade-offs

- Original A269 cause remains unidentified -> distinguish demonstrated defects from forensic certainty; require fresh physical qualification.
- Copy/hash adds cost -> enforce the 64-MiB limit before allocation and retain honest timing.
- Missing source baseline in clean branch -> block edits until reconciliation and exact-byte review.
- Missing current capacity -> complete independent work, then leave readiness blocked until the operator supplies a dated guarantee.
- Qualification/Q4 are substantial -> approximately 2.72 days of Q4 windows plus qualification/diagnostic/build/test/IO overhead; the later full matrix alone adds 13.61 days and is excluded here.
- Readiness expires -> bind observation/identities and revalidate at eventual launch.
- Missing CI -> explicitly track separate setup/required checks; do not claim merge readiness.

## Migration Plan

1. Review and approve this change's exact planning commit in its Draft PR; obtain a separate apply request.
2. Reconcile the runtime baseline, implement focused repairs and runbook, verify negative/positive regressions and renewal dependencies.
3. Complete package/parity/final-suite gates, fresh qualification, Q4, capacity, preflight and unstarted service validation.
4. Deliver the handoff with zero full-run arms launched. Preparation may then be completed/archived after its required checks; do not wait for or claim downstream full-run completion.
5. If a gate fails, preserve evidence and stop dependents. Rollback uses a reviewed source revision and renewed bindings, never resetting a live attempt or rewriting receipts.
6. Sync/archive in the same branch/PR only after this preparation scope is complete, then latest-commit checks, final approval and authorized merge.

## Open Questions

The actual dated capacity guarantee and fresh generated attempt/receipt identities remain to be supplied by their later stages; these do not change the design. Public publication remains blocked by the earlier approval-review rejection until explicitly authorized. Neither is assumed from this proposal request.
