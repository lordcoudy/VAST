"""Finite closed original CPU archive joins; no project imports or remote work."""
import collections,hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
ARCHIVE=OUT/'36764814739-cpu/original-artifact.zip'
def doc(path):return json.loads(path.read_bytes())
def ref(path):
    raw=path.read_bytes();return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=1024*1024
    with (OUT/name).open('xb') as stream:stream.write(raw)
    return ref(OUT/name)
inventory=doc(OUT/'36764814739-cpu/zip-readonly-inventory.v1.json')
assert ref(ARCHIVE)['size_bytes']==1937644 and ref(ARCHIVE)['sha256']=='8b03433fd6ffcbe0f231c8a7d92be8bda0b7f337bdd9792d9f92408e6fe32cd6'
assert inventory['all_member_crc_verified'] and inventory['zip_members']==178 and inventory['decoded_size_bytes']==10295796
jobs=doc(OUT/'provider-jobs.final.original.json')['structuredContent']['jobs']
assert next(row for row in jobs if row['id']==110056199709)['conclusion']=='failure'
with zipfile.ZipFile(ARCHIVE) as archive:
    report=json.loads(archive.read('report.json'));child=json.loads(archive.read('unittest-child.report.json'))
    before=json.loads(archive.read('tracked-source.before.json'));after=json.loads(archive.read('tracked-source.after.json'))
    assert before==after and report['changed_tracked_paths']==[]
    assert report['commit']=='5bc416a2beab98b6cc60229dac56332b48cc6ca2'
    assert report['unittest']==child and not report['successful'] and not child['successful']
    for source in doc(OUT/'host-original-readonly-review.v1.json')['committed_source_snapshots_match_original_hosted_bytes']:
        assert before[source['path']]=={key:source[key] for key in ('sha256','size_bytes')}
    failures=[dict(row,outcome=kind) for kind in ('errors','failures') for row in child[kind]]
    index=save('cpu-failure-index.v1.json',{'source_commit':report['commit'],'original_failure_rows':failures})
    assert child['selection']['counts']=={'discovered':2947,'portable':2938,'integration':9}
    assert child['tests_run']==len(child['successful_test_ids'])+len(child['skips'])+len(child['errors'])+len(child['failures'])==2938
    assert len(child['successful_test_ids'])==2804 and len(child['skips'])==len(child['portable_skip_audit'])==88
    assert len(child['errors'])==25 and len(child['failures'])==21 and not child['missing_required_successes']
    required=['test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.'+name for name in ('test_native_client_regression','test_native_policy_topology_regression','test_native_reset_queue_level_regression')]
    assert set(required)<=set(child['successful_test_ids'])
    assert len(report['built_targets'])==6 and set(report['gstreamer_factories'])=={'appsrc','queue','videoconvert'}
    assert all(row['command']['returncode']==0 and row['plugin']['sha256'] for row in report['gstreamer_factories'].values())
    observed=report['observer'];assert observed['returncode']==1 and observed['signal'] is None and not observed['forced_sigkill'] and not observed['forced_sigterm']
    ns=report['namespace_diagnostic'];denial=json.loads(archive.read('namespace-diagnostic/kernel-denial.json'))
    raw_query=archive.read('namespace-diagnostic/kernel-query/stdout.raw')
    query_records=[json.loads(line) for line in raw_query.splitlines()]
    assert len(query_records)==1 and denial['records'][0]['original_journal_record']==query_records[0]
    error=ns['first_failed_syscall'];assert error['pid']==ns['owner']['pid']==3991 and error['syscall']=='open' and error['path']=='/proc/self/setgroups' and error['errno']==13
    successful_unshare=[row for row in ns['original_setup_observations'] if row.get('event')=='syscall_completed' and row.get('syscall')=='unshare']
    assert len(successful_unshare)==1 and successful_unshare[0]['flags']==268435456
    kernel=query_records[0];message=kernel['MESSAGE'];assert 'apparmor="DENIED"' in message and 'pid=3991 ' in message and 'capname="sys_admin"' in message and 'profile="unprivileged_userns"' in message
    assert kernel['_BOOT_ID']==ns['owner']['boot_id'].replace('-','')
    event_wall=int(kernel['__REALTIME_TIMESTAMP'])*1000
    assert ns['started_wall_time_ns']<=event_wall<=ns['terminal_wall_time_ns']
    assert ns['capture_completed'] and not ns['timed_out'] and ns['original_group_absent'] and ns['original_group_members']==[]
    assert denial['original_kernel_query']['returncode']==0 and denial['policy_denial_proven'] is False
    namespace_refs=[]
    for name in ('namespace-diagnostic/stdout.raw','namespace-diagnostic/kernel-query/stdout.raw','namespace-diagnostic/kernel-denial.json','namespace-diagnostic/capture.json','namespace-diagnostic/kernel-query/capture.json'):
        raw=archive.read(name);assert len(raw)<=16384
        destination=OUT/('original-'+name.replace('/','--'))
        with destination.open('xb') as stream:stream.write(raw)
        namespace_refs.append(ref(destination))
log=doc(OUT/'cpu-job-110056199709.decoded-tool-result.original.json')['structuredContent']['content']
with (OUT/'cpu-job-110056199709.decoded.exact.original.log').open('xb') as stream:stream.write(log.encode('utf-8'))
groups=dict(collections.Counter(row['test_id'].split('.')[0] for row in failures))
result={
    'schema_version':1,'artifact_kind':'vast_5bc_original_cpu_ci_closed_readonly_review_v1',
    'run_id':36764814739,'job_id':110056199709,'source_commit':report['commit'],'original_conclusion':'failure',
    'archive':ref(ARCHIVE),'zip_inventory':ref(OUT/'36764814739-cpu/zip-readonly-inventory.v1.json'),
    'provider_jobs':ref(OUT/'provider-jobs.final.original.json'),'decoded_joblog':ref(OUT/'cpu-job-110056199709.decoded.exact.original.log'),
    'failure_index':index,'zip_members':178,'decoded_bytes':10295796,'crc_all_members_verified':True,
    'tracked_before_after_equal':True,'tracked_path_count':len(before),'four_original_committed_sources_match_hosted_bytes':True,
    'built_targets':report['built_targets'],'required_native_successes':required,
    'actual_loaded_gstreamer_factories':{key:{'plugin':value['plugin'],'returncode':value['command']['returncode']} for key,value in report['gstreamer_factories'].items()},
    'selection_counts':child['selection']['counts'],'test_outcomes':{'executed':2938,'success':2804,'existing_audited_skips':88,'errors':25,'failures':21,'missing_required_native_successes':0},
    'failure_module_counts':groups,'original_full_elapsed_s':report['elapsed_s'],
    'original_suite_observer':{'returncode':1,'signal':None,'forced_sigkill':False,'forced_sigterm':False,'pipe_eof':observed['pipe_eof'],'descendant_quiescence':observed['descendant_quiescence']},
    'namespace_observation':{'original_owner':ns['owner'],'successful_first_unshare':successful_unshare[0],
        'first_failed_syscall':error,'original_raw_evidence':namespace_refs,'original_kernel_record':kernel,
        'same_original_pid_boot_and_wall_interval':True,'journal_record_wall_minus_syscall_terminal_ns':event_wall-error['terminal_wall_time_ns'],
        'original_kernel_query_rc':0,'collector_policy_denial_proven':False,'original_namespace_group_absent':True,
        'interpretation':'A genuine matching AppArmor capable/sys_admin denial now exists for the same original interpreter PID/boot/time interval after successful CLONE_NEWUSER and failed setgroups open. This supports a narrowly scoped policy investigation; it does not authorize a profile or prove every remaining test failure shares that cause. The original candidate-only collector boolean stays false.'},
    'ranked_next_source_actions':['Investigate the actual same-PID sys_admin denial around the strict setgroups-open path before proposing a separately reviewed exact-executable ephemeral CI profile; no global waiver, skip or containment weakening.','Make the one remaining GVA pure policy/topology fixture hermetic using genuine historical metadata in an owned temp root; do not fabricate physical acceptance or defer this portable case by failure text.'],
    'limitations':['One original full run with normal childreport and exit1; no native139 observed here and no causal conclusion about historical139.','45 of46 remaining rows are in broker/transaction/supervisor modules; their exact tracebacks are preserved. Membership is not per-test syscall cause proof.','Original observer explicitly does not infer descendant quiescence from child status; no broader process/container cleanup claim added.','No model/native/engine/namespace/profile/test/rerun/cancellation by reviewer; only original archive/log retention and finite pure joins.'],
    'full_ci_successful':False,'hardware_acceptance':False,'temporary_urls_or_credentials_saved_or_output':False,
}
print(json.dumps(save('cpu-review.v1.json',result),sort_keys=True))
