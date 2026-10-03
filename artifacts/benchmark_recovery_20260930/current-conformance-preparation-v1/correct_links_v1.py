"""Correct the unpublished author index; no project source mutations."""
from pathlib import Path
p=Path(__file__).with_name('scenario_reviews_v1.py')
s=p.read_text()
replacements={
"'test_wrong_digest'":"'wrong_hash'",
"'_persist_protocol_failure'":"'persist_protocol_failure'",
"('scripts/publication_storage_recovery.py','reserve')":"(F,'def _disk_admission')",
"(T,'source_manifest')":"(T,'def source_changes')",
"('.gitattributes','BEGIN')":"('.gitattributes','Exact dependency bytes')",
"('.gitattributes','native-source-allowlist.txt')":"('.gitattributes','/deploy/native_gst_probe/publication/deepstream-source-allowlist.txt text eol=lf')",
"('scripts/analytics_peer_identity.py','/proc/sys/kernel/osrelease')":"(S,'/proc/sys/kernel/osrelease')",
"'_validate_container_engine'":"'def _open_pins'",
"(T,'Immediate')":"(T,'class RecordedResult')",
"'select_static_hybrid_map_v1'":"'def select_static_hybrid_map'",
"'test_component_authority_is_rejected_by_both_full_loaders'":"'test_legacy_kind_still_requires_original_image_patch_and_component_exact_four_projection'",
"'test_component_scope_rejects_foreign_requests_before_inference'":"'test_real_memfd_front_foreign_run_or_gva_implementation_or_resource_never_executes'",
"'test_component_context_requires_exact_two_original_operations'":"'test_active_context_binding_rejects_absent_or_changed_context'",
"('scripts/publication_worker_termination_facts_v1.py','OOMKilled')":"(S,'def termination_facts')",
"'test_unrelated_original_journal_cannot_be_used_for_prompt_failure'":"'test_hash_invalid_request_cannot_create_durable_authority'",
"('scripts/analyze_results.py','deadline')":"('scripts/checkpoint_publication_runtime.py','deadline_ms')",
"(RESEARCH+'guest_consumer.py','PinError')":"(RESEARCH+'research_protocol.py','class PinError')",
"(T,'run_suite')":"(T,'def run_test_suite')",
"(Y,'validate_original_denial')":"(Y,'def join_original_userns_denial_v1')",
"(T,'runtime_factory')":"(T,'runtime_prerequisites')",
"'test_shared_component_helpers_are_present_in_runtime_source_closure'":"'test_checkpoint_deepstream_sdk_runtime_v3.CheckpointDeepStreamSdkRuntimeV3Tests.test_production_allowlist_is_exact_multi_entry_runtime_closure','test_checkpoint_openvino_gva_publication_runtime_v3.CheckpointOpenVinoGvaPublicationRuntimeV3Tests.test_production_allowlist_is_exact_transitive_closure','test_checkpoint_savant_sdk_runtime_v3.CheckpointSavantSdkRuntimeV3Tests.test_production_allowlist_is_exact_multi_entry_runtime_closure'",
"'test_rejects_binding_with_mutated_worker_identity'":"'test_external_manifest_rejects_real_identity_and_coverage_drift'",
"'test_reaper_reclaims_only_stale_valid_namespace'":"'test_real_docker29_zero_mount_probe_passes_stale_reaper'",
"'test_default_all_mandatory_metadata_fixture_scope'":"'test_worker_fixture_needs_no_ignored_runtime_artifacts','test_worker_fixture_rejects_missing_and_foreign_metadata'",
"('.ci/integration-test-selection.v1.json','integration_tests')":"('.ci/integration-test-selection.v1.json','integration_declarations')",
"('artifacts/benchmark_recovery_20260930/component-ext4-relocation-preparation-v1/setup_finite_ext4_root_v1.py','def main')":"('artifacts/benchmark_recovery_20260930/component-ext4-relocation-preparation-v1/setup_finite_ext4_root_v1.py','shared_git_object_dependency')",
}
for a,b in replacements.items():
    assert a in s,a
    s=s.replace(a,b)
p.write_text(s,encoding='utf-8',newline='\n')
