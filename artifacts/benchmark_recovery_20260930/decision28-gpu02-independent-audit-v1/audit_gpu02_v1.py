"""Prepared finite closed GPU02 boundary audit. Never execute before original terminal."""
import hashlib,json,os,stat,sys,time
from pathlib import Path
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
PAIR=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02'
OBSERVER=PAIR.parent/'gpu-pair-02-original-controller'
COMMIT='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
EXPECTED_OWNER=None
V6SHA='3c91339d43f6154dd76afe8a89c02d82f60a4b1e5da16623039f691fdc6701f2'
OUT=Path(__file__).parent
assert len(sys.argv)==4,'audit ORIGINAL_TERMINAL_SHA256 ORIGINAL_TERMINAL_SIZE ORIGINAL_CLI_PID'
ORIGINAL_CLI_PID=int(sys.argv[3]);assert str(ORIGINAL_CLI_PID)==sys.argv[3] and ORIGINAL_CLI_PID>0
TERMSHA=sys.argv[1]; TERMSIZE=int(sys.argv[2]);assert len(TERMSHA)==64 and all(c in '0123456789abcdef' for c in TERMSHA) and 0<TERMSIZE<=1048576
START=time.monotonic();END=START+120;held={};report={};failure=None
FD_BEFORE=len(os.listdir('/proc/self/fd'))

def clock():
    if time.monotonic()>=END:raise TimeoutError('finite audit120s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def hold(path,expected=None,original_epoch=None,decode=False):
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
def doc(path,expected=None):return json.loads(hold(path,expected,decode=True)['raw'])
def desc(path):return hold(path)['descriptor']
def sealed(value):
    digest=value['sha256'];body={k:v for k,v in value.items() if k!='sha256'}
    assert hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()==digest
    return value
def content(reference):
    value=doc(reference['path'],reference);raw=value['content'].encode('utf-8')
    assert len(raw)==value['size_bytes'] and hashlib.sha256(raw).hexdigest()==value['content_sha256'];return raw
def write(name,value,maximum=1048576):
    raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode();assert len(raw)<=maximum
    with (OUT/name).open('xb') as f:
        offset=0
        while offset<len(raw):
            count=f.write(raw[offset:]);assert count is not None and count>0;offset+=count
        f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def scan(pids):
    members=[];errors=[]
    for path in Path('/proc').iterdir():
        clock()
        if not path.name.isdigit():continue
        try:
            v=(path/'stat').read_text().rsplit(')',1)[1].split()
            if int(path.name) in pids or int(v[2]) in pids or int(v[3]) in pids:
                ids=dict(line.split(':',1) for line in (path/'status').read_text().splitlines() if ':' in line)
                members.append({'pid':int(path.name),'state':v[0],'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19]),
                                'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0])})
        except FileNotFoundError:pass
        except (OSError,ValueError) as exc:errors.append({'pid':int(path.name),'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
    absent={}
    for pid in sorted(pids):
        try:Path('/proc',str(pid)).lstat();absent[str(pid)]=False
        except FileNotFoundError:absent[str(pid)]=True
        except OSError as exc:
            absent[str(pid)]=False;errors.append({'pid':pid,'type':type(exc).__name__,'errno':exc.errno})
    return {'observed_at_ns':time.time_ns(),'members':members,'read_errors':errors,'pids_absent':absent}
def recheck_all():
    for path,row in held.items():
        assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(path.lstat())
        os.lseek(row['fd'],0,os.SEEK_SET);digest=hashlib.sha256();total=0
        while block:=os.read(row['fd'],1048576):clock();digest.update(block);total+=len(block)
        assert total==row['descriptor']['size_bytes'] and digest.hexdigest()==row['descriptor']['sha256']
        assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(path.lstat())

try:
    me=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    write('audit.launch.v1.json',{'argv':sys.argv,'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),'startticks':int(me[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'source':desc(Path(__file__)),'scope':'read-only closed original metadata/current95 FDs/proc; no project imports or engine calls'})
    outer_path=OBSERVER/'original.terminal.v1.json'
    outer=doc(outer_path,{'path':str(outer_path),'size_bytes':TERMSIZE,'sha256':TERMSHA})
    assert outer['source_commit']==COMMIT
    assert outer['accepted'] is False and outer['failure'] is None and outer['error_overflow']==0
    assert outer['EOF']=={'stdout':True,'stderr':True} and outer['reaped'] is True
    assert outer['fd_before']==outer['fd_after']==6 and outer['all_pin_close_attempts_finished'] is True
    assert len(outer['pin_closes'])==95 and {r['pin_index'] for r in outer['pin_closes']}==set(range(95)) and all(r['closed'] is True for r in outer['pin_closes'])
    assert len(outer['process_group_scans'])==2
    assert all(s['original_pid']==ORIGINAL_CLI_PID and s['original_pid_identity']=='absent' and not s['members'] and not s['errors'] and s['error_overflow']==s['member_overflow']==0 for s in outer['process_group_scans'])
    EXPECTED_OWNER=outer['owner']
    assert type(EXPECTED_OWNER) is dict and set(EXPECTED_OWNER)=={'pid','ppid','pgid','startticks','uid','gid','boot_id'}
    assert EXPECTED_OWNER['pid']==ORIGINAL_CLI_PID==outer['original_child_pid'] and EXPECTED_OWNER['pgid']==ORIGINAL_CLI_PID
    assert EXPECTED_OWNER['uid']==EXPECTED_OWNER['gid']==1000 and EXPECTED_OWNER['startticks']>0
    assert EXPECTED_OWNER['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    launch=doc(OBSERVER/'original.launch.v1.json')
    prelaunch=doc(OBSERVER/'prelaunch.v1.json')
    assert launch['source_commit']==prelaunch['source_commit']==COMMIT and launch['owner']==EXPECTED_OWNER
    assert launch['original_child_pid']==ORIGINAL_CLI_PID and launch['argv']==prelaunch['argv']==outer['argv']
    assert prelaunch['controller']['pid']==EXPECTED_OWNER['ppid'] and prelaunch['controller']['uid']==prelaunch['controller']['gid']==1000
    assert prelaunch['controller']['boot_id']==EXPECTED_OWNER['boot_id']
    assert outer['timed_out'] is False and outer['capture_exceeded'] is False and outer['signals']==[] and outer['additional_errors']==[] and outer['original_cli_process_group_members']==[]
    for companion in ('late-limit-failure.v1.json','failure-companion.v1.json','failure.v4.json','late.v4.json'):
        assert not os.path.lexists(OBSERVER/companion)
    assert not os.path.lexists(PAIR/'component_cli_late_failure.v1.json')
    before=outer['pins_before'];assert before==outer['pins_after'] and len(before)==95
    assert outer['source_count']==87 and outer['input_count']==6 and len({r['descriptor']['path'] for r in before})==95
    for row in before:hold(row['descriptor']['path'],row['descriptor'],row['epoch'])
    v6=next(r for r in before if r['descriptor']['path'].endswith('/execution-code-closure.ext4-decision28.v4.json'))
    assert v6['descriptor']['sha256']==V6SHA
    host=doc(v6['descriptor']['path'],v6['descriptor'])
    sources=host['project_sources'];assert len(sources)==87
    actual_sources={r['descriptor']['path']:r['descriptor'] for r in before if r['descriptor']['path'].startswith(str(ROOT/'scripts')+'/')}
    assert len(actual_sources)==87
    for source in sources:
        expected={'path':str(ROOT/source['path']),'size_bytes':source['size_bytes'],'sha256':source['sha256']}
        assert actual_sources[expected['path']]==expected
    assert host['interpreter']['sha256']==prelaunch['interpreter']['sha256']
    controller=next(r for r in before if r['descriptor']['path'].endswith('/run_original_gpu_component_pair_ext4_decision28_v4.py'))
    assert controller['descriptor']['sha256']=='fa4bb696e20ac179557096525ad8eebfa0febae388f3e3033d8890eb7416f938' and controller['descriptor']['size_bytes']==23631
    for role in ('stdout','stderr'):hold(outer[role]['path'],outer[role])
    cli=sealed(doc(outer['original_cli_terminal']['path'],outer['original_cli_terminal']))
    complete=cli['status']=='component_pair_complete'
    assert cli['resource']=='gpu' and cli['full_arms']==cli['q4_runs']==cli['qualification_cells']==0
    assert cli['primary_error'] is None if complete else True
    for row in cli['input_pins'].values():hold(row['descriptor']['path'],row['descriptor'],row['epoch'])
    for row in cli['launch_source_pins'].values():hold(row['descriptor']['path'],row['descriptor'],row['epoch'])
    assert (outer['original_returncode']==0)==complete
    cold_present=cli['pair_result'] is not None
    assert cli['component_pairs']==int(complete) and (not complete or cold_present)
    assert all(cli[k] is False for k in ('qualification_eligible','q4_eligible','publication_ready','full_run_eligible'))
    reserve=cli['capacity_reservation'];assert reserve['released'] is True and reserve['reserved_bytes']==20*1024**3
    assert reserve['allocated_bytes']>=20*1024**3 and not os.path.lexists(reserve['path'])
    guardian=cli['guardian_observation'];pids={EXPECTED_OWNER['ppid'],EXPECTED_OWNER['pid']}
    if guardian.get('owner_process'):pids.add(guardian['owner_process']['pid'])
    lifecycle=None;authority=None
    if os.path.lexists(PAIR/'guardian/service_authority.v1.json'):
        authority=doc(PAIR/'guardian/service_authority.v1.json');lifecycle=doc(PAIR/'guardian/service_lifecycle.v1.json')
        assert authority['owner_process']==guardian['owner_process'] and lifecycle['service_authority_sha256']==authority['service_authority_sha256']
        if guardian.get('authenticated_stop'):
            stop=lifecycle['guardian_stop_attestation'];assert stop['peer_process']['pid']==EXPECTED_OWNER['pid'] and stop['peer_process']['proc_stat_starttime_ticks']==EXPECTED_OWNER['startticks']
            assert stop['service_authority_sha256']==authority['service_authority_sha256']
    if complete or cold_present:
        assert guardian['authenticated_stop'] and guardian['process_quiescent'] and guardian['returncode']==0 and guardian['cleanup_errors']==[] and cli['cleanup_errors']==[]
        assert lifecycle['status']=='clean_stop_nonpublication' and lifecycle['failure'] is None and lifecycle['cleanup_errors']==[]
    for key in ('guardian_stdout','guardian_stderr'):
        if key in cli:hold(cli[key]['path'],cli[key])
    assert not complete or (cli['phase_timing'] and guardian['container_cleanup_verified'] is True and cli['guardian_cleanup_verified'] is True)
    timing=[]
    if cli.get('phase_timing'):
        timing_pin=hold(cli['phase_timing']['path'],cli['phase_timing'],decode=True);assert timing_pin['descriptor']['size_bytes']<=16384
        timing=[json.loads(line) for line in timing_pin['raw'].splitlines()];assert len(timing)<=24
        assert all(row['nonauthority'] is True and row['explicit_fixture_dependencies'] is False for row in timing)
        if complete:
            phases=('reservation','source','context','capture','preprocessing','guardian_start','runtime','arm_baseline','arm_shared','guardian_stop','cold','context_close')
            assert len(timing)==24 and {r['phase'] for r in timing}==set(phases)
            for phase in phases:
                rows=[r for r in timing if r['phase']==phase]
                assert len(rows)==2 and rows[0]['event']=='start' and rows[1]['event']=='terminal' and rows[1]['status']=='complete' and rows[1]['error_type'] is None
                assert rows[1]['monotonic_ns']>=rows[0]['monotonic_ns']
            assert next(r for r in timing if r['phase']=='guardian_stop' and r['event']=='terminal')['monotonic_ns']<=next(r for r in timing if r['phase']=='cold' and r['event']=='start')['monotonic_ns']
    arms=[]
    for suffix in ('independent-processes','shared-video-dag'):
        operation='component-gstreamer_custom-gpu-h264-'+suffix
        arm_path=PAIR/'operations/arms'/operation/'component_arm_result.v1.json'
        if not os.path.lexists(arm_path):continue
        arm=sealed(doc(arm_path));assert arm['original_exit_code']==0 and arm['measurement_ingress_count']==1080
        assert all(n>0 for n in arm['physical_validation']['completed_frames_by_stream'].values())
        assert all(arm[k] is False for k in ('publication_ready','qualification_eligible','q4_eligible','full_run_eligible'))
        for reference in arm['outputs'].values():hold(reference['path'],reference)
        process=doc(arm['outputs']['process_receipt']['path'],arm['outputs']['process_receipt']);assert process['status']=='complete_original_cli_capture' and process['failure'] is None
        calls=[c for c in process['calls'] if c['phase']=='measurement'];assert len(calls)==1
        launch=doc(calls[0]['launch']['path'],calls[0]['launch']);terminal=doc(calls[0]['terminal']['path'],calls[0]['terminal']);assert terminal['returncode']==0
        assert terminal['launch_descriptor']==calls[0]['launch'] and not terminal['timed_out'] and not terminal['capture_exceeded'] and not terminal['capture_drain_failed']
        assert launch['child']['boot_id']==EXPECTED_OWNER['boot_id'] and launch['controller']['pid']==EXPECTED_OWNER['pid']
        pids.add(launch['child']['pid'])
        container=doc(arm['outputs']['container_receipt']['path'],arm['outputs']['container_receipt']);assert container['status']=='complete_original_container_custody' and container['failure'] is None and container['measurement_returncode']==0
        hold(container['cidfile']['path'],container['cidfile']);doc(container['reservation']['path'],container['reservation'])
        commands=[]
        for reference in container['commands']:
            c=doc(reference['path'],reference);commands.append((c,content(c['stdout']),content(c['stderr'])))
        c,stdout,stderr=next(row for row in commands if row[0]['seq']==container['terminal_command_seq'])
        assert c['argv'][-1]==container['container_id']
        if c['returncode']==1:
            assert stdout in (b'',b'\n') and stderr==('Error response from daemon: No such container: '+container['container_id']+'\n').encode()
            daemon='not retained; original --rm CLI0 plus exactCID NotFound'
        else:
            assert c['returncode']==0;inspect=json.loads(stdout);assert len(inspect)==1 and inspect[0]['Id']==container['container_id']
            state=inspect[0]['State'];assert state['Running'] is False and state['Pid']==0 and state['ExitCode']==0 and state['OOMKilled'] is False
            daemon={'positively_retained_terminal_state':state}
        arms.append({'operation_id':operation,'result':desc(arm_path),'native_cli_returncode':0,'measurement_ingress_count':1080,'completed_by_stream':arm['physical_validation']['completed_frames_by_stream'],'schedule_fingerprint':arm['physical_validation']['measurement_schedule_fingerprint_sha256'],'container_id':container['container_id'],'container_receipt':arm['outputs']['container_receipt'],'daemon_terminal_evidence':daemon})
    if len(arms)==2:assert arms[0]['schedule_fingerprint']==arms[1]['schedule_fingerprint']
    cold=None
    if cold_present:
        assert len(arms)==2
        cold=sealed(doc(cli['pair_result']['path'],cli['pair_result']));assert cold['artifact_kind']=='vast_gstreamer_component_pair_result_v1' and cold['component_arms']==2 and cold['component_pairs']==1 and cold['resource']=='gpu'
        assert cold['arm_results']==[a['result'] for a in arms]
        assert cold['measurement_schedule_fingerprint_sha256']==arms[0]['schedule_fingerprint']
        assert all(cold[k] is False for k in ('qualification_eligible','q4_eligible','publication_ready','full_run_eligible'))
        assert cold['scientific_scope']=='topology_load_proxy_only' and cold['confidence_interval'] is None
        for key in ('guardian_authority','guardian_lifecycle','guardian_companion','descriptive_csv','latency_ecdf_svg'):hold(cold[key]['path'],cold[key])
    scans=[scan(pids),scan(pids)];assert all(not s['members'] and not s['read_errors'] and all(s['pids_absent'].values()) for s in scans)
    head=prelaunch['sourceHEAD'];assert head==COMMIT
    # No Git operation: join original B sourceHEAD and all current87 full source pins.
    recheck_all()
    witness=write('held-inputs-and-processes.v1.json',{'source_commit':head,'original95':before,'actual_current95':[{'descriptor':held[Path(r['descriptor']['path'])]['descriptor'],'epoch':held[Path(r['descriptor']['path'])]['epoch']} for r in before],'process_scans':scans,'all_retained_input_descriptors':[r['descriptor'] for r in held.values()]})
    report={'schema_version':1,'artifact_kind':'vast_gpu02_ext4_closed_boundary_independent_review_v1','disposition':'closed_original_component_pair_complete' if complete else 'closed_failed_original','source_commit':head,'outer_terminal':desc(outer_path),'cli_terminal':outer['original_cli_terminal'],'original_cli_returncode':outer['original_returncode'],'outer_elapsed_s':outer['elapsed_s'],'outer_timeout':False,'outer_signals':[],'original95_before_after_current_full7epochs_equal':True,'witness':witness,'arms':arms,'reserve_released_and_absent':True,'guardian_original':guardian,'cold_pair':None if cold is None else {'descriptor':cli['pair_result'],'reconciliation':cold['operational_reconciliation'],'descriptive_csv':cold['descriptive_csv'],'latency_ecdf_svg':cold['latency_ecdf_svg'],'retained_cold_result_does_not_override_cli_failure':not complete},'benchmark_accepted':complete,'task_18_9_complete':complete,'original_phase_timing':timing,'original_first_error':cli['primary_error'],'hold_release':False,'all_retained_raw_output_descriptors_verified':True,'fresh_process_scans':scans,'original_outer_closure_verified':True,'current_source_HEAD_not_independently_queried':True,'limits':['This boundary audit joins retained authentic original receipts. It does not rerun the all-phase cold consumer or raw numeric/C_obs reducer.','Native daemon ExitCode/Pid/OOM fields are reported only when actually retained. Exact --rm CID absence plus originalCLI0 is stated separately.','Guardian cleanup is scoped to original authenticated lifecycle/CLI evidence and actual process absence. No daemon query or independent worker inspection.','No reviewer engine/model/native/guardian/namespace/test execution or historical failure reclassification.']}
except BaseException as exc:
    failure={'type':type(exc).__name__,'message':str(exc)[:4096]}
    report={'schema_version':1,'artifact_kind':'vast_gpu02_ext4_closed_boundary_independent_review_v1','disposition':'audit_failed_no_acceptance','source_commit':COMMIT,'failure':failure,'hold_release':False,'benchmark_accepted':False}
finally:
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
    if failure is not None:report['benchmark_accepted']=False;report['task_18_9_complete']=False;report['failure']=failure
    report['acceptance_requires_final_deadline_gate_and_original_tool_rc0']=True
    report['source_only_original_receipt_join_no_cold_or_numeric_reexecution']=True
    ref=write('review.v1.json',report);print(json.dumps(ref),flush=True)
final_elapsed_s=time.monotonic()-START
late_deadline_failure=final_elapsed_s>=120
if late_deadline_failure:
    late={'schema_version':1,'artifact_kind':'vast_gpu02_ext4_audit_late_failure_v1','disposition':'audit_failed_no_acceptance','audit_work_limit_s':120,'dispatch_containment_backstop_s':135,'elapsed_after_final_report_and_fd_release_s':final_elapsed_s,'closed_original_report':ref,'original_first_failure':failure,'late_failure':{'type':'TimeoutError','message':'finite audit120s exceeded after final report persistence and held FD release'},'reviewer_held_fds_released':not close_errors,'close_errors':close_errors,'benchmark_accepted':False,'task_18_9_complete':False,'closed_original_report_preserved':True}
    late_ref=write('late-failure.v1.json',late,maximum=65536);print(json.dumps({'late_failure':late_ref}),flush=True)
sys.exit(0 if failure is None and not close_errors and not late_deadline_failure else 1)
