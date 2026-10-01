"""One metadata-only review of the already executed, closed GPU auditor."""
import hashlib,json,os,stat,time
from pathlib import Path
WINDOWS=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=WINDOWS/'artifacts/benchmark_recovery_20260930'
AUDIT=BASE/'component-gpu01-ext4-postterminal-audit-preparation-v1'
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
PAIR=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-01'
OUT=Path(__file__).parent
COMMIT='0ad78d6abdb3c526544a17185af7fe8094716735'
START=time.monotonic();held={};report={};failure=None
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def hold(path,expected=None,decode=False):
    path=Path(path);assert path.is_absolute() and path.resolve(strict=True)==path
    if path not in held:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=1048576
            chunks=[];total=0
            while block:=os.read(fd,65536):chunks.append(block);total+=len(block)
            raw=b''.join(chunks);assert total==s.st_size and epoch(s)==epoch(os.fstat(fd))==epoch(path.lstat())
            held[path]={'fd':fd,'epoch':epoch(s),'raw':raw,'descriptor':{'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}
        except BaseException:os.close(fd);raise
    row=held[path]
    if expected is not None:assert row['descriptor']==expected
    return json.loads(row['raw']) if decode else row['descriptor']
def doc(path,expected=None):return hold(path,expected,True)
def sealed(value):
    body={k:v for k,v in value.items() if k!='sha256'}
    assert hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()==value['sha256']
    return value
def scan(pids):
    members=[];errors=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            v=(path/'stat').read_text().rsplit(')',1)[1].split()
            if int(path.name) in pids or int(v[2]) in pids or int(v[3]) in pids:
                ids=dict(line.split(':',1) for line in (path/'status').read_text().splitlines() if ':' in line)
                members.append({'pid':int(path.name),'state':v[0],'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19]),'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0])})
        except FileNotFoundError:pass
        except (OSError,ValueError) as exc:errors.append({'pid':int(path.name),'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
    return {'observed_at_ns':time.time_ns(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'members':members,'errors':errors,'actual_pid_absence':{str(p):not Path('/proc',str(p)).exists() for p in sorted(pids)}}
try:
    source=hold(Path(__file__))
    reader=hold(AUDIT/'audit_v1.py');assert reader['size_bytes']==17876 and reader['sha256']=='033a597766a461c8f1b1e2be43bb775ec27e3085202bb384e4ba2c15261d43f8'
    dispatcher=hold(AUDIT/'dispatch_v1.py');assert dispatcher['size_bytes']==1998 and dispatcher['sha256']=='7eb5ad62673ca3cfd947fe0d28b1273f2153a1c41b1e4a482f1e011216cb4bc6'
    r=doc(AUDIT/'review.v1.json');w=doc(r['witness']['path'],r['witness'])
    d=doc(AUDIT/'dispatch.terminal.v1.json');dl=doc(AUDIT/'dispatch.launch.v1.json');al=doc(AUDIT/'audit.launch.v1.json')
    assert d['returncode']==0 and d['timed_out'] is False and d['original_child_reaped'] is True and d['elapsed_s']<120
    assert d['reader']==dl['reader']==al['source']==reader and dl['source']==dispatcher
    assert d['argv']==dl['argv'] and d['original_child_pid']==al['pid']==52772 and dl['pid']==al['ppid']==52771 and al['pgid']==52772
    assert al['startticks']==28854363 and al['boot_id']=='dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
    hold(d['stdout']['path'],d['stdout']);hold(d['stderr']['path'],d['stderr']);assert d['stderr']['size_bytes']==0
    assert not os.path.lexists(AUDIT/'late-failure.v1.json')
    assert r['source_commit']==w['source_commit']==COMMIT and r['disposition']=='closed_original_component_pair_complete'
    assert r['benchmark_accepted'] is True and r['task_18_9_complete'] is True
    assert r['reviewer_held_fds_released'] is True and r['hold_release'] is True and r['close_errors']==[]
    assert r['acceptance_requires_final_deadline_gate_and_dispatch_rc0'] is True
    assert r['original95_before_after_current_full7epochs_equal'] is True and len(w['original95'])==95 and w['actual_current95']==w['original95']
    assert len(w['all_retained_input_descriptors'])==149
    outer=doc(r['outer_terminal']['path'],r['outer_terminal']);assert r['outer_terminal']['sha256']=='4c0e3fd34fb8ac8255bffab52fec7a310601eb4d29211a40f6948e882cbf3fc9' and r['outer_terminal']['size_bytes']==88102
    assert outer['source_commit']==COMMIT and outer['pins_before']==outer['pins_after']==w['original95']
    assert outer['source_count']==87 and outer['input_count']==6 and outer['accepted'] is False and outer['publication_ready'] is False
    assert outer['original_returncode']==0 and outer['timed_out'] is False and outer['capture_exceeded'] is False and outer['signals']==[] and outer['additional_errors']==[] and outer['original_cli_process_group_members']==[]
    owner=outer['owner'];assert owner['pid']==owner['pgid']==47763 and owner['ppid']==47761 and owner['startticks']==28764548 and owner['uid']==owner['gid']==1000 and owner['boot_id']==al['boot_id']
    cli=sealed(doc(r['cli_terminal']['path'],r['cli_terminal']));assert cli['status']=='component_pair_complete' and cli['primary_error'] is None and cli['cleanup_errors']==[]
    assert outer['original_cli_terminal']==r['cli_terminal'] and cli['pair_result']==r['cold_pair']['descriptor']
    guardian=cli['guardian_observation'];assert guardian==r['guardian_original'] and guardian['authenticated_stop'] and guardian['process_quiescent'] and guardian['returncode']==0 and guardian['cleanup_errors']==[]
    assert guardian['owner_process']['pid']==guardian['original_process_group']==48013 and guardian['owner_process']['proc_stat_starttime_ticks']==28773540
    lifecycle=doc(PAIR/'guardian/service_lifecycle.v1.json');authority=doc(PAIR/'guardian/service_authority.v1.json')
    assert lifecycle['status']=='clean_stop_nonpublication' and lifecycle['failure'] is None and lifecycle['cleanup_errors']==[]
    assert authority['owner_process']==guardian['owner_process'] and lifecycle['service_authority_sha256']==authority['service_authority_sha256']
    stop=lifecycle['guardian_stop_attestation'];assert stop['peer_process']['pid']==owner['pid'] and stop['peer_process']['proc_stat_starttime_ticks']==owner['startticks'] and stop['service_authority_sha256']==authority['service_authority_sha256']
    reserve=cli['capacity_reservation'];assert reserve['released'] and reserve['reserved_bytes']==20*1024**3 and reserve['allocated_bytes']>=20*1024**3 and not os.path.lexists(reserve['path'])
    cold=sealed(doc(cli['pair_result']['path'],cli['pair_result']));assert cold['resource']=='gpu' and cold['component_arms']==2 and cold['component_pairs']==1
    assert cold['scientific_scope']=='topology_load_proxy_only' and cold['confidence_interval'] is None
    for value in (cli,cold):assert all(value[k] is False for k in ('qualification_eligible','q4_eligible','publication_ready','full_run_eligible'))
    for key in ('descriptive_csv','latency_ecdf_svg'):hold(cold[key]['path'],cold[key])
    assert cold['arm_results']==[a['result'] for a in r['arms']] and len(r['arms'])==2
    for a in r['arms']:
        arm=sealed(doc(a['result']['path'],a['result']));assert arm['original_exit_code']==0 and arm['measurement_ingress_count']==1080
        assert arm['physical_validation']['completed_frames_by_stream']==a['completed_by_stream'] and a['native_cli_returncode']==0
        assert a['schedule_fingerprint']==cold['measurement_schedule_fingerprint_sha256'] and all(n>0 for n in a['completed_by_stream'].values())
    reconciliation=cold['operational_reconciliation'];assert reconciliation==r['cold_pair']['reconciliation'] and reconciliation['request_count']==10082 and reconciliation['measurement_request_count']==8594 and reconciliation['excluded_request_count']==1488
    assert reconciliation['publication_authority'] is False and reconciliation['original_operation_count']==2
    pids={47761,47763,48013,52771,52772};scans=[scan(pids),scan(pids)]
    assert all(s['boot_id']==owner['boot_id'] and not s['members'] and not s['errors'] and all(s['actual_pid_absence'].values()) for s in scans)
    for path,row in held.items():
        assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(path.lstat())
        os.lseek(row['fd'],0,os.SEEK_SET);chunks=[]
        while block:=os.read(row['fd'],65536):chunks.append(block)
        assert b''.join(chunks)==row['raw'] and epoch(os.fstat(row['fd']))==row['epoch']==epoch(path.lstat())
    report={'schema_version':1,'artifact_kind':'vast_gpu01_ext4_actual_closed_audit_metadata_review_v1','status':'accepted_original_gpu_component_boundary','benchmark_accepted_gpu_component_only':True,'source_commit':COMMIT,'reviewer_source':source,'original_review':hold(AUDIT/'review.v1.json'),'original_witness':r['witness'],'original_audit_reader':reader,'original_audit_dispatcher':dispatcher,'original_dispatch_terminal':hold(AUDIT/'dispatch.terminal.v1.json'),'original_audit_elapsed_s':d['elapsed_s'],'original_audit_fds_released':True,'original_audit95_before_after_current_equal':True,'original_auditor_retained_inputs_count':149,'late_companion_absent':True,'original_outer_terminal':r['outer_terminal'],'actual_original_cli_owner':owner,'actual_original_guardian_owner':guardian['owner_process'],'actual_original_outer_elapsed_s':outer['elapsed_s'],'original_outer_capture_accepted_false_preserved':True,'original_cli_terminal':r['cli_terminal'],'original_cli_status':cli['status'],'cold_pair':cli['pair_result'],'all_phase_reconciliation':reconciliation,'original_completed_frames_per_arm':[sum(a['completed_by_stream'].values()) for a in r['arms']],'original_ingress_per_arm':1080,'guardian_authenticated_stop':True,'reserve_absent':True,'fresh_two_actual_process_scans':scans,'metadata_witnesses':[{'descriptor':v['descriptor'],'epoch':v['epoch']} for v in held.values()],'task_18_9_complete':True,'task_recommendations':{'18.9':'Complete selected forced-GPU pair; CPU06 already independently accepted. No qualification/Q4/full grant.','21.4':'Both fresh original fixed-budget pairs accepted. Root may close after joining prior three-host-only impact/unchanged73/native3/worker2 and timing receipts.','22.2':'Genuine ext4 setup/new stock87 closure and both fixed-budget pairs accepted. Root may close after joining prior setup/bind/host/controller reviews.'},'full_publication_q4_accepted':False,'limitation':'Metadata-only second gate; original approved auditor performed95 full-byte/name/seven-epoch checks. No repeated weight reads, cold scan, engine/model/native/test operation.'}
except BaseException as exc:
    failure={'type':type(exc).__name__,'message':str(exc)[:4096]};report={'schema_version':1,'artifact_kind':'vast_gpu01_ext4_actual_closed_audit_metadata_review_v1','status':'review_failed_no_acceptance','failure':failure,'benchmark_accepted_gpu_component_only':False}
finally:
    close_errors=[]
    for row in held.values():
        try:os.close(row['fd'])
        except OSError as exc:close_errors.append({'type':type(exc).__name__,'errno':exc.errno})
    report['reviewer_metadata_fds_released']=not close_errors;report['close_errors']=close_errors;report['elapsed_after_release_s']=time.monotonic()-START
    name='review.v1.json' if failure is None and not close_errors else 'review.failed.v1.json'
    raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=1048576
    with (OUT/name).open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
    print(json.dumps({'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'failure':failure,'all_metadata_fds_released':not close_errors}),flush=True)
if failure is not None or close_errors:raise SystemExit(1)
