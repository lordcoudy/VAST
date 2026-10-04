"""Independent comparison of closed diagnostics; no target imports or execution."""
import collections
import csv
from decimal import Decimal as D
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / 'original-cli-execution-v1'
ARMS = ('cpu-baseline', 'cpu-shared', 'gpu-baseline', 'gpu-shared')
leaves = []


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size,
            s.st_mtime_ns, s.st_ctime_ns]


def read(path, maximum=2 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
        assert before.st_size <= maximum
        chunks = []
        while data := os.read(fd, 65536):
            chunks.append(data)
        raw = b''.join(chunks)
        assert len(raw) == before.st_size
        assert epoch(before) == epoch(os.fstat(fd)) == epoch(os.lstat(path))
        leaf = {'path': str(path), 'size_bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'epoch': epoch(before)}
        leaves.append(leaf)
        return raw, leaf
    finally:
        os.close(fd)


def quantiles(values):
    values = sorted(values)
    result = {'count': len(values)}
    for name, fraction in (('p50', D('.5')), ('p95', D('.95')), ('p99', D('.99'))):
        position = fraction * (len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        result[name] = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return result


def check_distribution(actual, expected):
    assert actual['count'] == expected.get('count', expected.get('n'))
    assert actual.get('reason') is None
    for key in ('p50', 'p95', 'p99'):
        assert math.isclose(float(actual[key]), float(expected[key]),
                            rel_tol=1e-14, abs_tol=1e-12), (key, actual[key], expected[key])


def main():
    original_raw, original_pin = read(BASE / 'raw-independent-review/calculation.v2.json')
    original = json.loads(original_raw)
    assert original_pin['sha256'] == 'e9b370012bcdc18204e1c868aaf921dd8f10e3da4d7b35cade0b5c96777b3f2b'
    invocation_raw, invocation_pin = read(OUT / 'invocation-terminal.v1.json')
    invocation = json.loads(invocation_raw)
    assert invocation['four_original_cli_successes'] is True
    assert invocation['primary_failure'] is None and invocation['stability_errors'] == []
    assert invocation['leaf_handles_closed'] is True
    assert invocation['source_before'] == invocation['source_after']
    source_raw, source_pin = read(BASE.parents[1] / 'scripts/analyze_component_latency_v1.py')
    assert source_pin['sha256'] == invocation['source_before']['sha256']
    assert source_pin['size_bytes'] == invocation['source_before']['size_bytes']
    expected_inputs = {v['path']: v for arm in original['arms'] for v in arm['inputs'].values()}
    assert len(expected_inputs) == len(invocation['input_stability']) == 20
    for held in invocation['input_stability']:
        expected = expected_inputs[held['path']]
        assert held['sha256'] == expected['sha256']
        assert held['before'] == held['opened_after'] == held['named_after'] == expected['epoch']
        assert held['unchanged'] is True
    results = []
    for index, name in enumerate(ARMS):
        expected = original['arms'][index]
        diagnostic_raw, diagnostic_pin = read(OUT / name / 'diagnostic.json')
        diagnostic = json.loads(diagnostic_raw)
        assert diagnostic['topology'].replace('_', '-') == expected['topology']
        assert {v['path']: v for v in diagnostic['inputs']} == {
            v['path']: {k: v[k] for k in ('path', 'size_bytes', 'sha256')}
            for v in expected['inputs'].values()}
        counts = diagnostic['counts']
        assert counts['admitted'] == expected['measurement_admissions']
        assert counts['completed'] == expected['completed_frames']
        assert counts['dropped'] == expected['frame_terminal_counts']['drop'] and counts['censored'] == 0
        assert counts['branch_completed'] == expected['policy_complete_branch_identity_joins']
        assert counts['branch_dropped'] == 4 * counts['admitted'] - counts['branch_completed']
        assert diagnostic['deadline']['completed_on_time'] == expected['on_time_completed_at_100ms']
        assert diagnostic['deadline']['deadline_ms'] == 100 and diagnostic['deadline']['policy_corroborated'] is True
        assert diagnostic['critical_branch_counts'] == expected['critical_branch_counts']
        check_distribution(diagnostic['latency_ms'], expected['completed_latency_ms'])
        for actual_key, expected_key in [('decoder_prefix_ms', 'critical_decoder_prefix_ms'),
                                        ('postdecode_residual_ms', 'critical_decoder_residual_ms'),
                                        ('decoder_share', 'per_frame_decoder_prefix_share')]:
            check_distribution(diagnostic['critical_path'][actual_key], expected[expected_key])
        assert diagnostic['critical_path']['per_frame_sum_verified'] is True
        assert set(diagnostic['stages']) == set(expected['observed_stage_parent_to_completion_envelopes_ms'])
        stage_count = 0
        for stage, metrics in diagnostic['stages'].items():
            check_distribution(metrics['parent_to_completion_ms'], expected['observed_stage_parent_to_completion_envelopes_ms'][stage])
            queue = metrics['recorded_queue_span_ms']
            assert queue['count'] == metrics['parent_to_completion_ms']['count']
            assert all(queue[q] == 0 for q in ('p50', 'p95', 'p99'))
            stage_count += queue['count']
        assert stage_count == expected['recorded_queue_enter_to_start_ms']['n']
        csv_raw, csv_pin = read(OUT / name / 'per_completed_frame.csv')
        rows = list(csv.DictReader(io.StringIO(csv_raw.decode('utf-8'), newline='')))
        assert len(rows) == expected['completed_frames']
        keys, critical = set(), []
        for row in rows:
            key = [row[k] for k in ('run_id', 'trace_id', 'stream_id', 'frame_id')]
            assert tuple(key) not in keys
            keys.add(tuple(key))
            prefix, residual, total = (D(row[k]) for k in ('decoder_prefix_ms', 'postdecode_residual_ms', 'e2e_latency_ms'))
            assert prefix + residual == total and total > 0
            assert D(row['decoder_share']) == prefix / total and row['decoder_share_reason'] == ''
            critical.append([*key, row['critical_branch'], str(prefix), str(residual), str(total)])
        critical_hash = hashlib.sha256(json.dumps(sorted(critical), separators=(',', ':')).encode()).hexdigest()
        assert critical_hash == expected['critical_rows_sha256']
        terminal_raw, terminal_pin = read(OUT / (name + '.terminal.v1.json'))
        terminal = json.loads(terminal_raw)
        assert terminal == invocation['terminals'][index] and terminal['exit_code'] == 0
        for channel in ('stdout', 'stderr'):
            raw, pin = read(OUT / (name + '.' + channel + '.txt'))
            assert pin['sha256'] == terminal[channel]['sha256'] and pin['size_bytes'] == terminal[channel]['size_bytes']
            if channel == 'stderr':
                assert raw == b''
        report_raw, report_pin = read(OUT / name / 'report.md')
        report = report_raw.decode('utf-8')
        assert f"Admissions {counts['admitted']}; completed {counts['completed']}; dropped {counts['dropped']}; censored 0." in report
        assert all(ref['sha256'] in report for ref in expected['inputs'].values())
        assert all(limit in report for limit in diagnostic['scientific_limits'])
        assert all(diagnostic[k] is False for k in ('qualification_eligible', 'publication_ready', 'full_campaign_ready', 'q4_ready'))
        assert all(metric['value'] is None for metric in diagnostic['unknown_components'].values())

        # Only metrics newly added by the CLI are recomputed from original rows.
        # The earlier calculation, e2e/stage totals and critical rows are not rerun.
        event_raw, event_pin = read(Path(expected['inputs']['frame_events.csv']['path']), 64 * 1024 * 1024)
        policy_raw, policy_pin = read(Path(expected['inputs']['publication_policy_decisions.jsonl']['path']), 64 * 1024 * 1024)
        branch_raw, branch_pin = read(Path(expected['inputs']['branch_terminals.csv']['path']), 64 * 1024 * 1024)
        for filename, pin in [('frame_events.csv', event_pin), ('publication_policy_decisions.jsonl', policy_pin), ('branch_terminals.csv', branch_pin)]:
            assert pin == expected['inputs'][filename]
        def identity(row):
            return tuple(row[k] for k in ('run_id', 'trace_id', 'stream_id', 'frame_id'))
        events = {(identity(row), row['stage']): row for row in csv.DictReader(io.StringIO(event_raw.decode(), newline=''))}
        terms = list(csv.DictReader(io.StringIO(branch_raw.decode(), newline='')))
        assert diagnostic['branch_drop_reasons'] == dict(collections.Counter(row['terminal_reason'] for row in terms if row['terminal_status'] == 'drop'))
        values = collections.defaultdict(lambda: collections.defaultdict(list))
        seen = set()
        pooled = []
        for line in policy_raw.decode().splitlines():
            row = json.loads(line, parse_float=D)
            request, native, branch = row['request'], row['native_decision_evidence'], row['branch']
            run, stream, frame = request['trace_id'].rsplit(':', 2)
            key = (run, request['trace_id'], stream, frame)
            assert (key, branch) not in seen
            seen.add((key, branch))
            stage = events[key, branch]
            post = events[key, 'postprocess_' + branch]
            path, terminal_time, carried = (D(str(native[k])) for k in ('path_entry_timestamp_ms', 'terminal_timestamp_ms', 'actual_service_ms'))
            values[branch]['parent_to_path_ms'].append(path - D(stage['stage_start_timestamp_ms']))
            values[branch]['path_to_terminal_ms'].append(terminal_time - path)
            values[branch]['carried_actual_service_ms'].append(carried)
            values[branch]['native_terminal_to_postprocess_ms'].append(D(post['stage_end_timestamp_ms']) - terminal_time)
            pooled.append(terminal_time - path)
        assert len(seen) == expected['policy_complete_branch_identity_joins']
        check_distribution({'count': len(pooled), 'reason': None, **{k: float(v) for k, v in quantiles(pooled).items() if k != 'count'}}, expected['native_policy_path_envelope_ms'])
        assert set(values) == set(diagnostic['policy_path']['by_branch'])
        for branch, metrics in values.items():
            assert len(metrics['path_to_terminal_ms']) == expected['branch_terminal_counts'][branch]['completed']
            for metric, population in metrics.items():
                check_distribution(diagnostic['policy_path']['by_branch'][branch][metric], quantiles(population))
        results.append({'arm': name, 'completed_frame_count': len(rows), 'critical_rows_sha256': critical_hash,
                        'recorded_stage_rows': stage_count, 'native_completed_branch_paths': len(seen),
                        'diagnostic': diagnostic_pin, 'per_frame_csv': csv_pin, 'report': report_pin,
                        'terminal': terminal_pin, 'all_compared_fields_equal': True})
    result = {'schema_version': 1, 'kind': 'independent_closed_offline_cli_comparison',
              'source': source_pin, 'original_calculation': original_pin, 'invocation_terminal': invocation_pin,
              'results': results, 'completed_frames_verified': sum(r['completed_frame_count'] for r in results),
              'stage_rows_verified': sum(r['recorded_stage_rows'] for r in results),
              'native_completed_branch_paths_verified': sum(r['native_completed_branch_paths'] for r in results),
              'reviewed_leaf_count': len(leaves), 'leaf_handles_closed': True,
              'acceptance_authority': False, 'target_cli_rerun': False, 'original_math_rerun': False,
              'findings': [], 'limits': ['Comparison verifies closed offline outputs and preserved input leaf facts, not original acceptance or ancestor custody.',
                  'Additional per-branch policy metrics and drop-reason counts were independently parsed from originals; no inference/campaign/engine was run.',
                  'CLI numeric summaries are compared within 1e-14 relative / 1e-12 absolute float representation tolerance; per-frame Decimal decomposition and identity hashes are exact.',
                  'No PID birth, EOF/reap, global process absence or numeric FD-count fact is invented; four recorded returncodes and empty stderr are joined.']}
    payload = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    with Path(sys.argv[1]).open('xb') as stream:
        stream.write(payload)
    print(json.dumps({'path': sys.argv[1], 'size_bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(),
                      'completed': result['completed_frames_verified'], 'stages': result['stage_rows_verified'], 'branches': result['native_completed_branch_paths_verified']}))


if __name__ == '__main__':
    main()
