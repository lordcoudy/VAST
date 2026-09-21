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
