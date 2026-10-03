"""Compact pointer-based summary of the already closed original review; no workload."""
import hashlib,json,os,pathlib,zipfile
ROOT=pathlib.Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=pathlib.Path(__file__).parent
RETAIN=ROOT/'artifacts/benchmark_recovery_20260930/ci-8fefa-original-retention-v1'
def descriptor(p):
    raw=p.read_bytes()
    return {'path':p.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
r=json.loads((OUT/'review.v1.json').read_bytes())
assert r['sha256']==hashlib.sha256(json.dumps({k:v for k,v in r.items() if k!='sha256'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
with zipfile.ZipFile(RETAIN/'36751014399-cpu/original-artifact.zip') as z:
    c=json.loads(z.read('unittest-child.report.json'))
    assert set(r['comparison']['new_discovered_ids'])<=set(c['successful_test_ids'])
    native_build=json.loads(z.read('native-build.json'))
    native_configure=json.loads(z.read('native-configure.json'))
index=json.loads((OUT/'failure-index.v1.json').read_bytes())
runner=r['original_runner']; query=r['kernel_query_original']; namespace=r['namespace_original']
value={'schema_version':1,'kind':'vast_ci8f_compact_original_review_v1','accepted':False,
    'run_id':r['run_id'],'source_commit':r['source_commit'],'complete_review':descriptor(OUT/'review.v1.json'),
    'failure_index':descriptor(OUT/'failure-index.v1.json'),'provider_metadata':r['provider_metadata'],
    'original_archives':r['archives'],'original_logs':r['original_decoded_logs'],
    'download_original_terminals':[descriptor(RETAIN/(k+'-download-terminal.v1.json')) for k in ('cpu','host')],
    'original_counts':r['counts'],'comparison':r['comparison'],'all_eighteen_new_methods_original_successful':True,
    'unchanged_88_actual_skip_pairs_under_original_80_declarations':r['comparison']['skip_id_reason_pairs_identical'],
    'exact_eight_undeclared_skips':index['exact_unapproved_skips'],'original_child_failure':r['original_child_failure'],
    'nine_unexecuted_integrations':index['declared_unexecuted_integrations'],
    'native_configure_original':native_configure,'native_build_original':native_build,
    'six_actual_built_targets':runner['built_targets'],'exact_native_three_success_ids':r['mandatory_native_success_ids'],
    'missing_required_successes':r['missing_required_successes'],
    'original_runner_summary':{k:runner[k] for k in ('commit','elapsed_s','canonical_python','python','changed_tracked_paths',
        'raw_checkout_bytes_match_commit','successful','failure','hardware_acceptance')},
    'original_host_report':r['original_host_report'],'original_tracked_source_count':r['original_tracked_source_count'],
    'host_cpu_before_after_source_manifests_equal':r['original_source_before_after_equal'],
    'five_original_commit_snapshots_independently_joined':r['committed_source_evidence'],
    'diagnostic_source_anchors':r['diagnostic_source_anchors'],
    'namespace_original_capture':namespace,'setup_original_events':r['setup_original_events'],
    'first_failed_syscall_derived_from_original_events':r['first_failed_syscall_derived_from_original_events'],
    'kernel_query_original_capture':query,'original_policy_denial':r['policy_denial_original'],
    'kernel_query_original_stderr_utf8':r['kernel_query_original_stderr_utf8'],
    'kernel_query_original_stdout_size':r['kernel_query_original_stdout_size'],
    'observed_denial_candidates':r['original_journal_records_and_joins'],
    'matching_failed_syscall_denial_proven':False,'profile_authorization':None,
    'actionable_new_difference':'The same-PID gate obtained an original initial-Python owner and complete query channels, replacing the prior owner-observation EACCES. The intended journal command still failed rc1 on the rejected --kernel option; no actual kernel denial was obtained. Correct the finite command in separately reviewed source before any later evidence claim; no policy/credential/profile change is supported.',
    'cause_limits':r['causality_limits'],
    'actual_external_observer':r['original_external_observer'],
    'observer_original_counts':r['observer_original_counts'],
    'tool_observation':'Complete review.v1.json conservatively retained the original runner body including its large tracked-source tables (1,940,468 bytes). This compact summary preserves its immutable physical descriptor; no original ZIP or review was overwritten.',
    'scope':r['scope']}
value['sha256']=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
target=OUT/'summary.v1.json'
with target.open('xb') as f:
    f.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode()); f.flush(); os.fsync(f.fileno())
print(json.dumps({'summary':descriptor(target),'review':descriptor(OUT/'review.v1.json'),'failure_index':descriptor(OUT/'failure-index.v1.json')}))
