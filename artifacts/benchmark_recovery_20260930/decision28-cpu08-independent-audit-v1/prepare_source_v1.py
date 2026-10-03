"""Source-only author transformation; does not import or execute the auditor."""
import ast, difflib, hashlib, json
from pathlib import Path

OUT = Path(__file__).parent
BASE = OUT.parent / 'component-cpu06-ext4-postterminal-audit-preparation-v1/audit_v2.py'
original = BASE.read_bytes()
assert len(original) == 17876 and hashlib.sha256(original).hexdigest() == 'e8e7e72280d2971d677763f512b0bede8710550c7a9518b6f19e779ad12e1d98'
text = original.decode('utf-8')
changes = []
def replace(before, after, count=1):
    global text
    assert text.count(before) == count, (before, text.count(before), count)
    text = text.replace(before, after)
    changes.append({'before': before, 'after': after, 'count': count})

replace('CPU06', 'CPU08', 1)
replace('cpu-pair-06', 'cpu-pair-08', 2)
replace('0ad78d6abdb3c526544a17185af7fe8094716735', 'a00aa57f7d9534f8e7920f14f70d6a75a23570ed')
replace('adbcb638a5f104e43c95b84e4d16388a8111d39321afb3e8e7a26f2ef537b498', '3c91339d43f6154dd76afe8a89c02d82f60a4b1e5da16623039f691fdc6701f2')
replace('execution-code-closure.ext4.v1.json', 'execution-code-closure.ext4-decision28.v4.json')
replace('run_original_cpu_component_pair_ext4_v1.py', 'run_original_cpu_component_pair_ext4_decision28_v4.py')
replace('49b6659ce3b6c595be21bf5ffefa721738a23094cc1a66642a9f5bab8666f559', '445535a2ea9176effbe97e5de1db53aae614645e40db65bc1debf74489371f36')
replace("==15089", "==23631")
replace('vast_cpu06_ext4', 'vast_cpu08_ext4', 3)
replace("import hashlib,json,os,stat,subprocess,sys,time", "import hashlib,json,os,stat,sys,time")
replace("START=time.monotonic();END=START+120;held={};report={};failure=None", "START=time.monotonic();END=START+120;held={};report={};failure=None\nFD_BEFORE=len(os.listdir('/proc/self/fd'))")
hold_start = text.index('def hold(')
hold_end = text.index('def doc(', hold_start)
old_hold = text[hold_start:hold_end]
new_hold = '''def hold(path,expected=None,original_epoch=None,decode=False):
    clock();path=Path(path);path=path if path.is_absolute() else ROOT/path
    assert path.resolve(strict=True)==path
    if path not in held:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        held[path]={'fd':fd,'epoch':None,'descriptor':None,'raw':None}
        s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=64*1024*1024
        if decode:assert s.st_size<=1048576
        digest=hashlib.sha256();raw=[];size=0
        while block:=os.read(fd,1048576):
            clock();digest.update(block);size+=len(block)
            if decode:raw.append(block)
        assert size==s.st_size and epoch(s)==epoch(path.lstat())==epoch(os.fstat(fd))
        d={'path':str(path),'size_bytes':size,'sha256':digest.hexdigest()}
        held[path].update({'epoch':epoch(s),'descriptor':d,'raw':b''.join(raw) if decode else None})
    row=held[path]
    if expected is not None:
        assert row['descriptor']=={k:expected[k] for k in ('path','size_bytes','sha256')}
        if 'epoch' in expected:assert row['epoch']==expected['epoch']
    if original_epoch is not None:assert row['epoch']==original_epoch
    if decode and row['raw'] is None:
        assert row['descriptor']['size_bytes']<=1048576
        os.lseek(row['fd'],0,os.SEEK_SET);chunks=[];remaining=row['descriptor']['size_bytes']
        while remaining:
            clock();block=os.read(row['fd'],min(remaining,65536));assert block;chunks.append(block);remaining-=len(block)
        row['raw']=b''.join(chunks)
    return row
'''
replace(old_hold,new_hold)
old_write = text[text.index('def write('):text.index('def scan(')]
replace(old_write, '''def write(name,value,maximum=1048576):
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\\n').encode();assert len(raw)<=maximum
    with (OUT/name).open('xb') as f:
        offset=0
        while offset<len(raw):
            count=f.write(raw[offset:]);assert count is not None and count>0;offset+=count
        f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
''')
replace("    return {'observed_at_ns':time.time_ns(),'members':members,'read_errors':errors,\n            'pids_absent':{str(p):not Path('/proc',str(p)).exists() for p in pids}}", "    absent={}\n    for pid in sorted(pids):\n        try:Path('/proc',str(pid)).lstat();absent[str(pid)]=False\n        except FileNotFoundError:absent[str(pid)]=True\n        except OSError as exc:\n            absent[str(pid)]=False;errors.append({'pid':pid,'type':type(exc).__name__,'errno':exc.errno})\n    return {'observed_at_ns':time.time_ns(),'members':members,'read_errors':errors,'pids_absent':absent}")
replace("    assert outer['source_commit']==COMMIT", "    assert outer['source_commit']==COMMIT\n    assert outer['accepted'] is False and outer['failure'] is None and outer['error_overflow']==0\n    assert outer['EOF']=={'stdout':True,'stderr':True} and outer['reaped'] is True\n    assert outer['fd_before']==outer['fd_after']==6 and outer['all_pin_close_attempts_finished'] is True\n    assert len(outer['pin_closes'])==95 and {r['pin_index'] for r in outer['pin_closes']}==set(range(95)) and all(r['closed'] is True for r in outer['pin_closes'])\n    assert len(outer['process_group_scans'])==2\n    assert all(s['original_pid']==ORIGINAL_CLI_PID and s['original_pid_identity']=='absent' and not s['members'] and not s['errors'] and s['error_overflow']==s['member_overflow']==0 for s in outer['process_group_scans'])")
replace("    assert not os.path.lexists(OBSERVER/'late-limit-failure.v1.json')", "    for companion in ('late-limit-failure.v1.json','failure-companion.v1.json','failure.v4.json','late.v4.json'):\n        assert not os.path.lexists(OBSERVER/companion)\n    assert not os.path.lexists(PAIR/'component_cli_late_failure.v1.json')")
replace("    assert v6['descriptor']['sha256']==V6SHA", "    assert v6['descriptor']['sha256']==V6SHA\n    host=doc(v6['descriptor']['path'],v6['descriptor'])\n    sources=host['project_sources'];assert len(sources)==87\n    actual_sources={r['descriptor']['path']:r['descriptor'] for r in before if r['descriptor']['path'].startswith(str(ROOT/'scripts')+'/')}\n    assert len(actual_sources)==87\n    for source in sources:\n        expected={'path':str(ROOT/source['path']),'size_bytes':source['size_bytes'],'sha256':source['sha256']}\n        assert actual_sources[expected['path']]==expected\n    assert host['interpreter']['sha256']==prelaunch['interpreter']['sha256']")
replace("    complete=cli['status']=='component_pair_complete'", "    complete=cli['status']=='component_pair_complete'\n    assert cli['resource']=='cpu' and cli['full_arms']==cli['q4_runs']==cli['qualification_cells']==0\n    assert cli['primary_error'] is None if complete else True\n    for row in cli['input_pins'].values():hold(row['descriptor']['path'],row['descriptor'],row['epoch'])\n    for row in cli['launch_source_pins'].values():hold(row['descriptor']['path'],row['descriptor'],row['epoch'])")
replace("        assert all(row['nonauthority'] is True for row in timing)", "        assert all(row['nonauthority'] is True and row['explicit_fixture_dependencies'] is False for row in timing)\n        if complete:\n            phases=('reservation','source','context','capture','preprocessing','guardian_start','runtime','arm_baseline','arm_shared','guardian_stop','cold','context_close')\n            assert len(timing)==24 and {r['phase'] for r in timing}==set(phases)\n            for phase in phases:\n                rows=[r for r in timing if r['phase']==phase]\n                assert len(rows)==2 and rows[0]['event']=='start' and rows[1]['event']=='terminal' and rows[1]['status']=='complete' and rows[1]['error_type'] is None\n                assert rows[1]['monotonic_ns']>=rows[0]['monotonic_ns']\n            assert next(r for r in timing if r['phase']=='guardian_stop' and r['event']=='terminal')['monotonic_ns']<=next(r for r in timing if r['phase']=='cold' and r['event']=='start')['monotonic_ns']")
replace("    timing=[]", "    assert not complete or (cli['phase_timing'] and guardian['container_cleanup_verified'] is True and cli['guardian_cleanup_verified'] is True)\n    timing=[]")
replace("        process=doc(arm['outputs']['process_receipt']['path'],arm['outputs']['process_receipt']);assert process['status']=='complete_original_cli_capture' and process['failure'] is None", "        for reference in arm['outputs'].values():hold(reference['path'],reference)\n        process=doc(arm['outputs']['process_receipt']['path'],arm['outputs']['process_receipt']);assert process['status']=='complete_original_cli_capture' and process['failure'] is None")
replace("launch=doc(calls[0]['launch']['path'],calls[0]['launch']);terminal=doc(calls[0]['terminal']['path'],calls[0]['terminal']);assert terminal['returncode']==0", "launch=doc(calls[0]['launch']['path'],calls[0]['launch']);terminal=doc(calls[0]['terminal']['path'],calls[0]['terminal']);assert terminal['returncode']==0\n        assert terminal['launch_descriptor']==calls[0]['launch'] and not terminal['timed_out'] and not terminal['capture_exceeded'] and not terminal['capture_drain_failed']\n        assert launch['child']['boot_id']==EXPECTED_OWNER['boot_id'] and launch['controller']['pid']==EXPECTED_OWNER['pid']\n        pids.add(launch['child']['pid'])")
old_git = "    git=['/usr/bin/git','-c','core.longpaths=true','--git-dir='+str(ROOT/'.git'),'--work-tree='+str(ROOT)]\n    head=subprocess.check_output(git+['rev-parse','HEAD'],timeout=5,text=True).strip();assert head==COMMIT\n    assert not subprocess.check_output(git+['diff','--cached','--name-only','-z'],timeout=5)"
replace(old_git,"    head=prelaunch['sourceHEAD'];assert head==COMMIT\n    # No Git operation: join original B sourceHEAD and all current87 full source pins.")
replace("'hold_release':True,'limits':[", "'hold_release':False,'all_retained_raw_output_descriptors_verified':True,'fresh_process_scans':scans,'original_outer_closure_verified':True,'current_source_HEAD_not_independently_queried':True,'limits':[")
replace("'hold_release':True,'benchmark_accepted':False", "'hold_release':False,'benchmark_accepted':False")
start=text.index('finally:\n    close_errors=[]')
old_finish=text[start:]
new_finish='''finally:
    close_errors=[];closes=[]
    for path,row in held.items():
        try:os.close(row['fd']);closes.append({'path':str(path),'closed':True})
        except OSError as exc:
            closes.append({'path':str(path),'closed':False});close_errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
    fd_after=len(os.listdir('/proc/self/fd'))
    if fd_after!=FD_BEFORE:close_errors.append({'type':'FDLeak','message':'auditor FD baseline not restored'})
    if close_errors and failure is None:failure=close_errors[0]
    report['reviewer_held_fds_released']=not close_errors;report['hold_release']=not close_errors;report['close_errors']=close_errors
    report['reviewer_fd_before']=FD_BEFORE;report['reviewer_fd_after']=fd_after;report['reviewer_pin_closes']=closes
    if failure is not None:report['benchmark_accepted']=False;report['task_18_8_complete']=False;report['failure']=failure
    report['acceptance_requires_final_deadline_gate_and_original_tool_rc0']=True
    report['source_only_original_receipt_join_no_cold_or_numeric_reexecution']=True
    ref=write('review.v1.json',report);print(json.dumps(ref),flush=True)
final_elapsed_s=time.monotonic()-START
late_deadline_failure=final_elapsed_s>=120
if late_deadline_failure:
    late={'schema_version':1,'artifact_kind':'vast_cpu08_ext4_audit_late_failure_v1','disposition':'audit_failed_no_acceptance','audit_work_limit_s':120,'dispatch_containment_backstop_s':135,'elapsed_after_final_report_and_fd_release_s':final_elapsed_s,'closed_original_report':ref,'original_first_failure':failure,'late_failure':{'type':'TimeoutError','message':'finite audit120s exceeded after final report persistence and held FD release'},'reviewer_held_fds_released':not close_errors,'close_errors':close_errors,'benchmark_accepted':False,'task_18_8_complete':False,'closed_original_report_preserved':True}
    late_ref=write('late-failure.v1.json',late,maximum=65536);print(json.dumps({'late_failure':late_ref}),flush=True)
sys.exit(0 if failure is None and not close_errors and not late_deadline_failure else 1)
'''
replace(old_finish,new_finish)
successor=text.encode('utf-8')
# Static parser and inverse only; neither target is imported/compiled/executed.
old_ast=ast.parse(original);new_ast=ast.parse(successor)
funcs=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
o,n=funcs(old_ast),funcs(new_ast)
inverse=text
for row in reversed(changes):
    assert inverse.count(row['after'])==row['count'],row['after']
    inverse=inverse.replace(row['after'],row['before'])
assert inverse.encode()==original
def save(name,raw):
    with (OUT/name).open('xb') as f:f.write(raw)
def pin(path,raw):return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
save('cpu06-audit_v2.original.raw',original)
save('audit_cpu08_v1.py',successor)
diff=''.join(difflib.unified_diff(original.decode().splitlines(True),text.splitlines(True),fromfile='original_cpu06',tofile='prepared_cpu08'))
save('author.diff.v1.txt',diff.encode())
author={'schema_version':1,'author':'/root/decision28_source_peer','scope':'Source-only successor author; ROOT independent review required before one read-only audit invocation. Not self-certified independent review.','source':pin(BASE,original),'successor':pin(OUT/'audit_cpu08_v1.py',successor),'exact_ordered_raw_inverse':True,'literal_and_guard_replacements':changes,'function_names_unchanged':set(o)==set(n),'unchanged_function_ASTs':[k for k in o if o[k]==n[k]],'changed_function_ASTs':[k for k in o if o[k]!=n[k]],'new_functions':sorted(set(n)-set(o)),'budgets_preserved':{'audit_s':120,'external_containment_s':135,'external_kill_after_s':5,'leaf_bytes':67108864,'decoded_document_bytes':1048576,'report_bytes':1048576},'additional_late_companion_cap_bytes':65536,'Git_calls_removed_for_explicit_no_Git_scope':True,'fresh_original_B_HEAD_and_current87_fullSHA_join_instead':True,'no_target_import_compile_execution_test_engine_model_device_or_cleanup':True,'future_auditor_owner':None,'future_audit_result':None,'original_terminal':{'path':'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08-original-controller/original.terminal.v1.json','size_bytes':94894,'sha256':'32a034c535e98adf13fdbcb3005414c24d3ab3c03da885ec24da464a0e74b185','original_CLI_PID':73802},'limits':['Joins original authentic cold/all-phase receipts and current exact outputs; does not rerun cold consumer or raw numeric/C_obs reducer.','Current filesystem/proc facts require the future actual CP312 -I -B observation; Windows source author metadata is not Linux epoch custody.','No daemon query; exact original CID NotFound+CLI0 is separated from positively retained daemon terminal state.','Source-only review does not close GPU or full CI acceptance.']}
save('author.v1.json',(json.dumps(author,sort_keys=True,indent=2)+'\n').encode())
prep={'schema_version':1,'source':author['successor'],'considered_commit':'a00aa57f7d9534f8e7920f14f70d6a75a23570ed','original_terminal':author['original_terminal'],'exact_original_owner':{'pid':73802,'pgid':73802,'startticks':49797196,'controller':73800,'guardian_pid':74048,'guardian_startticks':49806399},'future_auditor_owner':None,'future_result':None,'ROOT_independent_source_review_before_execution_required':True,'proposed_original_argv':['/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python','-I','-B',(OUT/'audit_cpu08_v1.py').as_posix().replace('E:','/mnt/e'),'32a034c535e98adf13fdbcb3005414c24d3ab3c03da885ec24da464a0e74b185','94894','73802'],'acceptance_requires':['ROOT source review','Original once-only tool returncode0/EOF/reaped','Review receipt after independent close attempts and FD baseline restoration','No late-failure companion','Original CLI0 and complete retained cold pair','All95 exact current descriptors/fullSHA/fresh7epochs and full output recheck','Two current error-free original controller/CLI/guardian/native-child process/group/session absence scans'],'no_engine_model_device_measurement_cleanup_retry_Git_or_production_mutation':True}
save('preparation.v1.json',(json.dumps(prep,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'source':author['successor'],'changed_functions':author['changed_function_ASTs'],'unchanged_functions':author['unchanged_function_ASTs'],'new_functions':author['new_functions']}))
