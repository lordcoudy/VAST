# Verification and conformance plan

This is a planned verification map, not a passing test report. During apply, record each requirement and every named scenario below with implementation file/line, exact test ID or physical evidence descriptor, invocation/exit status, observation time and any gap. A format check proves document structure only. Historical A268/A269 evidence cannot substitute for fresh acceptance.

## 1. Preparation has an explicit stopping point

Scenarios: Preparation succeeds; Readiness ages or inputs change.

Verify the preparation handoff fields against stock receipts, including zero full-run arms/invocations and no installed/enabled service. Check gate timestamps/dependency identities and demonstrate that a changed guardian/source/capacity input invalidates the affected gate. Existing integration points: tests/test_full_publication_entrypoint.py and tests/test_full_publication_wsl_user_service_v1.py. Add focused handoff validation only for newly implemented behavior; operator logs and systemd observation supply the physical non-starting evidence. An existing unrelated unit is not to be altered blindly.

## 2. Native payload descriptors match immutable bytes

Scenarios: Correct payload and reuse; Incorrect digest; Payload bounds.

Extend tests/cpp/checkpoint_analytics_execution_client_test.cpp and wire it into normal Linux discovery/build configuration. Capture the outgoing datagram/FD and compare bytes, declared size and digest to one owned snapshot. A valid-format wrong hash must fail with no send. Exercise zero, 67,108,864 and 67,108,865 sizes; confirm oversized input fails before allocation/copy. Coordinate storage reuse after snapshot capture, with no data race, and check descriptor cleanup on exceptions. Record a regression that fails against the pre-fix native path, then passes after repair. Python worker behavior in tests/test_analytics_execution_worker.py is reference coverage, not a substitute for executing C++.

## 3. Guardian preserves rejection and diagnostic evidence

Scenarios: Routed sealed wrong-content request; Invalid attribution or descriptor; Concurrent failures or diagnostic persistence error; Historical lifecycle.

Use tests/test_checkpoint_gstreamer_analytics_sidecar.py with tests/test_analytics_execution_protocol.py. Exercise correctly routed sealed same-size wrong bytes, both supported protocol modes, missing/extra FDs, missing seals, invalid IDs/routes/type/size and unsafe observations. Assert started/failed exactly once only after valid attribution, zero completed/inference, and all received descriptors closed. Check the diagnostic limit, safe field/null behavior, binding hashes and absence of raw payload/credentials. Race terminal failures and inject persistence failure: at most one committed diagnostic and original terminal failure retained. Existing lifecycle v1 fixtures must pass unchanged; verify new snapshot/closure consumers without inventing front-client authentication.

## 4. Retry and recovery policy is predictable

Scenarios: Retry option omitted; Transient offload or low storage; Remote integrity mismatch.

Use tests/test_full_publication_supervisor.py and tests/test_full_publication_wsl_user_service_v1.py for both API and parser defaults, materialized argv and exception/unknown-exit behavior. With budget omitted, assert one launch, no retry sleep, failed_permanent state and exit 78. Use tests/test_full_publication_runtime.py, tests/test_full_publication_runner.py and tests/test_publication_storage_recovery.py for reserve checks, transient exit 75, same-checkpoint resume, accepted-pair bypass and upload/readback/receipt-ledger/raw-cleanup ordering. Distinguish transport failure from completed wrong-size/hash readback; only verified offload may permit raw cleanup. Preserve tests/test_full_publication_results.py finalized-only export behavior.

## 5. Baselines and affected evidence are reproducible

Scenarios: Existing working tree differs from clean checkout; Packaged source changes; Deterministic planning replay.

Compare review-context.json and a complete implementation baseline before edits. Record the reviewed source reconciliation diff rather than staging the dirty tree wholesale. Map changes through image allowlists/build receipts and use tests/test_publication_image_build_v1.py plus affected publication-image/native tests. Require real rebuilt/package evidence and renewed physical parity/fixtures, not only mocked validator tests. Use final ext4 suite logs and exact before/after file manifests; explain skip identities against the historical 87. Replay plan generation with identical accepted inputs and compare frozen matrix/policy hashes, pair/arm order, ingress schedules/run seeds, durations and analysis settings using tests/test_publication_matrix.py, tests/test_full_publication_entrypoint.py and tests/test_publication_article_statistics_v1.py where applicable.

## 5A. Native-probe qualification path is integrated before qualification

Scenarios: Mixed-width queue properties; Branch identifier shorter than eight bytes; Policy decision names a manifest identity; Loaded path differs from manifest backend; Qualification bundle supplies a copied engine client; Postdecode prefix queue overflows before policy entry; Pre-detector queue overflows before policy entry; Queue-drop identity or ordering is invalid; Preprocessing evidence is missing without a verified prefix drop; Independent and shared prefix-drop coverage; Native stage resource sidecar; Pre-check fails.

Use the discovered native C++ and plugin runners plus focused host publication, native policy, source-closure and resource-attribution tests to prove queue width, manifest identity, copied-engine containment and exact drop/lineage behavior. For the sidecar, verify that the shared runtime writes `resource_events.csv` exclusively from accepted physical frame-stage intervals before publication, with one-to-one stage keys, duration/provenance fields and no invented prefix-drop preprocessing. Reject missing/duplicate/invalid/unmatched accepted-ingress intervals and preexisting output, while excluding warmup/drain rows; retain the separate publication missing-sidecar rejection. Then inspect original successful image builds, packaged tests, physical parity, final exact-byte suite and one nonpromoting CPU/GPU pre-check per native-probe system. A failed check's marker and guardian lifecycle remain nonpromoting and cannot be combined with a later chain.

## 5B. Published policy decisions preserve canonical linkage and actual runtime history

Scenarios: Worker traces and runtime sequence gaps enter a measurement cohort; Publication preserves live decision and feedback authority; Excluded feedback influences a measured adaptive decision; Nonadaptive publication preserves strict closure without adaptive history; Publication mapping or original proof is corrupt; Runtime history or projected ordering is incomplete; History input exceeds its bound or is malformed; Existing strict historical records are read; Independent Q4 reader runs under its isolated loader; Original producer success has rejected cold evidence.

Under exact approved planning commit `a8361805f49a1afe24674ef2e84f327b7712af28`/design decision 9, use discovered `tests/test_checkpoint_native_policy_publication_projection_v1.py`, `tests/test_publication_q4_policy_projection_v1.py`, `tests/test_publication_policy_history_acceptance_v1.py`, `tests/test_publication_policy_history_namespace_v1.py` and `tests/test_publication_policy_history_resume_v1.py`, retaining native/contract, legacy Q4 runner/reader and acceptance regressions. Verify actual coordinator warmup gaps and input-key/accepted-ingress/CSV-worker provenance mapping; dense outer/request/CSV coordinates; reversible original accepted/issued hashes and native worker/branch/transport-PTS proof; unchanged live wire responses, feedback payload/hash and contract equations. Do not equate native transport PTS to source/access-unit/schedule clocks. Require actual reset and validated terminal closure for every policy; do not add adaptive history to nonadaptive namespaces.

For adaptive arms, exercise excluded/interleaved updates, out-of-order measured terminals, original issuance/feedback ordinals and exact complete measurement membership from the full accepted-ingress mapping. Reject duplicate/reused native event IDs, removed/reordered/orphan/unclosed events, unsupported/mixed metadata, substituted reset/state/hash, malformed numeric domains and dense-view drift. Match the frozen original normalization domain, including actual coordinator-clamped expired deadlines, while retaining strict legacy behavior. Prove physical history SHA propagation through the real source-builder mapping, candidate hash loop and final acceptance rehash/commit; reject missing/mutated history and a persisted candidate omitting its hash. Mock only unrelated heavy graph/resource work and classify such checks as fixtures.

Exercise bounded streaming producer/reader rejection for 64 MiB/history file, 256 KiB/record, 1,000,000 events, duplicate keys/nonfinite numbers and truncation. Preserve acceptance's 256-MiB aggregate, tighter stage custody including Savant's 64-MiB child aggregate/file count, and legacy Q4 bulk limits. Run positive/negative projected nonadaptive and adaptive evidence through the actual pinned `python -I -S -B` verified-byte loader; no unpinned helper import or unrestricted project path is permitted. Record red-before-fix results and immutable command/exit/source/test descriptors without inventing physical logs.

Review the two helper leaves through four runtime Docker COPY and four sorted source allowlists, proving exact reachable Python/source/dependency sets and recording all nine current source/receipt relationships. Renew affected runtime images and dependent package/parity/final exact-byte suite, fresh inputs/guardian/bundles, all four nonpromoting native pre-checks and a successful Savant diagnostic with strengthened stock cold audit before qualification. Keep f original process success, cold rejection and authenticated clean stop separate and immutable. Any offline historical copy check must retain fixture-only/no-acceptance flags; it cannot recover f acceptance or authorize qualification/Q4. Record ongoing successor sessions at their original terminals, and leave tasks/CI/capacity pending until their actual gates pass.

## 6. Qualification and Q4 are complete before launch readiness

Scenarios: A269 has eight historical cells; Fresh qualification and Q4 succeed; A prerequisite is missing or fails.

Inspect existing qualification/policy validators and tests/test_publication_policy_qualification_pilot_executor_v2.py plus closure/index tests. Real acceptance requires the fresh diagnostic, all 32 cells, original successful terminals, authenticated stop, lifecycle/closure and promotion. Bind zero A269 cells into accepted evidence. For Q4 use tests/test_publication_q4_authority_plan_pipeline_v1.py, tests/test_backend_q4_two_phase_source_registry_v1.py and tests/test_backend_q4_two_phase_executor_v1.py, then verify physical 560-A/boundary/560-B/280-sizing records and backend binding. Inject missing/stale/partial prerequisite evidence in focused tests; preserve original failure receipts and prohibit dependent-stage launch. Long operations require one persisted owner/checkpoint and observation of its original terminal.

## 7. Cloud admission uses an actual dated guarantee

Scenarios: Confirmation missing; Sizing or readback exceeds the guarantee.

Use tests/test_full_publication_seafile_capacity_binding.py and the stock capacity-attestation validators. Verify rejection of missing/undated confirmation, wrong destination, incomplete 280-pair sizing, an insufficient byte guarantee and failed/wrong upload readback. Confirm the exact formula and ten repeats. Physical evidence must include the operator's actual UTC timestamp/reference and successful live validation; no test fixture can stand in for that statement. Keep capability URLs private. Missing confirmation blocks launch readiness while otherwise authorized qualification/Q4 can proceed.

## 8. Launch handoff preserves the full experiment

Scenarios: Unstarted package validates; Altered matrix or malformed command.

Use the stock entrypoint/service plan, preflight and validate paths with canonical run/state/output constraints. Test frozen-hash/count/settings changes and unsupported paths. Independently syntax-check all Bash fences without executing them, assert the variable allowlist and compare options/order to current parser/interface source. Record accepted sanitized argv, receipt hashes, observation time and zero startup calls. Include downstream install/start/verify/finalize/export procedure in prose only; later execution requires a separate request and renewed preflight. Do not treat a generated service bundle as evidence of installed or successful running state.

## 9. Documentation and conformance are truthful

Scenarios: Documentation reviewed; Required CI is unavailable.

Deliver docs/benchmark-preparation-runbook.md during apply and reconcile README.md, PLAN.md and progress.md without losing original obligations or historical failures. Read all new artifacts after writing; verify links/identifiers and scan for the prior character-substitution corruption. Complete this map per scenario using actual results and classify unverified/manual limitations explicitly. Read final-commit CI/check status when available; if absent, record the separate CI setup gap and block merge rather than equating local tests or OpenSpec validation with CI.

## Proposal-only checks

Before presenting this proposal: strict OpenSpec validation, required artifact completeness, whitespace/diff review, syntax-only Bash parsing, variable allowlist and parser-option/order comparison, physical rehash of the inspected baseline, and review for unsupported readiness claims. Store a compact result in proposal-validation.json. Do not execute benchmark commands or modify production/tests/CI in this stage.
