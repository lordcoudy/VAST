## 1. Approved baseline and evidence ownership

- [x] 1.1 Verify approval of this change's exact planning commit in its Draft PR and a separate apply request; record both in the implementation evidence record before code changes.
- [x] 1.2 Reconcile the reviewed dirty runtime into the same implementation branch without unrelated changes; verify the inspected-file manifest and record a complete source/fixture/configuration baseline and reviewed diff.
- [x] 1.3 Capture environment, resource settings, image/data/model identities and current process ownership; verify A269 remains retired and no duplicate worker, verifier or active stage is created.

## 2. Native payload integrity

- [x] 2.1 Validate envelope and 1..67,108,864-byte bounds before snapshot allocation, hash one owned snapshot, reject a mismatched supplied digest and seal that snapshot; verify correct payload, wrong digest, zero and oversized input regressions.
- [x] 2.2 Verify synchronized caller-buffer reuse after capture preserves transmitted bytes, upper-bound acceptance and exception/FD cleanup; ensure no test introduces an unsynchronized C++ data race.
- [x] 2.3 Integrate the standalone C++ client regression into normal Linux test discovery with existing GLib tooling; verify the runner actually executes it and fails on the pre-fix digest defect.

## 3. Guardian attribution and evidence

- [x] 3.1 Validate the control envelope and route before reserving a request, then verify payload integrity; verify exactly-once failed accounting for attributable wrong-content requests and connection-only accounting before attribution.
- [x] 3.2 Add the bounded immutable diagnostic and lifecycle-message/evidence hash binding described in design.md; verify safe expected/observed facts, null unknowns, no raw payload/credentials and the 8-KiB limit.
- [x] 3.3 Preserve original failures under concurrency or diagnostic-write failure and close received descriptors; verify no inference, retries or successful lifecycle outcome after terminal rejection.
- [x] 3.4 Verify existing lifecycle v1 fixtures remain valid unchanged and new evidence remains consumable by closure/snapshot validators; add focused compatibility regressions where needed.

## 4. Retry defaults and retained recovery

- [x] 4.1 Set all four supervisor/service API/CLI unexpected-retry defaults to zero; verify omission in each interface yields one launch, no retry sleep and failed_permanent (exit 78) for unknown exits/exceptions.
- [x] 4.2 Verify transport/low-space transient exit 75 recovery retains the same checkpoint, accepted pairs are not remeasured, and remote integrity failures remain permanent with raw evidence retained; preserve existing reserve and offload-order coverage.

## 5. Source closure and final validation

- [x] 5.1 Map the new shared-runtime source change through native foundations and publication/worker image allowlists; verify an explicit invalidation list covers every affected image, parity and downstream receipt.
- [ ] 5.2 Rebuild affected images deterministically and execute packaged regressions; verify source/image receipt hashes and preserved unaffected identities after the native resource-sidecar, topology-event projection, measurement-cohort policy-promotion and native drop semantic-identity repairs.
- [ ] 5.3 Renew required physical parity and identity fixtures, including all 480 executions/32 groups when that closure is affected; verify original successful invocations and complete accepted receipts after the native resource-sidecar, topology-event projection, measurement-cohort policy-promotion and native drop semantic-identity repairs.
- [ ] 5.4 Run affected native builds/tests and one final full ext4 suite on the final source/fixture/mirror bytes; verify before/after manifests, original exit status and reviewed skip-identity differences against the historical 87 skips after the native resource-sidecar, topology-event projection, measurement-cohort policy-promotion and native drop semantic-identity repairs.

The `20260927c` image/parity/suite checks passed for their then-current bytes, but its corrected OpenVINO GVA CPU pre-check exposed a packaged `checkpoint_publication_runtime.py` projection defect. The `20260927d` renewal completed tasks 5.2-5.4 for its exact source/image/fixture bytes; see implementation-validation.md. Its first OpenVINO GVA CPU pre-check then failed at the native measurement with an unmatched applied policy decision. Source review identified a likely measurement-cohort mismatch in native policy promotion, but the physical row-2 policy CSV is unavailable, so that cause is not proven. The narrow shared-runtime correction then invalidated d. The `20260927e` image/package/parity/pin/final-suite renewal completed tasks 5.2-5.4 for its exact bytes, with physical receipts in implementation-validation.md. Its first OpenVINO GVA CPU pre-check failed at `branch_terminals.csv:7` after 227.377 seconds; all 3,691 preserved applied policy decisions matched physical frame events, so the earlier policy/frame mismatch is absent from the e snapshots. The exact conflicting branch terminal values were not preserved. Source inspection suggests a native pre-policy queue drop carries the OpenVINO proxy model identity while a later completion carries the external worker model identity; this remains an inference for the observed row. The in-progress native C++ repair changes the source closure, reopening 5.2-5.4 for a wholly new `20260927f` nine-image/parity/pin/final-suite chain. Tasks 6.1 and 10.9 remain pending for fresh accepted inputs and four original-successful native pre-checks; no live acceptance is claimed.

## 6. Fresh qualification

- [ ] 6.1 Produce fresh input/preprocessing receipts and canonical mount/identity checks; start one new guardian with eight authenticated workers and materialize 32 bundles/four assets, verifying their current receipt bindings.
- [ ] 6.2 Run the gated 180-second Savant video diagnostic for the new chain; verify its original successful terminal and physical evidence before qualification.
- [ ] 6.3 Launch the single fresh 32-cell qualification under its supported owner and record invocation identity/checkpoint; verify no A269 cells or helpers are reused.
- [ ] 6.4 Collect all 32 successful cells, authenticated stop/lifecycle/closure and policy/resource promotion; verify every physical descriptor and accepted validator result before Q4.

## 10. Native-probe qualification integration (added 2026-09-26; required before 6.2-6.4)

- [x] 10.1 Read reset-check queue levels at their declared width and add a discovered native regression that fails on the pre-fix read (c61328db).
- [x] 10.2 Raise the OpenVINO GVA and GStreamer Custom container task ceiling to 4096 with runtime tests (0f25cb41).
- [x] 10.3 Limit decode-stage artifacts to loaded GStreamer factories with a regression that fails on the pre-fix list (0f25cb41).
- [x] 10.4 Validate native policy identifiers by manifest grammar and frozen branch membership; verify `damage` is accepted and invalid names still rejected.
- [x] 10.5 Bind CPU and GPU native policy identities to the frozen qualification-v2 manifest per design decision 8 and verify the loaded analytics path matches the manifest backend; add positive and fail-closed regressions.
- [x] 10.6 Accept the qualification bundle's copied, hash-verified container-engine client in the GStreamer Custom runtime; verify containment and byte mismatches are rejected.
- [x] 10.7 Handle only verified native queue drops before policy entry as one correctly linked branch drop with no policy/inference call; add executable native or deterministic adapter-level regressions for both queues and topologies and fail-closed regressions for wrong provenance/reason, orphan/duplicate PTS before emission and post-entry drop.
- [x] 10.8 Bind publication stage and resource-attribution checks to verified branch-level drop provenance: require decode but not fabricated preprocessing for a postdecode prefix drop, require both for pre-detector drops and completed branches, enforce shared all-or-none prefix drops, and version the changed measurement stage-reduction signature; verify independent mixed/all-prefix and shared all-prefix outcomes plus malformed provenance and missing/extra intervals with executable positive/negative tests.
- [x] 10.8.1 Produce and validate the native-probe `resource_events.csv` from accepted physical frame-stage intervals before publication for both OpenVINO GVA and GStreamer Custom; verify exact stage/duration/provenance coverage, prefix-drop omission, malformed/duplicate/unmatched accepted-ingress interval rejection, existing-file rejection and call order, while excluding warmup and drain events.
- [ ] 10.9 Renew affected images, parity, identity fixtures and the final exact-byte suite after 10.7-10.8.1, topology-event projection, measurement-cohort policy-promotion and native drop semantic-identity repairs, then run one fresh nonpromoting CPU and GPU pre-check per native-probe system to its original successful terminal before 6.2-6.4; preserve all failed 2026-09-27 pre-check chains, including `20260927c`, `20260927d` and `20260927e`, and each guardian's actual lifecycle without reuse.

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

- [x] 9.1 Publish the checked preparation runbook and link README/PLAN/progress while preserving historical facts and PLAN obligations; verify Bash syntax, variable allowlist, current flags and the stopping boundary.
- [ ] 9.2 Deliver the preparation handoff packet from design.md with accepted evidence for every gate; verify preparation_ready=true, full_run_started=false, publication_ready=false and zero full-run arms, or report an explicit blocker without marking this task complete.
- [ ] 9.3 Complete requirement/scenario conformance using verification-plan.md and review the final diff; verify each implementation/evidence location, actual test result, remaining CI limitation and latest commit. Follow the separate repository sync/archive/final-review workflow only after all preparation tasks pass; do not claim full-run completion.
