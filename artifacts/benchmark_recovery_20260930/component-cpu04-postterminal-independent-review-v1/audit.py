"""Finite original-terminal/input/cleanup audit. No project imports or engine calls."""
import hashlib,json,os,stat,subprocess,sys,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
PAIR=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04'
OBSERVER=PAIR.parent/'cpu-pair-04-original-controller'
OUT=Path(__file__).parent
START=time.monotonic(); END=START+60; held={}
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def hold(path,expected=None,original_epoch=None,decode=False):
    path=Path(path); path=path if path.is_absolute() else ROOT/path
    if path not in held:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW); s=os.fstat(fd)
        assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=64*1024*1024
        digest=hashlib.sha256(); raw=[]; size=0
        while block:=os.read(fd,1048576):
            assert time.monotonic()<END; digest.update(block);size+=len(block)
            if decode:raw.append(block)
        assert size==s.st_size and epoch(s)==epoch(path.lstat())==epoch(os.fstat(fd))
        d={'path':str(path),'size_bytes':size,'sha256':digest.hexdigest()}
        held[path]={'fd':fd,'epoch':epoch(s),'descriptor':d,'raw':b''.join(raw) if decode else None}
    row=held[path]
    if expected:assert row['descriptor']==expected
    if original_epoch is not None:assert row['epoch']==original_epoch
    if decode and row['raw'] is None:
        assert row['descriptor']['size_bytes']<=1048576
        os.lseek(row['fd'],0,os.SEEK_SET); row['raw']=os.read(row['fd'],row['descriptor']['size_bytes']+1)
    return row
def doc(path,expected=None):return json.loads(hold(path,expected,decode=True)['raw'])
def desc(path):return hold(path)['descriptor']
def content(descriptor):
    value=doc(descriptor['path'],descriptor);raw=value['content'].encode('utf-8')
    assert len(raw)==value['size_bytes'] and hashlib.sha256(raw).hexdigest()==value['content_sha256']
    return raw
def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
me=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
write('audit.launch.v1.json',{'argv':sys.argv,'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),
 'startticks':int(me[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
 'source':desc(Path(__file__)),'scope':'read-only original closed metadata/current pins/proc; no project imports or engine calls'})
outer_path=OBSERVER/'original.terminal.v1.json'
outer=doc(outer_path)
assert desc(outer_path)=={'path':str(outer_path),'size_bytes':91709,'sha256':'88b9c117f75b45454b8facc781e1bb291750de388b85f03c31fe7135b1496b0e'}
assert outer['source_commit']=='78f50184362c1bd77f9dc5eadd8cd69d6ab3c5ac'
assert outer['original_returncode']==1 and outer['timed_out'] is False and outer['capture_exceeded'] is False
assert outer['signals']==[] and outer['additional_errors']==[] and outer['original_cli_process_group_members']==[]
before=outer['pins_before'];assert before==outer['pins_after'] and len(before)==95
assert outer['source_count']==87 and outer['input_count']==6 and len({r['descriptor']['path'] for r in before})==95
for row in before:hold(row['descriptor']['path'],row['descriptor'],row['epoch'])
for role in ('stdout','stderr'):hold(outer[role]['path'],outer[role])
cli=doc(outer['original_cli_terminal']['path'],outer['original_cli_terminal'])
assert cli['status']=='failed' and cli['pair_result'] is None and cli['component_pairs']==0
assert cli['primary_error']['type']=='ImportError' and 'load_operational_jsonl_header_v1' in cli['primary_error']['message']
assert cli['capacity_reservation']['released'] is True and cli['capacity_reservation']['reserved_bytes']==20*1024**3
assert cli['capacity_reservation']['allocated_bytes']>=20*1024**3 and not os.path.lexists(cli['capacity_reservation']['path'])
guardian=cli['guardian_observation'];assert guardian['authenticated_stop'] and guardian['process_quiescent']
assert guardian['returncode']==0 and guardian['cleanup_errors']==[] and cli['cleanup_errors']==[]
for key in ('guardian_stdout','guardian_stderr'):hold(cli[key]['path'],cli[key])
lifecycle=doc(PAIR/'guardian/service_lifecycle.v1.json'); authority=doc(PAIR/'guardian/service_authority.v1.json')
assert lifecycle['status']=='clean_stop_nonpublication' and lifecycle['failure'] is None and lifecycle['cleanup_errors']==[]
assert lifecycle['service_authority_sha256']==authority['service_authority_sha256']
stop=lifecycle['guardian_stop_attestation'];assert stop['peer_process']['pid']==29183
assert stop['peer_process']['proc_stat_starttime_ticks']==outer['owner']['startticks']
assert stop['service_authority_sha256']==authority['service_authority_sha256']
assert authority['owner_process']==guardian['owner_process']
arms=[];measurement_owners=[]
for suffix in ('independent-processes','shared-video-dag'):
    operation='component-gstreamer_custom-cpu-h264-'+suffix
    arm_path=PAIR/'operations/arms'/operation/'component_arm_result.v1.json'; arm=doc(arm_path)
    assert arm['original_exit_code']==0 and arm['measurement_ingress_count']==1080
    assert all(n>0 for n in arm['physical_validation']['completed_frames_by_stream'].values())
    assert arm['publication_ready'] is False and arm['qualification_eligible'] is False and arm['q4_eligible'] is False
    process=doc(arm['outputs']['process_receipt']['path'],arm['outputs']['process_receipt'])
    assert process['status']=='complete_original_cli_capture' and process['failure'] is None
    calls=[c for c in process['calls'] if c['phase']=='measurement'];assert len(calls)==1
    launch=doc(calls[0]['launch']['path'],calls[0]['launch']); terminal=doc(calls[0]['terminal']['path'],calls[0]['terminal'])
    assert terminal['returncode']==0
    measurement_owners.append(launch)
    container=doc(arm['outputs']['container_receipt']['path'],arm['outputs']['container_receipt'])
    assert container['status']=='complete_original_container_custody' and container['failure'] is None and container['measurement_returncode']==0
    hold(container['cidfile']['path'],container['cidfile']); reservation=doc(container['reservation']['path'],container['reservation'])
    commands=[]
    for reference in container['commands']:
        c=doc(reference['path'],reference); stdout=content(c['stdout']);stderr=content(c['stderr']);commands.append((c,stdout,stderr))
    terminal_command=next(c for c in commands if c[0]['seq']==container['terminal_command_seq'])
    c,stdout,stderr=terminal_command
    assert c['argv'][-1]==container['container_id'] and c['returncode']==1 and stdout in (b'',b'\n')
    assert stderr==('Error response from daemon: No such container: '+container['container_id']+'\n').encode()
    arms.append({'operation_id':operation,'result':desc(arm_path),'native_cli_returncode':0,
       'measurement_ingress_count':1080,'completed_by_stream':arm['physical_validation']['completed_frames_by_stream'],
       'schedule_fingerprint':arm['physical_validation']['measurement_schedule_fingerprint_sha256'],
       'container_id':container['container_id'],'container_receipt':arm['outputs']['container_receipt'],
       'original_exact_cid_absence_command':desc(terminal_command[0]['stdout']['path']),
       'daemon_terminal_state':'not retained; original --rm CLI completed0 and exact CID NotFound observed'})
assert arms[0]['schedule_fingerprint']==arms[1]['schedule_fingerprint']
def scan():
    rows=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            v=(p/'stat').read_text().rsplit(')',1)[1].split()
            if int(p.name) in (29181,29183,29403) or int(v[2]) in (29181,29183,29403) or int(v[3]) in (29181,29183,29403):
                rows.append({'pid':int(p.name),'state':v[0],'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19])})
        except (OSError,ValueError):pass
    return {'observed_at_ns':time.time_ns(),'members':rows,'pids_absent':{str(p):not Path('/proc',str(p)).exists() for p in (29181,29183,29403)}}
scans=[scan(),scan()];assert all(not s['members'] and all(s['pids_absent'].values()) for s in scans)
head=subprocess.check_output(['/usr/bin/git','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT),'rev-parse','HEAD'],timeout=5,text=True).strip()
assert head==outer['source_commit']
for path,row in held.items():
    assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(path.lstat())
    os.lseek(row['fd'],0,os.SEEK_SET); digest=hashlib.sha256()
    while block:=os.read(row['fd'],1048576):assert time.monotonic()<END;digest.update(block)
    assert digest.hexdigest()==row['descriptor']['sha256']
witness=write('held-inputs-and-processes.v1.json',{'source_commit':head,'original95':before,'actual_current95':
 [{'descriptor':held[Path(r['descriptor']['path'])]['descriptor'],'epoch':held[Path(r['descriptor']['path'])]['epoch']} for r in before],
 'process_scans':scans,'retained_terminal_pins':[desc(p) for p in (outer_path,Path(outer['original_cli_terminal']['path']),PAIR/'guardian/service_lifecycle.v1.json',PAIR/'guardian/service_authority.v1.json')]})
report={'schema_version':1,'artifact_kind':'vast_independent_cpu04_closed_boundary_review_v1','disposition':'closed_failed_original_with_real_two_arm_outputs',
 'independent_review':True,'source_commit':head,'outer_terminal':desc(outer_path),'cli_terminal':outer['original_cli_terminal'],
 'original_cli_returncode':1,'outer_elapsed_s':outer['elapsed_s'],'outer_timeout':False,'outer_signals':[],
 'original95_before_after_current_full7epochs_equal':True,'witness':witness,'arms':arms,
 'reserve_allocated_bytes':cli['capacity_reservation']['allocated_bytes'],'reserve_released_and_absent':True,
 'guardian':{'owner_process':guardian['owner_process'],'authenticated_stop':True,'original_returncode':0,
  'lifecycle_status':lifecycle['status'],'requests_started':lifecycle['counters']['requests_started'],
  'requests_completed':lifecycle['counters']['requests_completed'],'requests_failed':lifecycle['counters']['requests_failed'],
  'process_and_group_absence_two_actual_scans':True,'cleanup_basis':'retained authenticated lifecycle and original CLI observation; no reviewer daemon query'},
 'blocker':{'file':'scripts/publication_gstreamer_component_runtime_v1.py','line':650,'original_error':cli['primary_error'],
 'correct_existing_definition':'scripts/publication_operational_request_reconciliation_v1.py:266'},
 'hold_release':True,'limits':['Both original native CLI measurements completed0 with nonzero retained six-stream results; final cold pair failed before reconciliation.',
 'No complete all-phase cold identity join, scientific metric re-reduction, component pair acceptance, full qualification/Q4/full-run grant claimed.',
 'Native --rm exact CID absence is retained; no positive native daemon ExitCode/Pid/OOM terminal projection is invented.',
 'Guardian worker-container cleanup remains scoped to retained original authenticated lifecycle/CLI facts; no new daemon query or independent worker CID inspection.',
 'No reviewer tests, model/source/decoder/worker operations.']}
for row in held.values():os.close(row['fd'])
report['reviewer_held_fds_released']=True
review=write('review.v1.json',report);print(json.dumps(review))
