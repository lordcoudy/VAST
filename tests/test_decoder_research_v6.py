"""One isolated, bounded CPU fixture suite; no research/container/GI authority."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

ROOT=Path(__file__).resolve().parents[1]
CODE=ROOT/'artifacts/benchmark_recovery_20260930/decoder-research-implementation-v6'
MODULES=('test_mapped_inputs_v4','test_pin_diagnostics_v3','test_preflight_diagnostics_v5',
    'test_research_protocol','test_setup_v2','test_successor_v6')
CHANNEL_MAX=1024*1024
INHERITED_IDS=frozenset((
    'test_mapped_inputs_v4.MappedInputTests.test_actual_guest_maps_snapshot_joins_cached_pin_and_backing_identity',
    'test_mapped_inputs_v4.MappedInputTests.test_actual_mapped_hardlink_accepts_join_but_default_still_rejects',
    'test_mapped_inputs_v4.MappedInputTests.test_cached_default_cannot_inherit_mapping_policy_or_wrong_identity',
    'test_mapped_inputs_v4.MappedInputTests.test_correct_identity_does_not_bypass_type_size_or_expected_hash',
    'test_mapped_inputs_v4.MappedInputTests.test_deleted_ambiguous_malformed_missing_inode_and_absent_name_fail',
    'test_mapped_inputs_v4.MappedInputTests.test_mapped_byte_mutation_remains_full_epoch_failure',
    'test_mapped_inputs_v4.MappedInputTests.test_mapped_link_count_mutation_remains_full_epoch_failure',
    'test_mapped_inputs_v4.MappedInputTests.test_maps_limit_reads_only_original_limit_plus_one_sentinel',
    'test_mapped_inputs_v4.MappedInputTests.test_named_substitution_cannot_match_original_mapping_identity',
    'test_mapped_inputs_v4.MappedInputTests.test_repeated_rows_keep_original_rows_and_conflicts_or_aliases_fail',
    'test_mapped_inputs_v4.MappedInputTests.test_snapshot_cap_failure_cannot_authorize_mapped_pin',
    'test_mapped_inputs_v4.MappedInputTests.test_tiny_original_child_uses_same_actual_source_pid_maps_parser',
    'test_mapped_inputs_v4.MappedInputTests.test_wrong_device_inode_and_invalid_tuple_reject_before_hash_and_close',
    'test_pin_diagnostics_v3.InnerFailureTests.test_actual_maps_failure_retains_first_inner_stack_before_cleanup',
    'test_pin_diagnostics_v3.InnerFailureTests.test_actual_readonly_fd_write_failure_closes_and_keeps_original_cause',
    'test_pin_diagnostics_v3.InnerFailureTests.test_diagnostic_cap_failure_is_sticky_without_truncating_original_error',
    'test_pin_diagnostics_v3.InnerFailureTests.test_exclusive_diagnostic_collision_keeps_original_cause_and_prior_bytes',
    'test_pin_diagnostics_v3.PinDiagnosticsTests.test_actual_directory_type_rejects_and_closes_fds',
    'test_pin_diagnostics_v3.PinDiagnosticsTests.test_actual_oversize_retains_original_size_and_limit_before_hash',
    'test_pin_diagnostics_v3.PinDiagnosticsTests.test_hardlink_preserves_original_rejection_and_actual_predicate_facts',
    'test_pin_diagnostics_v3.PinDiagnosticsTests.test_missing_resolve_retains_original_exception_and_unavailable_stats',
    'test_pin_diagnostics_v3.PinDiagnosticsTests.test_requested_symlink_and_resolved_target_are_distinct_original_facts',
    'test_pin_diagnostics_v3.PinDiagnosticsTests.test_substituted_inode_retains_held_and_named_failure_epochs',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_actual_readonly_primary_write_keeps_original_cause_and_retires_fds',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_actual_trace_write_failure_does_not_replace_structured_primary',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_close_companion_write_failure_stays_nonzero_and_reports_capture_error',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_exclusive_collision_keeps_prior_bytes_and_original_primary',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_metadata_close_failure_keeps_primary_and_retires_all_remaining_fds',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_original_mapped_rejection_persists_before_remaining_pin_retirement',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_outer_record_cap_failure_preserves_original_cause_without_truncation',
    'test_preflight_diagnostics_v5.PreflightDiagnosticsTests.test_terminal_persistence_failure_raises_original_primary_and_retires_fds',
    'test_research_protocol.ProtocolTests.test_active_rgb_excludes_padding_and_rejects_bad_layout_before_hash',
    'test_research_protocol.ProtocolTests.test_actual_sink_eos_keeps_fixed_central_cohort_and_marks_flush_insufficient',
    'test_research_protocol.ProtocolTests.test_bounded_auxiliary_real_python_child_drains_both_pipes_to_eof',
    'test_research_protocol.ProtocolTests.test_bounded_auxiliary_timeout_retains_original_failed_child',
    'test_research_protocol.ProtocolTests.test_clean_eof_truncation_and_invalid_json',
    'test_research_protocol.ProtocolTests.test_current_binary_requires_its_enabling_ack_and_next_declaration_waits_previous',
    'test_research_protocol.ProtocolTests.test_decoder_clock_negative_and_missing_join_reject',
    'test_research_protocol.ProtocolTests.test_digest_identity_flags_and_cadence_fail_closed',
    'test_research_protocol.ProtocolTests.test_evidence_caps_reserve_failure_receipt_and_preserve_failed_prefix',
    'test_research_protocol.ProtocolTests.test_exact32_no_extra_duplicate_foreign_or_late_admission',
    'test_research_protocol.ProtocolTests.test_external_previous_run_needs_sealed_terminal_before_next_start',
    'test_research_protocol.ProtocolTests.test_external_watchdog_does_not_complete_partial_or_unsealed_phase_file',
    'test_research_protocol.ProtocolTests.test_header_oversize_and_declared_length_mismatch_before_payload_allocation',
    'test_research_protocol.ProtocolTests.test_held_file_and_ancestor_epochs_reject_mutation_and_rename',
    'test_research_protocol.ProtocolTests.test_pair_complete_multiset_pixels_caps_order_and_tail_are_required',
    'test_research_protocol.ProtocolTests.test_post_receipt_crossing_is_immutable_failed_and_cannot_enable_next_run',
    'test_research_protocol.ProtocolTests.test_raw_aggregate_rejected_before_second_ack',
    'test_research_protocol.ProtocolTests.test_true_unsigned_dts_and_duration_are_retained',
    'test_research_protocol.ProtocolTests.test_truncated_text_payload_and_source_line_preserve_every_consumed_byte',
    'test_research_protocol.ProtocolTests.test_wrong_second_schedule_rejected_using_received_duration',
    'test_setup_v2.SetupTests.test_bad_cid_keeps_failure_but_cleans_positive_exact_name_owner',
    'test_setup_v2.SetupTests.test_cleanup_command_cannot_consume_final_deadline_reserve',
    'test_setup_v2.SetupTests.test_complete_cid_optional_newline_and_physical_hash',
    'test_setup_v2.SetupTests.test_delayed_name_publication_is_not_earlier_removal_absence',
    'test_setup_v2.SetupTests.test_fast_natural_launcher_exit_binds_complete_cid_and_removes_before_both_absences',
    'test_setup_v2.SetupTests.test_initialization_doc_cap_fails_before_single_intended_call',
    'test_setup_v2.SetupTests.test_malformed_and_oversize_cid_retain_actual_failure_stat',
    'test_setup_v2.SetupTests.test_original_initializer_failure_keeps_stage_type_and_bounded_trace_without_fallback',
    'test_setup_v2.SetupTests.test_original_inode_substitution_symlink_and_multiple_links_reject',
    'test_setup_v2.SetupTests.test_original_live_launcher_is_reaped_before_engine_fixture_observation',
    'test_setup_v2.SetupTests.test_original_partial_file_publication_stays_pending_until_stable_complete',
    'test_setup_v2.SetupTests.test_outer_failed_body_preserves_cause_when_original_cleanup15_is_crossed',
    'test_setup_v2.SetupTests.test_outer_successful_body_crosses_original_cleanup15_and_rejects_success',
    'test_setup_v2.SetupTests.test_single_explicit_list_initializer_records_actual_fixture_callable_and_stages',
    'test_setup_v2.SetupTests.test_unresolved_publication_keeps_unknown_and_never_claims_removal_absence',
))

# Actual isolated discovery 246d3e: freeze inherited66 plus every reviewed new case.
APPROVED_NEW_IDS=frozenset((
    'test_research_protocol.IndependentColdTests.test_complete_metadata_positive_uses_real_git_and_holds_all_files',
    'test_research_protocol.IndependentColdTests.test_complete_research_positive_reconstructs128_au64_pairs_and_legal_ack_interleaving',
    'test_research_protocol.IndependentColdTests.test_controller_positive_body_does_not_override_post_close_failure',
    'test_research_protocol.IndependentColdTests.test_current_task_progress_does_not_replace_reviewed_p_blobs',
    'test_research_protocol.IndependentColdTests.test_external_provisional_success_needs_genuine_final_tool_rc',
    'test_research_protocol.IndependentColdTests.test_failed_main_invalidates_prefix_after_real_held_epoch_mutation',
    'test_research_protocol.IndependentColdTests.test_failed_main_retains_prefix_and_independent_close_status_without_promotion',
    'test_research_protocol.IndependentColdTests.test_fd_namespace_byte_and_json_limits_refuse_without_unbounded_acquisition',
    'test_research_protocol.IndependentColdTests.test_flush_only_outputs_remain_insufficient_without_changing_cohorts',
    'test_research_protocol.IndependentColdTests.test_mapping_bridge_observer_owner_range_and_close_are_replayed',
    'test_research_protocol.IndependentColdTests.test_metadata_positive_cannot_authorize_foreign_owner_or_partial_maps',
    'test_research_protocol.IndependentColdTests.test_old_provisional_success_with_close_failure_companion_is_rejected',
    'test_research_protocol.IndependentColdTests.test_original_admission_types_u64_and_reserved_duration_are_rejected',
    'test_research_protocol.IndependentColdTests.test_raw_payload_corruption_has_independent_valid_prefix_only',
    'test_research_protocol.IndependentColdTests.test_real_leaf_replacement_links_and_close_fault_release_other_handles',
    'test_research_protocol.IndependentColdTests.test_resealed_journal_pts_caps_digest_eos_order_and_cohort_corruption_is_refused',
    'test_research_protocol.IndependentColdTests.test_resealed_raw_header_payload_ack_control_and_trailing_corruption_is_refused',
    'test_research_protocol.IndependentColdTests.test_source_and_reviewed_planning_raw_mutations_are_rejected_by_git',
    'test_research_protocol.IndependentColdTests.test_source_start_requires_ready_loaded_observation_and_enabling_intent',
    'test_research_protocol.IndependentColdTests.test_unknown_extra_output_and_foreign_mode_cannot_borrow_positive_body',
    'test_setup_v2.ControllerModeTests.test_controller_close_error_preserves_original_body_failure',
    'test_setup_v2.ControllerModeTests.test_controller_close_error_retires_remaining_pins_and_blocks_provisional_success',
    'test_setup_v2.ControllerModeTests.test_metadata_fast_exit_still_checks_shared_body_deadline',
    'test_setup_v2.ControllerModeTests.test_metadata_mode_rejects_any_original_run_directory',
    'test_setup_v2.ControllerModeTests.test_metadata_null_result_zero_runs_is_valid_after_original_close',
    'test_setup_v2.ControllerModeTests.test_metadata_rejects_research_result_or_run_namespace',
    'test_setup_v2.ControllerModeTests.test_missing_cli_mode_fails_before_engine_or_output_creation',
    'test_setup_v2.ControllerModeTests.test_mode_mismatch_and_close_failure_never_promote',
    'test_setup_v2.ReviewedInputTests.test_actual_git_stdout_stream_cap_rejects_and_reaps_owned_child',
    'test_setup_v2.ReviewedInputTests.test_changed_auxiliary_owner_join_prevents_signal_and_preserves_cap_failure',
    'test_setup_v2.ReviewedInputTests.test_expired_shared_prelaunch_deadline_rejects_before_git_child',
    'test_setup_v2.ReviewedInputTests.test_failed_initial_auxiliary_owner_observation_never_signals_unknown_group',
    'test_setup_v2.ReviewedInputTests.test_foreign_repository_and_unreviewed_source_drift_are_rejected',
    'test_setup_v2.ReviewedInputTests.test_git_capture_close_failure_still_retires_other_original_stream',
    'test_setup_v2.ReviewedInputTests.test_missing_runtime_source_and_nonexact_source_parameter_are_rejected',
    'test_setup_v2.ReviewedInputTests.test_oversized_reviewed_blob_is_rejected_before_raw_copy',
    'test_setup_v2.ReviewedInputTests.test_owned_auxiliary_is_killed_at_actual_remaining_shared_deadline',
    'test_setup_v2.ReviewedInputTests.test_reviewed_planning_must_be_ancestor_of_exact_source',
    'test_setup_v2.ReviewedInputTests.test_supported_native_git_worktree_is_accepted',
    'test_setup_v2.ReviewedInputTests.test_task_progress_and_archived_paths_use_exact_raw_reviewed_blobs',
    'test_successor_v6.BackingSuccessorTests.test_actual_full_maps_rejects_duplicate_but_classifier_retains_it',
    'test_successor_v6.BackingSuccessorTests.test_anonymous_inode_zero_and_strict_ranges_permissions_offsets',
    'test_successor_v6.BackingSuccessorTests.test_bridge_wrong_permissions_offset_deleted_and_missing_range_reject',
    'test_successor_v6.BackingSuccessorTests.test_buffer_acquisition_error_retires_mapping_without_release_obligation',
    'test_successor_v6.BackingSuccessorTests.test_cached_bridge_rechecks_real_ancestor_mode_after_probe_retirement',
    'test_successor_v6.BackingSuccessorTests.test_cached_bridge_uses_same_proof_and_expected_size_and_sha',
    'test_successor_v6.BackingSuccessorTests.test_cached_expected_size_cannot_be_ignored',
    'test_successor_v6.BackingSuccessorTests.test_cached_same_bytes_rewrite_during_rehash_keeps_full_epoch_guard',
    'test_successor_v6.BackingSuccessorTests.test_cancellation_primary_retires_probe_and_propagates_original_identity',
    'test_successor_v6.BackingSuccessorTests.test_duplicate_full_bridge_snapshot_rejects_and_retires',
    'test_successor_v6.BackingSuccessorTests.test_expired_real_probe_rejects_before_success',
    'test_successor_v6.BackingSuccessorTests.test_failed_ancestor_fstat_retires_partially_acquired_fd',
    'test_successor_v6.BackingSuccessorTests.test_final_snapshot_persistence_error_never_authorizes_collection',
    'test_successor_v6.BackingSuccessorTests.test_growth_after_admission_cannot_enlarge_original_hash_read_bound',
    'test_successor_v6.BackingSuccessorTests.test_held_bytes_changed_during_probe_remain_epoch_failure',
    'test_successor_v6.BackingSuccessorTests.test_original_selected_owner_and_complete_ranges_are_bracketed',
    'test_successor_v6.BackingSuccessorTests.test_original_tiny_child_exit_during_collection_is_rejected',
    'test_successor_v6.BackingSuccessorTests.test_owner_change_and_selected_range_change_refuse_before_final_snapshot',
    'test_successor_v6.BackingSuccessorTests.test_owner_reads_use_original_channel_limit_and_sentinel',
    'test_successor_v6.BackingSuccessorTests.test_parse_primary_survives_release_and_mapping_close_errors',
    'test_successor_v6.BackingSuccessorTests.test_pin_close_attempts_all_descriptors_and_preserves_first_error',
    'test_successor_v6.BackingSuccessorTests.test_real_held_fd_bridge_accepts_explicit_synthetic_visible_device',
    'test_successor_v6.BackingSuccessorTests.test_real_readonly_probe_retires_export_mapping_and_fd',
    'test_successor_v6.BackingSuccessorTests.test_selected_ambiguous_escapes_fail_classifier_and_actual_collector',
    'test_successor_v6.BackingSuccessorTests.test_self_selected_bracket_excludes_only_actual_unique_bridge',
    'test_successor_v6.BackingSuccessorTests.test_unreleased_real_export_causes_genuine_mapping_close_failure',
    'test_successor_v6.BackingSuccessorTests.test_wrong_backing_identity_fails_and_retires_real_probe',
    'test_successor_v6.BackingSuccessorTests.test_wrong_pybuffer_field_offsets_reject_before_mapping_or_c_api',
    'test_successor_v6.GuestConstructionSuccessorTests.test_code_descriptor_drift_and_nonfinite_budget_retire_acquired_pins',
    'test_successor_v6.GuestConstructionSuccessorTests.test_remaining_budget_and_exact_mounted_code_are_bound',
    'test_successor_v6.GuestConstructionSuccessorTests.test_required_mode_validated_before_metadata_and_no_fd_leak',
    'test_successor_v6.GuestModeSuccessorTests.test_metadata_completion_has_no_source_cohort_result_or_research_authority',
    'test_successor_v6.GuestModeSuccessorTests.test_metadata_final_close_obeys_remaining_prelaunch_not_new600_clock',
    'test_successor_v6.GuestModeSuccessorTests.test_metadata_original_preflight_error_keeps_identity_and_zero_runs',
    'test_successor_v6.GuestModeSuccessorTests.test_metadata_pin_close_failure_blocks_provisional_success',
    'test_successor_v6.GuestModeSuccessorTests.test_metadata_unexpected_run_namespace_blocks_body_completion',
    'test_successor_v6.GuestModeSuccessorTests.test_missing_or_mismatched_mode_never_enters_preflight',
    'test_successor_v6.GuestModeSuccessorTests.test_primary_survives_late_companion_write_and_close_failure',
    'test_successor_v6.GuestModeSuccessorTests.test_research_exact_four_order_and_complete_pairing_are_preserved',
    'test_successor_v6.GuestModeSuccessorTests.test_research_first_failure_stops_before_later_setting',
    'test_successor_v6.GuestRunRetirementTests.test_registry_reader_start_failure_preserves_primary_and_retires_auxiliary_fds',
    'test_successor_v6.GuestRunRetirementTests.test_run_drain_handoff_and_retirement_keep_real_fd_and_first_cause',
    'test_successor_v6.GuestRunRetirementTests.test_run_partial_pipe_acquisition_retires_real_first_pair',
    'test_successor_v6.GuestRunRetirementTests.test_run_retirement_errors_preserve_primary_and_attempt_remaining',
    'test_research_protocol.IndependentColdTests.test_P2_real_six_core_and_eight_external_owner_records_join',
    'test_research_protocol.IndependentColdTests.test_P2_real_guest_alias_and_physical_terminal_descriptor_join',
    'test_research_protocol.IndependentColdTests.test_P2_each_core_identity_and_exact_controller_schema_is_required',
    'test_research_protocol.IndependentColdTests.test_P2_external_parent_child_shape_and_containment_are_required',
    'test_research_protocol.IndependentColdTests.test_P2_terminal_paths_size_hash_and_mode_are_not_interchangeable',
    'test_research_protocol.IndependentColdTests.test_P2_distinct_git_C_executes_against_frozen_S_and_raw_P2_after_archive',
    'test_research_protocol.IndependentColdTests.test_P2_paired_observer_arguments_and_exact_C_ancestry_are_required',
    'test_research_protocol.IndependentColdTests.test_P2_current_C_and_original_S_files_keep_separate_physical_guards',
    'test_research_protocol.IndependentColdTests.test_P2_raw_amendment_blob_bound_is_enforced',
    'test_research_protocol.ProtocolTests.test_P3_cached_pin_uses_live_current_phase_after_original_deadline_expires',
    'test_research_protocol.ProtocolTests.test_P3_cached_pin_rejects_expired_current_phase_despite_live_original_deadline',
    'test_research_protocol.IndependentColdTests.test_P4_metadata_namespace_accepts_actual_36_leaf_research_shape',
    'test_research_protocol.IndependentColdTests.test_P4_metadata_namespace_accepts_40_and_rejects_41',
    'test_research_protocol.IndependentColdTests.test_P4_run_33_and_controller_129_leaves_still_reject',
    'test_research_protocol.IndependentColdTests.test_P4_typed_before_and_closed_mapping_documents_above_1MiB_accept',
    'test_research_protocol.IndependentColdTests.test_P4_mapping_document_2MiB_boundary_and_one_byte_overflow',
    'test_research_protocol.IndependentColdTests.test_P4_mapping_cap_cannot_admit_general_docs_or_foreign_paths_kinds',
    'test_research_protocol.IndependentColdTests.test_P6_transport_partial_positive_reads_complete_header_text_and_payload',
    'test_research_protocol.IndependentColdTests.test_P6_transport_zero_progress_refuses_without_spinning',
    'test_research_protocol.IndependentColdTests.test_P6_transport_partial_progress_keeps_original_absolute_deadline',
    'test_research_protocol.IndependentColdTests.test_P8_distinct_source_eof_clocks_preserve_order_and_original_drain_bound',
))



def descriptor(path):
    path=Path(path).resolve(strict=True)
    before=path.stat()
    if before.st_size>CHANNEL_MAX:raise RuntimeError('fixture descriptor1MiB cap')
    with path.open('rb') as stream:raw=stream.read(CHANNEL_MAX+1)
    after=path.stat()
    epoch=lambda info:[getattr(info,name) for name in
        ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')]
    if len(raw)>CHANNEL_MAX or epoch(before)!=epoch(after) or len(raw)!=before.st_size:
        raise RuntimeError('fixture descriptor changed or exceeded cap')
    return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch':epoch(after)}


def write_json(path,value):
    stream=Path(path).open('x',encoding='utf8');primary=None
    try:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    except BaseException as exc:primary=exc
    finally:
        for name,retire in (('flush',lambda:(stream.flush(),os.fsync(stream.fileno()))),('close',stream.close)):
            try:retire()
            except BaseException as exc:
                if primary is None:primary=exc
                else:primary.add_note('owned JSON writer '+name+': '+type(exc).__name__+': '+str(exc))
    if primary is not None:raise primary


def child_owner(pid,alive=False):
    """Bounded stdlib-only process facts; generic producer names stay out of this parent."""
    def text(path):
        with Path(path).open('rb') as stream:raw=stream.read(CHANNEL_MAX+1)
        if len(raw)>CHANNEL_MAX:raise RuntimeError('fixture owner observation cap')
        return raw.decode('ascii')
    raw=text(f'/proc/{pid}/stat');suffix=raw.rsplit(')',1)[1].split()
    if not raw.startswith(str(pid)+' (') or len(suffix)<20 or (alive and suffix[0] in ('Z','X','x')):
        raise RuntimeError('fixture original child owner not alive/valid')
    fields=dict(line.split(':',1) for line in text(f'/proc/{pid}/status').splitlines() if ':' in line)
    return {'pid':pid,'ppid':int(suffix[1]),'pgid':int(suffix[2]),'sid':int(suffix[3]),
        'starttime_ticks':int(suffix[19]),'uid':int(fields['Uid'].split()[0]),
        'gid':int(fields['Gid'].split()[0]),'boot_id':text('/proc/sys/kernel/random/boot_id').strip()}


def flatten(suite):
    for test in suite:
        if isinstance(test,unittest.TestSuite):yield from flatten(test)
        else:yield test


def validate_nested(report):
    ids=report['selected_test_ids'];outcomes=report['outcomes']
    if report.get('isolated') is not True or report.get('dont_write_bytecode') is not True:
        raise AssertionError('nested fixture process was not isolated -I -B')
    if len(INHERITED_IDS)!=66 or len(APPROVED_NEW_IDS)!=105 or INHERITED_IDS & APPROVED_NEW_IDS or \
            len(ids)!=len(set(ids)) or set(ids)!=INHERITED_IDS | APPROVED_NEW_IDS:
        raise AssertionError('full frozen inherited66 inventory missing or duplicated')
    if not any(name.startswith('test_successor_v6.') for name in ids):
        raise AssertionError('new successor cases missing')
    if set(outcomes)!=set(ids) or set(report['test_origins'])!=set(ids):
        raise AssertionError('individual outcome/origin inventory differs')
    if type(report['tests_run']) is not int or report['tests_run']!=len(ids) or \
            any(type(report[key]) is not int or report[key]!=0 for key in
                ('failures','errors','skips','expected_failures','unexpected_successes')) or \
            any(value!='success' for value in outcomes.values()):
        raise AssertionError('nested suite has failure/error/skip/incomplete outcome')
    if type(report['elapsed_s']) not in (int,float) or not math.isfinite(report['elapsed_s']) or not 0<=report['elapsed_s']<=120:
        raise AssertionError('nested suite elapsed time invalid')
    if set(report['module_origins'])!=set(MODULES):
        raise AssertionError('required full suite modules differ')
    for module,path in report['module_origins'].items():
        if Path(path).resolve()!=CODE/(module+'.py'):
            raise AssertionError('foreign nested module origin')
    for name,path in report['test_origins'].items():
        if name.split('.',1)[0] not in MODULES or Path(path).resolve()!=CODE/(name.split('.',1)[0]+'.py'):
            raise AssertionError('foreign individual case origin')
    if report['source_before']!=report['source_after']:
        raise AssertionError('fixture source changed during original execution')
    for name,path in report['runtime_module_origins'].items():
        if name not in ('controller','guest_consumer','research_protocol') or Path(path).resolve()!=CODE/(name+'.py'):
            raise AssertionError('foreign generic runtime import')
    if set(report['runtime_module_origins'])!={'controller','guest_consumer','research_protocol'}:
        raise AssertionError('runtime import inventory incomplete')


def child(output):
    """Import generic research names only in this fresh -I -B child."""
    if sys.version_info[:3]!=(3,12,3) or sys.implementation.name!='cpython':
        raise RuntimeError('fixture suite requires CPython3.12.3')
    output=Path(output).resolve(strict=True)
    fixtures=output/'local-fixtures';fixtures.mkdir();tempfile.tempdir=str(fixtures)
    source_paths=[CODE/(name+'.py') for name in MODULES]
    source_paths += [CODE/name for name in ('controller.py','guest_consumer.py','research_protocol.py')]
    source_paths += [ROOT/'artifacts/benchmark_recovery_20260930/decoder-independent-v6/cold_reader.py']
    source_paths += [Path(__file__).resolve(),*(ROOT/'scripts'/name for name in
        ('run_ci_checks.py','ci_external_test_observer_v1.py','ci_test_selection_v1.py','ci_userns_profile_v1.py'))]
    before=[descriptor(path) for path in source_paths]
    sys.path.insert(0,str(CODE))
    suite=unittest.defaultTestLoader.discover(str(CODE),pattern='test_*.py',top_level_dir=str(CODE))
    cases=list(flatten(suite));ids=[case.id() for case in cases]
    origins={case.id():str(Path(sys.modules[case.__class__.__module__].__file__).resolve()) for case in cases}
    modules={name:str(Path(sys.modules[name].__file__).resolve()) for name in MODULES}
    if len(ids)!=len(set(ids)) or set(ids)!=INHERITED_IDS | APPROVED_NEW_IDS:
        raise RuntimeError('discovery dropped or duplicated inherited cases')
    spec=importlib.util.spec_from_file_location('vast_decoder_v6_ci_recording',ROOT/'scripts/run_ci_checks.py')
    ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)
    began=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2,resultclass=ci.RecordedResult).run(suite)
    report={'artifact_kind':'vast_decoder_v6_fixture_suite_v1','python':sys.version,
        'isolated':bool(sys.flags.isolated),'dont_write_bytecode':bool(sys.dont_write_bytecode),
        'selected_test_ids':ids,'test_origins':origins,'module_origins':modules,'tests_run':result.testsRun,
        'runtime_module_origins':{name:str(Path(sys.modules[name].__file__).resolve())
            for name in ('controller','guest_consumer','research_protocol')},
        'outcomes':result.outcomes,'failures':len(result.failures),'errors':len(result.errors),
        'skips':len(result.skipped),'expected_failures':len(result.expectedFailures),
        'unexpected_successes':len(result.unexpectedSuccesses),'elapsed_s':time.monotonic()-began,
        'source_before':before,'source_after':[descriptor(path) for path in source_paths],
        'hardware_acceptance':False,'research_executed':False}
    write_json(output/'nested-suite.v1.json',report)
    validate_nested(report)
    if any(fixtures.iterdir()):raise RuntimeError('fixture namespace remained after its owners closed')
    return 0


def capture(output):
    """Actual originals, 120s child clock and a separate <=15s owned final close."""
    output=Path(output)
    argv=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'--v6-child',str(output)]
    began=time.monotonic();deadline=began+120
    paths={'stdout':output/'original.stdout','stderr':output/'original.stderr'}
    writers={};sizes={};process=None;streams={};primary=None;cleanup_started=None
    original_owner=None;close_errors=[];signal_observation=None
    def failed(exc,scope):
        nonlocal primary
        if primary is None:primary=exc
        else:close_errors.append(scope+': '+type(exc).__name__+': '+str(exc))
        close_errors.extend(scope+': '+note for note in getattr(exc,'__notes__',()))
    def final_clock(stage):
        observed=time.monotonic()
        if observed-cleanup_started>15:
            failed(RuntimeError('fixture cleanup15s cap after '+stage),'finalization deadline')
        return observed
    try:
        for name,path in paths.items():
            writers[name]=path.open('xb');sizes[name]=0
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=True)
        streams={process.stdout:'stdout',process.stderr:'stderr'}
        original_owner=child_owner(process.pid)
        if original_owner['ppid']!=os.getpid() or original_owner['uid']!=os.getuid() or original_owner['gid']!=os.getgid() or \
                original_owner['pgid']!=process.pid or original_owner['sid']!=process.pid:
            raise RuntimeError('fixture original child/group ownership differs')
        while streams:
            if time.monotonic()>=deadline:raise RuntimeError('V6 fixture child120s cap')
            for stream in select.select(list(streams),[],[],min(.1,max(0,deadline-time.monotonic())))[0]:
                raw=os.read(stream.fileno(),65536)
                if not raw:streams.pop(stream);continue
                name=streams[stream]
                if sizes[name]+len(raw)>CHANNEL_MAX:raise RuntimeError('fixture original channel1MiB cap')
                writers[name].write(raw);sizes[name]+=len(raw)
        process.wait(timeout=max(.001,deadline-time.monotonic()))
        if time.monotonic()>=deadline:raise RuntimeError('V6 fixture child120s cap after fast exit')
    except BaseException as exc:
        failed(exc,'original body')
    finally:
        cleanup_started=time.monotonic()
        if process is not None and process.poll() is None:
            try:
                current=child_owner(process.pid,alive=True)
                signal_observation={'owner':current,'sent':False}
                if current!=original_owner or current['ppid']!=os.getpid() or current['pgid']!=process.pid or current['sid']!=process.pid:
                    raise RuntimeError('fixture current live original owner/group differs')
                os.killpg(process.pid,signal.SIGKILL);signal_observation['sent']=True
            except BaseException as exc:close_errors.append('owned signal unavailable: '+str(exc))
        if process is not None:
            try:process.wait(timeout=max(.001,15-(time.monotonic()-cleanup_started)))
            except BaseException as exc:close_errors.append('owned child reap: '+str(exc))
            for stream in (process.stdout,process.stderr):
                if stream is None:continue
                try:stream.close()
                except BaseException as exc:close_errors.append('owned pipe close: '+str(exc))
        for stream in writers.values():
            try:stream.flush();os.fsync(stream.fileno())
            except BaseException as exc:close_errors.append('owned log flush: '+str(exc))
            finally:
                try:stream.close()
                except BaseException as exc:close_errors.append('owned log close: '+str(exc))
    observed=final_clock('original retirement')
    logs_closed=all(stream.closed for stream in writers.values())
    if not logs_closed:failed(RuntimeError('owned original log close unavailable'),'original retirement')
    if process is not None and process.returncode!=0 and primary is None:
        failed(RuntimeError('isolated V6 child returned '+str(process.returncode)),'original child')
    descriptors=dict.fromkeys(paths)
    for name in writers:
        if time.monotonic()-cleanup_started>15:break
        if not writers[name].closed:continue
        try:descriptors[name]=descriptor(paths[name])
        except BaseException as exc:failed(exc,'closed original descriptor '+name)
        observed=final_clock('closed original descriptor '+name)
    nested=None
    if primary is None and not close_errors:
        try:
            nested=json.loads((output/'nested-suite.v1.json').read_text())
            validate_nested(nested)
            events=[]
            for raw in paths['stderr'].read_text().splitlines():
                try:value=json.loads(raw)
                except (ValueError,UnicodeError):continue
                if isinstance(value,dict) and value.get('event') in ('test_started','test_terminal'):events.append(value)
            selected=set(nested['selected_test_ids'])
            for kind in ('test_started','test_terminal'):
                rows=[row['test_id'] for row in events if row['event']==kind]
                if len(rows)!=len(selected) or set(rows)!=selected:
                    raise AssertionError('original per-case '+kind+' inventory differs')
            if any(row.get('outcome')!='success' or not 0<=row.get('elapsed_s',-1)<=120
                   for row in events if row['event']=='test_terminal'):
                raise AssertionError('original terminal outcomes/times differ')
        except BaseException as exc:failed(exc,'nested validation')
        observed=final_clock('nested validation')
    report={'artifact_kind':'vast_decoder_v6_fixture_capture_v1','argv':argv,
        'pid':None if process is None else process.pid,
        'returncode':None if process is None else process.returncode,
        'failure':None if primary is None else str(primary),
        'failure_type':None if primary is None else type(primary).__name__,'elapsed_s':observed-began,
        'child_owner':original_owner,'signal_observation':signal_observation,'close_errors':close_errors,
        'cleanup_elapsed_s':observed-cleanup_started,'logs_closed':logs_closed,
        'acquired_logs':list(writers),'child_reaped':process is not None and process.poll() is not None,
        **descriptors,'research_executed':False,'successful':False,
        'provisional_until_owner_final_close':True}
    try:write_json(output/'adapter-terminal.v1.json',report)
    except BaseException as exc:failed(exc,'provisional terminal persist/close')
    observed=final_clock('provisional terminal persist/close')
    if primary is None and not close_errors:
        try:
            terminal=descriptor(output/'adapter-terminal.v1.json')
            observed=final_clock('provisional terminal descriptor')
            if primary is None:
                write_json(output/'adapter-final-close.v1.json',{
                    'artifact_kind':'vast_decoder_v6_fixture_final_close_v1','terminal':terminal,
                    'observed_after_terminal_persist_monotonic_s':observed,
                    'elapsed_s':observed-began,'cleanup_elapsed_s':observed-cleanup_started,
                    'candidate_success':True,'successful':False,'research_executed':False,
                    'provisional_until_capture_return':True})
        except BaseException as exc:failed(exc,'final close receipt persist/close')
        observed=final_clock('final close receipt persist/close')
    if primary is not None or close_errors:
        failure_record={'artifact_kind':'vast_decoder_v6_fixture_close_failure_v1',
            'successful':False,'failure':None if primary is None else str(primary),
            'failure_type':None if primary is None else type(primary).__name__,
            'close_errors':close_errors,'observed_after_finalization_monotonic_s':observed,
            'elapsed_s':observed-began,'cleanup_elapsed_s':observed-cleanup_started,
            'logs_closed':logs_closed,'child_reaped':process is not None and process.poll() is not None,
            'provisional_until_failure_receipt_close':True,'research_executed':False}
        receipt_error=None
        try:write_json(output/'adapter-close-failure.v1.json',failure_record)
        except BaseException as exc:receipt_error=exc  # One attempt; no recursive capture or overwrite.
        raise AssertionError('isolated V6 suite failed; originals: '+str(output)+
            '; primary: '+str(primary)+'; cleanup: '+repr(close_errors)+
            '; failure receipt: '+str(receipt_error)) from primary
    return nested


class DecoderResearchV6CaptureLifecycleTests(unittest.TestCase):
    """Real files/children; only the deadline clock and nested outcomes are synthetic."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.output=Path(self.temp.name)
        self.real_popen=subprocess.Popen
        self.real_open=Path.open
        self.real_monotonic=time.monotonic
        self.clock_shift=0
        self.writers=[]

    def tearDown(self):
        for writer in self.writers:
            if not writer.closed:writer.close()
        self.temp.cleanup()

    def retain_writer(self,path,*args,**kwargs):
        writer=self.real_open(path,*args,**kwargs)
        if path.parent==self.output and path.name in ('original.stdout','original.stderr') and args==('xb',):
            self.writers.append(writer)
        return writer

    def tiny_child(self,argv,**kwargs):
        # A genuine owned CPython child exercises capture; these declared outcomes
        # are explicit synthetic fixture packets, never a claim that inner cases ran.
        ids=sorted(INHERITED_IDS | APPROVED_NEW_IDS)
        report={'isolated':True,'dont_write_bytecode':True,'selected_test_ids':ids,
            'outcomes':dict.fromkeys(ids,'success'),'test_origins':{
                name:str(CODE/(name.split('.',1)[0]+'.py')) for name in ids},
            'module_origins':{name:str(CODE/(name+'.py')) for name in MODULES},
            'runtime_module_origins':{name:str(CODE/(name+'.py')) for name in
                ('controller','guest_consumer','research_protocol')},
            'tests_run':len(ids),'failures':0,'errors':0,'skips':0,'expected_failures':0,
            'unexpected_successes':0,'elapsed_s':.1,
            'source_before':[{'explicit_synthetic_capture_fixture':True}],
            'source_after':[{'explicit_synthetic_capture_fixture':True}]}
        write_json(self.output/'nested-suite.v1.json',report)
        program="import json,sys,time;ids="+repr(ids)+";"+\
            "[print(json.dumps(dict(event=kind,test_id=name,outcome='success',elapsed_s=.1)),file=sys.stderr,flush=True) "+\
            "for name in ids for kind in ('test_started','test_terminal')];time.sleep(.1)"
        return self.real_popen([sys.executable,'-I','-B','-c',program],**kwargs)

    def observe_failure(self):
        path=self.output/'adapter-close-failure.v1.json'
        self.assertTrue(path.is_file(),'failed finalization needs its own exclusive failure receipt')
        failure=json.loads(path.read_text())
        self.assertFalse(failure['successful'])
        return failure

    def test_partial_log_acquisition_retires_first_writer_and_keeps_collision(self):
        (self.output/'original.stderr').write_bytes(b'original collision')
        with mock.patch.object(Path,'open',lambda path,*a,**kw:self.retain_writer(path,*a,**kw)), \
                mock.patch.object(subprocess,'Popen') as launch:
            with self.assertRaises(Exception):capture(self.output)
        self.assertFalse(launch.called)
        self.assertEqual(len(self.writers),1)
        self.assertTrue(self.writers[0].closed,'first actual writer leaked after second exclusive open failed')
        self.assertEqual((self.output/'original.stderr').read_bytes(),b'original collision')
        self.assertIn('FileExistsError',self.observe_failure()['failure_type'])

    def test_invalid_executable_retires_both_actual_logs_and_keeps_launch_cause(self):
        def invalid(argv,**kwargs):
            return self.real_popen([str(self.output/'absent-executable')],**kwargs)
        with mock.patch.object(Path,'open',lambda path,*a,**kw:self.retain_writer(path,*a,**kw)), \
                mock.patch.object(subprocess,'Popen',invalid):
            with self.assertRaises(Exception):capture(self.output)
        self.assertEqual(len(self.writers),2)
        self.assertTrue(all(writer.closed for writer in self.writers),'Popen acquisition left log FDs open')
        self.assertIn('absent-executable',self.observe_failure()['failure'])

    def test_descriptor_failure_after_real_close_is_retained(self):
        def failed_descriptor(path):
            self.assertTrue(all(writer.closed for writer in self.writers))
            raise OSError('explicit descriptor failure after actual log close')
        with mock.patch.object(Path,'open',lambda path,*a,**kw:self.retain_writer(path,*a,**kw)), \
                mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.dict(capture.__globals__,descriptor=failed_descriptor):
            with self.assertRaises(Exception):capture(self.output)
        self.assertIn('explicit descriptor failure',self.observe_failure()['failure'])

    def test_descriptor_time_after_real_close_cannot_bypass_cleanup_clock(self):
        original=descriptor
        def delayed(path):
            result=original(path)
            self.assertTrue(all(writer.closed for writer in self.writers))
            self.clock_shift=16  # Explicit synthetic deadline only, after actual FD close/hash.
            return result
        with mock.patch.object(Path,'open',lambda path,*a,**kw:self.retain_writer(path,*a,**kw)), \
                mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.object(time,'monotonic',lambda:self.real_monotonic()+self.clock_shift), \
                mock.patch.dict(capture.__globals__,descriptor=delayed):
            with self.assertRaises(AssertionError):capture(self.output)
        self.assertIn('15s',self.observe_failure()['failure'])

    def test_validation_time_cannot_bypass_cleanup_clock(self):
        original=validate_nested
        def delayed(value):
            original(value)
            self.clock_shift=16  # Synthetic clock advancement after real nested validation.
        with mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.object(time,'monotonic',lambda:self.real_monotonic()+self.clock_shift), \
                mock.patch.dict(capture.__globals__,validate_nested=delayed):
            with self.assertRaises(AssertionError):capture(self.output)
        self.assertIn('15s',self.observe_failure()['failure'])

    def test_terminal_persist_time_after_real_close_cannot_bypass_cleanup_clock(self):
        original=write_json
        def delayed(path,value):
            original(path,value)
            if Path(path).name=='adapter-terminal.v1.json':
                self.clock_shift=16  # Synthetic deadline after genuine exclusive write/close.
        with mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.object(time,'monotonic',lambda:self.real_monotonic()+self.clock_shift), \
                mock.patch.dict(capture.__globals__,write_json=delayed):
            with self.assertRaises(AssertionError):capture(self.output)
        self.assertIn('15s',self.observe_failure()['failure'])

    def test_terminal_close_failure_retains_real_prefix_without_recursion(self):
        original=write_json
        def failed(path,value):
            original(path,value)
            if Path(path).name=='adapter-terminal.v1.json':
                raise OSError('explicit failure after actual terminal close')
        with mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.dict(capture.__globals__,write_json=failed):
            with self.assertRaises(Exception):capture(self.output)
        self.assertTrue((self.output/'adapter-terminal.v1.json').is_file())
        self.assertIn('explicit failure after actual terminal close',self.observe_failure()['failure'])

    def test_launch_primary_survives_actual_flush_close_faults_and_remaining_retirement(self):
        class FaultWriter:
            def __init__(self,actual):self.actual=actual
            @property
            def closed(self):return self.actual.closed
            def flush(self):self.actual.flush();raise OSError('explicit after real log flush')
            def fileno(self):return self.actual.fileno()
            def close(self):self.actual.close();raise OSError('explicit after real log close')
        def open_writer(path,*args,**kwargs):
            writer=self.retain_writer(path,*args,**kwargs)
            return FaultWriter(writer) if path.name=='original.stdout' and args==('xb',) else writer
        def invalid(argv,**kwargs):
            return self.real_popen([str(self.output/'absent-executable')],**kwargs)
        with mock.patch.object(Path,'open',open_writer),mock.patch.object(subprocess,'Popen',invalid):
            with self.assertRaises(Exception):capture(self.output)
        self.assertEqual(len(self.writers),2)
        self.assertTrue(all(writer.closed for writer in self.writers))
        failure=self.observe_failure()
        self.assertIn('absent-executable',failure['failure'])
        self.assertTrue(any('after real log flush' in item for item in failure['close_errors']))
        self.assertTrue(any('after real log close' in item for item in failure['close_errors']))

    def test_final_receipt_persist_time_after_actual_close_still_blocks_success(self):
        original=write_json
        def delayed(path,value):
            original(path,value)
            if Path(path).name=='adapter-final-close.v1.json':self.clock_shift=16
        with mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.object(time,'monotonic',lambda:self.real_monotonic()+self.clock_shift), \
                mock.patch.dict(capture.__globals__,write_json=delayed):
            with self.assertRaises(AssertionError):capture(self.output)
        self.assertIn('15s',self.observe_failure()['failure'])

    def test_healthy_tiny_capture_observes_terminal_close_and_returns_after_final_receipt(self):
        original=write_json;closed={}
        def observed(path,value):
            original(path,value);closed[Path(path).name]=self.real_monotonic()
        with mock.patch.object(Path,'open',lambda path,*a,**kw:self.retain_writer(path,*a,**kw)), \
                mock.patch.object(subprocess,'Popen',self.tiny_child), \
                mock.patch.dict(capture.__globals__,write_json=observed):
            nested=capture(self.output)
        returned=self.real_monotonic()
        self.assertEqual(nested['tests_run'],len(INHERITED_IDS | APPROVED_NEW_IDS))
        self.assertTrue(all(writer.closed for writer in self.writers))
        final=json.loads((self.output/'adapter-final-close.v1.json').read_text())
        self.assertGreaterEqual(final['observed_after_terminal_persist_monotonic_s'],closed['adapter-terminal.v1.json'])
        self.assertLessEqual(closed['adapter-final-close.v1.json'],returned)
        self.assertTrue(final['candidate_success'])
        self.assertTrue(final['provisional_until_capture_return'])
        self.assertFalse((self.output/'adapter-close-failure.v1.json').exists())

    def test_partial_terminal_write_keeps_primary_and_actual_flush_close_failures(self):
        class ReportWriterFault:
            def __init__(self,actual):self.actual=actual
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
            def write(self,value):self.actual.write(value);raise OSError('explicit partial terminal write cause')
            def flush(self):self.actual.flush();raise OSError('explicit terminal after real flush')
            def fileno(self):return self.actual.fileno()
            def close(self):self.actual.close();raise OSError('explicit terminal after real close')
        def fault_open(path,*args,**kwargs):
            actual=self.real_open(path,*args,**kwargs)
            return ReportWriterFault(actual) if path.name=='adapter-terminal.v1.json' else actual
        with mock.patch.object(Path,'open',fault_open),mock.patch.object(subprocess,'Popen',self.tiny_child):
            with self.assertRaises(Exception):capture(self.output)
        self.assertTrue((self.output/'adapter-terminal.v1.json').read_bytes(),'original partial prefix retained')
        failure=self.observe_failure()
        self.assertIn('partial terminal write cause',failure['failure'])
        self.assertTrue(any('terminal after real flush' in item for item in failure['close_errors']))
        self.assertTrue(any('terminal after real close' in item for item in failure['close_errors']))


class DecoderResearchV6Tests(unittest.TestCase):
    def test_full_v6_suite(self):
        if sys.version_info[:3]!=(3,12,3):self.fail('canonical CPython3.12.3 required; no skip')
        base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))/'vast-cpu-checks/decoder-v6-fixtures'
        base.mkdir(parents=True,exist_ok=True)
        output=base/('attempt-'+uuid.uuid4().hex);output.mkdir(mode=0o700)
        nested=capture(output)
        self.assertGreater(nested['tests_run'],66)
        # These contract faults must never turn a partial/foreign/skipped suite green.
        for fault in ('missing','missing_cold','duplicate','skip','origin','source'):
            damaged=json.loads(json.dumps(nested));name=next(iter(INHERITED_IDS))
            if fault=='missing':damaged['selected_test_ids'].remove(name)
            elif fault=='missing_cold':damaged['selected_test_ids'].remove(
                next(case for case in APPROVED_NEW_IDS if case.startswith('test_research_protocol.')))
            elif fault=='duplicate':damaged['selected_test_ids'].append(name)
            elif fault=='skip':damaged['outcomes'][name]='skip';damaged['skips']=1
            elif fault=='origin':damaged['test_origins'][name]='/foreign/test_setup_v2.py'
            else:damaged['source_after']=[]
            with self.subTest(fault=fault):
                with self.assertRaises(AssertionError):validate_nested(damaged)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--v6-child':sys.exit(child(sys.argv[2]))
    unittest.main()
