"""Close the original pure reduction and describe its observed arithmetic."""
import hashlib
import json
import os
import time
from pathlib import Path

BASE = Path(__file__).parent
OUT = BASE / 'attempt01'
def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
def doc(name):
    return json.loads((OUT / name).read_bytes())
def owner(pid):
    try:
        fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'pgid': int(fields[2]), 'session': int(fields[3]), 'startticks': int(fields[19])}
    except (FileNotFoundError, ProcessLookupError):
        return None
terminal, launch, custody = doc('terminal.v1.json'), doc('launch.v1.json'), doc('custody-and-comparison.v1.json')
rows = doc('recomputed-summaries.v1.json')
assert terminal['completed_pure_reduction'] and terminal['original_child_returncode'] == 0
assert terminal['elapsed_s'] < 120 and not terminal['timed_out'] and not terminal['capture_exceeded']
assert terminal['source_before'] == terminal['source_after'] and terminal['observed_eof'] == ['stderr', 'stdout']
assert custody['before'] == custody['after'] and custody['primary_error'] is None and custody['fd_holds_released']
assert custody['all_fields_match'] and len(rows) == 2
for row in terminal['outputs'].values():
    assert descriptor(Path(row['path'])) == row
for name in ('custody', 'recomputed_summaries'):
    assert descriptor(Path(terminal[name]['path'])) == terminal[name]
snapshots = []
identities = [launch['observer'], launch['child']]
for index in range(2):
    group = []
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            fact = owner(int(path.name))
            if fact and fact['pgid'] == launch['child']['pgid']:
                group.append(fact)
    direct = {str(row['pid']): owner(row['pid']) for row in identities}
    assert not group and all(value is None for value in direct.values())
    snapshots.append({'observed_at_ns': time.time_ns(), 'original_processes': direct, 'original_child_group_members': group})
    if index == 0:
        time.sleep(.05)
baseline, shared = [row['recomputed_v2_summary'] for row in rows]
assert all(baseline[key] == shared[key] for key in
           ('measurement_signature', 'input_schedule_sha256', 'input_frame_key_sequence_sha256', 'measurement_window_duration_ms'))
arms = []
for row in rows:
    summary = row['recomputed_v2_summary']
    admitted, completed = summary['ingress_frame_count'], summary['completed_frame_count']
    assert admitted == 1080 and completed == row['completed_rows']
    assert summary['censored_frame_count'] == 0 and row['completed_deadline_misses'] == completed
    arms.append({'operation_id': row['operation_id'], 'candidate_keys_exactly_matched': row['candidate_comparison']['keys_compared'],
        'carried_arm_keys_exactly_matched': row['carried_arm_comparison']['keys_compared'],
        'cold_summary_keys_exactly_matched': row['cold_summary_comparison']['keys_compared'],
        'cold_descriptive_keys_exactly_matched': row['cold_descriptive_comparison']['keys_compared'],
        'cold_csv_fields_exactly_matched': row['cold_csv_fields_exactly_matched'],
        'descriptive_metrics': row['recomputed_descriptive_metrics'],
        'admitted': admitted, 'completed': completed, 'dropped': summary['dropped_frame_count'], 'censored': 0,
        'completion_coverage_percent': completed / admitted * 100,
        'completed_deadline_misses': completed, 'completed_deadline_miss_percent': 100,
        'on_time_completed': 0, 'completed_per_180s_fps': completed / 180,
        'recorded_decode_stage_count': summary['decode_count'], 'recorded_preprocess_stage_count': summary['preprocess_count'],
        'c_obs_total_ms': summary['c_obs_total_ms'], 'c_obs_cpu_total_ms': summary['c_obs_cpu_total_ms'],
        'c_obs_gpu_total_ms': summary['c_obs_gpu_total_ms'],
        'c_obs_in_ms_per_ingress': summary['c_obs_in_ms_per_ingress'],
        'c_obs_comp_ms_per_completed': summary['c_obs_comp_ms_per_completed'], 'c_obs_is_partial': summary['c_obs_is_partial'],
        'decoder_factory': summary['decoder_factory'], 'decoder_required_resource': summary['decoder_required_resource']})
report = {'schema_version': 1, 'artifact_kind': 'vast_cpu05_pure_sidecar_scientific_reduction_v1',
    'disposition': 'metric_consistency_verified_original_cli_still_failed',
    'original_reduction_terminal': descriptor(OUT / 'terminal.v1.json'),
    'custody': descriptor(OUT / 'custody-and-comparison.v1.json'), 'recomputed_summaries': descriptor(OUT / 'recomputed-summaries.v1.json'),
    'helper_sources': [descriptor(BASE / name) for name in ('reduce.py', 'run.py', 'close.py')],
    'held_inputs': len(custody['before']), 'held_reducer_sources': sum('/scripts/' in row['path'] for row in custody['before']),
    'all_held_bytes_and_full_7_epochs_unchanged': True, 'fd_holds_released': True, 'postterminal_process_observations': snapshots,
    'exact_summary_field_comparison': '72 candidate keys,72 carried arm keys and72 cold pair summary keys per arm; complete typed canonical JSON comparisons. Cold descriptive metrics and all14 CSV fields independently recomputed; SVG bound by original descriptor only.',
    'arms': arms, 'measurement_signature': baseline['measurement_signature'],
    'input_schedule_sha256': baseline['input_schedule_sha256'],
    'input_frame_key_sequence_sha256': baseline['input_frame_key_sequence_sha256'],
    'descriptive_partial_c_obs_reduction_percent': (1 - shared['c_obs_total_ms'] / baseline['c_obs_total_ms']) * 100,
    'completion_coverage_shared_minus_baseline_percentage_points': (shared['completed_frame_count'] - baseline['completed_frame_count']) / 1080 * 100,
    'interpretation': 'The shared graph recorded fewer decode/preprocess stage executions, lower partial attributed stage elapsed per admitted ingress, and more completed frames in this one CPU pair. Both arms delivered zero completed frames within100ms. The lower C_obs does not establish lower processor work, energy or native decoder busy time; differing completion/drop populations remain visible.',
    'limitations': ['One original descriptive CPU pair, no statistical repeats or GPU pair.',
        'CPU-only denotes analytics placement; both plans use nvh264dec/NVDEC.',
        'Completed-frame deadline percentages exclude dropped ingress; no latency was assigned to drops.',
        'The unchanged stock legacy reducer, summarize_frames and pure full-resource validator were run. All72 fields join candidate/arm/cold summaries; no public cold/full authority/all-phase entrypoint or current complete87-source validation.',
        'Original CPU05 CLI78/late deadline failure remains immutable. Authentic retained cold exports do not override it. This check cannot complete task18.8 or grant measurement/publication/fullcampaign acceptance.', 'nvdec_busy_equivalent_ns/device_sample and fanout resource counters may match their original carried summaries; no measured native decoder busy-time, quality or population claim is inferred.', 'Original SVG is physically descriptor-verified; no new rendering or independent SVG curve geometry check was performed.'],
    'measurement_acceptance': False, 'task_18_8_complete': False, 'original_cpu05_cli_exit_code': 78, 'all_phase_cold': False, 'model_or_engine_or_native_or_guardian_operations': False}
path = BASE / 'scientific-report.v1.json'
with path.open('xb') as stream:
    stream.write((json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
    stream.flush(); os.fsync(stream.fileno())
print(json.dumps(descriptor(path)))
