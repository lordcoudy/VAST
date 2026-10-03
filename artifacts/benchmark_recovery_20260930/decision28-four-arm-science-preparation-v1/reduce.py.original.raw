"""One pure reduction of closed CPU06/GPU01 sidecars; no new measurement grant."""
import hashlib
import argparse
import json
import os
import stat
import sys
import time
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project-root',required=True,type=Path)
parser.add_argument('--output-dir',required=True,type=Path)
parser.add_argument('--execution-deadline-ns',required=True,type=int)
parser.add_argument('--font-cache',required=True,type=Path)
for resource in ('cpu','gpu'):
    parser.add_argument('--'+resource+'-original-terminal',required=True,type=Path)
    parser.add_argument('--'+resource+'-original-terminal-sha256',required=True)
    parser.add_argument('--'+resource+'-original-terminal-size',required=True,type=int)
args=parser.parse_args()
ROOT=args.project_root.resolve(strict=True)
assert ROOT==Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
OUT=args.output_dir.resolve(strict=True)
END=args.execution_deadline_ns
START=time.monotonic()
assert START<END/1e9
MUTABLE = {'publication_gstreamer_component_cli_v1.py', 'publication_gstreamer_component_inputs_v1.py',
           'publication_gstreamer_component_runtime_v1.py'}
held, ancestors, namespaces = {}, {}, {}
original_input_epochs = {}
AUTHENTIC = {
 'cpu': {'terminal': (88066,'e87c878c725f309cf344f27926cb6e12647e839a8f5745084b69619c090d3db9'),
         'cli': '325b61a733baaa6b304131d6b45e4b612d29d7e4212521d0f7d4a0ef231f5b99',
         'cold': 'a44e07d2f943de47789ce2fd7eb6f20610da1849268a18603aed5a6a80251841',
         'pid':42153,'ppid':42151,'startticks':28495618},
 'gpu': {'terminal': (88102,'4c0e3fd34fb8ac8255bffab52fec7a310601eb4d29211a40f6948e882cbf3fc9'),
         'cli': 'abea1a00a5cb5c68e56657b78bea0683461bed121cce61afb11f2f1cd046460e',
         'cold': 'a28af5697096df8a468be6c04cf6307c4a425778a3b9b83f6dfae1c54025562d',
         'pid':47763,'ppid':47761,'startticks':28764548},
}


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]

def ancestor(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]

def clock():
    assert time.monotonic_ns()<END, 'original pure science110s execution deadline exceeded'

def check(path):
    clock()
    fd, first = held[path]['fd'], held[path]['before']['epoch']
    assert epoch(os.fstat(fd)) == epoch(path.lstat()) == first, f'leaf epoch drift: {path}'
    for parent, observed in ancestors.items():
        assert ancestor(parent.lstat()) == observed and not parent.is_symlink(), f'ancestor drift: {parent}'

def hash_fd(fd):
    digest, size = hashlib.sha256(), 0
    os.lseek(fd, 0, os.SEEK_SET)
    while raw := os.read(fd, 1048576):
        clock()
        size += len(raw)
        assert size <= 64 * 1024 * 1024
        digest.update(raw)
    return size, digest.hexdigest()

def hold(path, expected=None, allow_empty=False):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    assert path.resolve(strict=True) == path
    if path not in held:
        for parent in path.parents:
            ancestors.setdefault(parent, ancestor(parent.lstat()))
        assert len(held)<512, 'finite pure input count exceeded'
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and (0 <= info.st_size if allow_empty else 0 < info.st_size) and info.st_size <= 64 * 1024 * 1024
            size, digest = hash_fd(fd)
            assert epoch(os.fstat(fd))==epoch(path.lstat())==epoch(info), 'input changed while initially hashing'
            if str(path) in original_input_epochs:
                original=original_input_epochs[str(path)]
                assert epoch(info)==original['epoch'] and size==original['descriptor']['size_bytes'] and digest==original['descriptor']['sha256'], 'original input epoch/bytes no longer match'
            held[path] = {'fd': fd, 'before': {'path': str(path), 'size_bytes': size, 'sha256': digest, 'epoch': epoch(info)}}
        except BaseException:
            os.close(fd)
            raise
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
all_latencies, accepted_inputs = [], []
try:
    hold(Path(__file__))
    hold(Path(__file__).with_name('run.py'))
    renderer_path=Path(__file__).with_name('render.py')
    hold(renderer_path)
    import importlib.util
    spec=importlib.util.spec_from_file_location('science_render',renderer_path)
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    for resource in ('cpu','gpu'):
        terminal_path=getattr(args,resource+'_original_terminal')
        expected={'path':str(terminal_path),'size_bytes':getattr(args,resource+'_original_terminal_size'),
                  'sha256':getattr(args,resource+'_original_terminal_sha256')}
        assert (expected['size_bytes'],expected['sha256'])==AUTHENTIC[resource]['terminal']
        original=doc(terminal_path,expected)
        assert original['source_commit']=='0ad78d6abdb3c526544a17185af7fe8094716735'
        assert original['original_returncode']==0 and original['failure'] is None and not original['signals']
        assert not original['timed_out'] and not original['capture_exceeded']
        assert original['original_cli_process_group_members']==[] and original['pins_before']==original['pins_after']
        recorded_owner=original['owner'];auth=AUTHENTIC[resource]
        assert recorded_owner=={'pid':auth['pid'],'ppid':auth['ppid'],'pgid':auth['pid'],
            'startticks':auth['startticks'],'uid':1000,'gid':1000,'boot_id':'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'}
        assert original['original_child_pid']==auth['pid'] and original['elapsed_s']<2250
        assert len(original['pins_before'])==95
        for item in original['pins_before']:
            key=item['descriptor']['path']
            assert key not in original_input_epochs or original_input_epochs[key]==item, 'CPU/GPU original input identity differs'
            original_input_epochs[key]=item
        argv=original['argv']
        def argument(flag):
            assert argv.count(flag)==1
            return argv[argv.index(flag)+1]
        assert argument('--project-root')==str(ROOT) and argument('--resource')==resource
        pair=Path(argument('--output-dir'))
        assert pair==ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'/('cpu-pair-06' if resource=='cpu' else 'gpu-pair-01')
        assert terminal_path==pair.parent/(pair.name+'-original-controller')/'original.terminal.v1.json'
        assert argument('--execution-code-closure-path')==str(pair.parent/'host/execution-code-closure.ext4.v1.json')
        assert original['original_cli_terminal']['path']==str(pair/'component_cli_terminal.v1.json')
        assert original['original_cli_terminal']['sha256']==auth['cli']
        cli=ref(original['original_cli_terminal'])
        assert cli['pair_result']['sha256']==auth['cold']
        assert cli['status']=='component_pair_complete' and cli['resource']==resource and cli['primary_error'] is None
        assert not cli['cleanup_errors'] and cli['guardian_cleanup_verified'] is True
        assert cli['capacity_reservation']['released'] is True
        for channel in ('stdout','stderr'):hold(original[channel]['path'],original[channel],allow_empty=True)
        accepted_inputs.append((resource,pair,original,cli))
    closure_path=accepted_inputs[0][1].parent/'host/execution-code-closure.ext4.v1.json'
    closure=doc(closure_path)
    assert held[closure_path]['before']['sha256']=='adbcb638a5f104e43c95b84e4d16388a8111d39321afb3e8e7a26f2ef537b498'
    original_sources={row['path']:row for row in closure['project_sources']}
    sys.path.insert(0,str(ROOT/'scripts'))
    import yaml
    import benchmark_contract as contract
    import checkpoint_publication_runtime as runtime
    from topology_contract import validate_topology_events
    from publication_acceptance_evidence import frozen_policy_requires_feedback
    from full_resource_contract import validate_full_resource_evidence
    from publication_operational_request_domain_v1 import payload_with_sha256_v1
    def hold_project_imports():
        for module in tuple(sys.modules.values()):
            location=getattr(module,'__file__',None)
            if not location:continue
            path=Path(location).absolute()
            try:relative=path.relative_to(ROOT/'scripts')
            except ValueError:continue
            assert path.name not in MUTABLE,'mutable component/full authority module imported'
            hold(path,original_sources['scripts/'+relative.as_posix()])
    hold_project_imports()
    for resource,PAIR,original_terminal,cli in accepted_inputs:
        authority = doc(PAIR / 'source/gstreamer-component-authority.v1.json')
        configuration_path = hold(authority['environment']['experiments_config']['path'], authority['environment']['experiments_config'])
        configuration = yaml.safe_load(configuration_path.read_bytes())
        index = doc(PAIR / 'operations/capture-plan/capture_plan_index.v1.json')
        operations = ref(index['operation_manifest'])['operations']
        cold = doc(PAIR / 'cold-pair/component_pair_result.v1.json')
        assert payload_with_sha256_v1({key:value for key,value in cli.items() if key!='sha256'})==cli
        assert cli['pair_result']=={key:held[PAIR/'cold-pair/component_pair_result.v1.json']['before'][key] for key in ('path','size_bytes','sha256')}
        assert cold['publication_ready'] is False
        assert payload_with_sha256_v1({key:value for key,value in cold.items() if key!='sha256'})==cold
        authority_descriptor={key:held[PAIR/'source/gstreamer-component-authority.v1.json']['before'][key] for key in ('path','size_bytes','sha256')}
        assert cold['component_authority']=={**authority_descriptor,'path':str(Path(authority_descriptor['path']).relative_to(ROOT))}
        assert payload_with_sha256_v1({key:value for key,value in authority.items() if key!='sha256'})==authority
        assert cold['scientific_scope'] == 'topology_load_proxy_only' and cold['resource'] == resource
        assert len(cold['arms']) == len(cold['arm_results']) == 2
        for row in (cold['descriptive_csv'], cold['latency_ecdf_svg']):
            hold(row['path'], row)
        import csv
        csv_path = hold(PAIR / 'cold-pair/component_pair_metrics.csv', cold['descriptive_csv'])
        with csv_path.open(newline='') as csv_stream:
            csv_rows = list(csv.DictReader(csv_stream))
        assert len(csv_rows) == 2 and len(csv_rows[0])==len(csv_rows[1])==14

        assert len(operations) == 2 and authority['resource'] == resource
        for position, operation in enumerate(operations):
            name = 'baseline' if position == 0 else 'shared'
            plan = ref(authority['source_plans'][name])
            original = ref(operation['original_operation'])
            directory = Path(original['outputs']['measurement_dir'])
            assert original['operation'] == {key: value for key, value in operation.items() if key != 'original_operation'}
            assert directory.parent.name == operation['operation_id']
            assert directory.is_relative_to(PAIR/'operations')
            assert operation['system'] == plan['system'] == 'gstreamer_custom'
            assert operation['scenario'] == plan['scenario'] and operation['policy'] == resource+'_only'
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
            outcome = {'resource':resource,'operation_id': operation['operation_id'], 'scenario': operation['scenario'],
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
            outcome['decoder_placement']=plan['decoder_placement']
            outcome['source_playback']=plan['source_playback']
            outcome['logical_stream_recordings']=[{'stream_id':stream['stream_id'],'source_id':stream['source_id']} for stream in plan['streams']]
            outcome['schedule_fingerprint_sha256']=cold['measurement_schedule_fingerprint_sha256']
            all_latencies.append(frames['e2e_latency_ms'].sort_values().to_numpy().tolist())
            results.append(outcome)
            print(json.dumps({'operation': operation['operation_id'], 'legacy_match': outcome['candidate_comparison']['equal'],
                              'arm_match': outcome['carried_arm_comparison']['equal']}), flush=True)
    assert len(results)==4 and [(row['resource'],row['scenario']) for row in results]==[
        ('cpu','checkpoint_independent_processes_baseline'),('cpu','checkpoint_video_dag_shared'),
        ('gpu','checkpoint_independent_processes_baseline'),('gpu','checkpoint_video_dag_shared')]
    fingerprint_keys=('measurement_signature','input_schedule_sha256','input_frame_key_sequence_sha256','measurement_window_duration_ms')
    baseline=results[0]['recomputed_v2_summary']
    for row in results:
        assert row['schedule_fingerprint_sha256']==results[0]['schedule_fingerprint_sha256']
        assert all(row['recomputed_v2_summary'][key]==baseline[key] for key in fingerprint_keys),'original source/input cohort differs'
    hold_project_imports()
    save('recomputed-summaries.v1.json',results)
    exports=renderer.render_four_arm_exports_v1(results,all_latencies,OUT,args.font_cache,hold,doc,clock)
    save('exports-and-interpretation.v1.json',exports)
    hold_project_imports()
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
        close_errors=[]
        for row in held.values():
            try:os.close(row['fd'])
            except OSError as exc:close_errors.append(str(exc))
        closed=not close_errors
        if close_errors and primary is None:primary={'type':'OSError','message':'original held FD release failed: '+str(close_errors)[:1000]}
    save('custody-and-comparison.v1.json', {'schema_version': 1, 'scope': 'Pure original closed CPU06/GPU01 four-arm sidecar reduction; no new cold or measurement grant',
        'before': [row['before'] for row in held.values()], 'after': after, 'namespaces': {str(path): names for path, names in namespaces.items()},
        'source_scope': 'Actual reducer import closure only; mutable component CLI/inputs/runtime excluded, no claim about all87 sources.',
        'primary_error': primary, 'original_receipts': {r:{'outer':AUTHENTIC[r]['terminal'],'cli_sha256':AUTHENTIC[r]['cli'],'cold_sha256':AUTHENTIC[r]['cold']} for r in ('cpu','gpu')}, 'fd_holds_released': closed, 'reduced_arms': len(results), 'elapsed_s': time.monotonic() - START,
        'all_fields_match': len(results) == 4 and all(all(row[key]['equal'] for key in ('candidate_comparison', 'carried_arm_comparison', 'cold_summary_comparison', 'cold_descriptive_comparison')) for row in results),
        'measurement_acceptance': False, 'all_phase_cold': False, 'original_cli_status':'both_original_success_required',
        'engine_or_model_or_native_or_guardian_operations': False})
clock()
raise SystemExit(0 if primary is None and len(results) == 4 else 78)
