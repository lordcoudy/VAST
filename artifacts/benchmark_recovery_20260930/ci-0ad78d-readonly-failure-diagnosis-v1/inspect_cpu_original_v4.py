"""Finite original0ad hosted archive diagnosis; no tests or policy/engine work."""
from pathlib import Path,PurePosixPath
import collections,hashlib,json,os,stat,subprocess,zipfile
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
RETAIN=ROOT/'artifacts/benchmark_recovery_20260930/ci-0ad78d-original-host-retention-v1'
OUT=Path(__file__).parent/'original-inspection-v3'
ARCHIVE=RETAIN/'36773798497-cpu/original-artifact.zip'
COMMIT='0ad78d6abdb3c526544a17185af7fe8094716735'
OUT.mkdir(mode=0o700)
def ref(p):
 raw=p.read_bytes();return {'path':p.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def doc(p):return json.loads(p.read_bytes())
def save(name,value):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=1024*1024
 with (OUT/name).open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
 return ref(OUT/name)
archive_ref=ref(ARCHIVE)
assert archive_ref['size_bytes']==1946953 and archive_ref['sha256']=='ab520c48107272ad2b03615c3c1e0a755537cb9faf5ddbdedc0cc606b307e31b'
jobs=doc(RETAIN/'provider-jobs.final.original.json')['structuredContent']['jobs']
assert next(row for row in jobs if row['id']==110086521669)['conclusion']=='failure'
with zipfile.ZipFile(ARCHIVE) as z:
 names=[]
 for i in z.infolist():
  p=PurePosixPath(i.filename);assert not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename and '\0' not in i.filename
  assert p.as_posix()==i.filename and p.parts and ':' not in p.parts[0]
  assert not stat.S_ISLNK(i.external_attr>>16) and i.file_size<=16*1024*1024
  assert i.filename not in names;names.append(i.filename)
 assert len(names)==178 and sum(i.file_size for i in z.infolist())==10338880
 assert z.testzip() is None
 report=json.loads(z.read('report.json'));child=json.loads(z.read('unittest-child.report.json'))
 before=json.loads(z.read('tracked-source.before.json'));after=json.loads(z.read('tracked-source.after.json'))
 assert report['commit']==COMMIT and before==after and report['changed_tracked_paths']==[] and report['raw_checkout_bytes_match_commit'] is True
 assert report['unittest']==child and report['successful'] is False and child['successful'] is False
 failures=[dict(row,outcome=kind) for kind in ['errors','failures'] for row in child[kind]]
 index=save('cpu-failure-index.v1.json',{'source_commit':COMMIT,'run_id':36773798497,'job_id':110086521669,'original_failure_rows':failures})
 counts={key:len(child[key]) for key in ['successful_test_ids','errors','failures','skips']}
 assert child['tests_run']==sum(counts.values())==len(child['selection']['portable_ids'])
 assert child['selection']['counts']['discovered']==len(child['discovered_ids'])==len(child['selection']['discovered_ids'])
 assert child['selection']['counts']['portable']==child['tests_run'] and child['selection']['counts']['integration']==len(child['selection']['integration_declarations'])
 assert len(child['portable_skip_audit'])==len(child['skips'])
 assert not child['missing_required_successes'] and not child['unexpected_successes']
 required=['test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.'+name for name in ['test_native_client_regression','test_native_policy_topology_regression','test_native_reset_queue_level_regression']]
 assert set(required)<=set(child['successful_test_ids'])
 assert len(report['built_targets'])==6 and set(report['gstreamer_factories'])=={'appsrc','queue','videoconvert'}
 assert all(value['command']['returncode']==0 and value['plugin']['sha256'] for value in report['gstreamer_factories'].values())
 observed=report['observer'];assert observed['returncode']==1 and observed['signal'] is None and not observed['forced_sigkill'] and not observed['forced_sigterm']
 sources=['scripts/run_ci_checks.py','scripts/ci_namespace_diagnostic_v1.py','scripts/ci_test_selection_v1.py','.ci/integration-test-selection.v1.json','.github/workflows/ci.yml','tests/test_run_ci_checks.py','tests/test_ci_namespace_diagnostic_v1.py','tests/test_checkpoint_openvino_gva_qualification_fragment_v3.py']
 command=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','cat-file','--batch']
 original=subprocess.run(command,input=(''.join(COMMIT+':'+p+'\n' for p in sources)).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True)
 assert len(original.stdout)<=2*1024*1024 and not original.stderr
 cursor=0;source_joins=[]
 for path in sources:
  newline=original.stdout.index(b'\n',cursor);header=original.stdout[cursor:newline].split();assert len(header)==3 and header[1]==b'blob'
  size=int(header[2]);raw=original.stdout[newline+1:newline+1+size];cursor=newline+size+2;assert original.stdout[cursor-1:cursor]==b'\n'
  row={'path':path,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'original_git_blob':header[0].decode()}
  assert before[path]=={key:row[key] for key in ['sha256','size_bytes']};source_joins.append(row)
 assert cursor==len(original.stdout)
 old_dir=ROOT/'artifacts/benchmark_recovery_20260930/ci-5bc416-original-host-retention-v1'
 old_failure=doc(old_dir/'cpu-failure-index.v1.json')
 gva_ids=[row['test_id'] for row in old_failure['original_failure_rows'] if 'gva' in row['test_id']]
 assert len(gva_ids)==1 and set(gva_ids)<=set(child['successful_test_ids'])
 with zipfile.ZipFile(old_dir/'36764814739-cpu/original-artifact.zip') as prior:
  old_child=json.loads(prior.read('unittest-child.report.json'))
  skip_ids_equal={row['test_id'] for row in child['skips']}=={row['test_id'] for row in old_child['skips']}
  selected_ids_equal=set(child['selection']['portable_ids'])==set(old_child['selection']['portable_ids'])
 assert skip_ids_equal and selected_ids_equal
 ns=report['namespace_diagnostic'];denial=json.loads(z.read('namespace-diagnostic/kernel-denial.json'))
 query=json.loads(z.read('namespace-diagnostic/kernel-query/capture.json'));capture=json.loads(z.read('namespace-diagnostic/capture.json'))
 assert all(ns[k]==v for k,v in capture.items()) and ns['policy_denial']==denial
 assert set(ns)-set(capture)=={'hardware_acceptance','first_failed_syscall','namespace_succeeded','policy_denial','original_setup_observations'}
 assert ns['original_setup_observations']==[json.loads(line) for line in z.read('namespace-diagnostic/stdout.raw').splitlines()]
 kernel_records=[json.loads(line) for line in z.read('namespace-diagnostic/kernel-query/stdout.raw').splitlines()]
 assert len(kernel_records)==1 and denial['records'][0]['original_journal_record']==kernel_records[0]
 kernel=kernel_records[0];error=ns['first_failed_syscall'];pid=ns['owner']['pid']
 assert pid==3946 and error['original_pid']==error['pid']==pid and error['syscall']=='open' and error['path']=='/proc/self/setgroups' and error['errno']==13
 unshare=[row for row in ns['original_setup_observations'] if row.get('event')=='syscall_completed' and row.get('syscall')=='unshare']
 assert len(unshare)==1 and unshare[0]['flags']==268435456 and unshare[0]['original_pid']==pid
 ready=[row for row in ns['original_setup_observations'] if row.get('event')=='original_ready']
 assert len(ready)==1 and ready[0]['label']=={'path':'/proc/self/attr/current','value':'unconfined'}
 assert ready[0]['executable']==ns['owner']['executable_realpath']
 assert ns['capture_completed'] and not ns['timed_out'] and not ns['capture_exceeded'] and ns['original_group_absent'] and not ns['original_group_members']
 message=kernel['MESSAGE'];assert all(value in message for value in ['apparmor="DENIED"','operation="capable"','profile="unprivileged_userns"','pid='+str(pid)+' ','capname="sys_admin"'])
 assert kernel['_BOOT_ID']==ns['owner']['boot_id'].replace('-','')
 event_wall=int(kernel['__REALTIME_TIMESTAMP'])*1000
 assert ns['started_wall_time_ns']<=event_wall<=ns['terminal_wall_time_ns']
 assert query['returncode']==denial['original_kernel_query']['returncode']==0
 assert denial['query_credential_transition'] is False and denial['query_uid']==ns['owner']['uid']==1001
 assert denial['original_kernel_query']['gate_owner_executable_is_initial_python'] is True and denial['original_kernel_query']['post_exec_executable_observed'] is False
 assert denial['policy_denial_proven'] is False
 raw_copies=[]
 for name in ['namespace-diagnostic/stdout.raw','namespace-diagnostic/kernel-query/stdout.raw','namespace-diagnostic/kernel-denial.json','namespace-diagnostic/capture.json','namespace-diagnostic/kernel-query/capture.json']:
  raw=z.read(name);assert len(raw)<=16384
  destination=OUT/('original-'+name.replace('/','--'))
  with destination.open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
  raw_copies.append({'zip_member':name,'member_crc32':z.getinfo(name).CRC,'copy':ref(destination),'bytes_equal_original_zip_member':True})
 failure_groups=dict(collections.Counter(row['test_id'].split('.')[0] for row in failures))
 result={'schema_version':1,'artifact_kind':'vast_0ad78d_original_cpu_ci_closed_readonly_review_v1','run_id':36773798497,'job_id':110086521669,'source_commit':COMMIT,
 'original_conclusion':'failure','archive':archive_ref,'zip_member_count':len(names),'decoded_zip_bytes':10338880,'all_members_crc_verified':True,
 'provider_jobs':ref(RETAIN/'provider-jobs.final.original.json'),'provider_artifacts':ref(RETAIN/'provider-artifacts.final.original.json'),
 'decoded_original_joblog':ref(RETAIN/'cpu-job-110086521669.decoded.exact.original.log'),
 'failure_index':index,'tracked_source_before_after_equal':True,'tracked_source_path_count':len(before),'original_report_raw_checkout_matches_commit':True,
 'eight_exact_committed_source_blob_joins':source_joins,'source_blob_read_argv':command,'source_blob_bytes_read':len(original.stdout),
 'built_targets':report['built_targets'],'required_three_native_success_ids':required,'all_required_native_successes_present':True,
 'loaded_gstreamer_factories':{key:{'plugin':value['plugin'],'returncode':value['command']['returncode']} for key,value in report['gstreamer_factories'].items()},
 'selection_counts':child['selection']['counts'],'outcomes':{'executed':child['tests_run'],'success':counts['successful_test_ids'],'errors':counts['errors'],'failures':counts['failures'],'existing_audited_skips':counts['skips'],'missing_required_successes':len(child['missing_required_successes'])},
 'full_discovery_selection_ids_unchanged_from_original5bc':selected_ids_equal,'all88_original_skip_ids_unchanged_from5bc':skip_ids_equal,
 'failure_module_counts':failure_groups,'prior_pure_GVA_failure_now_original_success_ids':gva_ids,
 'original_full_elapsed_s':report['elapsed_s'],'original_suite_observer':{'returncode':observed['returncode'],'signal':observed['signal'],'forced_sigkill':observed['forced_sigkill'],'forced_sigterm':observed['forced_sigterm'],'pipe_eof':observed['pipe_eof'],'descendant_quiescence':observed['descendant_quiescence']},
 'original_namespace':{'owner':ns['owner'],'original_label_before_unshare':ready[0]['label'],'successful_CLONE_NEWUSER':unshare[0],'first_failed_syscall':error,
 'kernel_record':kernel,'matching_original_pid_boot_wall_interval':True,'journal_wall_minus_failed_syscall_terminal_ns':event_wall-error['terminal_wall_time_ns'],
 'query_returncode':0,'query_uid':denial['query_uid'],'query_supplementary_groups':denial['query_supplementary_groups'],'query_credential_transition':False,
 'query_initial_owner_python_only':True,'post_exec_executable_observed':False,'collector_policy_denial_proven':False,'original_group_absent':True,'five_raw_original_copy_provenance':raw_copies},
 'interpretation':'This original run repeats same-PID/boot/wall AppArmor capable/sys_admin denial after successful CLONE_NEWUSER and setgroups-open EACCES13. It supports the separately reviewed exact-executable ephemeral CI policy investigation; collectorFalse remains unchanged. The45 individual test tracebacks are retained, and membership is not proof of each failure syscall cause.',
 'differences_from5bc':['One prior pure GVA error is now a genuine original success, with the method unchanged in mandatory portable selection.','Errors reduce25->24 and successes2804->2805; failures21/skips88/selected2938/discovered2947/integration9 and native3 successes stay unchanged.','Namespace denial is a new actual original PID3946/boot41beccfd… record; no old PID3991/journal record is substituted.'],
 'limitations':['Original fullCI exit1, never successful. No attribution of historical139 or blanket per-test namespace-cause assertion.','Source before/after is the original full3663-path report; own exact Git comparisons are explicitly scoped to eight relevant committed blobs, not rehashing all tracked source files.','No workflow/test/policy/source edits, CI retry/cancel, local test/model/native/engine/namespace operation or credential/signedURL disclosure.'],
 'full_ci_successful':False,'hardware_acceptance':False}
print(json.dumps(save('cpu-review.v1.json',result),sort_keys=True))

