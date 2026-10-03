"""Finite original run34 evidence reader. No workflow/test/model/engine operation."""
from pathlib import Path
import ast,collections,hashlib,io,json,os,re,stat,sys,time,traceback,zipfile
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930/ci-9d47-original-host-retention-v1'
RAW_CONTROL=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/tests/test_benchmark_contract.py')
RAW_CONTROL_HEAD=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/.git/HEAD')
HERE=Path(__file__).parent;OUT=HERE/'attempt02'
COMMIT='9d47e99b623df44816f7b0a0b73b249a940f7723';RUN=36802923013
START=time.monotonic();END=START+120;held={};dirs={};owned=False;failure=None;report={};baseline=len(list(Path('/proc/self/fd').iterdir()))
def clock():
 if time.monotonic()>=END:raise TimeoutError('original metadata review120s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(p,expected=None):
 clock();p=Path(p);assert p.is_absolute() and (ROOT in p.parents or p in (RAW_CONTROL,RAW_CONTROL_HEAD)) and p.resolve(strict=True)==p
 for parent in reversed(p.parents):
  if parent not in dirs:
   fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
   try:s=os.fstat(fd);assert stat.S_ISDIR(s.st_mode) and (s.st_dev,s.st_ino,s.st_mode)==(parent.lstat().st_dev,parent.lstat().st_ino,parent.lstat().st_mode);dirs[parent]=(fd,[s.st_dev,s.st_ino,s.st_mode])
   except BaseException:os.close(fd);raise
  fd,ident=dirs[parent];s=os.fstat(fd);assert [s.st_dev,s.st_ino,s.st_mode]==ident==[parent.lstat().st_dev,parent.lstat().st_ino,parent.lstat().st_mode]
 if p not in held:
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
  try:
   st=os.fstat(fd);assert stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_size<=8*1024*1024
   pieces=[];h=hashlib.sha256()
   while b:=os.read(fd,65536):clock();pieces.append(b);h.update(b)
   raw=b''.join(pieces);assert len(raw)==st.st_size and epoch(st)==epoch(os.fstat(fd))==epoch(p.lstat())
   held[p]={'fd':fd,'epoch':epoch(st),'raw':raw,'descriptor':{'path':str(p),'size_bytes':len(raw),'sha256':h.hexdigest()}}
  except BaseException:os.close(fd);raise
 row=held[p]
 if expected is not None:
  if row['descriptor']['sha256']!=expected['sha256'] or row['descriptor']['size_bytes']!=expected['size_bytes']:
   raise AssertionError(json.dumps({'pin_requested_path':str(p),'expected':expected,'observed':row['descriptor'],'original_stat_epoch':row['epoch']},sort_keys=True))
 return row

def doc(p,expected=None):return json.loads(pin(p,expected)['raw'])
def save(name,value):
 assert owned;raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=8*1024*1024
 with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
try:
 OUT.mkdir();owned=True
 me=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split();launch={'argv':sys.argv,'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),'startticks':int(me[19]),'uid':os.getuid(),'gid':os.getgid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'source':pin(Path(__file__))['descriptor'],'mode':'closed retained original metadata only'};save('launch.v1.json',launch)
 retained=doc(BASE/'original-retention-terminal.v1.json');provider=doc(BASE/'original-provider-metadata.v1.json',retained['metadata'])
 assert retained['status']=='originals_retained' and retained['run_id']==RUN and retained['source_commit']==COMMIT and retained['workflow_action'] is None
 assert provider['run']['id']==RUN and provider['run']['head_sha']==COMMIT and provider['run']['status']=='completed' and provider['run']['conclusion']=='success'
 jobs={r['id']:r for r in provider['jobs']['jobs']};assert set(jobs)=={110181019042,110181019292}
 assert all(j['head_sha']==COMMIT and j['run_id']==RUN and j['status']=='completed' and j['conclusion']=='success' for j in jobs.values())
 raw={};members={};zips={};artifact_rows={};artifacts={r['id']:r for r in provider['artifacts']['artifacts']}
 for row in retained['originals']:
  clock();q=ROOT/row['path'];pinned=pin(q,row)
  if row['kind']=='original_job_log':assert row['job_id'] in jobs;continue
  assert row['kind']=='original_artifact';kind='cpu' if 'cpu-checks' in row['artifact_name'] else 'host';assert kind not in zips
  api=artifacts[row['artifact_id']];assert api['digest']=='sha256:'+row['sha256'] and api['size_in_bytes']==row['size_bytes'] and api['workflow_run']['head_sha']==COMMIT and api['workflow_run']['id']==RUN
  assert (row['member_count'],row['size_bytes'],row['sha256'])==((197,2044415,'950e7a614922909194ba9d67089df053acc51a7a33d94b2783e6e1078949a973') if kind=='cpu' else (51,430689,'efc8a7ecb0a17c6fab6c93f187df3eddee3a4720dd864c0a65f92ecda13e252a'))
  refs={x['name']:x for x in row['members']};assert len(refs)==row['member_count']
  with zipfile.ZipFile(io.BytesIO(pinned['raw'])) as z:
   names=[i.filename for i in z.infolist()];assert len(names)==len(set(names))==len(refs) and set(names)==set(refs)
   assert sum(i.file_size for i in z.infolist())==row['decoded_size_bytes']<=16*1024*1024
   for item in z.infolist():
    clock();assert not Path(item.filename).is_absolute() and '..' not in Path(item.filename).parts and not item.is_dir() and item.file_size<=8*1024*1024
    with z.open(item) as f:
     b=f.read(item.file_size+1);assert len(b)==item.file_size
    ref=refs[item.filename];assert len(b)==ref['size_bytes'] and hashlib.sha256(b).hexdigest()==ref['sha256'] and item.CRC==ref['crc32']
    members[(kind,item.filename)]={'archive':pinned['descriptor'],'member':ref}
    if not item.filename.startswith('build/'):raw[(kind,item.filename)]=b
  zips[kind]=pinned['descriptor'];artifact_rows[kind]=row
 def original(name,kind='cpu'):return json.loads(raw[(kind,name)])
 report=original('report.json');unit=original('unittest-child.report.json');selection=unit['selection'];host=original('report.json','host')
 assert report['commit']==COMMIT and report['successful'] and report['raw_checkout_bytes_match_commit'] and report['changed_tracked_paths']==[] and report['unittest']==unit
 assert report['python'].startswith('3.12.3 ') and unit['successful'] and not any(unit[k] for k in ('errors','failures','expected_failures','unexpected_successes','missing_required_successes'))
 discovered=set(unit['discovered_ids']);portable=set(selection['portable_ids']);success=set(unit['successful_test_ids']);skips={x['test_id']:x['reason'] for x in unit['skips']};allowed={x['test_id']:x['reason'] for x in selection['allowed_portable_skips']};deferred={x['test_id'] for x in selection['integration_declarations']}
 assert len(discovered)==2972 and len(portable)==unit['tests_run']==2963 and len(success)==2875 and len(skips)==88 and len(deferred)==9
 assert success.isdisjoint(skips) and success|set(skips)==portable and portable.isdisjoint(deferred) and portable|deferred==discovered and skips==allowed
 assert all(x['acceptance_claim'] is False for x in unit['portable_skip_audit']) and unit['portable_skip_audit']==selection['allowed_portable_skips']
 before=original('tracked-source.before.json');assert before==original('tracked-source.after.json')==original('tracked-source.before.json','host')==original('tracked-source.after.json','host') and len(before)==5039
 recovery=ROOT/'artifacts/benchmark_recovery_20260930/component-supervisor-renewal-recovery-preparation-v1/original-checkout-recovery-attempt01'
 execution=doc(recovery/'execution.v1.json',{'size_bytes':13862,'sha256':'7952a8243c0275d193f976736000f922ab7587439638db33eb4667cfdd0ac087'})
 tracked=doc(recovery/'tracked-after.v1.json',{'size_bytes':2787538,'sha256':'03c8101aec854cb927e0aad5af1ea4bb55697b0c8ca0d13558948b0b2b4430ec'})
 recovery_peer=doc(ROOT/'artifacts/benchmark_recovery_20260930/component-supervisor-renewal-recovery-actual-independent-review-v1/review.v1.json',{'size_bytes':10446,'sha256':'af9100991c6b79102fb47dc2ed41e8515e3b1d901537bb9b4b0533fa3369d723'})
 assert recovery_peer['source_commit']==COMMIT and recovery_peer['status']=='closed_actual_recovery_and_fresh_stock_source_readiness_peer_pass' and recovery_peer['blockers']==[] and recovery_peer['all_reviewer_read_handles_released']
 assert execution['source_commit']==COMMIT and execution['all_fds_retired'] and execution['facts']['raw_byte_Git_blob_mode_equality'] and execution['facts']['raw_tracked_new_count']==5039 and execution['first_error'] is None
 assert set(tracked)==set(before) and all(before[k]=={'size_bytes':v['size_bytes'],'sha256':v['sha256']} and v['path']==k and len(v['git_blob_sha1'])==40 for k,v in tracked.items())
 controls={'.github/workflows/ci.yml','.ci/integration-test-selection.v1.json','scripts/run_ci_checks.py','scripts/ci_test_selection_v1.py','scripts/ci_namespace_diagnostic_v1.py','scripts/ci_userns_profile_v1.py','scripts/ci_external_test_observer_v1.py','tests/test_checkpoint_analytics_execution_client_cpp.py'}
 for row in selection['allowed_portable_skips']:controls.add('tests/'+row['test_id'].split('.')[0]+'.py')
 for row in selection['integration_declarations']:controls.add(row['source']['path'])
 original_control_root_head=pin(RAW_CONTROL_HEAD,{'size_bytes':41,'sha256':hashlib.sha256((COMMIT+'\n').encode()).hexdigest()});assert original_control_root_head['raw']==(COMMIT+'\n').encode()
 source_rows=[];asts={}
 for name in sorted(controls):
  assert name in before;row=pin(RAW_CONTROL if name=='tests/test_benchmark_contract.py' else ROOT/name,before[name]);blob=hashlib.sha1(b'blob '+str(len(row['raw'])).encode()+b'\0'+row['raw']).hexdigest();assert blob==tracked[name]['git_blob_sha1'];source_rows.append({'role':name,'descriptor':row['descriptor'],'epoch':row['epoch'],'raw_Git_blob_sha1':blob,'physical_root_provenance':'genuine original9d47 ext4 raw control leaf' if name=='tests/test_benchmark_contract.py' else 'Windows raw control leaf exactly matches original5039 source table'})
  if name.endswith('.py'):asts[name]=ast.parse(row['raw'])
 manifest=json.loads(held[ROOT/'.ci/integration-test-selection.v1.json']['raw']);assert hashlib.sha256(held[ROOT/'.ci/integration-test-selection.v1.json']['raw']).hexdigest()==selection['manifest_sha256']
 assert manifest['allowed_portable_skips']==selection['allowed_portable_skips'] and manifest['integration_declarations']==selection['integration_declarations']
 anchors=[]
 for row in selection['allowed_portable_skips']:
  module,cls,method=row['test_id'].split('.');tree=asts['tests/'+module+'.py'];classes=[n for n in ast.walk(tree) if isinstance(n,ast.ClassDef) and n.name==cls];assert classes
  assert any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==method for n in ast.walk(tree))
  literals={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)};assert row['reason'] in literals
  anchors.append({'test_id':row['test_id'],'reason':row['reason'],'classification':row['classification'],'source':'tests/'+module+'.py','source_literal_and_method_attested':True,'acceptance_claim':False})
 native_ids=['test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.'+n for n in ('test_native_client_regression','test_native_policy_topology_regression','test_native_reset_queue_level_regression')]
 assert set(native_ids)<=success and original('native-configure.json')['returncode']==original('native-build.json')['returncode']==0
 assert report['built_targets']==['vast_native_gst_probe','vast_checkpoint_source','gstadaptivescheduler','gstvastanalyticsterminal','gstvastanalyticsqueue','gstvastcheckpointprefixqueue']
 assert set(report['gstreamer_factories'])=={'appsrc','queue','videoconvert'}
 observer=original('external-test-observer/terminal.v1.json');launch=original('external-test-observer/launch.v1.json')
 assert observer['owner']==launch['owner'] and observer['argv']==launch['argv'] and observer['returncode']==0 and observer['successful'] and observer['failure'] is None
 assert observer['pipe_eof']=={'control':True,'trace':True} and not observer['forced_sigkill'] and not observer['forced_sigterm'] and not observer['pidfd_acquisition_failed'] and observer['requests_stopped_before_disposition_restore']
 assert launch['interval_s']==60 and launch['pidfd_opened'] and observer['started_monotonic_ns']<=observer['finished_monotonic_ns']<observer['absolute_deadline_ns']==report['absolute_deadline_ns']-30*10**9
 assert report['absolute_deadline_ns']-report['job_started_monotonic_ns']==5400*10**9
 events=[json.loads(x) for x in raw[('cpu','external-test-observer/events.original.jsonl')].splitlines()];responses=[json.loads(x) for x in raw[('cpu','external-test-observer/responses.original.jsonl')].splitlines()]
 ready=next(x for x in responses if x['event']=='ready');assert ready['native_task_count']==1 and ready['handler']=='python_main_thread_safe_gil' and ready['pid']==observer['owner']['pid']
 ec=collections.Counter(x['event'] for x in events);rc=collections.Counter(x['event'] for x in responses)
 assert ec['request_sent']==observer['requests_sent']==23 and rc['response_started']==observer['responses_started']==23 and rc['response_finished']==observer['responses_completed']==23
 assert observer['trace_bytes']==len(raw[('cpu','external-test-observer/trace.original.log')])<=1048576 and observer['response_channel_bytes']==len(raw[('cpu','external-test-observer/responses.original.jsonl')])<=1048576
 requests=[x for x in events if x['event']=='request_sent'];starts=[x for x in responses if x['event']=='response_started'];ends=[x for x in responses if x['event']=='response_finished']
 request_lateness=[r['sent_monotonic_ns']-r['scheduled_monotonic_ns'] for r in requests];response_elapsed=[b['child_monotonic_ns']-a['child_monotonic_ns'] for a,b in zip(starts,ends)]
 assert all(n>=0 for n in request_lateness+response_elapsed)
 capture=original('namespace-diagnostic/capture.json');joined=original('namespace-profile/joined-denial.json');kernel=original('namespace-diagnostic/kernel-denial.json');profile=original('namespace-profile/profile-lifecycle.json');intent=original('namespace-profile/load-intent.json');ns=[json.loads(x) for x in raw[('cpu','namespace-diagnostic/stdout.raw')].splitlines()]
 assert capture['capture_completed'] and capture['original_group_absent'] and not capture['capture_exceeded'] and not capture['timed_out'] and capture['eof']=={'stderr':True,'stdout':True} and capture['failure'] is None
 assert capture['owner']['pid']==joined['join']['pid'] and capture['owner']['boot_id']==joined['join']['boot_id']==observer['owner']['boot_id']
 assert capture['owner']['executable_realpath']==joined['join']['python']==observer['owner']['executable_realpath'] and capture['owner']['executable_stat']==observer['owner']['executable_stat']
 failed=next(x for x in ns if x['event']=='syscall_failed');assert failed['syscall']=='open' and failed['path']=='/proc/self/setgroups' and failed['errno']==13 and failed['pid']==capture['owner']['pid']
 assert any(x['event']=='syscall_completed' and x['syscall']=='unshare' and x['pid']==capture['owner']['pid'] for x in ns)
 records=kernel['records'];assert len(records)==1;record=records[0]['original_journal_record'];message=record['MESSAGE'];pid=joined['join']['pid']
 assert record['_BOOT_ID']==joined['join']['boot_id'].replace('-','') and ('pid='+str(pid)+' ') in message and 'apparmor="DENIED"' in message and 'profile="unprivileged_userns"' in message and 'operation="capable"' in message and 'capname="sys_admin"' in message
 assert joined['join']['denied_capability']=='sys_admin' and joined['join']['denied_profile']=='unprivileged_userns' and joined['join']['wall_clock_quantization_allowance_ns']==2000000
 assert abs(joined['join']['audit_wall_time_ns']-failed['wall_time_ns'])<=joined['join']['wall_clock_quantization_allowance_ns'] and int(record['__REALTIME_TIMESTAMP'])*1000>=joined['join']['audit_wall_time_ns']-2000000
 for ref in joined['inputs']:
  if ref['path']==joined['join']['python']:assert ref['size_bytes']==capture['owner']['executable_stat']['st_size'] and re.fullmatch('[0-9a-f]{64}',ref['sha256']) and report['canonical_python']==ref['path'];continue
  relative=ref['path'].split('/vast-cpu-checks/',1)[1];b=raw[('cpu',relative)];assert len(b)==ref['size_bytes'] and hashlib.sha256(b).hexdigest()==ref['sha256']
 assert profile['held_fds_released'] and profile['load_verified'] and profile['unload_verified'] and profile['status']=='completed' and intent['unique_name_absent_before_original_add']
 assert intent['profile']==profile['profile'] and intent['argv'][8]=='--add' and '--replace' not in intent['argv']
 profile_raw=raw[('cpu','namespace-profile/owned.profile')];assert hashlib.sha256(profile_raw).hexdigest()==profile['profile']['sha256'] and len(profile_raw)==profile['profile']['size_bytes']
 name=profile['name'];assert re.fullmatch('vast-ci-userns-[0-9a-f]{32}',name)
 expected_profile=('abi <abi/4.0>,\nprofile '+name+' '+joined['join']['python']+' flags=(unconfined) {\n  userns,\n}\n').encode('ascii')
 assert profile_raw==expected_profile
 assert name not in raw[('cpu','namespace-profile/load-before/stdout.raw')].decode() and (name+' (unconfined)') in raw[('cpu','namespace-profile/load-after/stdout.raw')].decode() and name not in raw[('cpu','namespace-profile/unload-after/stdout.raw')].decode()
 assert unit['profile_observation']['actual_label']['value']==unit['profile_observation']['expected_profile']==name+' (unconfined)' and unit['profile_observation']['pid']==observer['owner']['pid'] and unit['profile_observation']['boot_id']==observer['owner']['boot_id']
 captures=[]
 for phase in ('load-before','load','load-after','unload','unload-after'):
  c=original('namespace-profile/'+phase+'/capture.json');assert c['capture_completed'] and c['returncode']==0 and not c['timed_out'] and not c['capture_exceeded'] and c['failure'] is None and c['original_group_absent'] and c['eof']=={'stderr':True,'stdout':True} and not c.get('signal_failures')
  assert c['minimum_start_budget_ns']==(21000000000 if phase in ('load','unload') else 3000000000);captures.append({'phase':phase,'terminal':members[('cpu','namespace-profile/'+phase+'/capture.json')]})
 assert host['commit']==COMMIT and host['diagnostic_passed'] and len(host['test_ids'])==2 and host['original_process']['returncode']==0 and host['full_ci_successful'] is False
 for p,row in held.items():
  clock();assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat());os.lseek(row['fd'],0,os.SEEK_SET);h=hashlib.sha256()
  while b:=os.read(row['fd'],65536):clock();h.update(b)
  assert h.hexdigest()==row['descriptor']['sha256'] and epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())
 for parent,(fd,identity) in dirs.items():
  clock();a=os.fstat(fd);b=parent.lstat();assert stat.S_ISDIR(a.st_mode) and stat.S_ISDIR(b.st_mode) and [a.st_dev,a.st_ino,a.st_mode]==identity==[b.st_dev,b.st_ino,b.st_mode]
 report={'schema_version':1,'status':'closed_original_hosted_full_portable_CI_evidence_success','source_commit':COMMIT,'original_run_id':RUN,'original_run_number':provider['run']['run_number'],'provider_jobs':[{k:j[k] for k in ('id','name','head_sha','started_at','completed_at','conclusion')} for j in jobs.values()],'artifacts':zips,'provider_members_SHA_CRC_verified':248,'original_logs_verified':2,'source_integrity':{'cpu_host_before_after_full5039_identical':True,'source_bytes':sum(r['size_bytes'] for r in before.values()),'all5039_fullSHA_size_match_actual_closed_samecommit_rawGit_proof':True,'original_raw_checkout_guard_passed':True,'closed_original_fullbyte_provenance':{'execution':pin(recovery/'execution.v1.json')['descriptor'],'tracked_after':pin(recovery/'tracked-after.v1.json')['descriptor'],'actual_peer':pin(ROOT/'artifacts/benchmark_recovery_20260930/component-supervisor-renewal-recovery-actual-independent-review-v1/review.v1.json')['descriptor']},'independent_control_anchor_sources':source_rows,'one_original_control_anchor_proper_root':{'logical_path':'tests/test_benchmark_contract.py','physical_path':str(RAW_CONTROL),'current_actual_HEAD':original_control_root_head['descriptor'],'all37_other_Windows_raw_anchors_unchanged':True,'no_physical_byte_normalization':True},'full234MB_payload_not_replayed':True},'portable_selection':{'discovered':2972,'portable_executed':2963,'successes':2875,'skips_nonexecution':88,'integration_deferred_nonexecution':9,'failures':0,'errors':0,'unexpected_successes':0,'expected_failures':0,'missing_required_successes':0,'skip_source_anchors':anchors,'integration_declarations':selection['integration_declarations'],'manifest_sha256':selection['manifest_sha256'],'all_required_native_successes':native_ids,'six_build_targets':report['built_targets']},'observer':{'original_owner':observer['owner'],'native_tasks_at_ready':1,'requests_sent':23,'responses_started':23,'responses_completed':23,'raw_trace_bytes':observer['trace_bytes'],'request_lateness_ns':request_lateness,'observed_response_elapsed_ns':response_elapsed,'pipe_eof':observer['pipe_eof'],'original_returncode':0,'forced_signals_absent':True,'job_budget_s':5400,'suite_cleanup_reservation_s':30,'descendant_quiescence':observer['descendant_quiescence'],'ordinary_signal_matching_limit':observer['response_matching']},'fresh_conditional_profile':{'namespace_owner':capture['owner'],'joined_denial':joined['join'],'suite_subject':unit['profile_observation'],'profile':profile['profile'],'name':name,'owned_add_then_actual_kernel_present_then_subject_label_then_owned_remove_then_kernel_absent':True,'profile_FDs_released':True,'captures':captures,'collector_generic_policy_denial_proven':kernel['policy_denial_proven'],'kernel_query_post_exec_executable_observed':kernel['original_kernel_query']['post_exec_executable_observed'],'strict_scoped_join_separate_from_generic_flags':True},'independent_host_diagnostics':{'report':members[('host','report.json')],'test_ids':host['test_ids'],'original_process':host['original_process'],'does_not_equal_full_CI':True},'specification_inventory_scope':original('specification-inventory.json')['behavior_conformance'],'scope_limits':['This joins genuine run34 at exact9d47. No new CI/job/test/profile/namespace/model/engine/hardware run or global hosted /proc replay.','88 skips and9 deferred integrations are nonexecution, not success or hardware acceptance.','All5039 original raw-source SHA/size values join the physically sealed samecommit recovery table; this reader does not reread234MB original tracked blobs or model payloads.','Observer exact original child status/EOF does not prove global descendant quiescence; original limitation retained.','Generic collector policy_denial_proven and postexec executable flags remain exactly originalfalse; strict fresh profile evidence is a separate scope.','Portable/native controls do not establish NVIDIA/model/SDK/Q4/full qualification/scientific/archive acceptance.'],'hardware_acceptance':False,'all_input_rows':[{'descriptor':r['descriptor'],'epoch':r['epoch']} for r in held.values()]}
except BaseException as exc:
 failure={'type':type(exc).__name__,'message':str(exc)[:4096],'traceback':traceback.format_exc()[-16000:]};report={'schema_version':1,'status':'failed_no_CI_evidence_acceptance','source_commit':COMMIT,'original_run_id':RUN,'failure':failure,'hardware_acceptance':False}
finally:
 close_errors=[]
 for row in held.values():
  try:os.close(row['fd'])
  except OSError as exc:close_errors.append({'type':type(exc).__name__,'errno':exc.errno})
 for fd,_ in dirs.values():
  try:os.close(fd)
  except OSError as exc:close_errors.append({'type':type(exc).__name__,'errno':exc.errno})
 report['all_review_FDs_released']=not close_errors;report['close_errors']=close_errors;report['fd_count_before']=baseline;report['fd_count_after']=len(list(Path('/proc/self/fd').iterdir()));report['elapsed_after_close_s']=time.monotonic()-START
 if close_errors or report['fd_count_after']!=baseline or time.monotonic()>=END:report['status']='failed_no_CI_evidence_acceptance';failure=failure or {'type':'DeadlineOrFdError','message':'120s or closedFD predicate failed'};report['failure']=failure
 if owned:reference=save('review.v1.json',report);print(json.dumps({'review':reference,'status':report['status'],'all_review_FDs_released':report['all_review_FDs_released']}),flush=True)
late=time.monotonic()>=END
if late and owned:save('late-failure.v1.json',{'status':'failed_no_CI_evidence_acceptance','elapsed_s':time.monotonic()-START,'closed_report':reference,'original_failure':failure})
sys.exit(0 if failure is None and not late else 1)
