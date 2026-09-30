"""One pure reduction of original CPU05 sidecars; no authority or publication."""
import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
PAIR = ROOT / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-05'
OUT = Path(__file__).parent / 'attempt01'
MUTABLE = {'publication_gstreamer_component_cli_v1.py', 'publication_gstreamer_component_inputs_v1.py',
           'publication_gstreamer_component_runtime_v1.py'}
START = time.monotonic()
held, ancestors, namespaces = {}, {}, {}

def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

def ancestor(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]

def check(path):
    fd, first = held[path]['fd'], held[path]['before']['epoch']
    assert epoch(os.fstat(fd)) == epoch(path.lstat()) == first, f'leaf epoch drift: {path}'
    for parent, observed in ancestors.items():
        assert ancestor(parent.lstat()) == observed and not parent.is_symlink(), f'ancestor drift: {parent}'

def hash_fd(fd):
    digest, size = hashlib.sha256(), 0
    os.lseek(fd, 0, os.SEEK_SET)
    while raw := os.read(fd, 1048576):
        size += len(raw)
        assert size <= 64 * 1024 * 1024
        digest.update(raw)
    return size, digest.hexdigest()

def hold(path, expected=None):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    assert path.resolve(strict=True) == path
    if path not in held:
        for parent in path.parents:
            ancestors.setdefault(parent, ancestor(parent.lstat()))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 64 * 1024 * 1024
        size, digest = hash_fd(fd)
        held[path] = {'fd': fd, 'before': {'path': str(path), 'size_bytes': size, 'sha256': digest, 'epoch': epoch(info)}}
        check(path)
    result = held[path]['before']
    if expected is not None:
        assert all(result[k] == expected[k] for k in ('size_bytes', 'sha256')), f'physical descriptor drift: {path}'
    return path

def doc(path, expected=None):
    path = hold(path, expected)
    fd = held[path]['fd']
    assert held[path]['before']['size_bytes'] <= 1048576
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, 1048577)
    check(path)
    return json.loads(raw)

def ref(row):
    return doc(row['path'], row)

def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    assert len(raw) <= 1048576
    with (OUT / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'path': str(OUT / name), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def forbidden(event, args):
    if event in {'subprocess.Popen', 'os.system', 'os.fork', 'os.posix_spawn', 'socket.connect', 'socket.bind'}:
        raise RuntimeError('pure reducer forbids process/network operation: ' + event)

sys.addaudithook(forbidden)
primary, after, closed, results = None, [], False, []
try:
    hold(Path(__file__))
    recipe_path = ROOT / 'artifacts/benchmark_recovery_20260930/component-cold-scientific-export-readonly-plan-v1/cold-sidecar-reduction-arguments.v1.json'
    recipe = doc(recipe_path)
    assert held[recipe_path]['before']['sha256'] == '79a5f65ea6d46fc3b256dbbee682e392dd507fe212741b32ec67ed4efb7b214a'
    for row in recipe['source_witnesses']:
        hold(row['path'], row)
    closure_path = PAIR.parent / 'host/execution-code-closure.v6.json'
    closure = doc(closure_path)
    original_sources = {row['path']: row for row in closure['project_sources']}
    sys.path.insert(0, str(ROOT / 'scripts'))
    import yaml
    import benchmark_contract as contract
    import checkpoint_publication_runtime as runtime
    from topology_contract import validate_topology_events
    from publication_acceptance_evidence import frozen_policy_requires_feedback
    from full_resource_contract import validate_full_resource_evidence
    for module in tuple(sys.modules.values()):
        location = getattr(module, '__file__', None)
        if not location:
            continue
        path = Path(location).absolute()
        try:
            relative = path.relative_to(ROOT / 'scripts')
        except ValueError:
            continue
        assert path.name not in MUTABLE, 'mutable component module unexpectedly imported'
        hold(path, original_sources['scripts/' + relative.as_posix()])
    authority = doc(PAIR / 'source/gstreamer-component-authority.v1.json')
    configuration_path = hold(authority['environment']['experiments_config']['path'], authority['environment']['experiments_config'])
    configuration = yaml.safe_load(configuration_path.read_bytes())
    index = doc(PAIR / 'operations/capture-plan/capture_plan_index.v1.json')
    operations = ref(index['operation_manifest'])['operations']
    cold = doc(PAIR / 'cold-pair/component_pair_result.v1.json')
    cli = doc(PAIR / 'component_cli_terminal.v1.json')
    late = doc(PAIR / 'component_cli_late_failure.v1.json')
    assert cli['status'] == late['status'] == 'failed' and cli['pair_result']['sha256'] == held[PAIR / 'cold-pair/component_pair_result.v1.json']['before']['sha256']
    assert late['original_terminal_sha256'] == cli['sha256'] and cold['publication_ready'] is False
    assert cold['scientific_scope'] == 'topology_load_proxy_only' and cold['resource'] == 'cpu'
    assert len(cold['arms']) == len(cold['arm_results']) == 2
    for row in (cold['descriptive_csv'], cold['latency_ecdf_svg']):
        hold(row['path'], row)
    import csv
    csv_path = hold(PAIR / 'cold-pair/component_pair_metrics.csv', cold['descriptive_csv'])
    with csv_path.open(newline='') as csv_stream:
        csv_rows = list(csv.DictReader(csv_stream))
    assert len(csv_rows) == 2

    assert len(operations) == 2 and authority['resource'] == 'cpu'
    for position, operation in enumerate(operations):
        name = 'baseline' if position == 0 else 'shared'
        plan = ref(authority['source_plans'][name])
        original = ref(operation['original_operation'])
        directory = Path(original['outputs']['measurement_dir'])
        assert original['operation'] == {key: value for key, value in operation.items() if key != 'original_operation'}
        assert directory.parent.name == operation['operation_id']
        assert operation['system'] == plan['system'] == 'gstreamer_custom'
        assert operation['scenario'] == plan['scenario'] and operation['policy'] == 'cpu_only'
        assert operation['warmup_s'] == 30 and operation['measurement_s'] == 180 and operation['drain_timeout_s'] == 10
        assert operation['deadline_ms'] == 100 and len(plan['streams']) == 6 and len(plan['required_branches']) == 4
        leaves = tuple(sorted(directory.iterdir()))
        assert all(path.is_file() and not path.is_symlink() for path in leaves)
        namespaces[directory] = [path.name for path in leaves]
        for path in leaves:
            hold(path)
        candidate = doc(directory / 'checkpoint_publication_candidate.json')
        arm = doc(directory.parent / 'component_arm_result.v1.json')
        assert arm['original_operation'] == operation['original_operation'] and arm['original_exit_code'] == 0
        assert candidate['run_id'] == arm['physical_validation']['run_id'] == operation['run_id']
        cold_arm = cold['arms'][position]
        assert cold_arm['operation_id'] == operation['operation_id'] and cold_arm['scenario'] == operation['scenario']
        assert cold['arm_results'][position] == {'path': str(directory.parent / 'component_arm_result.v1.json'),
            'size_bytes': held[directory.parent / 'component_arm_result.v1.json']['before']['size_bytes'],
            'sha256': held[directory.parent / 'component_arm_result.v1.json']['before']['sha256']}
        assert cold_arm['schedule_sha256'] == cold['measurement_schedule_fingerprint_sha256'] == arm['physical_validation']['measurement_schedule_fingerprint_sha256']

        for filename, digest in candidate['evidence_sha256'].items():
            assert held[directory / filename]['before']['sha256'] == digest
        for filename, digest in arm['physical_validation']['full_resource_evidence_sha256'].items():
            assert held[directory / filename]['before']['sha256'] == digest
        scenario = dict(configuration['scenarios'][operation['scenario']])
        scenario['name'] = operation['scenario']
        frames = contract.canonicalize_frames_csv(directory / 'frames.csv', mode='benchmark',
            run_id=operation['run_id'], detector=contract.CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
            backend=runtime.checkpoint_aggregate_backend(operation['system']))
        events = contract.validate_frame_events(directory / 'frame_events.csv')
        contract.validate_stage_trace_coverage(directory / 'frames.csv', directory / 'frame_events.csv',
            required_stages=[str(stage) for stage in scenario['pipeline']])
        topology = validate_topology_events(directory / 'topology_events.csv', frames=frames, frame_events=events, scenario=scenario)
        common = dict(frames=frames, topology_events=topology, required_branches=plan['required_branches'],
            topology_kind=plan['topology_kind'], expected_streams=len(plan['streams']),
            expected_run_id=operation['run_id'], require_reset_evidence=True)
        sidecars = contract.validate_required_sidecars(directory, **common,
            require_labeled_provenance=True, require_full_policy_trace=True, require_causal_policy_trace=True,
            require_online_policy_trace=frozen_policy_requires_feedback(operation['policy']),
            require_ingress_ledger=True, require_branch_terminals=True, require_stage_contracts=True)
        legacy = runtime._json_finite_or_null(contract.summarize_sidecars(directory, **common,
            require_full_resource_evidence=False, decoder_placement_contract=plan['decoder_placement']))
        full = validate_full_resource_evidence(directory, expected_run_id=operation['run_id'],
            ingress_ledger=sidecars['ingress_ledger'], topology_events=topology, frame_events=events,
            topology_kind=plan['topology_kind'])['summary']
        assert full['evidence_accepted'] is True and full['full_resource_coverage_complete'] is True
        updated = dict(legacy)
        updated.update(resource_contract_version=2, full_resource_evidence_accepted=True, full_resource_coverage_complete=True)
        updated.update({key: full[key] for key in ('nvdec_busy_equivalent_ns', 'nvdec_counter_scope',
            'fanout_thread_cpu_time_ns', 'fanout_work_units', 'fanout_counter_scope')})
        def comparison(observed, carried):
            keys = sorted(set(observed) | set(carried))
            def exact(value):
                return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
            return {'keys_compared': len(keys), 'equal': exact(observed) == exact(carried),
                'differences': {key: {'recomputed': observed.get(key), 'carried': carried.get(key),
                    'recomputed_present': key in observed, 'carried_present': key in carried}
                    for key in keys if key not in observed or key not in carried or exact(observed[key]) != exact(carried[key])}}
        metrics = contract.summarize_frames(directory / 'frames.csv', deadline_ms=operation['deadline_ms'],
            measurement_s=operation['measurement_s'])
        metrics.update(completed_deadline_misses=int((frames['e2e_latency_ms'] > operation['deadline_ms']).sum()),
            measurement_admitted=updated['ingress_frame_count'],
            measurement_dropped=updated['ingress_frame_count'] - len(frames), measurement_censored=0,
            completion_coverage=len(frames) / updated['ingress_frame_count'], latency_population='completed_measurement_frames')
        assert metrics['measurement_dropped'] == updated['dropped_frame_count']
        assert cold_arm['measurement_ingress_count'] == updated['ingress_frame_count']
        csv_expected = {**metrics, 'operation_id': operation['operation_id'], 'scenario': operation['scenario']}
        assert csv_rows[position] == {key: str(csv_expected[key]) for key in csv_rows[position]}
        assert len(legacy) == len(updated) == len(candidate['summary']) == len(arm['physical_validation']['summary']) == len(cold_arm['summary']) == 72
        outcome = {'operation_id': operation['operation_id'], 'scenario': operation['scenario'],
            'arguments': {'run_dir': str(directory), 'run_id': operation['run_id'], 'mode': 'benchmark',
                'policy': operation['policy'], 'topology_kind': plan['topology_kind'], 'required_branches': plan['required_branches'],
                'expected_streams': len(plan['streams']), 'decoder_placement_contract': plan['decoder_placement']},
            'recomputed_legacy_summary': legacy, 'recomputed_v2_summary': updated,
            'candidate_comparison': comparison(legacy, candidate['summary']),
            'carried_arm_comparison': comparison(updated, arm['physical_validation']['summary']),
            'cold_summary_comparison': comparison(updated, cold_arm['summary']),
            'cold_descriptive_comparison': comparison(metrics, cold_arm['descriptive_metrics']),
            'recomputed_descriptive_metrics': metrics, 'cold_csv_fields_exactly_matched': len(csv_rows[position]),
            'completed_rows': len(frames), 'completed_deadline_misses': int((frames['e2e_latency_ms'] > 100).sum())}
        assert all(outcome[key]['equal'] for key in ('candidate_comparison', 'carried_arm_comparison',
            'cold_summary_comparison', 'cold_descriptive_comparison')), 'original carried metric mismatch'
        results.append(outcome)
        print(json.dumps({'operation': operation['operation_id'], 'legacy_match': outcome['candidate_comparison']['equal'],
                          'arm_match': outcome['carried_arm_comparison']['equal']}), flush=True)
    save('recomputed-summaries.v1.json', results)
except BaseException as exc:
    primary = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
    import traceback
    traceback.print_exc()
finally:
    try:
        for path, row in held.items():
            check(path)
            size, digest = hash_fd(row['fd'])
            current = {'path': str(path), 'size_bytes': size, 'sha256': digest, 'epoch': epoch(os.fstat(row['fd']))}
            assert current == row['before']
            after.append(current)
        for directory, names in namespaces.items():
            assert sorted(path.name for path in directory.iterdir()) == names
    except BaseException as exc:
        if primary is None:
            primary = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
    finally:
        for row in held.values():
            os.close(row['fd'])
        closed = True
    save('custody-and-comparison.v1.json', {'schema_version': 1, 'scope': 'Pure closed CPU05 sidecar reduction, not full cold/CLI acceptance',
        'before': [row['before'] for row in held.values()], 'after': after, 'namespaces': {str(path): names for path, names in namespaces.items()},
        'source_scope': 'Actual reducer import closure only; mutable component CLI/inputs/runtime excluded, no claim about all87 sources.',
        'primary_error': primary, 'fd_holds_released': closed, 'reduced_arms': len(results), 'elapsed_s': time.monotonic() - START,
        'all_fields_match': len(results) == 2 and all(all(row[key]['equal'] for key in ('candidate_comparison', 'carried_arm_comparison', 'cold_summary_comparison', 'cold_descriptive_comparison')) for row in results),
        'measurement_acceptance': False, 'all_phase_cold': False, 'original_cli_status': 'failed_immutable',
        'engine_or_model_or_native_or_guardian_operations': False})
raise SystemExit(0 if primary is None and len(results) == 2 else 78)
