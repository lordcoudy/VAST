"""Finite closed-result/descriptor arithmetic review; no reducer or producer imports."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930/component-cpu05-sidecar-independent-reduction-v2'
OUT = Path(__file__).parent

def descriptor(path):
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def physical(row):
    path = Path(row['path'])
    if not path.is_absolute():
        path = ROOT / path
    actual = descriptor(path)
    assert actual['sha256'] == row['sha256'] and actual['size_bytes'] == row['size_bytes'], path
    return path

def doc(path):
    return json.loads(path.read_bytes())

def exact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

report = doc(BASE / 'scientific-report.v1.json')
provenance = doc(BASE / 'reader-adaptation-provenance.v1.json')
assert descriptor(BASE / 'scientific-report.v1.json')['sha256'] == 'c9fdc0483b439cadeea1edf22ac75eb223db1a040943b38cc3bf1d2accc22fc4'
assert descriptor(BASE / 'reader-adaptation-provenance.v1.json')['sha256'] == 'df0762f0ad07efd36827d0d41c2b2892ac7a887827787b79d9548a1d054f7a17'
terminal = doc(physical(report['original_reduction_terminal']))
custody = doc(physical(report['custody']))
rows = doc(physical(report['recomputed_summaries']))
for row in report['helper_sources']:
    physical(row)
for row in terminal['outputs'].values():
    physical(row)
assert terminal['source_before'] == terminal['source_after'] and terminal['original_child_returncode'] == 0
assert terminal['completed_pure_reduction'] and not terminal['timed_out'] and not terminal['capture_exceeded']
assert terminal['primary_error'] is None and terminal['additional_errors'] == []
assert terminal['observed_eof'] == ['stderr', 'stdout'] and terminal['original_child_current'] is None and terminal['original_group_members'] == []
assert terminal['elapsed_s'] == provenance['original_successful_reduction']['elapsed_s'] < 120
assert custody['before'] == custody['after'] and custody['primary_error'] is None and custody['fd_holds_released']
assert len(custody['before']) == 73 and sum('/scripts/' in row['path'] for row in custody['before']) == 25
assert all(len(row['epoch']) == 7 for row in custody['before']) and custody['reduced_arms'] == 2
assert report['measurement_acceptance'] is False and report['task_18_8_complete'] is False and report['original_cpu05_cli_exit_code'] == 78
assert len(rows) == len(report['arms']) == 2
snapshots = report['postterminal_process_observations']
assert len(snapshots) == 2 and all(row['original_child_group_members'] == [] and all(value is None for value in row['original_processes'].values()) for row in snapshots)
original_pair = ROOT / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-05'
held = {row['path']: row for row in custody['before']}
cold_path = original_pair / 'cold-pair/component_pair_result.v1.json'
cold = doc(physical(held[str(cold_path)]))
arms = []
for position, row in enumerate(rows):
    operation = row['operation_id']
    candidate_matches = [path for path in held if Path(path).name == 'checkpoint_publication_candidate.json' and Path(path).parent.parent.name == operation]
    assert len(candidate_matches) == 1
    candidate_path = physical(held[candidate_matches[0]])
    arm_path = candidate_path.parent.parent / 'component_arm_result.v1.json'
    arm = doc(physical(held[str(arm_path)]))
    candidate = doc(candidate_path)
    legacy, summary = row['recomputed_legacy_summary'], row['recomputed_v2_summary']
    assert len(legacy) == len(summary) == 72
    assert exact(candidate['summary']) == exact(legacy)
    assert exact(arm['physical_validation']['summary']) == exact(summary) == exact(cold['arms'][position]['summary'])
    assert exact(cold['arms'][position]['descriptive_metrics']) == exact(row['recomputed_descriptive_metrics'])
    assert all(row[name]['equal'] and row[name]['differences'] == {} for name in ('candidate_comparison', 'carried_arm_comparison', 'cold_summary_comparison', 'cold_descriptive_comparison'))
    assert row['cold_csv_fields_exactly_matched'] == 14
    assert summary['completed_frame_count'] == row['completed_rows'] == row['completed_deadline_misses']
    assert summary['ingress_frame_count'] == 1080 and summary['censored_frame_count'] == 0
    assert summary['ingress_frame_count'] - summary['completed_frame_count'] == summary['dropped_frame_count']
    arms.append({
        'operation_id': operation, 'completed': summary['completed_frame_count'], 'admitted': 1080,
        'dropped': summary['dropped_frame_count'], 'censored': 0, 'on_time_completed': 0,
        'recorded_decode_count': summary['decode_count'], 'recorded_preprocess_count': summary['preprocess_count'],
        'c_obs_total_ms': summary['c_obs_total_ms'], 'c_obs_is_partial': summary['c_obs_is_partial'],
        'completion_coverage_percent': summary['completed_frame_count'] / 1080 * 100,
        'candidate_arm_cold_summary72_values_exact': True,
    })
assert [row['completed'] for row in arms] == [562, 682] and [row['dropped'] for row in arms] == [518, 398]
reduction = (1 - arms[1]['c_obs_total_ms'] / arms[0]['c_obs_total_ms']) * 100
coverage = (arms[1]['completed'] - arms[0]['completed']) / 1080 * 100
assert reduction == report['descriptive_partial_c_obs_reduction_percent'] and coverage == report['completion_coverage_shared_minus_baseline_percentage_points']
result = {
    'schema_version': 1, 'artifact_kind': 'vast_cpu05_scientific_closed_reduction_peer_review_v1',
    'disposition': 'approved_metric_consistency_only_original_cli_failed', 'measurement_acceptance': False,
    'task_18_8_complete': False, 'all_phase_cold': False, 'original_cli_exit_code': 78,
    'reviewed_report': descriptor(BASE / 'scientific-report.v1.json'),
    'reader_provenance': descriptor(BASE / 'reader-adaptation-provenance.v1.json'),
    'original_reduction_terminal': descriptor(BASE / 'attempt01/terminal.v1.json'),
    'custody_record': descriptor(BASE / 'attempt01/custody-and-comparison.v1.json'),
    'recomputed_summaries': descriptor(BASE / 'attempt01/recomputed-summaries.v1.json'),
    'helper_sources': [descriptor(physical(row)) for row in report['helper_sources']],
    'original_execution': {'returncode': 0, 'elapsed_s': terminal['elapsed_s'], 'both_eof': True,
                           'held_inputs': 73, 'held_reducer_import_sources': 25, 'recorded_all_7_epochs_and_bytes_unchanged': True,
                           'fd_holds_released': True, 'two_actual_closed_process_scans': True},
    'arms': arms, 'partial_attributed_elapsed_reduction_percent': reduction,
    'completion_coverage_change_percentage_points': coverage,
    'findings': [
        'The original pure reader called unchanged summarize_sidecars, summarize_frames, sidecar/topology/full-resource validators and compared complete typed summaries. This reviewer rejoined closed descriptors and all72 candidate/arm/cold values without executing a reducer.',
        'Observed shared completion coverage was11.1111 percentage points higher and partial attributed elapsed46.7226% lower in one failed-original CPU pair. Both delivered zero completed frames within100ms. These remain descriptive observations with explicit drops, not an accepted benchmark or statistical conclusion.',
        'benchmark_contract.py:6804 labels CPU resource_time with stage duration;6974 explicitly calls NVDEC accounting host-stage elapsed rather than NVDEC busy time;7310-7434 sum those recorded components and normalize by admitted/completed populations. C_obs cannot establish processor work, energy, actual decoder busy time or quality.',
        'Recorded baseline decode4320/preprocess4318 versus shared1080/1080 supports fewer recorded stage executions. Different completion/drop populations and overlapping stage residence prevent treating their sums as wall-clock or device utilization savings.',
        'CPU-only analytics placement still uses nvh264dec/NVDEC. No GPU analytics pair or repeated population, independent pixel/quality check or SVG geometry reconstruction exists in this review.',
        'Preserved original v1 reader failed before reducing any arm because it confused physical terminal SHA with internal JSON body seal. The authorized v2 changed that reader join and separately verified unchanged stock CLI/body seals; original producer references and failure stayed immutable.',
    ],
    'limitations': [
        'No producer imports, stock cold/reducer/model/engine/native/guardian/test/redecode execution by this peer review. Original successful raw reduction is separate recorded evidence.',
        'The73 FD/epoch/raw checks and process closure are authenticated original reader records, not a fresh reviewer full raw sweep or current87-source authority. SVG physical descriptor only.',
        'Original CLI78 and late deadline failure remain decisive. Task18.8, accepted four-arm release, green CI and full campaign remain incomplete.',
    ],
    'blockers': [], 'reviewer_new_workloads': [],
}
with (OUT / 'review.v1.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(result, stream, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps(descriptor(OUT / 'review.v1.json'), sort_keys=True))
