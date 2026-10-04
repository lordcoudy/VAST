"""Independent stdlib calculation over fixed accepted originals; no target imports."""
import collections
import csv
from decimal import Decimal as D
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7')
BRANCHES = {'damage', 'foreign_object', 'plate_number', 'vehicle_type'}
FILES = ('frames.csv', 'ingress_ledger.csv', 'branch_terminals.csv', 'frame_events.csv', 'publication_policy_decisions.jsonl')
LIMIT = 64 * 1024 * 1024


def epoch(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def raw(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= LIMIT
        assert epoch(path.lstat()) == epoch(before)
        data = bytearray()
        while piece := os.read(fd, 65536):
            data.extend(piece)
            assert len(data) <= LIMIT
        assert epoch(os.fstat(fd)) == epoch(before) == epoch(path.lstat())
        assert len(data) == before.st_size
        return bytes(data), {'path': str(path), 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'epoch': epoch(before)}
    finally:
        os.close(fd)


def q(values):
    x = sorted(values)
    if not x:
        return {'n': 0, 'p50': None, 'p95': None, 'p99': None, 'reason': 'empty_population'}
    result = {'n': len(x)}
    for name, fraction in (('p50', D('.5')), ('p95', D('.95')), ('p99', D('.99'))):
        index = fraction * (len(x) - 1)
        low = int(index)
        high = min(low + 1, len(x) - 1)
        result[name] = x[low] + (x[high] - x[low]) * (index - low)
    result.update(min=x[0], max=x[-1], mean=sum(x) / len(x))
    return result


def key(row):
    return tuple(row[name] for name in ('run_id', 'trace_id', 'stream_id', 'frame_id'))


def unique(rows, identity):
    result = {}
    for row in rows:
        item = identity(row)
        assert item not in result, item
        result[item] = row
    return result


def calculate(directory):
    inputs = {}
    tables = {}
    for filename in FILES:
        data, inputs[filename] = raw(directory / filename)
        text = data.decode('utf-8')
        if filename.endswith('.csv'):
            tables[filename] = list(csv.DictReader(io.StringIO(text, newline='')))
        else:
            tables[filename] = [json.loads(line, parse_float=D) for line in text.splitlines()]
    ledger = unique(tables['ingress_ledger.csv'], key)
    frames = unique(tables['frames.csv'], key)
    terms = unique(tables['branch_terminals.csv'], lambda r: (key(r), r['branch_id']))
    events = unique(tables['frame_events.csv'], lambda r: (key(r), r['stage']))
    assert len(ledger) == 1080 and set(frames) == {k for k, r in ledger.items() if r['terminal_status'] == 'completed'}
    assert len(terms) == 4 * len(ledger)
    assert {b for _, b in terms} == BRANCHES
    for (k, _), terminal in terms.items():
        assert k in ledger and terminal['input_frame_key'] == ledger[k]['input_frame_key']
    policy = {}
    for row in tables['publication_policy_decisions.jsonl']:
        request, native = row['request'], row['native_decision_evidence']
        trace = request['trace_id']
        run, stream, frame = trace.rsplit(':', 2)
        k = (run, trace, stream, frame)
        branch = row['branch']
        identity = (k, branch)
        assert identity not in policy and k in ledger and identity in terms
        assert row['trace_id'] == trace == row['publication_projection']['original_worker_trace_id']
        assert row['decision_id'] == request['decision_id'] == native['decision_id']
        assert branch == request['branch'] == native['branch']
        assert native['input_frame_key'] == ledger[k]['input_frame_key']
        assert terms[identity]['terminal_status'] == native['terminal_status'] == 'completed'
        assert D(str(request['deadline_ms'])) - D(str(request['arrival_ms'])) == 100
        assert D(str(native['terminal_timestamp_ms'])) >= D(str(native['path_entry_timestamp_ms']))
        policy[identity] = row
    completed_branches = {identity for identity, r in terms.items() if r['terminal_status'] == 'completed'}
    assert set(policy) == completed_branches
    critical_rows, latency, prefix, residual, shares = [], [], [], [], []
    critical_counts = collections.Counter()
    for k, frame in frames.items():
        assert all(terms[k, b]['terminal_status'] == 'completed' for b in BRANCHES)
        ends = {b: D(events[k, 'postprocess_' + b]['stage_end_timestamp_ms']) for b in BRANCHES}
        critical = max(sorted(BRANCHES, reverse=True), key=lambda b: ends[b])
        decoder = 'decode' if (k, 'decode') in events else 'decode_' + critical
        start, decode_end, end = D(frame['ingress_timestamp_ms']), D(events[k, decoder]['stage_end_timestamp_ms']), D(frame['egress_timestamp_ms'])
        total = D(frame['e2e_latency_ms'])
        assert start <= decode_end <= end and end == max(ends.values())
        assert end - start == total and total > 0
        pre, res = decode_end - start, end - decode_end
        assert pre + res == total
        critical_counts[critical] += 1
        latency.append(total); prefix.append(pre); residual.append(res); shares.append(pre / total)
        critical_rows.append([*k, critical, str(pre), str(res), str(total)])
    spans = collections.defaultdict(list)
    queue_spans = []
    for (k, stage), event in events.items():
        assert k in ledger
        enter, start, end = (D(event[n]) for n in ('queue_enter_timestamp_ms', 'stage_start_timestamp_ms', 'stage_end_timestamp_ms'))
        assert enter <= start <= end
        queue_spans.append(start - enter)
        spans[stage].append(end - start)
    paths = [D(str(r['native_decision_evidence']['terminal_timestamp_ms'])) - D(str(r['native_decision_evidence']['path_entry_timestamp_ms'])) for r in policy.values()]
    path_reported_deltas = [abs(span - D(str(r['native_decision_evidence']['actual_service_ms']))) for span, r in zip(paths, policy.values(), strict=True)]
    ingress_boundaries = sum(D(r['ingress_timestamp_ms']) < D(r['window_start_timestamp_ms']) for r in ledger.values())
    branch_counts = {b: dict(collections.Counter(r['terminal_status'] for (k, branch), r in terms.items() if branch == b)) for b in sorted(BRANCHES)}
    output = {
        'evidence_directory': str(directory), 'inputs': inputs,
        'measurement_admissions': len(ledger), 'frame_terminal_counts': dict(collections.Counter(r['terminal_status'] for r in ledger.values())),
        'branch_terminal_counts': branch_counts, 'completed_frames': len(frames),
        'on_time_completed_at_100ms': sum(t <= 100 for t in latency), 'completed_latency_ms': q(latency),
        'critical_branch_counts': dict(critical_counts), 'critical_decoder_prefix_ms': q(prefix), 'critical_decoder_residual_ms': q(residual),
        'per_frame_decoder_prefix_share': q(shares), 'sum_decoder_prefix_over_sum_latency': sum(prefix) / sum(latency),
        'critical_decomposition_exact': True, 'critical_rows_sha256': hashlib.sha256(json.dumps(sorted(critical_rows), separators=(',', ':')).encode()).hexdigest(),
        'observed_stage_parent_to_completion_envelopes_ms': {stage: q(x) for stage, x in sorted(spans.items())},
        'recorded_queue_enter_to_start_ms': q(queue_spans), 'true_queue_wait_ms': None, 'pure_inference_service_ms': None,
        'policy_complete_branch_identity_joins': len(policy), 'native_policy_path_envelope_ms': q(paths),
        'maximum_path_span_vs_named_actual_service_ms_absolute_difference': max(path_reported_deltas),
        'admissions_before_wall_window_start_kept': ingress_boundaries,
    }
    match = {(r['stream_id'], r['frame_id'], r['input_frame_key']) for r in ledger.values()}
    completed = {(r['stream_id'], r['frame_id'], ledger[k]['input_frame_key']) for k, r in frames.items()}
    return output, match, completed


def main():
    outputs, paired = [], {}
    for resource, pair in (('cpu', 'cpu-pair-08'), ('gpu', 'gpu-pair-02')):
        members = []
        for topology in ('independent-processes', 'shared-video-dag'):
            directory = ROOT / pair / 'operations/arms' / ('component-gstreamer_custom-' + resource + '-h264-' + topology) / 'evidence'
            output, admissions, completed = calculate(directory)
            output.update(resource=resource, topology=topology)
            outputs.append(output); members.append((admissions, completed))
        assert members[0][0] == members[1][0]
        paired[resource] = {'identical_admissions_by_stream_frame_input': len(members[0][0]),
            'common_completed_input_count': len(members[0][1] & members[1][1]),
            'baseline_only_completed_input_count': len(members[0][1] - members[1][1]),
            'shared_only_completed_input_count': len(members[1][1] - members[0][1]), 'causal_speedup_inferred': False}
    output_path = Path(sys.argv[1])
    summary = {'kind': 'independent_original_four_arm_calculation', 'acceptance_authority': False,
        'quantile_formula': 'linear interpolation at q*(n-1)', 'arms': outputs, 'paired_populations': paired,
        'limits': ['completed frame envelopes, not hardware busy or pure inference service', 'policy-path population is all completed measurement branches',
            'one baseline-first pair per resource; two recordings; no causal or population inference', 'recorded measurement cohort retained regardless of rounded wall boundary']}
    with output_path.open('xb') as stream:
        stream.write((json.dumps(summary, indent=2, sort_keys=True, default=str) + '\n').encode('utf-8'))
    print(json.dumps({'output': str(output_path), 'arms': len(outputs), 'calculation_completed': True}))


if __name__ == '__main__':
    main()
