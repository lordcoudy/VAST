# Conformance progress — implementation in progress

This public record maps every requirement and scenario in the active change to source and evidence as of 2026-09-23. It is not a readiness receipt, CI result, qualification result, Q4 result, capacity confirmation, or authorization to start the full benchmark. No full-matrix arm has been launched by this change.

**Evidence terms:** **current local result** is an executed test or package check recorded for this change. **Existing coverage, current execution pending** names an applicable test that has not been executed in this change. **Physical evidence pending** requires a real accepted operation or its current receipts. The executed repair evidence is limited to the recorded focused suites, collector suite, source-closure checks, native CUDA checks, and package checks. The collector’s durable nine-test record is a local non-authorizing result; its paths are deliberately not published here.

## 1. Preparation has an explicit stopping point — implemented; physical evidence pending

Source: `scripts/full_publication_entrypoint.py` keeps plan/preflight read-only; `scripts/full_publication_wsl_user_service_v1.py` separates materialize, validate, install, and start; `docs/benchmark-preparation-runbook.md` excludes start and launch.

- **Preparation succeeds — current local result for the no-start guard; otherwise unverified.** `tests/test_full_publication_wsl_user_service_v1.py::FullPublicationWslUserServiceTests.test_materialization_is_canonical_self_hashed_and_does_not_start` executed successfully. No accepted handoff, live preflight, or current unstarted package exists.
- **Readiness ages or inputs change — current local result for bundle drift checks; physical evidence pending.** Executed service-suite checks include `test_pinned_source_command_rejects_post_manifest_replacement`, `test_fully_rehashed_manifest_and_receipt_pin_drift_is_rejected`, and `test_validation_fails_on_source_unit_and_receipt_tampering`. No real handoff gate has expired or been revalidated.

## 2. Native payload descriptors match immutable bytes — current local result

Source: `deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp::CheckpointAnalyticsExecutionClient`, particularly `submit`, `validate_request`, and `create_sealed_memfd`, validates 1..67,108,864 bytes before snapshot allocation, hashes the owned snapshot, compares the supplied digest, and seals that snapshot.

- **Correct payload and reuse — current local result.** `tests/test_checkpoint_analytics_execution_client_cpp.py::CheckpointAnalyticsExecutionClientCppTest.test_native_client_regression` executed `tests/cpp/checkpoint_analytics_execution_client_test.cpp::test_maximum_snapshot_reuse_and_cleanup`.
- **Incorrect digest — current local result.** The same runner executed `test_local_payload_rejections`, including valid-format wrong-digest rejection before exchange.
- **Payload bounds — current local result.** The native regression covers zero, maximum, and one-byte-over-maximum input before copy/allocation.

The native images were rebuilt twice after the OpenVINO native-policy repair, with matching A/B receipts and image IDs. The affected parity was renewed after this repair: 480 physical executions in 32 groups, with independent tensor-hash comparison against the read-only reference.

## 3. Guardian preserves rejection and diagnostic evidence — current local result for repair regressions; physical evidence pending

Source: `scripts/checkpoint_gstreamer_analytics_bridge.py` validates route, binding, request, and payload facts before reservation. `scripts/checkpoint_gstreamer_analytics_sidecar.py` records counters and first terminal diagnostic. `scripts/benchmark_preparation_evidence_v1.py::snapshot_failed_guardian_evidence` is non-authorizing and leaves the successful-only qualification closure unchanged.

- **Routed sealed wrong-content request — current local result.** Executed coverage includes `tests/test_checkpoint_gstreamer_analytics_sidecar.py::GStreamerAnalyticsSidecarTests.test_production_integrity_failure_keeps_request_diagnostic`, `test_worker_protocol_integrity_failure_is_attributed`, and bridge round-trip cases.
- **Invalid attribution or descriptor — current local result.** Executed sidecar/protocol coverage includes pre-attribution rejection, descriptor count/seal/binding failures, unsafe observations, and descriptor closure; schema tests are in `tests/test_analytics_execution_protocol.py::AnalyticsExecutionProtocolTests`.
- **Concurrent failures or diagnostic persistence error — current local result.** `test_concurrent_terminal_failures_commit_only_first_diagnostic`, `test_diagnostic_persistence_failure_preserves_original_integrity_error`, and `test_pre_authority_failure_cannot_commit_an_orphan_diagnostic` executed successfully.
- **Historical lifecycle — current local result for compatibility.** `tests/test_benchmark_preparation_evidence_v1.py::BenchmarkPreparationEvidenceV1Tests.test_historical_failed_lifecycle_without_diagnostic_is_explicitly_missing`, `test_actual_sidecar_failure_is_consumable`, and the executed successful-closure check `tests/test_publication_policy_qualification_execution_closure_v1.py::PublicationPolicyQualificationExecutionClosureV1Tests.test_wrong_authority_or_nonclean_lifecycle_fails_closed` cover the compatibility boundary.

**Snapshot persistence behavior — current local result.** The collector intentionally creates immutable individual copies, not an atomic directory bundle. `test_late_persistence_failure_retains_partial_evidence_and_allows_fresh_path` covers second- and third-write failures: source evidence remains unchanged, partial output is retained, the same path is rejected, and a fresh path can complete. A later handoff must use a new directory after retained partial output and must not claim atomic-bundle semantics.

## 4. Retry and recovery policy is predictable — current local result for code paths; operational recovery pending

Source: `scripts/full_publication_supervisor.py` and `scripts/full_publication_wsl_user_service_v1.py` default `max_unexpected_retries` to zero, forward it explicitly, use permanent exit 78, and retain transient exit 75 recovery.

- **Retry option omitted — current local result.** Executed checks include `tests/test_full_publication_supervisor.py::FullPublicationSupervisorTests.test_default_budget_stops_exceptions_and_unknown_exits_without_sleep`, `test_cli_default_budget_stops_unknown_exit_after_one_launch`, `tests/test_full_publication_wsl_user_service_v1.py::FullPublicationWslUserServiceTests.test_materialize_api_default_disables_unexpected_retries`, and `test_materialize_cli_default_disables_unexpected_retries`.
- **Transient offload or low storage — current local result for fixtures.** Executed `tests/test_publication_storage_recovery.py` cases cover disk admission, accepted-pair recovery without remeasurement, temporary storage failure, and transport retry. No real storage-pressure recovery run occurred.
- **Remote integrity mismatch — current local result for fixtures.** `tests/test_publication_storage_recovery.py::SeafileReadbackTransportTests.test_completed_wrong_size_or_sha_remains_permanent` executed; no live cloud readback occurred.

## 5. Baselines and affected evidence are reproducible — partially verified

Source: `scripts/publication_matrix.py::build_full_publication_matrix` fixes dimensions, paired order, seed, warmup, and measurement duration. Local reviewed baseline and source-reconciliation evidence are retained privately; this public record does not reference unpublished inventory artifacts.

- **Existing working tree differs from clean checkout — current local result.** Selected source reconciliation is commit `067fa429ab05d0ede56807af0c65e383ca9f5088`. `review-context.json` (44 files) still matches the original dirty runtime. `implementation-baseline.json` records 544 selected paths. The reviewed diff is `reviewed-runtime-reconciliation.json` plus the LF-normalized check; unrelated dirty-tree files were not staged. Later repair commits changed some reconciled bytes by design; the accepted ext4 suite locked the final source/fixture/mirror hashes.
- **Packaged source changes — current local result and accepted physical parity.** All three native probes rebuilt with matching A/B receipts; two dependent workers and all four runtimes rebuilt and passed stock receipt/patch capture. Twelve packaged historical/native checks and ten protocol/bridge/sidecar/worker checks passed. The renewed parity service exited 0 on 480 physical executions in 32 groups of 15. The stock acceptance loader, 3,535 descriptor references and all 480 input/output tensor hashes passed independent verification against A244. Its acceptance identity is `f089b711…`. The final ext4 suite passed on the current source and fixture bytes: 2,515 tests, zero failures, 88 reviewed skips, unchanged source/mirror/fixture/recovered manifests, and 2,272 independently rehashed current files. Its passed result admits the fresh qualification input chain, but does not establish qualification or Q4 completion.
- **Deterministic planning replay — existing coverage, current execution pending.** Relevant coverage is `tests/test_publication_matrix.py::PublicationMatrixTests.test_full_matrix_is_deterministic_complete_and_paired`, `tests/test_full_publication_entrypoint.py::OfflinePublicationPlanTests.test_real_plan_factory_is_offline_read_only_and_needs_no_run_root`, and `tests/test_publication_article_statistics_v1.py::PublicationArticleStatisticsV1Tests.test_twenty_sealed_arms_reproduce_exact_preregistered_paired_inference`. No replay from current accepted preparation identities has run.

## 6. Qualification and Q4 are complete before launch readiness — unverified physical stages

Existing coverage, current execution pending: `tests/test_publication_policy_qualification_pilot_executor_v2.py`, `tests/test_publication_policy_qualification_execution_closure_v1.py`, `tests/test_publication_q4_authority_plan_pipeline_v1.py`, `tests/test_backend_q4_two_phase_source_registry_v1.py`, and `tests/test_backend_q4_two_phase_executor_v1.py` exercise validators, receipts, fail-closed behavior, qualification construction, Q4 phase chains, and 560/280 fixture cardinalities. The executed closure suite does not establish a fresh qualification or Q4 result.

- **A269 has eight historical cells — unverified current physical audit.** Historical cells remain excluded; no new accepted 32-cell attempt exists.
- **Fresh qualification and Q4 succeed — in progress.** The fresh input/preprocessing chain, eight-worker guardian, 32 runtime bundles/four assets, and bounded Savant diagnostic passed their original checks. One fresh 32-cell pilot is active under InvocationID `920b5cfea7474bcdbebb44434459bd3d`; no completed checkpoint or Q4 evidence has been accepted.
- **A prerequisite is missing or fails — existing coverage, current execution pending.** The named closure and Q4 modules contain rejection cases for missing, stale, partial, tampered, and cross-bound inputs; the retained partial pilot and supported resume record real prerequisite failure, but no accepted completion.

## 7. Cloud admission uses an actual dated guarantee — unverified

Existing coverage, current execution pending: `tests/test_full_publication_seafile_capacity_binding.py::FullPublicationSeafileCapacityBindingTests` covers lower-bound attestation, destination binding, rotation/tamper rejection, and legacy-capacity rejection.

- **Confirmation missing — existing coverage, current execution pending; operationally unverified.** The operator supplied a 600-GiB current guaranteed-free-capacity statement for the existing Seafile destination on 2026-09-23. The Q4 sizing-based attestation and live destination check remain pending.
- **Sizing or readback exceeds the guarantee — existing coverage, current execution pending; operationally unverified.** There are no accepted Q4 sizing records or successful live upload/readback evidence.

## 8. Launch handoff preserves the full experiment — implemented; handoff unverified

Source: `scripts/publication_matrix.py` fixes four systems, two codecs, two topologies, seven policies, five deadlines, ten repeats, 2,800 pairs, 5,600 arms, seed 20260323, 30-second warmup, and 180-second measurement. `scripts/full_publication_entrypoint.py` validates frozen matrix identity; `scripts/full_publication_wsl_user_service_v1.py` pins materialized command inputs and zero retries.

- **Unstarted package validates — current local result for materialization guards; physical evidence pending.** Executed service tests include `test_materialization_is_canonical_self_hashed_and_does_not_start`, `test_rendered_unit_passes_systemd_verify`, and `test_start_never_enables_when_preflight_is_not_exact_ready`. Current accepted identities, live preflight, package receipt, sanitized argv record, and zero-start observation are absent.
- **Altered matrix or malformed command — existing coverage, current execution pending.** Relevant tests are `tests/test_full_publication_entrypoint.py::OfflinePublicationPlanTests.test_valid_alternate_2800_pair_matrix_is_permanent_78`, `test_cli_expected_pin_cannot_authorize_an_alternate_matrix`, and `ProductionEntrypointTests.test_plan_preflight_and_run_reject_matrix_identity_drift_before_execution`. The runbook’s Bash and parser checks did run, but no operational command was executed.

## 9. Documentation and conformance are truthful — partially verified

Source: `docs/benchmark-preparation-runbook.md`, `README.md`, `PLAN.md`, and `progress.md` distinguish preparation from full execution.

- **Documentation reviewed — current local result.** Syntax-only Bash, variable allowlist, and parser-option checks passed; the runbook excludes full-run start. A final post-change link and document review remains pending.
- **Required CI is unavailable — merge-blocking.** The latest commit reports no configured workflow entries and no required CI runs. Local tests and OpenSpec document checks are not CI and do not establish merge readiness.

All preparation gates that depend on physical qualification, Q4, capacity, current preflight, handoff, or final CI remain false or unverified. Full-run execution remains unstarted.
