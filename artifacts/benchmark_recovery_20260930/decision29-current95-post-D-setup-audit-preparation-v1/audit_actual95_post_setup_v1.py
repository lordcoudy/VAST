"""One read-only120+10s Linux full-SHA/seven-epoch custody join after original CI setup."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
SETUP=BASE/'decision29-successor-ci-D-preparation-v1'
OUT=HERE/'original-audit-attempt01'
BENCH=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
B='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
C='3c025b29b3c1d5275c2ec693410e4b83700583de'
MANIFEST=BASE/'decision28-current95-preparation-v1/decision28-current95-original-attempt01/current95-inputs.v1.json'
START=time.monotonic();END=START+120;HARD=END+10
held={};directories={};first=None;errors=[];error_overflow=0;closes=[];close_errors=[]
output_owned=False;fd_before=fd_after=fd_final=None;reviewer=None;rows=[];after=[];scans=[];original_owners=[]
MAX_FILE=16*1048576;MAX_INPUT95=64*1048576;MAX_DOC=1048576;MAX_ERRORS=64

def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
def clock(cleanup=False):
    if time.monotonic()>=(HARD if cleanup else END):raise TimeoutError('post-setup95 original120+10s bound')
def fail(phase,exc,closing=False):
    global first,error_overflow
    row={'phase':phase,'type':type(exc).__name__,'message':str(exc)[:4096]}
    if first is None:first=row
    if len(errors)<MAX_ERRORS:errors.append(row)
    else:error_overflow+=1
    if closing and len(close_errors)<MAX_ERRORS:close_errors.append(row)
def fd_count():return len(os.listdir('/proc/self/fd'))
def owner(pid):
    p=Path('/proc',str(pid));f=(p/'stat').read_text().rsplit(')',1)[1].split()
    s=p.stat()
    return {'pid':pid,'ppid':int(f[1]),'pgid':int(f[2]),'session':int(f[3]),'startticks':int(f[19]),
            'uid':s.st_uid,'gid':s.st_gid,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def hold_ancestors(path):
    for parent in reversed(path.parents):
        clock();assert parent.resolve(strict=True)==parent
        if parent in directories:continue
        directories[parent]={'fd':None,'identity':None}
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        directories[parent]['fd']=fd
        s=os.fstat(fd);assert stat.S_ISDIR(s.st_mode) and identity(s)==identity(parent.lstat())
        directories[parent]['identity']=identity(s)
def digest(path,fd,cleanup=False):
    clock(cleanup);s=os.fstat(fd);before=epoch(s)
    assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and 0<=s.st_size<=MAX_FILE
    assert path.resolve(strict=True)==path and before==epoch(path.lstat())
    h=hashlib.sha256();size=0;offset=0
    while block:=os.pread(fd,65536,offset):
        clock(cleanup);size+=len(block);offset+=len(block);assert size<=MAX_FILE;h.update(block)
    assert size==s.st_size and before==epoch(os.fstat(fd))==epoch(path.lstat())
    return {'descriptor':{'path':str(path),'size_bytes':size,'sha256':h.hexdigest()},'epoch':before}
def hold(path,expected=None,expected_epoch=None):
    path=Path(path);assert path.is_absolute() and path.resolve(strict=True)==path
    if path not in held:
        hold_ancestors(path);assert len(held)<128
        held[path]={'fd':None,'before':None}
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        held[path]['fd']=fd
        held[path]['before']=digest(path,fd)
    value=held[path]['before']
    if expected is not None:assert value['descriptor']=={k:expected[k] for k in ('path','size_bytes','sha256')}
    if expected_epoch is not None:assert value['epoch']==expected_epoch
    return value
def doc(path,size,sha):
    value=hold(path,{'path':str(path),'size_bytes':size,'sha256':sha});assert value['descriptor']['size_bytes']<=MAX_DOC
    raw=os.pread(held[path]['fd'],size+1,0);assert len(raw)==size and hashlib.sha256(raw).hexdigest()==sha
    return json.loads(raw)
def scan_originals(owners):
    result={'started_monotonic_ns':time.monotonic_ns(),'members':[],'errors':[],'error_overflow':0,'member_overflow':0,
            'pids_absent':{},'vanished_during_scan':0}
    ids={r['pid'] for r in owners};groups={r['pgid'] for r in owners}
    def problem(phase,exc):
        if len(result['errors'])<MAX_ERRORS:result['errors'].append({'phase':phase,'type':type(exc).__name__,'message':str(exc)[:240]})
        else:result['error_overflow']+=1
    try:clock(True);entries=os.listdir('/proc')
    except BaseException as exc:problem('enumeration',exc);entries=[]
    for name in entries:
        if time.monotonic()>=HARD:problem('deadline',TimeoutError('original scan cleanup bound'));break
        if not name.isdigit():continue
        try:
            clock(True);f=Path('/proc',name,'stat').read_text().rsplit(')',1)[1].split()
            if int(name) in ids or int(f[2]) in groups:
                if len(result['members'])<MAX_ERRORS:result['members'].append({'pid':int(name),'pgid':int(f[2]),'startticks':int(f[19]),'state':f[0]})
                else:result['member_overflow']+=1
        except (FileNotFoundError,ProcessLookupError):result['vanished_during_scan']+=1
        except BaseException as exc:problem('pid:'+name,exc)
    for pid in sorted(ids):
        if time.monotonic()>=HARD:problem('exact-pid-deadline',TimeoutError('original scan cleanup bound'));break
        try:clock(True);os.stat('/proc/'+str(pid));result['pids_absent'][str(pid)]=False
        except (FileNotFoundError,ProcessLookupError):result['pids_absent'][str(pid)]=True
        except BaseException as exc:result['pids_absent'][str(pid)]=None;problem('exact-pid:'+str(pid),exc)
    result['terminal_monotonic_ns']=time.monotonic_ns()
    return result
def save(name,value,maximum=MAX_DOC):
    clock(True);raw=json.dumps(value,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n';assert len(raw)<=maximum
    with (OUT/name).open('xb') as stream:assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

try:
    assert os.getuid()==os.getgid()==1000 and sys.version_info[:3]==(3,12,3) and sys.implementation.name=='cpython'
    fd_before=fd_count();reviewer=owner(os.getpid())
    assert not os.path.lexists(OUT) and HERE.resolve(strict=True)==HERE
    OUT.mkdir(mode=0o700);output_owned=True
    hold(Path(__file__).resolve(strict=True))
    recipe=doc(SETUP/'recipe.bound.v1.json',11220,'e8df0e735c27bd282eee9692144fb0e42ab7491259bedb2626e1714fe64865c5')
    manifest=doc(MANIFEST,44579,'3c9b7eca9c9b33e01624764b7ccfccb9d748c3ac9623389f7e12447f0085b150')
    capture=doc(SETUP/'original-setup.capture-terminal.v1.json',4639,'7d3ed43ad2ae5d4a60b8ae2e6ae47ae36338f3b147cf39a8ca278e280a8e622c')
    setup=doc(SETUP/'original-setup-attempt01/execution.v1.json',29015,'96ed65f0d6e59acf5ee75400b43d11b5312741e446883fcdb64cf93d041043e4')
    assert recipe['source_commit']==C and recipe['benchmark_root_commit_untouched']==B and C!=B
    assert recipe['current95_manifest']==held[MANIFEST]['before']['descriptor']
    assert manifest['source_commit']==B and manifest['project_root']==str(BENCH) and manifest['all_collection_fds_released'] is True
    assert manifest['composition']=={'role_documents':6,'fresh_project_sources':87,'canonical_interpreter':1,'exact_current_controller':1,'unique_total':95}
    assert manifest['fresh_stock_closure_descriptor']==recipe['fresh_stock_closure_descriptor'] and manifest['current_controller_descriptor']==recipe['current_controller_descriptor']
    assert capture['returncode']==0 and capture['failure'] is None and capture['signals']==[] and capture['capture_fds_closed'] is True
    assert capture['original_child_reaped'] is True and capture['late_failure_absent'] is True and capture['elapsed_s']<310
    assert capture['source_before']==capture['source_after']
    hold(capture['source_before']['path'],capture['source_before'],capture['source_before']['epoch7'])
    for channel in ('stdout','stderr'):hold(capture[channel]['path'],capture[channel],capture[channel]['epoch7'])
    assert setup['source_commit']==C and setup['status']=='prepared_exact_source_and_prerequisites'
    assert setup['benchmark_root_commit']==setup['benchmark_root_head_unchanged']==B and setup['benchmark_root_identity_unchanged'] is True
    assert setup['ci_checkpoint_distinct_from_benchmark'] is True and setup['benchmark95_input_epochs_unchanged'] is True
    assert setup['held95_fds_released'] is True and setup['current95_manifest_fd_released'] is True and setup['close_errors']==[]
    assert setup['raw_committed_bytes_equal'] is True and setup['tracked_count']==5577 and setup['tracked_bytes']==280799517
    assert len(setup['commands'])==14 and all(r['returncode']==0 and r['child_reaped'] is True for r in setup['commands'])
    assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in setup['command_process_scans']+capture['process_scans'])
    original_owners=[capture[k] for k in ('capture_owner','timeout_owner','setup_owner')]+[r['owner'] for r in setup['commands']]
    assert len({r['pid'] for r in original_owners})==17 and all(r['uid']==r['gid']==1000 and r['boot_id']==reviewer['boot_id'] for r in original_owners)
    for command in (setup['commands'][0],setup['commands'][-1]):
        row=command['stdout'];hold(row['path'],row,row['epoch7'])
        assert os.pread(held[Path(row['path'])]['fd'],row['size_bytes']+1,0)==(B+'\n').encode()
    rows=manifest['actual_current95'];assert len(rows)==len({r['descriptor']['path'] for r in rows})==95
    assert sum(r['descriptor']['size_bytes'] for r in rows)<=MAX_INPUT95
    assert recipe['benchmark_root_untouched']==str(BENCH) and BENCH.resolve(strict=True)==BENCH
    for row in rows:hold(row['descriptor']['path'],row['descriptor'],row['epoch'])
    interpreter=Path(sys.executable).resolve(strict=True)
    assert str(interpreter) in {r['descriptor']['path'] for r in rows}
    assert held[interpreter]['before']['descriptor']=={k:setup['canonical_python'][k] for k in ('path','size_bytes','sha256')}
    for late in (SETUP/'original-setup-attempt01/late-failure.v1.json',):assert not os.path.lexists(late)
except BaseException as exc:fail('original-metadata-and-current95-acquisition',exc)
finally:
    for path,row in held.items():
        try:
            assert row['fd'] is not None and row['before'] is not None
            value=digest(path,row['fd'],True);assert value==row['before'];after.append(value)
        except BaseException as exc:fail('rehash:'+str(path),exc)
    for path,row in directories.items():
        try:clock(True);assert row['fd'] is not None and row['identity'] is not None and row['identity']==identity(os.fstat(row['fd']))==identity(path.lstat()) and path.resolve(strict=True)==path
        except BaseException as exc:fail('ancestor:'+str(path),exc)
    for kind,items in (('leaf',held.items()),('ancestor',reversed(list(directories.items())))):
        for path,row in items:
            fd=row['fd'];released=fd is None
            if fd is not None:
                try:os.close(fd);row['fd']=None;released=True
                except BaseException as exc:fail('close-'+kind+':'+str(path),exc,True)
            closes.append({'kind':kind,'path':str(path),'acquired':fd is not None,'released':released})
    try:fd_after=fd_count();assert fd_before is not None and fd_after==fd_before
    except BaseException as exc:fail('FD-baseline-after-independent-closes',exc)
    if original_owners:
        for _ in range(2):
            observed=scan_originals(original_owners);scans.append(observed)
            if observed['members'] or observed['errors'] or observed['error_overflow'] or observed['member_overflow'] or not all(v is True for v in observed['pids_absent'].values()):fail('fresh-original-process-absence',RuntimeError('uncertain/present original PID/group'))
    else:fail('fresh-original-process-absence',RuntimeError('original owners unavailable; absence not proved'))
    result={'schema_version':1,'artifact_kind':'post_setup_original95_full_sha_and_seven_epoch_custody_v1',
       'reviewable':first is None,'blocking_findings':[] if first is None else [first],'first_error':first,'errors':errors,'error_overflow':error_overflow,
       'reviewer':reviewer,'CI_checkpoint_D':C,'benchmark_checkpoint_B':B,'actual95_count':len(rows),
       'actual95_full_SHA_and_original_Linux_seven_epochs_current_equal':len(rows)==95 and all(Path(r['descriptor']['path']) in held and held[Path(r['descriptor']['path'])]['before']==r for r in rows),
       'before':[r['before'] for r in held.values() if r['before'] is not None],'after':after,
       'all_source_and_metadata_before_after_equal':len(after)==len(held),'independent_close_attempts':closes,'close_errors':close_errors,
       'all_read_handles_released':all(row['fd'] is None for row in held.values()) and all(row['fd'] is None for row in directories.values()),
       'fd_before':fd_before,'fd_after':fd_after,'fresh_process_scans':scans,'elapsed_s':time.monotonic()-START,
       'acceptance_requires_original_tool_rc0_and_final_FD_baseline_and_no_companion':True,
       'limits':['Read-only95 descriptors/full bytes and original Linux epochs plus exact sealed setup metadata. No Git/engine/model/native/test/setup replay or stock loader execution.',
                 'Original setup raw5577/280799517 equality is retained metadata, not independently repeated raw Git. No new benchmark HEAD query or CI success is claimed.',
                 'Original timeout initial argv empty remains unobserved; actual PID/startticks/boot/UID/GID/process group are retained and must be absent twice.'],
       'hardware_acceptance':False,'full_ci_acceptance':False}
    ref=None
    if output_owned:
        try:ref=save('review.v1.json',result)
        except BaseException as exc:fail('exclusive-final-review-publication',exc)
    try:clock();fd_final=fd_count();assert fd_before is not None and fd_final==fd_before
    except BaseException as exc:fail('receipt-last-deadline-or-FD-baseline',exc)
    if first is not None and output_owned:
        try:save('failure-companion.v1.json',{'reviewable':False,'first_error':first,'original_review':ref,'fd_before':fd_before,'fd_final':fd_final,'elapsed_s':time.monotonic()-START},65536)
        except BaseException as exc:fail('failure-companion-publication',exc)
    try:print(json.dumps({'review':ref,'first_error':first,'reviewable':first is None,'fd_before':fd_before,'fd_final':fd_final,'elapsed_s':time.monotonic()-START}),flush=True)
    except BaseException as exc:
        was_clean=first is None;fail('final-stdout-write',exc)
        if was_clean and output_owned:
            try:save('failure-companion.v1.json',{'reviewable':False,'first_error':first,'original_review':ref},65536)
            except BaseException as companion_error:fail('final-stdout-failure-companion',companion_error)
    try:clock();assert fd_count()==fd_before
    except BaseException as exc:
        was_clean=first is None;fail('final-stdout-deadline-or-FD-baseline',exc)
        if was_clean and output_owned:
            try:save('failure-companion.v1.json',{'reviewable':False,'first_error':first,'original_review':ref},65536)
            except BaseException as companion_error:fail('final-failure-companion',companion_error)
raise SystemExit(0 if first is None else 1)
