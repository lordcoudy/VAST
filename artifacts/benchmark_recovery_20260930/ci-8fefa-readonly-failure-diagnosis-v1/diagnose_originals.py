"""Finite original hosted archive review. No test/project/engine imports or execution."""
import collections, hashlib, json, os, pathlib, re, stat, subprocess, zipfile

ROOT = pathlib.Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = pathlib.Path(__file__).parent
RETAIN = ROOT/'artifacts/benchmark_recovery_20260930/ci-8fefa-original-retention-v1'
PRIOR = ROOT/'artifacts/benchmark_recovery_20260930/ci-6358-readonly-failure-diagnosis-v1'
COMMIT='8fefa4ba0c5b135c66f85a6eb7f4fd1aaebfdc21'
RUN=36751014399

def seal(v):
    return {**v,'sha256':hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:
        f.write((json.dumps(v,sort_keys=True,indent=2)+'\n').encode()); f.flush(); os.fsync(f.fileno())
def descriptor(p):
    raw=p.read_bytes()
    return {'path':p.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def epoch(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
class Archive:
    def __init__(self,p,expected):
        self.p=p; self.fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        self.before=epoch(os.fstat(self.fd)); self.entries={}
        assert stat.S_ISREG(self.before[2]) and self.before[3]==1
        self.verify(); self.descriptor=descriptor(p); assert self.descriptor['sha256']==expected
        self.stream=os.fdopen(self.fd,'rb',closefd=False); self.z=zipfile.ZipFile(self.stream)
    def verify(self):
        assert self.before==epoch(os.fstat(self.fd))==epoch(self.p.lstat())
    def read(self,name,maximum=4*1024*1024):
        info=self.z.getinfo(name); assert info.file_size<=maximum
        raw=self.z.read(info); assert len(raw)==info.file_size
        self.entries[name]={'archive':self.descriptor,'entry':name,'size_bytes':len(raw),
            'sha256':hashlib.sha256(raw).hexdigest(),'crc32':info.CRC,'original_crc_read':True}
        self.verify(); return raw
    def doc(self,name): return json.loads(self.read(name))
    def close(self):
        self.verify(); self.z.close(); self.stream.close(); os.close(self.fd)

metadata=json.loads((RETAIN/'provider-metadata.final.v1.json').read_bytes())
assert metadata['source_commit']==COMMIT and metadata['run_id']==RUN
assert all(r['status']=='completed' for r in metadata['jobs'])
rows={r['name'].split('-')[1]:r for r in metadata['artifacts']}
assert set(rows)=={'cpu','host'} and all(r['workflow_run']['head_sha']==COMMIT for r in rows.values())
cpu=Archive(RETAIN/f'{RUN}-cpu/original-artifact.zip',rows['cpu']['digest'].removeprefix('sha256:'))
host=Archive(RETAIN/f'{RUN}-host/original-artifact.zip',rows['host']['digest'].removeprefix('sha256:'))
old=Archive(ROOT/'artifacts/benchmark_recovery_20260930/ci-6358-original-retention-v1/36743387786-cpu/original-artifact.zip',
    '8d2eef0bcdcf0dbfcf3dad801deb91c9c4c3ab525ebd0453d797f9e29fdcbf8f')
try:
    current=cpu.doc('unittest-child.report.json'); previous=old.doc('unittest-child.report.json')
    runner=cpu.doc('report.json'); prior_runner=old.doc('report.json'); host_report=host.doc('report.json')
    assert runner['commit']==COMMIT
    before=cpu.doc('tracked-source.before.json'); after=cpu.doc('tracked-source.after.json')
    host_before=host.doc('tracked-source.before.json'); host_after=host.doc('tracked-source.after.json')
    assert before==after==host_before==host_after
    prior_index=json.loads((PRIOR/'failure-index.v1.json').read_bytes())
    prior_review=json.loads((PRIOR/'review.v1.json').read_bytes())
    groups={(r['category'],r['test_id']):r['group'] for r in prior_index['rows']}
    failures=[]
    for category in ('errors','failures'):
        for i,r in enumerate(current[category]):
            failures.append({'category':category,'test_id':r['test_id'],'group':groups.get((category,r['test_id']),'new_original_failure'),
                'original_report_pointer':f'/{category}/{i}','original_report':cpu.entries['unittest-child.report.json'],
                'traceback':r['traceback'],'traceback_sha256':hashlib.sha256(r['traceback'].encode()).hexdigest()})
    normalize=lambda s:s.split(' (',1)[0]
    methods=lambda rows:{normalize(r['test_id']) for r in rows}
    old_bad=methods(previous['errors']+previous['failures']); new_bad=methods(current['errors']+current['failures'])
    allowed={(r['test_id'],r['reason']) for r in current['selection']['allowed_portable_skips']}
    unapproved=[r for r in current['skips'] if (r['test_id'],r['reason']) not in allowed]
    native=prior_review['mandatory_native_actual_success_ids']
    observer=cpu.doc('external-test-observer/terminal.v1.json')
    events=[json.loads(r) for r in cpu.read('external-test-observer/events.original.jsonl').splitlines()]
    responses=[json.loads(r) for r in cpu.read('external-test-observer/responses.original.jsonl').splitlines()]
    cpu.doc('external-test-observer/launch.v1.json'); cpu.read('external-test-observer/trace.original.log')
    namespace=cpu.doc('namespace-diagnostic/capture.json'); denial=cpu.doc('namespace-diagnostic/kernel-denial.json')
    setup=[json.loads(r) for r in cpu.read('namespace-diagnostic/stdout.raw').splitlines()]
    cpu.read('namespace-diagnostic/stderr.raw')
    query=cpu.doc('namespace-diagnostic/kernel-query/capture.json')
    query_stdout=cpu.read('namespace-diagnostic/kernel-query/stdout.raw')
    query_stderr=cpu.read('namespace-diagnostic/kernel-query/stderr.raw')
    actual_failed=[r for r in setup if r.get('event')=='syscall_failed' and not r.get('stock_tolerated_missing_setgroups')]
    failed=actual_failed[0] if actual_failed else None
    ready=[r for r in setup if r.get('event')=='original_ready']
    labels=[r.get('label') for r in ready]
    parsed=[]
    for line in query_stdout.splitlines():
        try: record=json.loads(line)
        except (ValueError,UnicodeError):
            parsed.append({'complete_json':False,'raw_line_sha256':hashlib.sha256(line).hexdigest()}); continue
        message=record.get('MESSAGE','')
        facts={m.group(1):(m.group(2) if m.group(2) is not None else m.group(3))
            for m in re.finditer(r'(\w+)=(?:"([^"]*)"|([^\s]+))',message)} if isinstance(message,str) else {}
        timestamp=record.get('__REALTIME_TIMESTAMP')
        realtime_ns=int(timestamp)*1000 if isinstance(timestamp,str) and timestamp.isdecimal() else None
        expected_pid=(namespace.get('owner') or {}).get('pid')
        operation=facts.get('operation')
        candidate=facts.get('apparmor')=='DENIED' and facts.get('pid')==str(expected_pid) and (
            operation in ('userns_create','unshare') or operation=='capable' and facts.get('capname')=='sys_admin')
        in_syscall=bool(failed and realtime_ns is not None and failed['wall_time_ns']<=realtime_ns<=failed['terminal_wall_time_ns'])
        path_equal=bool(failed and failed.get('path') and facts.get('name')==failed['path'])
        parsed.append({'original_journal_record':record,'parsed_message_fields':facts,'realtime_ns':realtime_ns,
            'exact_original_pid_userns_or_sys_admin_denial_candidate':candidate,
            'timestamp_inside_actual_first_failed_syscall_interval':in_syscall,
            'denial_name_matches_actual_first_failed_syscall_path':path_equal,
            'matches_observed_pre_setup_label':any(isinstance(l,dict) and l.get('value')==facts.get('profile') for l in labels),
            'label_at_actual_failed_syscall_observed':False})
    paths=('scripts/run_ci_checks.py','scripts/ci_namespace_diagnostic_v1.py','scripts/ci_test_selection_v1.py',
           '.ci/integration-test-selection.v1.json','scripts/backend_publication_process_supervisor_v3.py')
    result=subprocess.run(['/usr/bin/git','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
        '--work-tree='+str(ROOT),'cat-file','--batch'],input=('\n'.join(COMMIT+':'+p for p in paths)+'\n').encode(),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=True)
    assert not result.stderr and len(result.stdout)<2*1024*1024
    offset=0; sources=[]; anchors=[]
    for p in paths:
        end=result.stdout.index(b'\n',offset); header=result.stdout[offset:end].split(); assert header[1]==b'blob'
        size=int(header[2]); raw=result.stdout[end+1:end+1+size]; assert result.stdout[end+1+size:end+2+size]==b'\n'
        offset=end+2+size; facts={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}; assert before[p]==facts
        target=OUT/'committed-source'/p; target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        sources.append({'original_commit':COMMIT,'path':p,**facts,'snapshot':descriptor(target)})
        if p.endswith('ci_namespace_diagnostic_v1.py'):
            anchors=[{'line':i,'text':s.strip()} for i,s in enumerate(raw.decode().splitlines(),1)
                if any(t in s for t in ('journalctl','--kernel','--grep=','_gated_execv_argv','post_exec_executable','query_credential_transition','sys_admin'))]
    assert offset==len(result.stdout)
    cpu.doc('native-configure.json'); cpu.doc('native-build.json'); cpu.read('unittest.original.log')
    acquisitions={'cpu':cpu.doc('model-acquisition/report.json'),'host':host.doc('model-acquisition/report.json')}
    index={'schema_version':1,'kind':'vast_ci8f_original_finite_failure_index_v1','accepted':False,'run_id':RUN,'source_commit':COMMIT,
        'rows':failures,'original_skips':current['skips'],'original_allowed_portable_skips':current['selection']['allowed_portable_skips'],
        'exact_unapproved_skips':unapproved,'declared_unexecuted_integrations':current['selection']['integration_declarations']}
    save(OUT/'failure-index.v1.json',seal(index))
    counts={'discovered':len(current['discovered_ids']),'portable':current['selection']['counts']['portable'],
        'unexecuted_integrations':current['selection']['counts']['integration'],'tests_run':current['tests_run'],
        'successful_method_ids':len(current['successful_test_ids']),'error_rows':len(current['errors']),
        'distinct_error_methods':len(methods(current['errors'])),'failure_rows':len(current['failures']),
        'skip_rows':len(current['skips']),'allowed_skip_declarations':len(allowed),'unapproved_skips':len(unapproved),
        'failure_groups':dict(collections.Counter(r['group'] for r in failures))}
    assert len(current['successful_test_ids'])+len(new_bad)+len(current['skips'])==current['tests_run']
    review={'schema_version':1,'kind':'vast_ci8f_readonly_original_diagnosis_v1','accepted':False,'run_id':RUN,'source_commit':COMMIT,
        'provider_metadata':descriptor(RETAIN/'provider-metadata.final.v1.json'),
        'original_decoded_logs':[descriptor(RETAIN/(k+'-decoded-job.log')) for k in ('cpu','host')],
        'archives':{k:a.descriptor for k,a in (('cpu',cpu),('host',host),('prior_cpu',old))},
        'original_entries':{'cpu':cpu.entries,'host':host.entries},'original_source_before_after_equal':True,
        'original_tracked_source_count':len(before),'committed_source_evidence':sources,'diagnostic_source_anchors':anchors,
        'counts':counts,'original_runner':runner,'original_host_report':host_report,'original_child_failure':current['child_failure'],
        'missing_required_successes':current['missing_required_successes'],
        'mandatory_native_success_ids':native,'native_three_original_successes_present':set(native)<=set(current['successful_test_ids']),
        'comparison':{'new_discovered_ids':sorted(set(current['discovered_ids'])-set(previous['discovered_ids'])),
            'removed_discovered_ids':sorted(set(previous['discovered_ids'])-set(current['discovered_ids'])),
            'new_bad_method_ids':sorted(new_bad-old_bad),'prior_bad_now_successful_ids':sorted((old_bad-new_bad)&set(current['successful_test_ids'])),
            'skip_id_reason_pairs_identical':current['skips']==previous['skips'],
            'integration_declarations_identical':current['selection']['integration_declarations']==previous['selection']['integration_declarations'],
            'prior_elapsed_s':prior_runner['elapsed_s'],'actual_elapsed_s':runner['elapsed_s'],'no_elapsed_cause_claim':True},
        'namespace_original':namespace,'policy_denial_original':denial,'kernel_query_original':query,
        'kernel_query_original_stdout_size':len(query_stdout),'kernel_query_original_stderr_size':len(query_stderr),
        'kernel_query_original_stderr_utf8':query_stderr.decode('utf8'),
        'setup_original_events':setup,'first_failed_syscall_derived_from_original_events':failed,
        'original_journal_records_and_joins':parsed,
        'matching_original_failed_syscall_policy_denial_proven':False,
        'profile_authorization':None,
        'causality_limits':['The owner/executable observation at the gate is the initial Python process. Intended later exec argv is not a post-exec observation.',
            'Namespace initial_ready label is a pre-setup observation; it does not establish the label at the later failed syscall.',
            'Original errno and candidate PID/time/operation records are retained separately. Absent or unmatched denial supplies no profile authorization.',
            'Independent namespace diagnostic errno is not proof of every failing broker test cause; original per-test journals are not synthesized.',
            'No benchmark timing, hardware acceptance, earlier139 cause or pending fixture/selection repair is inferred.'],
        'original_external_observer':observer,'observer_original_counts':{'events':dict(collections.Counter(r['event'] for r in events)),
            'responses':len(responses),'no_post_exec_or_descendant_quiescence_claim':True},
        'model_acquisitions':acquisitions,'failure_index':descriptor(OUT/'failure-index.v1.json'),'prior_review':descriptor(PRIOR/'review.v1.json'),
        'scope':{'tests_or_project_imports_executed':False,'source_index_head_mutated':False,'engine_kernel_namespace_model_query':False,
            'workflow_retry_or_cancel':None,'full_ci_success_claim':False}}
    save(OUT/'review.v1.json',seal(review))
    print(json.dumps({'review':descriptor(OUT/'review.v1.json'),'failure_index':descriptor(OUT/'failure-index.v1.json'),'counts':counts}))
finally:
    cpu.close(); host.close(); old.close()
