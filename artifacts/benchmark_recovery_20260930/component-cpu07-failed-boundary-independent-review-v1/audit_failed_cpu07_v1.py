"""One closed FAILED CPU07 custody/source audit; no project imports or workload."""
import hashlib,json,os,stat,time,traceback
from pathlib import Path
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
BASE=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'
PAIR=BASE/'cpu-pair-07';ORIGINAL=BASE/'cpu-pair-07-original-controller'
OUT=Path(__file__).parent;COMMIT='9d47e99b623df44816f7b0a0b73b249a940f7723'
TERMSHA='e83d65c50d80f79efc9339dfab07d38618cf0995de4f9420bb6dbe190bf51a85'
START=time.monotonic();END=START+120;held={};ancestors={};first=None;report={}
baseline=len(list(Path('/proc/self/fd').iterdir()))
def clock():
    if time.monotonic()>=END:raise TimeoutError('failed CPU07 audit120s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
def hold(path,expected=None,max_bytes=1048576):
    clock();p=Path(path);assert p.is_absolute() and p.resolve(strict=True)==p,str(p)
    if p not in held:
        for a in reversed(p.parents):
            if a not in ancestors:
                fd=os.open(a,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:
                    s=os.fstat(fd);assert stat.S_ISDIR(s.st_mode) and identity(s)==identity(a.lstat());ancestors[a]=(fd,identity(s))
                except BaseException:os.close(fd);raise
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=max_bytes
            h=hashlib.sha256();chunks=[];total=0
            while b:=os.read(fd,65536):clock();chunks.append(b);h.update(b);total+=len(b);assert total<=max_bytes
            assert total==s.st_size and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
            held[p]={'fd':fd,'epoch':epoch(s),'raw':b''.join(chunks),'descriptor':{'path':str(p),'size_bytes':total,'sha256':h.hexdigest()}}
        except BaseException:os.close(fd);raise
    v=held[p]
    if expected is not None:assert v['descriptor']=={k:expected[k] for k in ('path','size_bytes','sha256')},str(p)
    return v

def doc(path,expected=None):return json.loads(hold(path,expected)['raw'])
def sealed(v):
    body={k:x for k,x in v.items() if k!='sha256'}
    raw=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
    assert hashlib.sha256(raw).hexdigest()==v['sha256'];return v

def scan(ids):
    clock();members=[];errors=[]
    for p in Path('/proc').iterdir():
        clock()
        if not p.name.isdigit():continue
        try:
            v=(p/'stat').read_text().rsplit(')',1)[1].split()
            if int(p.name) in ids or int(v[2]) in ids or int(v[3]) in ids:
                status=dict(x.split(':',1) for x in (p/'status').read_text().splitlines() if ':' in x)
                members.append({'pid':int(p.name),'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19]),'state':v[0],'uid':int(status['Uid'].split()[0]),'gid':int(status['Gid'].split()[0])})
        except FileNotFoundError:pass
        except (OSError,ValueError) as e:errors.append({'pid':int(p.name),'type':type(e).__name__,'errno':getattr(e,'errno',None)})
    return {'at_ns':time.time_ns(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'members':members,'errors':errors,'pids_absent':{str(i):not Path('/proc',str(i)).exists() for i in sorted(ids)}}
def save(name,v):
    raw=(json.dumps(v,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=1048576
    with (OUT/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
try:
    src=hold(Path(__file__));me=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    launch={'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),'startticks':int(me[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'uid':os.getuid(),'gid':os.getgid(),'source':src['descriptor'],'argv':__import__('sys').argv}
    save('launch.v1.json',launch)
    outerpath=ORIGINAL/'original.terminal.v1.json';outer=doc(outerpath)
    assert held[outerpath]['descriptor']['size_bytes']==88208 and held[outerpath]['descriptor']['sha256']==TERMSHA
    assert outer['source_commit']==COMMIT and outer['original_returncode']==78 and not outer['accepted'] and not outer['publication_ready']
    assert not outer['timed_out'] and not outer['capture_exceeded'] and outer['signals']==[] and outer['additional_errors']==[]
    rows=outer['pins_before'];assert rows==outer['pins_after'] and len(rows)==95 and len({r['descriptor']['path'] for r in rows})==95
    assert outer['source_count']==87 and outer['input_count']==6
    for r in rows:
        v=hold(r['descriptor']['path'],r['descriptor'],16777216);assert v['epoch']==r['epoch'],r['descriptor']['path']
    assert (ROOT/'.git/HEAD').read_text().strip()==COMMIT
    cli=sealed(doc(outer['original_cli_terminal']['path'],outer['original_cli_terminal']))
    assert cli['status']=='failed' and cli['component_pairs']==0 and cli['pair_result'] is None
    guardian=cli['guardian_observation'];assert guardian['returncode']==78 and guardian['authenticated_stop'] is False and guardian['container_cleanup_verified'] is False
    life=doc(PAIR/'guardian/service_lifecycle.v1.json');authority=doc(PAIR/'guardian/service_authority.v1.json');diag=doc(PAIR/'guardian/protocol_failure_diagnostic.v1.json')
    assert life['status']=='failed_stop_nonpublication' and life['guardian_stop_attestation'] is None
    assert life['service_authority_sha256']==authority['service_authority_sha256']==diag['service_authority_sha256']
    assert diag['expected']==diag['observed'] and diag['failure_stage']=='inference'
    for k in ('guardian_stdout','guardian_stderr','phase_timing'):hold(cli[k]['path'],cli[k])
    for k in ('stdout','stderr'):hold(outer[k]['path'],outer[k])
    capture_dir=PAIR/'operations/process-captures/component-gstreamer_custom-cpu-h264-independent-processes'
    native=sealed(doc(capture_dir/'original_engine_process_capture.v1.json'));custody=sealed(doc(capture_dir/'container-custody/original_container_custody.v1.json'))
    assert native['status']=='failed_original_cli_capture' and native['container_quiescence_verified'] is False
    assert custody['measurement_returncode']==1 and custody['failure']=='original_measurement_failed'
    ids={outer['owner']['pid'],outer['owner']['ppid'],outer['owner']['pgid'],guardian['original_child_pid'],guardian['original_process_group']};engine=[]
    for c in native['calls']:
        l=sealed(doc(c['launch']['path'],c['launch']));t=sealed(doc(c['terminal']['path'],c['terminal']));assert t['launch_descriptor']==c['launch']
        ids.add(l['child']['pid']);engine.append({'phase':c['phase'],'launch':c['launch'],'terminal':c['terminal'],'owner':l['child'],'returncode':t['returncode'],'timed_out':t['timed_out']})
    commands=[]
    for ref in custody['commands']:
        c=sealed(doc(ref['path'],ref));ids.add(c['child']['pid']);streams={}
        for key in ('stdout','stderr'):
            v=sealed(doc(c[key]['path'],c[key]));content=v['content'].encode();assert len(content)==v['size_bytes'] and hashlib.sha256(content).hexdigest()==v['content_sha256'];streams[key]=v['content']
        commands.append({'role':c['role'],'argv':c['argv'],'returncode':c['returncode'],'owner':c['child'],'started_at_ns':c['started_at_ns'],'terminal_at_ns':c['terminal_at_ns'],'streams':streams})
    hold(custody['cidfile']['path'],custody['cidfile']);assert held[Path(custody['cidfile']['path'])]['raw'].decode()==custody['container_id']
    reserve=cli['capacity_reservation'];assert reserve['released'] is True and not os.path.lexists(reserve['path'])
    scans=[scan(ids),scan(ids)];assert all(s['boot_id']==outer['owner']['boot_id'] and not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
    for p,v in held.items():
        clock();assert v['epoch']==epoch(os.fstat(v['fd']))==epoch(p.lstat());os.lseek(v['fd'],0,os.SEEK_SET);h=hashlib.sha256();count=0
        while b:=os.read(v['fd'],65536):clock();h.update(b);count+=len(b)
        assert count==v['descriptor']['size_bytes'] and h.hexdigest()==v['descriptor']['sha256'] and v['epoch']==epoch(os.fstat(v['fd']))==epoch(p.lstat())
    for p,(fd,s) in ancestors.items():assert identity(os.fstat(fd))==s==identity(p.lstat())
    witness={'original95':rows,'retained_metadata':[{'descriptor':v['descriptor'],'epoch':v['epoch']} for v in held.values()],'actual_two_scans':scans,'reader_launch':launch}
    report={'schema_version':1,'status':'closed_failed_original_cpu07','source_commit':COMMIT,'outer_terminal':held[outerpath]['descriptor'],'original_returncode':78,'original_outer_elapsed_s':outer['elapsed_s'],'original95_bytes_full7epochs_before_after_current_equal':True,'source_count':87,'input_count':6,'original95_count':95,'guardian_original':guardian,'guardian_lifecycle_failure':life['failure'],'guardian_lifecycle_cleanup_errors':life['cleanup_errors'],'protocol_diagnostic':diag,'original_engine_calls':engine,'original_container_custody_failure':custody['failure'],'container_id':custody['container_id'],'original_container_commands':commands,'capacity_reserve_released_and_absent':True,'fresh_two_actual_process_scans':scans,'native_container_positive_terminal_exit_or_OOM':None,'guardian_authenticated_stop':False,'guardian_container_cleanup_verified':False,'container_quiescence_verified':False,'causal_limit':'Original retained Broken pipe inference failure and failed native measurement precede the later guardian-stop /proc custody diagnostic. No first failing native stderr bytes or failed /proc field snapshot are reconstructed; host PID absence does not establish hidden worker-container cleanup.','benchmark_accepted':False,'task_18_8_complete':False,'gpu_accepted':False,'full_publication_accepted':False,'model_or_engine_or_native_or_test_operation':False,'witness':save('witness.v1.json',witness)}
except BaseException as e:
    first={'type':type(e).__name__,'message':str(e)[:4096],'reader_traceback':traceback.format_exc()[-8192:]};report={'schema_version':1,'status':'failed_audit_no_acceptance','first_error':first,'benchmark_accepted':False}
finally:
    errors=[]
    for fd in [v['fd'] for v in held.values()]+[v[0] for v in ancestors.values()]:
        try:os.close(fd)
        except OSError as e:errors.append({'type':type(e).__name__,'errno':e.errno})
    report.update({'reviewer_fds_released':not errors,'close_errors':errors,'fd_before':baseline,'fd_after':len(list(Path('/proc/self/fd').iterdir())),'elapsed_after_close_s':time.monotonic()-START})
    if errors or report['fd_after']!=baseline or time.monotonic()>=END:
        if first is None:first={'type':'AuditReleaseOrDeadlineFailure','message':'final FD/deadline predicate failed'}
        report['status']='failed_audit_no_acceptance';report['first_error']=first
    ref=save('review.v1.json',report);print(json.dumps(ref),flush=True)
late=time.monotonic()>=END
if late:save('late-failure.v1.json',{'status':'failed_audit_no_acceptance','closed_report':ref,'first_error':first,'elapsed_s':time.monotonic()-START})
raise SystemExit(0 if first is None and not errors and not late else 1)
