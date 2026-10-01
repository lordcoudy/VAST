"""Finite read-only metadata joins for a retained original SUCCESS run; never execute CI."""
from pathlib import Path
import collections,hashlib,json,re,subprocess,time,zipfile
ROOT=Path(r'E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930/ci-e897-original-host-retention-v1'
COMMIT='e897514dbefe3015756995d05f924aa44dd39552'
START=time.monotonic()
def descriptor(p):
 b=p.read_bytes();return {'path':p.relative_to(ROOT).as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def save(name,value):
 b=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(b)<=8*1024*1024
 with (BASE/name).open('xb') as f:f.write(b)
 return descriptor(BASE/name)
retained=json.loads((BASE/'original-retention-terminal.v1.json').read_bytes());assert retained['status']=='originals_retained'
provider=json.loads((BASE/'original-provider-metadata.v1.json').read_bytes())
artifacts={('cpu' if 'cpu-checks' in x['artifact_name'] else 'host'):x for x in retained['originals'] if x['kind']=='original_artifact'}
archives={};raw={};leaf_descriptors={}
for kind,row in artifacts.items():
 path=BASE/Path(row['path']).name;assert descriptor(path)['sha256']==row['sha256'];archives[kind]=zipfile.ZipFile(path)
 for item in row['members']:
  if item['name'].startswith('build/'):continue
  b=archives[kind].read(item['name']);assert len(b)==item['size_bytes'] and hashlib.sha256(b).hexdigest()==item['sha256'];raw[(kind,item['name'])]=b
  leaf_descriptors[(kind,item['name'])]={'zip':descriptor(path),'member':item}
def doc(name,kind='cpu'):return json.loads(raw[(kind,name)])
report=doc('report.json');unit=doc('unittest-child.report.json');selection=unit['selection']
assert report['commit']==COMMIT and report['successful'] and report['raw_checkout_bytes_match_commit'] and not report['changed_tracked_paths']
assert unit['successful'] and not any(unit[k] for k in ('errors','failures','expected_failures','unexpected_successes','missing_required_successes'))
discovered=set(unit['discovered_ids']);portable=set(selection['portable_ids']);success=set(unit['successful_test_ids']);skips={x['test_id']:x['reason'] for x in unit['skips']};allowed={x['test_id']:x['reason'] for x in selection['allowed_portable_skips']};deferred={x['test_id'] for x in selection['integration_declarations']}
assert len(discovered)==2972 and len(portable)==unit['tests_run']==2963 and len(success)==2875 and len(skips)==88
assert success.isdisjoint(skips) and success|set(skips)==portable and portable.isdisjoint(deferred) and portable|deferred==discovered and len(deferred)==9 and skips==allowed
assert all(x['acceptance_claim'] is False for x in unit['portable_skip_audit'])
assert doc('tracked-source.before.json')==doc('tracked-source.after.json') and len(doc('tracked-source.before.json'))==4402
assert doc('tracked-source.before.json','host')==doc('tracked-source.after.json','host')
original_sources=BASE/'committed-source';original_sources.mkdir(exist_ok=False)
git=Path(r'C:/Program Files/Git/cmd/git.exe');gitdir=Path(r'E:/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec')
source_records=[]
for name in ('.github/workflows/ci.yml','.ci/integration-test-selection.v1.json','scripts/run_ci_checks.py','scripts/ci_external_test_observer_v1.py','scripts/ci_namespace_diagnostic_v1.py','scripts/ci_userns_profile_v1.py','scripts/ci_test_selection_v1.py'):
 result=subprocess.run([str(git),'-c','core.longpaths=true','--git-dir='+str(gitdir),'--work-tree='+str(ROOT),'show',COMMIT+':'+name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True)
 b=result.stdout;assert len(b)<=1024*1024
 expected=doc('tracked-source.before.json')[name];assert len(b)==expected['size_bytes'] and hashlib.sha256(b).hexdigest()==expected['sha256']
 p=original_sources/name;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
 source_records.append(descriptor(p))
manifest=json.loads((original_sources/'.ci/integration-test-selection.v1.json').read_bytes());assert hashlib.sha256((original_sources/'.ci/integration-test-selection.v1.json').read_bytes()).hexdigest()==selection['manifest_sha256']
observer=doc('external-test-observer/terminal.v1.json');launch=doc('external-test-observer/launch.v1.json')
assert observer['owner']==launch['owner'] and observer['argv']==launch['argv'] and observer['returncode']==0 and observer['successful'] and observer['failure'] is None and not observer['forced_sigkill'] and not observer['forced_sigterm'] and observer['pipe_eof']=={'control':True,'trace':True}
assert observer['started_monotonic_ns']<=observer['finished_monotonic_ns']<observer['absolute_deadline_ns']<report['absolute_deadline_ns'] and report['absolute_deadline_ns']-report['job_started_monotonic_ns']==5400*10**9
responses=[json.loads(x) for x in raw[('cpu','external-test-observer/responses.original.jsonl')].splitlines()];events=[json.loads(x) for x in raw[('cpu','external-test-observer/events.original.jsonl')].splitlines()]
ready=next(x for x in responses if x['event']=='ready');assert ready['native_task_count']==1 and ready['handler']=='python_main_thread_safe_gil' and ready['pid']==observer['owner']['pid']
assert collections.Counter(x['event'] for x in responses)['response_finished']==observer['responses_completed']==22 and collections.Counter(x['event'] for x in events)['request_sent']==observer['requests_sent']==22
profile=doc('namespace-profile/profile-lifecycle.json');intent=doc('namespace-profile/load-intent.json');joined=doc('namespace-profile/joined-denial.json');capture=doc('namespace-diagnostic/capture.json');ns=[json.loads(x) for x in raw[('cpu','namespace-diagnostic/stdout.raw')].splitlines()]
assert capture['capture_completed'] and capture['original_group_absent'] and capture['owner']['pid']==joined['join']['pid']==3982 and capture['owner']['boot_id']==joined['join']['boot_id']
failed=next(x for x in ns if x['event']=='syscall_failed');assert failed['syscall']=='open' and failed['path']=='/proc/self/setgroups' and failed['errno']==13
assert any(x['event']=='syscall_completed' and x['syscall']=='unshare' for x in ns)
kernel=doc('namespace-diagnostic/kernel-denial.json');record=kernel['records'][0]['original_journal_record'];assert record['_BOOT_ID']==joined['join']['boot_id'].replace('-','')
message=record['MESSAGE'];assert 'pid=3982 ' in message and 'profile="unprivileged_userns"' in message and 'capname="sys_admin"' in message and 'operation="capable"' in message
for ref in joined['inputs']:
 if ref['path'].endswith('python3.12'):continue
 relative=ref['path'].split('/vast-cpu-checks/',1)[1];b=raw[('cpu',relative)];assert len(b)==ref['size_bytes'] and hashlib.sha256(b).hexdigest()==ref['sha256']
assert profile['held_fds_released'] and profile['load_verified'] and profile['unload_verified'] and profile['status']=='completed' and intent['unique_name_absent_before_original_add']
assert intent['profile']==profile['profile'] and intent['argv'][8]=='--add'
assert hashlib.sha256(raw[('cpu','namespace-profile/owned.profile')]).hexdigest()==profile['profile']['sha256']
name=profile['name'];assert name not in raw[('cpu','namespace-profile/load-before/stdout.raw')].decode() and (name+' (unconfined)') in raw[('cpu','namespace-profile/load-after/stdout.raw')].decode() and name not in raw[('cpu','namespace-profile/unload-after/stdout.raw')].decode()
assert unit['profile_observation']['actual_label']['value']==unit['profile_observation']['expected_profile']==name+' (unconfined)' and unit['profile_observation']['pid']==observer['owner']['pid']
for phase in ('load','unload'):
 c=doc('namespace-profile/'+phase+'/capture.json');assert c['capture_completed'] and c['returncode']==0 and not c['timed_out'] and c['failure'] is None
assert doc('native-configure.json')['returncode']==doc('native-build.json')['returncode']==0 and len(report['built_targets'])==6
host=doc('report.json','host');assert host['commit']==COMMIT and host['diagnostic_passed'] and len(host['test_ids'])==2 and host['original_process']['returncode']==0 and host['full_ci_successful'] is False
protected_modules=('test_native_gst','test_checkpoint_source','test_backend_publication_process_supervisor','test_ci_','test_publication_gstreamer_component_','test_publication_operational_','test_backend_publication_broker_terminal_v3')
module_success_counts=dict(sorted(collections.Counter(x.split('.',1)[0] for x in success if x.startswith(protected_modules)).items()))
result={'schema_version':1,'artifact_kind':'vast_original_e897_hosted_ci_scoped_author_review_v1','status':'retained_original_full_portable_ci_success','run_id':36794448836,'source_commit':COMMIT,'cpu_job_id':110154542231,'host_job_id':110154541899,'provider_run_success':True,'cpu_report_member':leaf_descriptors[('cpu','report.json')],'host_report_member':leaf_descriptors[('host','report.json')],'original_retention_terminal':descriptor(BASE/'original-retention-terminal.v1.json'),'original_provider_metadata':descriptor(BASE/'original-provider-metadata.v1.json'),'source_snapshots':{'cpu_rows':4402,'host_rows':len(doc('tracked-source.before.json','host')),'before_after_equal':True,'cpu_raw_checkout_bytes_match_commit_reported':True,'seven_exact_original_CI_sources_independently_joined_to_raw_Git':source_records},'counts':{'discovered':len(discovered),'portable_executed':unit['tests_run'],'successes':len(success),'skips':len(skips),'declared_integration_deferred':len(deferred),'failures':0,'errors':0,'unexpected_successes':0,'expected_failures':0,'missing_required_successes':0},'skips':unit['portable_skip_audit'],'integrations_not_executed':selection['integration_declarations'],'manifest_sha256':selection['manifest_sha256'],'protected_module_success_counts':module_success_counts,'native':{'built_targets':report['built_targets'],'configure':doc('native-configure.json'),'build':doc('native-build.json'),'factories':list(report['gstreamer_factories'])},'observer':{'original_owner':observer['owner'],'ready_native_task_count':1,'requests_sent':22,'responses_started':22,'responses_completed':22,'request_stop_and_EOF':True,'returncode':0,'no_forced_signals':True,'actual_terminal_descendant_quiescence_limit':observer['descendant_quiescence'],'trace_bytes':observer['trace_bytes'],'event_kinds':dict(collections.Counter(x['event'] for x in events)),'response_kinds':dict(collections.Counter(x['event'] for x in responses))},'profile':{'exact_fresh_join':joined['join'],'initial_namespace_PID':3982,'suite_child_PID':3993,'unique_profile':name,'loaded_named_unconfined_observed':True,'actual_fresh_child_expected_label_observed':True,'exact_owned_unload_rc0_and_name_absent_observed':True,'held_FDs_released':True,'profile_source_sha256':profile['profile']['sha256'],'initial_collector_candidate_flag':kernel['policy_denial_proven'],'strict_join_is_separate_from_collector_candidate':True},'timing':{'job_original_budget_s':5400,'suite_deadline_reserve_s':30,'report_elapsed_s':report['elapsed_s'],'original_suite_elapsed_s':(observer['finished_monotonic_ns']-observer['started_monotonic_ns'])/1e9,'host_original_elapsed_s':host['original_process']['elapsed_s'],'CPU_provider_started_at':next(j for j in provider['jobs']['jobs'] if j['id']==110154542231)['started_at'],'CPU_provider_completed_at':next(j for j in provider['jobs']['jobs'] if j['id']==110154542231)['completed_at']},'scope_limits':['Original hosted portable CI at exacte897 is successful; current78b run33 and later checkpoints are separate originals.','88 skips are nonexecution:78 exactplatform/prerequisite and10 retired-schema migration.9 integrations remain unexecuted; none become success.','Native build and selected real native/unit test successes do not establish NVIDIA decode, packaged SDK/runtime inference/model parity/qualification/Q4/full campaign/scientific acceptance.','Original child return0+EOF does not prove global descendant quiescence; the retained observer explicitly states that limitation. No hosted /proc replay is possible.','No new workflow, test, native, namespace, AppArmor operation, engine, model or benchmark was run by this reader.'], 'hardware_acceptance':False,'workflow_action':None,'elapsed_review_s':time.monotonic()-START}
for z in archives.values():z.close()
ref=save('scoped-author-review.v1.json',result);print(json.dumps({'review':ref,'counts':result['counts'],'profile_loaded_removed':True,'source_snapshots_equal':True}),flush=True)
