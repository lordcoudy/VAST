## 1. Approved baseline and evidence ownership

- [ ] 1.1 Verify approval of this change's exact planning commit in its Draft PR and a separate apply request; record both in the implementation evidence record before code changes.
- [ ] 1.2 Reconcile the reviewed dirty runtime into the same implementation branch without unrelated changes; verify the inspected-file manifest and record a complete source/fixture/configuration baseline and reviewed diff.
- [ ] 1.3 Capture environment, resource settings, image/data/model identities and current process ownership; verify A269 remains retired and no duplicate worker, verifier or active stage is created.

## 2. Native payload integrity

- [ ] 2.1 Validate envelope and 1..67,108,864-byte bounds before snapshot allocation, hash one owned snapshot, reject a mismatched supplied digest and seal that snapshot; verify correct payload, wrong digest, zero and oversized input regressions.
- [ ] 2.2 Verify synchronized caller-buffer reuse after capture preserves transmitted bytes, upper-bound acceptance and exception/FD cleanup; ensure no test introduces an unsynchronized C++ data race.
- [ ] 2.3 Integrate the standalone C++ client regression into normal Linux test discovery with existing GLib tooling; verify the runner actually executes it and fails on the pre-fix digest defect.

## 3. Guardian attribution and evidence

- [ ] 3.1 Validate the control envelope and route before reserving a request, then verify payload integrity; verify exactly-once failed accounting for attributable wrong-content requests and connection-only accounting before attribution.
- [ ] 3.2 Add the bounded immutable diagnostic and lifecycle-message/evidence hash binding described in design.md; verify safe expected/observed facts, null unknowns, no raw payload/credentials and the 8-KiB limit.
- [ ] 3.3 Preserve original failures under concurrency or diagnostic-write failure and close received descriptors; verify no inference, retries or successful lifecycle outcome after terminal rejection.
- [ ] 3.4 Verify existing lifecycle v1 fixtures remain valid unchanged and new evidence remains consumable by closure/snapshot validators; add focused compatibility regressions where needed.

## 4. Retry defaults and retained recovery

- [ ] 4.1 Set all four supervisor/service API/CLI unexpected-retry defaults to zero; verify omission in each interface yields one launch, no retry sleep and failed_permanent (exit 78) for unknown exits/exceptions.
- [ ] 4.2 Verify transport/low-space transient exit 75 recovery retains the same checkpoint, accepted pairs are not remeasured, and remote integrity failures remain permanent with raw evidence retained; preserve existing reserve and offload-order coverage.

## 5. Source closure and final validation

- [ ] 5.1 Map changed files through native foundations and publication/worker image allowlists; verify an explicit invalidation list covers every affected image, parity and downstream receipt.
- [ ] 5.2 Rebuild affected images deterministically and execute packaged regressions; verify source/image receipt hashes and preserved unaffected identities.
- [ ] 5.3 Renew required physical parity and identity fixtures, including all 480 executions/32 groups when that closure is affected; verify original successful invocations and complete accepted receipts.
- [ ] 5.4 Run affected native builds/tests and one final full ext4 suite on the final source/fixture/mirror bytes; verify before/after manifests, original exit status and reviewed skip-identity differences against the historical 87 skips.

## 6. Fresh qualification

- [ ] 6.1 Produce fresh input/preprocessing receipts and canonical mount/identity checks; start one new guardian with eight authenticated workers and materialize 32 bundles/four assets, verifying their current receipt bindings.
- [ ] 6.2 Run the gated 180-second Savant video diagnostic for the new chain; verify its original successful terminal and physical evidence before qualification.
- [ ] 6.3 Launch the single fresh 32-cell qualification under its supported owner and record invocation identity/checkpoint; verify no A269 cells or helpers are reused.
- [ ] 6.4 Collect all 32 successful cells, authenticated stop/lifecycle/closure and policy/resource promotion; verify every physical descriptor and accepted validator result before Q4.

## 7. Q4 prerequisite evidence

- [ ] 7.1 Start the accepted-policy guardian and generate Q4 source request/material, phase1 plan/runtime registry, phase2 and two-phase source registry; verify exact receipt file/semantic hashes and reviewed ordered executor argv.
- [ ] 7.2 Launch phase A under one recorded owner/checkpoint; verify persistent invocation identity and supported observation/resume procedures without duplicate launch.
- [ ] 7.3 Observe phase A to its original terminal and verify all 560 accepted records; preserve failures and block boundary on incompleteness.
- [ ] 7.4 Execute the identity/grant boundary in the same Q4 work directory; verify accepted identities, grants and checkpoint transition.
- [ ] 7.5 Launch phase B with the same owner/checkpoint; verify persistent invocation identity and no phase-A remeasurement.
- [ ] 7.6 Observe phase B to its original terminal and verify all 560 records, 280 derived sizing pairs and persisted backend binding; reject partial or substituted historical evidence.

## 8. Capacity, preflight and unstarted package

- [ ] 8.1 Obtain current dated operator capacity confirmation for the existing destination and materialize attestation from actual Q4 sizing; verify the stock capacity formula and successful live upload/readback without exposing capability links.
- [ ] 8.2 Generate and replay the canonical full-run plan from accepted identities; verify frozen hashes, 2,800 pairs/5,600 arms, order/seeds/durations/analysis settings and zero executed full-run arms.
- [ ] 8.3 Complete live preflight with current guardian/backend identities and storage/memory checks; verify every prerequisite and the 20-GiB reserve on required volumes, recording observation time and expiry conditions.
- [ ] 8.4 Materialize and validate the unstarted service package using canonical paths and explicit zero unexpected retries; verify receipt hashes and absence of installation, enablement, startup or full-run invocation.

## 9. Handoff and conformance

- [ ] 9.1 Publish the checked preparation runbook and link README/PLAN/progress while preserving historical facts and PLAN obligations; verify Bash syntax, variable allowlist, current flags and the stopping boundary.
- [ ] 9.2 Deliver the preparation handoff packet from design.md with accepted evidence for every gate; verify preparation_ready=true, full_run_started=false, publication_ready=false and zero full-run arms, or report an explicit blocker without marking this task complete.
- [ ] 9.3 Complete requirement/scenario conformance using verification-plan.md and review the final diff; verify each implementation/evidence location, actual test result, remaining CI limitation and latest commit. Follow the separate repository sync/archive/final-review workflow only after all preparation tasks pass; do not claim full-run completion.
