# Conformance: fix-decoder-preflight — 5 октября 2026

Авторский вывод: текущая bounded implementation соответствует рассмотренному contract в указанном ниже scope. Source S8, canonical fixtures, latest S8 hosted CI и чтение исходной S3 research-попытки независимо проверены. Этот документ **не является independent final conformance approval**; final review пакета, sync/archive, required CI итогового commit и merge остаются отдельными действиями.

Producer S3 `bdb6cd8104e2dc8d1dd764777bdbcfccbb6ded73` / P1 `3aa35c3b2eedc05d22cf16ba37d470143d080f6b` не ретаргетированы. Observer S8 `470120a3b3f9692775656cdb8114471ab991f14b` / P8 `da0a3f93e060c87b35423729c48388f4e77fab13` прочитал те же immutable originals. Technical COMMENT5409200896 был once-read grant; COMMENT5409320401 принял только scoped result. Это COMMENT, а не выдуманный human APPROVE и не разрешение повторить consumed operation.

## Что фактически закрыто

- [Source/canonical peer](evidence/P8-implementation-independent-v1/review.v1.json): exact3 changed sources, one causal P8 old RED/new GREEN, old60 method ASTs/old170 IDs сохранены; единственное разрешённое старое fixture изменение — timestamp chronology. [Canonical originals](evidence/P8-implementation-v1/) дают root12/nested171,171 unique starts/terminals/successes, source15 before=after и обе реальные15s negative cases. Persisted successful:false/provisional fields сохранены отдельно от genuine outer rc0.
- [S8 hosted original CI peer](evidence/S8-ci-v1/independent-review.v1.json),12260B/SHA256 `b5c920d3dd2e9f0c0594f9537881078e69bd8295244c67460aa6eecbb899b230`: run37249161136/#65/attempt1,3049 discovered,3040 selected,2952 successes,88 audited skips,9 deferred integrations,zero failures/errors; six native builds/three required regressions/root12/nested171. Complete retained source6509 before=after. Это CI exact S8, не будущего archive/doc commit.
- [Scoped cold peer](evidence/S8-cold-v1/independent-review.v1.json),28578B/SHA256 `e394e9fdf4ee3e525f3171994ddf373307170282337ee0ac55d762977531bc5c`: original4×32,128 actual compressed H264 payload hashes,128 sink/src/RGB observations,64 setting pairs; actual control/admission/ACK/PTS/caps/RGB/ABI/backing/source/EOF/EOS joins. [Original report](evidence/S8-cold-v1/original-report.v1.json),128372B/`a423192a…`, actual42.715633661s/FD6→6/223 released holds/close[]/late null. Original producer rc0/container terminal/removal/CID+name absence и named reader closure проверены в разных ownership domains. Global quiescence, reader SID и parent birth/SID не додуманы.

Literal `accepted:false`, `provisional_until_owner_final_close:true`, `publication_ready:false`, model/parity:false и benchmark/native/qualification counts0 остаются исходными. Независимый descriptive research PASS не переписывает их. S2 partial research, S3 namespace-cap cold, S4 CI concurrency, S5 short-pread cold, S6 transcript CI и S6 two-clock refusal остаются своими original FAILED outcomes. Никакой автоматической повторной producer/AU/media операции не было.

## Проверяемый scope и ограничения

[Machine traceability](evidence/conformance-traceability.v1.json) сохраняет полные тела всех20 benchmark requirements,28 R15 clauses/108 other benchmark scenarios и4 diagnostic requirements/12 scenarios:148 mappings. Каждая запись содержит implementation, source anchor, named tests/assertions либо physical/manual evidence, disposition и limits. Original82 scenario/72-task register сохранён как исторический baseline; это не текущий task count. Ниже перечислены все148 IDs; краткий named-test anchor не заменяет остальные tests и raw assertions в JSON.

Current actual task snapshot —50/56. Bounded implementation scope содержит54 obligations; четыре documentation/conformance closures завершаются этим пакетом и root review, а8.4/archive и8.5/archived-head CI/final review/merge остаются непроверенными process gates. Автор checkboxes не меняет. Standing user carte-blanche сохраняет право на завершение, но не подменяет required checks.

R5/S5 — manual LF/raw-checkout evidence; R12/S1 — manual command/path/source review; R14/S2 — оригинальный failed lifecycle; R20/S1 — genuine physical copy/bind/current-source proofs. Для этих строк не создан фиктивный named test. R13/S6 сохраняет проверенный source/manual exact-kind ordering, но direct negative coverage **каждого** full qualification/promotion/Q4/publication consumer отсутствует. Это явный coverage limit, не обещание нового полного теста и не permission пропустить kind guard. Deferred15 legacy execution scenarios сохраняют active strict interfaces; их кампании не запускались. Отдельный historical research/failure-integrity scenario также не переписан текущим PASS.

P8 сохраняет `observed EOF ≤ bookkeeping EOF ≤ actual sink EOS ≤ completion` и inclusive10s от раннего observed EOF, startup45/declaredelapsed10. Нет fitted tolerance или nanosecond precision guarantee для float bookkeeping. Nonflush fixture2M/2M/2.5M/3M и flush100k/100k/200k/3M — рассмотренная timestamp-only exception; outputs/residence/cohorts/−10 deltas/assertions неизменны.

## Требования и каждый сценарий

Статусы ниже: «active» — сохранённые implementation guards и их соответствующая test/manual evidence; «deferred» — strict interface сохранён, legacy execution не заявляется; «historical» — original research/negative disposition; «manual» — physical/document review; «research» — current scoped decoder fixtures/actual original reading; «diagnostic» — ранее принятые offline/source/manual results без replay. Final independent approval всего пакета pending.

### R1 — Benchmark recovery has explicit execution and completion gates

- **R1/S1 — Preparation succeeds** (active). Source `publication_gstreamer_component_cli_v1.py:run_component_pair_v1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_exact_two_original_operations_one_guardian_stop_before_cold`.
- **R1/S2 — Readiness ages or inputs change** (active). Source `publication_gstreamer_component_authority_v1.py:ComponentPinsV1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_source_drift_during_original_terminal_commit_creates_failed_companion`.

### R2 — Native payload descriptors match immutable bytes

- **R2/S1 — Correct payload and reuse** (active). Source `checkpoint_analytics_execution_client.hpp:const std::vector<std::uint8_t> snapshot`; evidence `test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_client_regression`.
- **R2/S2 — Incorrect digest** (active). Source `checkpoint_analytics_execution_client.hpp:snapshot_sha256 == request.raw_input_sha256`; evidence `test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_client_regression`.
- **R2/S3 — Payload bounds** (active). Source `checkpoint_analytics_execution_client.hpp:kMaximumPayloadBytes`; evidence `test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_client_regression`.

### R3 — Guardian preserves rejection and diagnostic evidence

- **R3/S1 — Routed sealed wrong-content request** (active). Source `checkpoint_gstreamer_analytics_sidecar.py:_protocol_failure_diagnostic`; evidence `test_checkpoint_gstreamer_analytics_sidecar.GStreamerAnalyticsSidecarTests.test_production_integrity_failure_keeps_request_diagnostic`.
- **R3/S2 — Invalid attribution or descriptor** (active). Source `checkpoint_gstreamer_analytics_sidecar.py:_protocol_failure_diagnostic`; evidence `test_checkpoint_gstreamer_analytics_sidecar.GStreamerAnalyticsSidecarTests.test_production_rejection_diagnostics_keep_untrusted_fields_unattributed`.
- **R3/S3 — Concurrent failures or diagnostic persistence error** (active). Source `checkpoint_gstreamer_analytics_sidecar.py:persist_protocol_failure`; evidence `test_checkpoint_gstreamer_analytics_sidecar.GStreamerAnalyticsSidecarTests.test_concurrent_terminal_failures_commit_only_first_diagnostic`.
- **R3/S4 — Historical lifecycle** (active). Source `benchmark_preparation_evidence_v1.py:snapshot`; evidence `test_benchmark_preparation_evidence_v1.BenchmarkPreparationEvidenceV1Tests.test_historical_failed_lifecycle_without_diagnostic_is_explicitly_missing`.
- **R3/S5 — Preflight library rejection retains original structured facts** (historical). Source `guest_consumer.py:original-inner-failure.v1.json`; evidence `test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_original_mapped_rejection_persists_before_remaining_pin_retirement`.

### R4 — Retry and recovery policy is predictable

- **R4/S1 — Retry option omitted** (active). Source `full_publication_supervisor.py:max_unexpected_retries`; evidence `test_full_publication_supervisor.FullPublicationSupervisorTests.test_default_budget_stops_exceptions_and_unknown_exits_without_sleep`.
- **R4/S2 — Transient offload or low storage** (deferred). Source `full_publication_runtime.py:def _disk_admission`; evidence `test_publication_storage_recovery.PublicationStorageRecoveryTests.test_space_exhaustion_between_pairs_never_starts_next_pair`.
- **R4/S3 — Remote integrity mismatch** (deferred). Source `seafile_artifact_store.py:sha256`; evidence `test_publication_storage_recovery.SeafileReadbackTransportTests.test_completed_wrong_size_or_sha_remains_permanent`.

### R5 — Baselines and affected evidence are reproducible

- **R5/S1 — Existing working tree differs from clean checkout** (active). Source `publication_policy_qualification_execution_code_closure_v1.py:_receipt_body`; evidence `test_publication_policy_qualification_execution_code_closure_v1.QualificationExecutionCodeClosureV1Tests.test_builder_recursively_freezes_exact_project_sources_and_interpreter`.
- **R5/S2 — Packaged source changes** (active). Source `publication_gstreamer_component_inputs_v1.py:_current_runtime`; evidence `test_publication_runtime_frozen_identity_constants_v1.PublicationRuntimeFrozenIdentityConstantsV1Tests.test_gstreamer_current_runtime_is_exactly_refrozen`.
- **R5/S3 — Deterministic planning replay** (active). Source `full_publication_runner.py:plan`; evidence `test_full_publication_runner.FullPublicationRunnerTests.test_plan_uses_the_frozen_2800_pair_publication_matrix`.
- **R5/S4 — Exact source identity depends on inherited line endings** (active). Source `.gitattributes:Exact dependency bytes`; evidence `test_publication_policy_qualification_execution_code_closure_v1.QualificationExecutionCodeClosureV1Tests.test_loader_rejects_mutate_restore_snapshot_drift`.
- **R5/S5 — Stock build controller requires canonical LF metadata** (manual). Source `.gitattributes:/deploy/native_gst_probe/publication/deepstream-source-allowlist.txt text eol=lf`; evidence `manual/physical evidence; named test unavailable`.
- **R5/S6 — Peer-observer unit runs on a non-WSL Linux CI host** (active). Source `test_analytics_peer_identity.py:def test_observer_reads_exact_proc_file_and_small_docker_projection`; evidence `test_analytics_peer_identity.AnalyticsPeerIdentityAuthorityTests.test_observer_reads_exact_proc_file_and_small_docker_projection`.
- **R5/S7 — Portable unit fixture preserves non-WSL rejection** (active). Source `test_analytics_peer_identity.py:def test_platform_parser_rejects_non_wsl_kernel_bytes`; evidence `test_analytics_peer_identity.AnalyticsPeerIdentityAuthorityTests.test_platform_parser_rejects_non_wsl_kernel_bytes`.

### R6 — Native-probe qualification path is integrated before qualification

- **R6/S1 — Mixed-width queue properties** (active). Source `vast_native_gst_probe.cpp:g_object_class_find_property`; evidence `test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_reset_queue_level_regression`.
- **R6/S2 — Branch identifier shorter than eight bytes** (active). Source `checkpoint_native_policy_client.hpp:branch`; evidence `test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.test_native_policy_identity_regression`.
- **R6/S3 — Policy decision names a manifest identity** (active). Source `checkpoint_gstreamer_runtime.py:native_policy`; evidence `test_checkpoint_runtime.CheckpointRuntimeTests.test_native_policy_worker_specs_inject_frozen_manifest_identities`.
- **R6/S4 — Loaded path differs from manifest backend** (active). Source `checkpoint_native_policy_runtime.py:loaded worker executable`; evidence `test_checkpoint_native_policy_runtime.NativePolicyRuntimeCoordinatorTests.test_cpu_capability_must_match_loaded_binary_and_model_identity`.
- **R6/S5 — Qualification bundle supplies a copied engine client** (active). Source `checkpoint_gstreamer_publication_runtime_v3.py:def _open_pins`; evidence `test_checkpoint_gstreamer_custom_publication_runtime_v3.GstreamerPublicationRuntimeV3Tests.test_container_engine_accepts_the_bundle_copied_client`.
- **R6/S6 — Postdecode prefix queue overflows before policy entry** (active). Source `vast_native_gst_probe.cpp:native_postdecode_preprocess_queue_full_drop_newest`; evidence `test_checkpoint_runtime.CheckpointRuntimeTests.test_native_postdecode_prefix_drop_closes_baseline_after_decode`.
- **R6/S7 — Pre-detector queue overflows before policy entry** (active). Source `vast_native_gst_probe.cpp:native_pre_detector_queue_full_drop_newest`; evidence `test_checkpoint_runtime.CheckpointRuntimeTests.test_explicit_native_branch_drop_resolves_frame_without_creating_join`.
- **R6/S8 — Queue-drop identity or ordering is invalid** (active). Source `vast_native_gst_probe.cpp:resolved_terminal.terminal_reason`; evidence `test_checkpoint_runtime.CheckpointRuntimeTests.test_cpp_analytics_terminal_transport_rejects_identity_and_ambiguous_drop`.
- **R6/S9 — Preprocessing evidence is missing without a verified prefix drop** (active). Source `checkpoint_publication_runtime.py:prefix`; evidence `test_checkpoint_publication_runtime.CheckpointPublicationRuntimeTests.test_prefix_reduction_rejects_fabricated_or_missing_stages_and_forged_lineage`.
- **R6/S10 — Independent and shared prefix-drop coverage** (active). Source `checkpoint_publication_runtime.py:prefix`; evidence `test_checkpoint_publication_runtime.CheckpointPublicationRuntimeTests.test_independent_mixed_and_all_prefix_reduce_only_completed_stages`.
- **R6/S11 — Native stage resource sidecar** (active). Source `checkpoint_publication_runtime.py:resource_events.csv`; evidence `test_checkpoint_publication_runtime.CheckpointPublicationRuntimeTests.test_native_resource_producer_matches_physical_intervals_and_excludes_warmup_drain`.
- **R6/S12 — Pre-check fails** (active). Source `publication_policy_qualification_execution_closure_v1.py:_validate_chain`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_original_failure_no_second_operation_and_authenticated_stop`.

### R7 — Published policy decisions preserve canonical linkage and actual runtime history

- **R7/S1 — Worker traces and runtime sequence gaps enter a measurement cohort** (active). Source `publication_policy_projection_v1.py:project_accepted_decision_v1`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionCoordinatorTests.test_warmup_gap_projects_both_coordinates_without_changing_live_hashes`.
- **R7/S2 — Publication preserves live decision and feedback authority** (active). Source `publication_policy_projection_v1.py:reconstruct_original_decision_v1`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionColdReplayTests.test_original_accepted_hash_and_issued_hash_cannot_be_relabelled`.
- **R7/S3 — Excluded feedback influences a measured adaptive decision** (active). Source `publication_policy_projection_v1.py:_validate_history`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionCoordinatorTests.test_actual_interleaving_preserves_excluded_feedback_and_measurement_state`.
- **R7/S4 — Nonadaptive publication preserves strict closure without adaptive history** (active). Source `publication_policy_projection_v1.py:validate_published_decisions_v1`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionCoordinatorTests.test_incomplete_excluded_decision_blocks_publication`.
- **R7/S5 — Publication mapping or original proof is corrupt** (active). Source `publication_policy_projection_v1.py:_ingress_mapping`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionColdReplayTests.test_physical_mapping_and_original_worker_provenance_are_authoritative`.
- **R7/S6 — Runtime history or projected ordering is incomplete** (active). Source `publication_policy_projection_v1.py:_validate_history`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionColdReplayTests.test_missing_history_and_removed_excluded_predecessor_fail_closed`.
- **R7/S7 — History input exceeds its bound or is malformed** (active). Source `publication_policy_projection_v1.py:read_runtime_history_v1`; evidence `test_checkpoint_native_policy_publication_projection_v1.PublicationProjectionColdReplayTests.test_strict_reader_rejects_duplicate_keys_nonfinite_and_truncation`.
- **R7/S8 — Existing strict historical records are read** (active). Source `publication_policy_projection_v1.py:validate_published_decisions_v1`; evidence `test_publication_policy_history_acceptance_v1.PublicationPolicyHistoryAcceptanceTests.test_legacy_cpu_and_adaptive_acceptance_keep_the_original_exact_names`.
- **R7/S9 — Independent Q4 reader runs under its isolated loader** (deferred). Source `publication_q4_evidence_validator_v4.py:runtime_history`; evidence `test_publication_q4_policy_projection_v1.PublicationQ4PolicyProjectionV1Tests.test_actual_isolated_formal_runner_accepts_projected_cpu_and_rejects_drift`.
- **R7/S10 — Original producer success has rejected cold evidence** (active). Source `publication_gstreamer_component_cli_v1.py:run_component_pair_v1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_original_failure_no_second_operation_and_authenticated_stop`.

### R8 — Qualification reconciles the complete operational request domain

- **R8/S1 — Allowed predecessor and pilot traffic completes** (deferred). Source `publication_operational_request_reconciliation_v1.py:reconcile_operational_request_domain_v1`; evidence `test_publication_operational_boundary_v1.PublicationOperationalBoundaryTests.test_complete_cold_workload_includes_warmup_measurement_and_drain`.
- **R8/S2 — Unknown traffic preserves aggregate totals** (active). Source `publication_operational_request_reconciliation_v1.py:_identity`; evidence `test_publication_operational_boundary_v1.PublicationOperationalBoundaryTests.test_same_count_foreign_front_frame_cannot_pass_complete_cold_join`.
- **R8/S3 — Separate invocations repeat a wire identity** (deferred). Source `publication_operational_request_reconciliation_v1.py:reconcile_operational_request_domain_v1`; evidence `test_publication_operational_boundary_v1.PublicationOperationalBoundaryTests.test_legitimate_repeated_wire_identity_keeps_both_original_operations`.
- **R8/S4 — A measurement request finishes during drain** (active). Source `publication_operational_request_domain_v1.py:validate_native_occurrence_v1`; evidence `test_publication_operational_boundary_v1.PublicationOperationalBoundaryTests.test_complete_cold_workload_includes_warmup_measurement_and_drain`.
- **R8/S5 — Request or terminal capture is incomplete** (active). Source `publication_guardian_operational_recorder_v1.py:terminal`; evidence `test_publication_guardian_operational_recorder_v1.RecorderTests.test_terminal_duplicate_and_unfinished_rejected`.
- **R8/S6 — Operational evidence exceeds bounds or cannot persist** (active). Source `publication_operational_request_domain_v1.py:validate_native_request_source_v1`; evidence `test_publication_operational_request_domain_v1.OperationalRequestDomainTests.test_supported_source_bounds_and_6744_cap_block_before_engine_allocation`.
- **R8/S7 — Domain custody or schema is invalid** (active). Source `publication_operational_request_reconciliation_v1.py:_PinnedFile`; evidence `test_publication_operational_request_domain_v1.OperationalRequestDomainTests.test_stream_reader_rejects_truncation_descriptor_drift_and_wrong_complete_counts`.
- **R8/S8 — Only legacy aggregate evidence exists** (active). Source `publication_policy_qualification_execution_closure_v1.py:load_publication_policy_qualification_execution_closure_v1`; evidence `test_qualification_operational_closure_cold_gate_v1.OperationalClosureColdGateTests.test_legacy_exact_32_closure_remains_readable_but_cannot_promote`.
- **R8/S9 — Source accounting defect is found before pilots** (deferred). Source `publication_policy_qualification_execution_closure_v1.py:_scan_accepted_guardian_workload`; evidence `test_qualification_complete_operational_promotion_gate_v1.CompleteOperationalPromotionGateV1Tests.test_policy_assessment_requires_strict_cold_accounting`.
- **R8/S10 — Component pair reconciles all phases** (active). Source `publication_gstreamer_component_runtime_v1.py:_cold_component_pair_from_held_v1`; evidence `test_publication_operational_boundary_v1.PublicationOperationalBoundaryTests.test_complete_cold_workload_includes_warmup_measurement_and_drain`.

### R9 — Qualification and Q4 are complete before full launch readiness

- **R9/S1 — A269 has eight historical cells** (deferred). Source `publication_policy_qualification_execution_closure_v1.py:load_publication_policy_qualification_execution_closure_v1`; evidence `test_qualification_operational_closure_cold_gate_v1.OperationalClosureColdGateTests.test_legacy_exact_32_closure_remains_readable_but_cannot_promote`.
- **R9/S2 — Fresh qualification and Q4 succeed** (deferred). Source `publication_policy_qualification_execution_closure_v1.py:_validate_chain`; evidence `test_qualification_complete_operational_promotion_gate_v1.CompleteOperationalPromotionGateV1Tests.test_current_accepted_policy_guardian_requires_strict_cold_accounting`.
- **R9/S3 — A prerequisite is missing or fails** (active). Source `full_publication_runtime.py:preflight`; evidence `test_full_publication_runtime.FullPublicationRuntimeTests.test_preflight_fails_closed_on_readiness_capacity_or_owned_namespace_corruption`.

### R10 — Cloud admission uses an actual dated guarantee

- **R10/S1 — Confirmation missing** (deferred). Source `seafile_operator_capacity_attestation_v2.py:operator`; evidence `test_full_publication_seafile_capacity_binding.FullPublicationSeafileCapacityBindingTests.test_legacy_capacity_number_is_not_a_production_authority`.
- **R10/S2 — Sizing or readback exceeds the guarantee** (deferred). Source `seafile_capacity_attestation_v1.py:500`; evidence `test_seafile_operator_capacity_attestation_v2.SeafileOperatorCapacityAttestationV2Tests.test_sizing_above_operator_lower_bound_fails_closed`.

### R11 — Launch handoff preserves the full experiment

- **R11/S1 — Unstarted package validates** (deferred). Source `full_publication_wsl_user_service_v1.py:materialize`; evidence `test_full_publication_wsl_user_service_v1.FullPublicationWslUserServiceTests.test_materialization_is_canonical_self_hashed_and_does_not_start`.
- **R11/S2 — Altered matrix or malformed command** (deferred). Source `full_publication_runner.py:_validate_matrix`; evidence `test_full_publication_supervisor.FullPublicationSupervisorTests.test_subprocess_invoker_requires_exact_frozen_contract_arguments`.

### R12 — Documentation and conformance are truthful

- **R12/S1 — Documentation reviewed** (manual). Source `gstreamer-component-benchmark-runbook.md:CPU`; evidence `manual/physical evidence; named test unavailable`.
- **R12/S2 — Required CI is unavailable** (active). Source `run_ci_checks.py:main`; evidence `test_run_ci_checks.RunCiChecksTests.test_required_native_skip_does_not_become_a_pass`.
- **R12/S3 — Clean checkout lacks the frozen model assets** (active). Source `prepare_ci_model_assets.py:_download`; evidence `test_prepare_ci_model_assets.PrepareCiModelAssetsTests.test_clean_empty_checkout_acquires_exact_eight_without_input_changes`.
- **R12/S4 — Hosted test failure or interruption occurs before the suite report** (active). Source `run_ci_checks.py:class RecordedResult`; evidence `test_run_ci_checks.RunCiChecksTests.test_failure_traceback_is_flushed_before_the_suite_returns`.

### R13 — Recovery first proves a bounded genuine native pair

- **R13/S1 — Forced-resource diagnostic pair completes** (active). Source `publication_gstreamer_component_runtime_v1.py:execute_component_operation_v1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_exact_two_original_operations_one_guardian_stop_before_cold`.
- **R13/S2 — Static-hybrid inputs are not yet materialized** (deferred). Source `publication_policy_contract.py:def select_static_hybrid_map`; evidence `test_publication_policy_contract.PublicationPolicyContractTests.test_static_hybrid_calibration_is_exhaustive_mixed_and_deterministic`.
- **R13/S3 — Diagnostic authority or accounting is incomplete** (active). Source `publication_gstreamer_component_authority_v1.py:validate_component_original_native_row_v1`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentPhysicalAuthorityTests.test_original_seven_roles_and_front_workers_are_independently_bound`.
- **R13/S4 — Selected component authority materializes** (active). Source `publication_gstreamer_component_inputs_v1.py:materialize_component_authority_v1`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentPhysicalAuthorityTests.test_real_physical_selected_eight_keep_complete_declaration_verbatim`.
- **R13/S5 — Selected physical or declaration row drifts** (active). Source `publication_gstreamer_component_authority_v1.py:_load`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentPhysicalAuthorityTests.test_resealed_sibling_policy_count_and_model_binding_fail`.
- **R13/S6 — Component authority reaches a full entrypoint** (active). Source `publication_guardian_component_preprocessing_contract_v1.py:AUTHORITY_KIND`; evidence `test_publication_guardian_component_preprocessing_contract_v1.ComponentPreprocessingTests.test_legacy_kind_still_requires_original_image_patch_and_component_exact_four_projection`.
- **R13/S7 — Component request is outside its original pair** (active). Source `publication_guardian_component_preprocessing_contract_v1.py:_scope`; evidence `test_publication_guardian_component_preprocessing_contract_v1.ComponentFrontTests.test_real_memfd_front_foreign_run_or_gva_implementation_or_resource_never_executes`.

### R14 — Operations retain bounded ownership and worker termination facts

- **R14/S1 — Worker exits during a diagnostic** (active). Source `checkpoint_gstreamer_analytics_sidecar.py:termination`; evidence `test_checkpoint_gstreamer_analytics_sidecar.GStreamerAnalyticsSidecarTests.test_runtime_worker_crash_interrupts_front_service`.
- **R14/S2 — Historical guardian already failed** (manual). Source `original-g-service_lifecycle.v1.json:failed_stop_nonpublication`; evidence `manual/physical evidence; named test unavailable`.
- **R14/S3 — Original launcher terminates during container ID publication** (active). Source `publication_operational_container_custody_v1.py:measurement_container_custody_v1`; evidence `test_publication_operational_container_custody_v1.OriginalContainerCompositionTests.test_start_persistence_failure_recovers_owned_name_and_cleans_original_cid`.
- **R14/S4 — Early broker setup fails with a validated durable journal** (active). Source `backend_publication_process_supervisor_v3.py:_posix_broker_entry_v3`; evidence `test_backend_publication_broker_terminal_v3.BackendPublicationBrokerTerminalV3Tests.test_normal_early_setup_failure_commits_original_failed_terminal`.
- **R14/S5 — Quiescent broker has no durable terminal response** (active). Source `backend_publication_process_supervisor_v3.py:wait_journal_result`; evidence `test_backend_publication_broker_terminal_v3.BackendPublicationBrokerTerminalV3Tests.test_quiescent_failed_stdout_is_not_durable_authority_and_fails_promptly`.
- **R14/S6 — Validated worker transport fails before frontend exit is visible** (active). Source `checkpoint_gstreamer_analytics_sidecar.py:_record_production_failure`; evidence `test_checkpoint_gstreamer_analytics_sidecar.GStreamerAnalyticsSidecarTests.test_response_send_epipe_captures_live_validated_worker_before_teardown`.
- **R14/S7 — Worker history contains frequent health-check events** (active). Source `checkpoint_gstreamer_analytics_sidecar.py:event=die`; evidence `test_publication_worker_termination_facts_v1.TerminationTests.test_terminal_event_argv_is_original_cid_only_and_unchanged_bounded`.
- **R14/S8 — Original native measurement has a failed captured terminal** (active). Source `publication_operational_process_custody_v1.py:_write_failure_channel`; evidence `test_publication_operational_process_custody_v1.ProcessCustodyTests.test_failed_measurement_retains_actual_binary_channels_and_unchanged_terminal`.

### R15 — Scientific interpretation matches the executed workload

- **R15/S1 — Relative quality passes despite absolute deadline misses** (research). Source `publication_gstreamer_component_runtime_v1.py:_descriptive_arm_metrics_v1`; evidence `test_checkpoint_publication_runtime.CheckpointPublicationRuntimeTests.test_acceptance_summary_serializes_unavailable_metrics_as_json_null`.
- **R15/S2 — Only proxy or partial resource evidence exists** (research). Source `publication_gstreamer_component_runtime_v1.py:_component_flags`; evidence `test_checkpoint_publication_runtime.CheckpointPublicationRuntimeTests.test_acceptance_summary_serializes_unavailable_metrics_as_json_null`.
- **R15/S3 — Frozen policy labels are placement aliases** (research). Source `publication_policy_contract.py:select_ready_task`; evidence `test_publication_policy_contract.PublicationPolicyContractTests.test_all_seven_policies_emit_replayable_but_unaccepted_records`.
- **R15/S4 — Deadline and attributed elapsed measurements are saturated or confounded** (research). Source `publication_gstreamer_component_runtime_v1.py:_descriptive_comparison_v1`; evidence `test_benchmark_contract.BenchmarkContractTests.test_throughput_uses_completed_frames_per_window`.
- **R15/S5 — Decoder mechanism research precedes an adopted regime** (research). Source `guest_consumer.py:Guest.run`; evidence `test_research_protocol.ProtocolTests.test_actual_sink_eos_keeps_fixed_central_cohort_and_marks_flush_insufficient`.
- **R15/S6 — Research fails before source or decoder admission** (research). Source `guest_consumer.py:Guest.record_inner_failure`; evidence `test_pin_diagnostics_v3.InnerFailureTests.test_exclusive_diagnostic_collision_keeps_original_cause_and_prior_bytes`.
- **R15/S7 — A strict research file pin fails without original path facts** (research). Source `research_protocol.py:Pin.__init__`; evidence `test_pin_diagnostics_v3.PinDiagnosticsTests.test_actual_oversize_retains_original_size_and_limit_before_hash`.
- **R15/S8 — A mapped library has several hard links** (research). Source `research_protocol.py:verify_mapped_file`; evidence `test_mapped_inputs_v4.MappedInputTests.test_actual_mapped_hardlink_accepts_join_but_default_still_rejects`.
- **R15/S9 — Reviewed mapped-input correction precedes another research attempt** (research). Source `guest_consumer.py:Guest.mapped_library_pins`; evidence `test_mapped_inputs_v4.MappedInputTests.test_actual_guest_maps_snapshot_joins_cached_pin_and_backing_identity`.
- **R15/S10 — Unchanged intake runs before mechanism research completes** (research). Source `publication_gstreamer_component_authority_v1.py:_load`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentPhysicalAuthorityTests.test_real_physical_selected_eight_keep_complete_declaration_verbatim`.
- **R15/S11 — Selected mapping and visible file identities differ** (research). Source `research_protocol.py:readonly_backing_probe`; evidence `test_successor_v6.BackingSuccessorTests.test_bridge_wrong_permissions_offset_deleted_and_missing_range_reject`.
- **R15/S12 — A mapped file is reused through the package cache** (research). Source `guest_consumer.py:Guest.pin`; evidence `test_successor_v6.BackingSuccessorTests.test_cached_bridge_rechecks_real_ancestor_mode_after_probe_retirement`.
- **R15/S13 — Alive mapping observations belong to self or the original source child** (research). Source `guest_consumer.py:Guest.mapped_library_pins`; evidence `test_research_protocol.IndependentColdTests.test_source_start_requires_ready_loaded_observation_and_enabling_intent`.
- **R15/S14 — A backing observation or its retirement fails** (research). Source `research_protocol.py:readonly_backing_probe`; evidence `test_setup_v2.ControllerModeTests.test_controller_close_error_preserves_original_body_failure`.
- **R15/S15 — Reviewed planning bytes outlive task progress and archive** (research). Source `controller.py:Controller.git_command`; evidence `test_research_protocol.IndependentColdTests.test_current_task_progress_does_not_replace_reviewed_p_blobs`.
- **R15/S16 — Reviewed source and immutable physical inputs have separate roots** (research). Source `controller.py:Controller.prepare_reviewed_inputs`; evidence `test_research_protocol.IndependentColdTests.test_source_and_reviewed_planning_raw_mutations_are_rejected_by_git`.
- **R15/S17 — Execution mode is explicit and sealed end to end** (research). Source `controller.py:Controller.__init__`; evidence `test_setup_v2.ControllerModeTests.test_metadata_mode_rejects_any_original_run_directory`.
- **R15/S18 — Metadata-only preflight completes without a source cohort** (research). Source `guest_consumer.py:Guest.preflight`; evidence `test_setup_v2.ControllerModeTests.test_metadata_fast_exit_still_checks_shared_body_deadline`.
- **R15/S19 — Inherited and successor regressions are actually discovered by CI** (research). Source `test_decoder_research_v6.py:validate_nested`; evidence `test_decoder_research_v6.DecoderResearchV6CaptureLifecycleTests.test_healthy_tiny_capture_observes_terminal_close_and_returns_after_final_receipt`.
- **R15/S20 — One metadata-only deployment precedes independent cold review** (research). Source `cold_reader.py:Replay.external`; evidence `test_research_protocol.IndependentColdTests.test_complete_metadata_positive_uses_real_git_and_holds_all_files`.
- **R15/S21 — Accepted preflight permits one separately dispatched unchanged experiment** (research). Source `guest_consumer.py:Guest.execute`; evidence `test_research_protocol.ProtocolTests.test_exact32_no_extra_duplicate_foreign_or_late_admission`.
- **R15/S22 — Original successor research evidence is cold reconstructed** (research). Source `cold_reader.py:Replay.packets`; evidence `test_research_protocol.IndependentColdTests.test_P6_transport_partial_positive_reads_complete_header_text_and_payload`.
- **R15/S23 — External containment extends the controller owner record** (research). Source `cold_reader.py:validate_owner`; evidence `test_research_protocol.IndependentColdTests.test_P2_each_core_identity_and_exact_controller_schema_is_required`.
- **R15/S24 — Guest and controller retain different paths for the same terminal** (research). Source `cold_reader.py:Replay.guest`; evidence `test_research_protocol.IndependentColdTests.test_P2_real_guest_alias_and_physical_terminal_descriptor_join`.
- **R15/S25 — A corrected observer reads an immutable original attempt** (research). Source `cold_reader.py:Replay.__init__`; evidence `test_research_protocol.IndependentColdTests.test_P2_current_C_and_original_S_files_keep_separate_physical_guards`.
- **R15/S26 — A cached file is checked in a later owned phase** (research). Source `guest_consumer.py:Guest.pin`; evidence `test_research_protocol.ProtocolTests.test_P3_cached_pin_rejects_expired_current_phase_despite_live_original_deadline`.
- **R15/S27 — A reviewed phase-clock correction precedes fresh source-bound observations** (research). Source `guest_consumer.py:Guest.pin`; evidence `test_research_protocol.ProtocolTests.test_P3_cached_pin_rejects_expired_current_phase_despite_live_original_deadline`.
- **R15/S28 — Bounded mapped evidence is independently replayed after producer completion** (research). Source `cold_reader.py:Held.document`; evidence `test_research_protocol.IndependentColdTests.test_P4_mapping_cap_cannot_admit_general_docs_or_foreign_paths_kinds`.

### R16 — Component release closes durable results and repository evidence

- **R16/S1 — Full benchmark finishes with valid negative results** (deferred). Source `full_publication_runner.py:_finalize_locked`; evidence `test_full_publication_runner.FullPublicationRunnerTests.test_complete_run_executes_each_pair_in_sequence_and_finalizes`.
- **R16/S2 — Accepted pairs exist when transient offload fails** (deferred). Source `full_publication_runner.py:_run_locked`; evidence `test_full_publication_runner.FullPublicationRunnerTests.test_cloud_failure_resumes_from_durable_acceptance_without_rerunning_arms`.
- **R16/S3 — Completion or final repository gate is missing** (active). Source `publication_gstreamer_component_cli_v1.py:run_component_pair_v1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_original_failure_no_second_operation_and_authenticated_stop`.
- **R16/S4 — Selected component release finishes** (active). Source `publication_gstreamer_component_runtime_v1.py:_component_flags`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_exact_two_original_operations_one_guardian_stop_before_cold`.

P5 exporter addendum: POSIX held-root lock precedes bootstrap; old bundle/PhysicalIO/Windows guards unchanged. Actual module8 and current S8 CI support the named race/cleanup cases; old S4 CI remains FAILED.

### R17 — CPU CI observation preserves native process invariants

- **R17/S1 — Full-suite worker enters strict native containment** (active). Source `ci_external_test_observer_v1.py:child_trace_handler`; evidence `test_ci_external_test_observer_v1.ExternalObserverTests.test_real_signal_dump_has_one_native_task_and_actual_response`.
- **R17/S2 — Scheduled stack request is late or absent** (active). Source `ci_external_test_observer_v1.py:observe_test_child`; evidence `test_ci_external_test_observer_v1.ExternalObserverTests.test_long_native_call_records_delay_and_possible_coalescing`.
- **R17/S3 — Trace channel overflows or persistence fails** (active). Source `ci_external_test_observer_v1.py:observe_test_child`; evidence `test_ci_external_test_observer_v1.ExternalObserverTests.test_trace_overflow_retains_exact_prefix_and_sticky_failure`.
- **R17/S4 — Full-suite child crashes or is interrupted** (active). Source `ci_external_test_observer_v1.py:observe_test_child`; evidence `test_ci_external_test_observer_v1.ExternalObserverTests.test_original_nonzero_and_signal_are_not_success`.
- **R17/S5 — Namespace setup emits a generic denial** (active). Source `ci_namespace_diagnostic_v1.py:observe_namespace_setup_v1`; evidence `test_ci_namespace_diagnostic_v1.NamespaceDiagnosticTests.test_exact_first_unshare_failure_delegates_once_and_retains_original_errno`.
- **R17/S6 — Exact executable userns policy denial is observed** (active). Source `ci_userns_profile_v1.py:held_ci_userns_profile_v1`; evidence `test_ci_userns_profile_v1.UsernsProfileTests.test_original_shape_joins_only_exact_interpreter_pid_boot_operation_and_time`.
- **R17/S7 — Observer repair passes focused checks** (active). Source `run_ci_checks.py:main`; evidence `test_ci_test_selection_v1.SelectionContracts.test_current_broker_and_operational_custody_cannot_be_deferred`.
- **R17/S8 — Original audit clock differs from the fine syscall clock** (active). Source `ci_namespace_diagnostic_v1.py:instrument_namespace_calls`; evidence `test_ci_namespace_diagnostic_v1.NamespaceDiagnosticTests.test_coarse_samples_enclose_original_user_unshare_and_failed_setgroups_once`.
- **R17/S9 — New coarse-clock evidence is missing or inconsistent** (active). Source `ci_namespace_diagnostic_v1.py:instrument_namespace_calls`; evidence `test_ci_userns_profile_v1.AuditClockTests.test_missing_and_malformed_new_clock_evidence_cannot_downgrade`.
- **R17/S10 — A legacy denial record has no new clock contract** (active). Source `ci_userns_profile_v1.py:expected_clock_contract_version`; evidence `test_ci_userns_profile_v1.AuditClockTests.test_explicit_legacy_retains_original_strict_rejection_and_cannot_take_v2`.

### R18 — CI executes explicit portable contracts and preserves physical integration obligations

- **R18/S1 — Hosted executable is an alias and repository imports are isolated** (active). Source `run_ci_checks.py:canonical`; evidence `test_run_ci_checks.RunCiChecksTests.test_real_alias_launcher_uses_canonical_interpreter_for_suite_and_assets`.
- **R18/S2 — Native build succeeds but a runtime factory is absent** (active). Source `run_ci_checks.py:def gstreamer_factory_facts`; evidence `test_run_ci_checks.RunCiChecksTests.test_missing_runtime_factory_remains_a_failed_prerequisite`.
- **R18/S3 — Shared imports reach new component helpers in a sibling image** (active). Source `runtime-source-allowlist.txt:publication_guardian_component_preprocessing_contract_v1.py`; evidence `test_checkpoint_deepstream_runtime_source_closure_v3.DeepStreamRuntimeSourceClosureV3Tests.test_production_allowlist_is_exact_multi_entry_runtime_closure`.
- **R18/S4 — Pure contract tests depend on ignored historical fixture files** (active). Source `test_checkpoint_external_execution_manifest.py:worker_manifest_fixture`; evidence `test_checkpoint_external_execution_manifest.ExternalExecutionManifestTests.test_external_manifest_rejects_real_identity_and_coverage_drift`.
- **R18/S5 — Manifest omits a portable test or hides a mandatory failure** (active). Source `ci_test_selection_v1.py:select_portable_suite_v1`; evidence `test_ci_test_selection_v1.SelectionContracts.test_new_tests_remain_mandatory_and_original_cases_order_are_preserved`.
- **R18/S6 — Actual physical integration prerequisites are unavailable or historical** (active). Source `integration-test-selection.v1.json:integration_declarations`; evidence `test_ci_test_selection_v1.SelectionContracts.test_missing_reason_or_real_capability_is_rejected`.
- **R18/S7 — Portable lane succeeds with remaining campaign obligations** (active). Source `run_ci_checks.py:main`; evidence `test_ci_test_selection_v1.SelectionContracts.test_exact_skip_identity_and_reason_are_audited_without_success_claim`.

### R19 — Selected pair owns one physically held validation session

- **R19/S1 — Borrowed context is foreign or closed** (active). Source `publication_gstreamer_component_inputs_v1.py:_SelectedComponentSession`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentHeldSessionTests.test_raw_dict_foreign_pid_root_authority_and_closed_session_fail`.
- **R19/S2 — One original pair traverses repeated runtime stages** (active). Source `publication_gstreamer_component_inputs_v1.py:_model_material`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentHostPredicatesTests.test_actual_materializer_commits_last_and_raw_refusal_leaves_only_owned_prefix`.
- **R19/S3 — Public validator runs independently** (active). Source `publication_gstreamer_component_inputs_v1.py:held_selected_component_inputs_v1`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentHeldSessionTests.test_public_held_inputs_retains_independent_complete_validation`.
- **R19/S4 — Held source or live engine facts drift** (active). Source `publication_gstreamer_component_authority_v1.py:ComponentPinsV1`; evidence `test_publication_gstreamer_component_inputs_v1.ComponentHeldSessionTests.test_same_bytes_replacement_is_rejected_before_live_image_observation`.
- **R19/S5 — Cold consumer fails after real native arms** (active). Source `publication_policy_qualification_execution_code_closure_v1.py:load_execution_code_closure_v1`; evidence `test_publication_policy_qualification_execution_code_closure_v1.QualificationExecutionCodeClosureV1Tests.test_loader_rejects_mutate_restore_snapshot_drift`.
- **R19/S6 — Runtime improvement is assessed** (active). Source `publication_gstreamer_component_cli_v1.py:_PhaseTimelineV1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_original_pair_retains_bounded_phase_starts_and_real_terminals`.

### R20 — Relocated selected execution preserves genuine physical validation

- **R20/S1 — Genuine finite inputs are copied to a new root** (manual). Source `setup_finite_ext4_root_v1.py:shared_git_object_dependency`; evidence `manual/physical evidence; named test unavailable`.
- **R20/S2 — A historical closure or execution receipt is reused after relocation** (active). Source `publication_policy_qualification_execution_code_closure_v1.py:load_execution_code_closure_v1`; evidence `test_publication_policy_qualification_execution_code_closure_v1.QualificationExecutionCodeClosureV1Tests.test_loader_rejects_mutate_restore_snapshot_drift`.
- **R20/S3 — A relocated pair completes or exceeds its original deadline** (active). Source `publication_gstreamer_component_cli_v1.py:run_component_pair_v1`; evidence `test_publication_gstreamer_component_cli_v1.ComponentCliTests.test_original_failure_no_second_operation_and_authenticated_stop`.

### DIAG/R1 — Current status distinguishes completed release and incomplete campaigns

- **DIAG/R1/S1 — Previous release actions are already complete** (diagnostic). Source `PLAN.md:14`; evidence `manual/physical evidence; named test unavailable`.
- **DIAG/R1/S2 — Full input closures are stale** (diagnostic). Source `PLAN.md:35`; evidence `manual/physical evidence; named test unavailable`.

### DIAG/R2 — Offline diagnostics retain original populations and identities

- **DIAG/R2/S1 — Complete original evidence is analyzed** (diagnostic). Source `analyze_component_latency_v1.py:112`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_cli_real_entrypoint_uses_only_selected_fixture_directory`.
- **DIAG/R2/S2 — Diagnostic deadline is explicitly supplied** (diagnostic). Source `analyze_component_latency_v1.py:332`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_required_deadline_is_finite_and_positive`.
- **DIAG/R2/S3 — Cohort boundary wall clocks differ** (diagnostic). Source `analyze_component_latency_v1.py:175`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_recorded_cohort_early_ingress_and_shuffled_rows_are_preserved`.
- **DIAG/R2/S4 — Malformed or inconsistent evidence is supplied** (diagnostic). Source `analyze_component_latency_v1.py:48`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_missing_input_invalid_utf8_and_duplicate_headers_fail`.
- **DIAG/R2/S5 — Output is occupied** (diagnostic). Source `analyze_component_latency_v1.py:472`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_occupied_output_preserves_existing_files_and_source`.

### DIAG/R3 — Latency diagnostics report observed envelopes and unknown service components

- **DIAG/R3/S1 — Critical-path branch varies** (diagnostic). Source `analyze_component_latency_v1.py:87`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_shared_critical_branches_and_nonadditive_medians`.
- **DIAG/R3/S2 — Queue timestamps are equal by construction** (diagnostic). Source `analyze_component_latency_v1.py:385`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_promoted_zero_queue_span_does_not_claim_zero_true_wait`.
- **DIAG/R3/S3 — Optional policy evidence is unavailable** (diagnostic). Source `analyze_component_latency_v1.py:294`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_missing_optional_policy_reports_unavailable_not_zero`.

### DIAG/R4 — Actual four-arm review preserves scientific limits

- **DIAG/R4/S1 — Decoder envelope dominates GPU latency** (diagnostic). Source `four-arm-report.md:13`; evidence `test_component_latency_diagnostics.ComponentLatencyDiagnosticsTests.test_promoted_zero_queue_span_does_not_claim_zero_true_wait`.
- **DIAG/R4/S2 — Next performance experiment is proposed** (diagnostic). Source `four-arm-report.md:32`; evidence `manual/physical evidence; named test unavailable`.

## Научная интерпретация и неисполненная работа

Column nearest-rank p50 central16 (rank8): front-gate default1013.664823ms/zero1009.732428ms; underbody default2002.406025ms/zero2004.325781ms. Statistical median16 paired zero−default deltas:−2.445557ms и+1.648382ms. Это разные статистики; колонный p50 не even-column median. Central pre-EOS16/16 во всех run не доказывает stationarity; tail после EOS — flush-only. Один serial pair на clip с reversed order между разными clips не даёт causal property effect/confidence interval.

Paired observed RGB equality не independent software decode/reference. Residence включает queueing/backpressure, не pure NVDEC service/busy/utilization. Meaningful zero-setting benefit не установлен. Для future engineering default/unset остаётся provisional только после отдельно accepted derived-YUV/RGB/EOS intake; adopted decoder regime пока false. Future finite24/12, six-stream100ms, accuracy/energy, qualification32/Q4/1120/5600 не исполнены и не приняты. Следующий route — material/reference и native lifecycle/STOP/owner-abort/partial-I/O/reap/Gst-teardown fault gates, не новый property sweep.

## Release disposition

В author scope critical implementation discrepancy не заявлен; manual/direct-test limits описаны выше и остаются предметом independent final review. [Release gates](release-gates.md) сохраняют pending sync/archive/latest-head CI/final review/merge. AST equality, green structure или ранний S8 CI не позволяют автору предзакрыть их. Этот report и machine JSON требуют независимого semantic review до process completion.
