"""Conditional CI-only userns profile, admitted by this job's original denial.

No profile is provisioned from errno alone or historical evidence. The literal
Ubuntu userns rule attaches only to the physically held CPython3.12.3 path.
Privileged commands are fixed and self-bounded; none are run by unit fixtures.
"""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

_spec = importlib.util.spec_from_file_location('ci_profile_diagnostic',
    Path(__file__).with_name('ci_namespace_diagnostic_v1.py'))
_diagnostic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_diagnostic)
EPOCH = ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
IDENTITY = ('st_dev','st_ino','st_mode','st_nlink','st_size','st_uid','st_gid')
PROFILE_NAME = re.compile(r'vast-ci-userns-[0-9a-f]{32}')
KERNEL_PROFILES = '/sys/kernel/security/apparmor/profiles'
PHASE_LIMIT = 64*1024


def _require(predicate, message):
    if not predicate:
        raise RuntimeError(message)


def _epoch(info):
    return [getattr(info,key) for key in EPOCH]


def hold_regular_v1(path, maximum, deadline_ns):
    path=Path(path)
    _require(path.is_absolute() and path.resolve(strict=True)==path,
             'CI policy input path must be physically canonical')
    fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and
                 0<=before.st_size<=maximum and _epoch(path.lstat())==_epoch(before),
                 'CI policy input is not bounded single-link original regular bytes')
        digest=hashlib.sha256();raw=bytearray()
        while True:
            _require(time.monotonic_ns()<deadline_ns,'CI policy input deadline exceeded')
            block=os.read(fd,min(65536,maximum+1-len(raw)))
            if not block:break
            raw.extend(block);digest.update(block)
            _require(len(raw)<=maximum,'CI policy input exceeds original bound')
        identity={'path':str(path),'size_bytes':len(raw),'sha256':digest.hexdigest(),
                  'epoch':_epoch(before),'stat':{key:getattr(before,key) for key in IDENTITY},
                  'raw':bytes(raw)}
        verify_held_v1(path,fd,identity,deadline_ns)
        return fd,identity
    except BaseException:
        os.close(fd)
        raise


def verify_held_v1(path, fd, identity, deadline_ns=None):
    deadline_ns = deadline_ns if deadline_ns is not None else time.monotonic_ns()+20_000_000_000
    _require(Path(path).resolve(strict=True)==Path(path) and
             _epoch(os.fstat(fd))==identity['epoch']==_epoch(Path(path).lstat()),
             'original CI policy input named/held epoch changed')
    digest=hashlib.sha256();offset=0
    while offset<identity['size_bytes']:
        _require(time.monotonic_ns()<deadline_ns,'original CI input rehash deadline exceeded')
        block=os.pread(fd,min(65536,identity['size_bytes']-offset),offset)
        _require(bool(block),'original CI input truncated during rehash')
        digest.update(block);offset+=len(block)
    _require(digest.hexdigest()==identity['sha256'] and
             _epoch(os.fstat(fd))==identity['epoch']==_epoch(Path(path).lstat()),
             'original CI policy input bytes/epoch changed')


def _safe_python(path):
    _require(isinstance(path,str) and re.fullmatch(r'/[A-Za-z0-9_./-]{1,255}',path) and
             all(part not in ('.','..','') for part in path.split('/')[1:]),
             'unsafe exact interpreter attachment')


def profile_bytes_v1(name, python):
    _require(isinstance(name,str) and PROFILE_NAME.fullmatch(name),'unsafe owned CI profile name')
    _safe_python(python)
    return (f'abi <abi/4.0>,\nprofile {name} {python} flags=(unconfined) {{\n  userns,\n}}\n').encode('ascii')


def parser_command_v1(action, fdpath):
    _require(action in ('--add','--remove'),'only original profile add/remove admitted')
    _require(isinstance(fdpath,str) and re.fullmatch(r'/proc/'+str(os.getpid())+r'/fd/[0-9]+',fdpath),
             'parser source is not this original controller held FD')
    return ['/usr/bin/sudo','-n','--','/usr/bin/timeout','--signal=TERM','--kill-after=1s','19s',
            '/usr/sbin/apparmor_parser',action,'--skip-cache','--jobs=0','--',fdpath]


def fixed_root_timeout_budget_v1(command):
    """Only these fixed commands may use the privileged gated capture."""
    if isinstance(command,list) and len(command)==13 and command[8] in ('--add','--remove') and        command==parser_command_v1(command[8],command[-1]):
        return 21_000_000_000  #19s TERM+1s KILL+1s closing within existing cleanup.
    if command==['/usr/bin/sudo','-n','--','/usr/bin/timeout','--signal=TERM','--kill-after=1s','1s',
                  '/usr/bin/cat',KERNEL_PROFILES]:
        return 3_000_000_000
    raise RuntimeError('unknown privileged command shape; no dispatch')


def kernel_profile_present_v1(raw,name):
    _require(len(raw)<=8192 and (not raw or raw.endswith(b'\n')),'kernel profile inventory incomplete/overlimit')
    try:lines=raw.decode('ascii').splitlines()
    except UnicodeError as error:raise RuntimeError('kernel profile inventory not ASCII') from error
    matches=[line for line in lines if line==name or line.startswith(name+' ')]
    _require(not matches or matches==[name+' (unconfined)'],'profile collision/ambiguous enforcement mode')
    return bool(matches)


def join_original_userns_denial_v1(capture,rows,record,python_identity,boot_id,job_start_ns,now_ns):
    """Pure strict join; the caller separately holds/re-reads all original leaves."""
    _require(capture.get('capture_completed') is True and type(capture.get('returncode')) is int and capture.get('returncode')==1 and
             capture.get('failure') is None and not capture.get('timed_out') and
             not capture.get('capture_exceeded') and capture.get('eof')=={'stdout':True,'stderr':True}
             and capture.get('original_group_absent') is True,'original namespace status not a closed ordinary failure')
    _require(job_start_ns<=capture['started_monotonic_ns']<=now_ns<capture['cleanup_deadline_ns'],
             'denial not from the current original job interval')
    owner=capture.get('owner') or {};pid=owner.get('pid');python=python_identity['path']
    _require(type(pid) is int and pid>0 and owner.get('boot_id')==boot_id and
             owner.get('executable_realpath')==python and owner.get('executable_stat')==python_identity['stat'] and
             owner.get('uid')==os.getuid() and owner.get('gid')==os.getgid(),
             'denial owner/boot/executable physical identity does not join')
    _require(isinstance(rows,list) and 0<len(rows)<=32 and all(isinstance(r,dict) and
             r.get('original_pid')==pid for r in rows),'original syscall rows foreign/overlimit')
    def one(event,syscall=None):
        found=[r for r in rows if r.get('event')==event and (syscall is None or r.get('syscall')==syscall)]
        _require(len(found)==1,'missing/ambiguous original '+event+':'+str(syscall))
        return found[0]
    ready=one('original_ready');started=one('syscall_started','unshare');entered=one('syscall_completed','unshare')
    failed=one('syscall_failed');opened=one('syscall_started','open')
    _require(ready.get('executable')==python and ready.get('label')==
             {'path':'/proc/self/attr/current','value':'unconfined'},'original executable label not unconfined')
    _require(all(r.get('pid')==pid for r in (started,entered,opened,failed)) and
             started.get('flags')==entered.get('flags')==268435456 and
             started['monotonic_ns']==entered['monotonic_ns'] and
             ready['monotonic_ns']<=started['monotonic_ns']<=entered['terminal_monotonic_ns']<=
             opened['monotonic_ns']==failed['monotonic_ns']<=failed['terminal_monotonic_ns'] and
             opened.get('path')==failed.get('path')=='/proc/self/setgroups' and
             failed.get('syscall')=='open' and failed.get('errno')==13 and
             failed.get('stock_tolerated_missing_setgroups') is False,
             'original unshare/setgroups operation/chronology does not join')
    _require(isinstance(record,dict) and record.get('_TRANSPORT')=='kernel' and
             record.get('_BOOT_ID')==boot_id.replace('-',''),'original kernel record boot/transport mismatch')
    message=record.get('MESSAGE','')
    _require(isinstance(message,str),'original kernel message not text')
    for key,value in [('apparmor','DENIED'),('operation','capable'),('class','cap'),
                      ('profile','unprivileged_userns'),('comm','python3.12'),('capname','sys_admin')]:
        _require(re.findall(r'\b'+key+r'="([^"]*)"',message)==[value],'original kernel '+key+' mismatch')
    _require(re.findall(r'\bpid=([0-9]+)',message)==[str(pid)] and
             re.findall(r'\bcapability=([0-9]+)',message)==['21'],'original denied PID/capability mismatch')
    match=re.search(r'\baudit\(([0-9]+)\.([0-9]{3}):[0-9]+\)',message)
    _require(match is not None,'original audit event wall timestamp missing')
    audit_ns=(int(match[1])*1000+int(match[2]))*1_000_000
    try:wall_ns=int(record['__REALTIME_TIMESTAMP'])*1000;mono_ns=int(record['__MONOTONIC_TIMESTAMP'])*1000
    except (KeyError,ValueError,TypeError) as error:raise RuntimeError('original kernel clocks missing') from error
    _require(capture['started_wall_time_ns']<=wall_ns<=capture['terminal_wall_time_ns'] and
             started['wall_time_ns']-2_000_000<=audit_ns<=failed['terminal_wall_time_ns']+2_000_000 and
             started['monotonic_ns']-2_000_000<=mono_ns<=failed['terminal_monotonic_ns']+2_000_000,
             'original kernel denial outside exact syscall/clock interval')
    return {'pid':pid,'boot_id':boot_id,'python':python,'initial_label':'unconfined',
            'failed_operation':'open:/proc/self/setgroups','denied_capability':'sys_admin',
            'denied_profile':'unprivileged_userns','audit_wall_time_ns':audit_ns,
            'wall_clock_quantization_allowance_ns':2_000_000}


def _decode(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            _require(key not in result,'duplicate original JSON key');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique)


def _save(path,value,maximum):
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    _require(len(raw)<=maximum,'CI policy metadata exceeds bounded reserve')
    with path.open('xb') as stream:
        _require(stream.write(raw)==len(raw),'incomplete original CI policy metadata write')
        stream.flush();os.fsync(stream.fileno())


def _descriptor(identity):
    return {key:identity[key] for key in ('path','size_bytes','sha256','epoch','stat')}


def observe_suite_profile_v1(expected_profile=None):
    actual=_diagnostic._label()
    if expected_profile is not None:
        _require(isinstance(expected_profile,str) and re.fullmatch(
                 r'vast-ci-userns-[0-9a-f]{32} \(unconfined\)',expected_profile),'unsafe expected CI profile')
        _require(actual.get('value')==expected_profile,'original suite child AppArmor label mismatch/unavailable')
    return {'pid':os.getpid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'executable':str(Path(sys.executable).resolve(strict=True)),
            'expected_profile':expected_profile,'actual_label':actual}


@contextmanager
def held_ci_userns_profile_v1(*,diagnostic_dir,diagnostic,python,output_dir,job_start_ns,absolute_deadline_ns):
    """One original add, full unchanged suite, then owned-only remove; no retry."""
    report={'status':'not_required','attempted':False,'load_verified':False,'unload_verified':False}
    result={'expected_profile':None,'report':report,'suite_deadline_ns':absolute_deadline_ns}
    if diagnostic.get('namespace_succeeded') is True:
        yield result
        return
    output=Path(output_dir);pins=[];failure=None;owns_loaded=False;name=None;profile_identity=None
    finalization_deadline=absolute_deadline_ns
    source=Path(diagnostic_dir).resolve(strict=True)
    def hold(path,maximum,deadline):
        fd,identity=hold_regular_v1(path,maximum,deadline);pins.append((Path(path),fd,identity))
        return fd,identity
    def verify(deadline=absolute_deadline_ns):
        for path,fd,identity in pins:verify_held_v1(path,fd,identity,deadline)
    def run(command,path,deadline,execution_s):
        _require(time.monotonic_ns()<deadline,'original policy command deadline already elapsed')
        verify(deadline)
        minimum=fixed_root_timeout_budget_v1(command)
        _require(deadline-time.monotonic_ns()>=minimum,
                 'original root command self-timeout plus closing reserve does not fit after verify')
        capture=_diagnostic.capture_original_child(_diagnostic._gated_execv_argv(python,command),path,
            deadline,execution_s=execution_s,cleanup_s=min(10,max(.001,(deadline-time.monotonic_ns())/1e9)),
            start_gate=True,raw_limit=8192,report_limit=8192,minimum_start_budget_ns=minimum)
        verify(deadline)
        return capture
    def inventory(path,deadline):
        command=['/usr/bin/sudo','-n','--','/usr/bin/timeout','--signal=TERM','--kill-after=1s','1s',
                 '/usr/bin/cat',KERNEL_PROFILES]
        capture=run(command,path,deadline,min(2,max(.001,(deadline-time.monotonic_ns())/1e9)))
        _require(capture['capture_completed'] and capture['returncode']==0,'original kernel profile inventory unavailable/failed')
        raw=(path/'stdout.raw').read_bytes()
        _require(len(raw)<=8192,'original kernel profile inventory exceeds bound')
        return raw
    try:
        _safe_python(python)
        _require(sys.version_info[:3]==(3,12,3) and sys.implementation.name=='cpython' and
                 str(Path(sys.executable).resolve(strict=True))==python,'profile requires original canonical CPython3.12.3')
        _,py_identity=hold(Path(python),32*1024*1024,absolute_deadline_ns)
        _require(not (py_identity['stat']['st_mode']&0o022) and os.access(python,os.X_OK),
                 'original interpreter is writable/unsupported executable')
        documents={}
        for rel,limit in [('capture.json',_diagnostic.REPORT_LIMIT),('stdout.raw',_diagnostic.RAW_LIMIT),
                          ('kernel-denial.json',_diagnostic.DENIAL_LIMIT),
                          ('kernel-query/capture.json',_diagnostic.REPORT_LIMIT),
                          ('kernel-query/stdout.raw',_diagnostic.RAW_LIMIT)]:
            _,documents[rel]=hold(source/rel,limit,absolute_deadline_ns)
        capture=_decode(documents['capture.json']['raw'])
        rows=[_decode(line) for line in documents['stdout.raw']['raw'].splitlines()]
        denial=_decode(documents['kernel-denial.json']['raw']);query=_decode(documents['kernel-query/capture.json']['raw'])
        records=[_decode(line) for line in documents['kernel-query/stdout.raw']['raw'].splitlines()]
        _require(capture.get('owner')==diagnostic.get('owner') and
                 capture.get('started_monotonic_ns')==diagnostic.get('started_monotonic_ns'),
                 'returned diagnostic differs from original physical capture')
        expected=[python,'-I','-B',str(Path(_diagnostic.__file__).resolve()),'--worker','--start-gate-fd']
        _require(capture.get('argv',[])[:-1]==expected and str(capture['argv'][-1]).isdigit(),
                 'original namespace argv is not the unchanged stock diagnostic')
        _require(query.get('capture_completed') is True and query.get('returncode')==0 and
                 query.get('failure') is None and not query.get('timed_out') and not query.get('capture_exceeded') and
                 query.get('original_group_absent') is True and query.get('eof')=={'stdout':True,'stderr':True},
                 'original kernel query has no complete original terminal')
        for observed in (capture,query):
            owner=observed.get('owner') or {}
            _require(owner.get('ppid')==os.getpid() and owner.get('pgid')==owner.get('pid') and
                     owner.get('boot_id')==Path('/proc/sys/kernel/random/boot_id').read_text().strip() and
                     owner.get('executable_realpath')==python and owner.get('executable_stat')==py_identity['stat'] and
                     owner.get('uid')==os.getuid() and owner.get('gid')==os.getgid(),
                     'original diagnostic/query does not belong to current interpreter/controller')
        command=['/usr/bin/journalctl','--dmesg','--since',
                 '@'+str(capture['started_wall_time_ns']//1_000_000_000-1),'--until',
                 '@'+str(capture['terminal_wall_time_ns']//1_000_000_000+1),'--no-pager','--output=json',
                 '--lines=32','--case-sensitive=no','--grep=apparmor=.*DENIED.*(userns|unshare|capable)']
        _require(query.get('argv',[])[:-2]==_diagnostic._gated_execv_argv(python,command) and
                 query['argv'][-2]=='--start-gate-fd' and str(query['argv'][-1]).isdigit() and
                 query['started_monotonic_ns']>=capture['started_monotonic_ns'] and
                 query['started_wall_time_ns']>=capture['terminal_wall_time_ns'] and
                 query['terminal_wall_time_ns']<=time.time_ns(),
                 'original kernel query argv/time not the fixed current diagnostic')
        pid=(capture.get('owner') or {}).get('pid')
        joined=[entry.get('original_journal_record') for entry in denial.get('records',[]) if
                isinstance(entry,dict) and isinstance(entry.get('original_journal_record'),dict) and
                _diagnostic._relevant_original_denial(entry['original_journal_record'].get('MESSAGE'),pid)]
        _require(len(joined)==1 and records.count(joined[0])==1,'original denial absent/ambiguous/not in raw kernel output')
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        proof=join_original_userns_denial_v1(capture,rows,joined[0],py_identity,boot,job_start_ns,time.monotonic_ns())
        output.mkdir(parents=True,mode=0o700,exist_ok=False)
        _save(output/'joined-denial.json',{'join':proof,'inputs':[
            {key:identity[key] for key in ('path','size_bytes','sha256')}
            for _,_,identity in pins]},3072)
        name='vast-ci-userns-'+uuid.uuid4().hex;raw=profile_bytes_v1(name,python)
        _require(len(raw)<=512,'literal CI profile exceeds512 bytes')
        path=output/'owned.profile'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
        try:_require(os.write(fd,raw)==len(raw),'incomplete original profile write');os.fsync(fd)
        finally:os.close(fd)
        profile_fd,profile_identity=hold(path,512,absolute_deadline_ns)
        report.update(status='provisioning',attempted=True,name=name,profile=_descriptor(profile_identity))
        load_start=time.monotonic_ns();load_execution=min(absolute_deadline_ns,load_start+20_000_000_000)
        load_deadline=min(absolute_deadline_ns,load_execution+10_000_000_000)
        finalization_deadline=load_deadline
        report['load_phase']={'started_monotonic_ns':load_start,'execution_deadline_ns':load_execution,
                              'cleanup_deadline_ns':load_deadline}
        before=inventory(output/'load-before',load_execution)
        _require(not kernel_profile_present_v1(before,name),'owned profile name already exists')
        _require(not any(line.startswith(python.encode()+b' ') for line in before.splitlines()),
                 'exact interpreter already has a named-path profile collision')
        command=parser_command_v1('--add',f'/proc/{os.getpid()}/fd/{profile_fd}')
        _save(output/'load-intent.json',{'argv':command,'profile':_descriptor(profile_identity),
              'unique_name_absent_before_original_add':True},2048)
        load_error=None;load=None
        try:
            load=run(command,output/'load',load_deadline,
                     min(20,max(.001,(load_execution-time.monotonic_ns())/1e9)))
            report['load_terminal']={key:load[key] for key in ('returncode','capture_completed','timed_out','failure')}
        except BaseException as error:
            load_error=error;report['load_capture_failure']=f'{type(error).__name__}: {error}'[:512]
        try:after=inventory(output/'load-after',load_deadline)
        except BaseException as error:
            if load_error is not None:
                load_error.add_note('original post-add ownership observation failed: '+str(error))
                raise load_error
            raise
        present=kernel_profile_present_v1(after,name)
        # Ownership and acceptance are separate. This exclusive random name was
        # absent immediately before one literal held-FD add; its exact positive
        # post-state establishes an owned effect even if original capture failed.
        # A preexisting/colliding or unavailable state never admits removal.
        owns_loaded=present
        if load_error is not None:raise load_error
        _require(load['capture_completed'] and load['returncode']==0 and not load['timed_out'] and
                 owns_loaded and time.monotonic_ns()<load_execution,
                 'original profile load/enforcement not verified within20s')
        report.update(status='active',load_verified=True)
        result.update(expected_profile=name+' (unconfined)',suite_deadline_ns=absolute_deadline_ns-30_000_000_000)
        _require(time.monotonic_ns()<result['suite_deadline_ns'],'no original job budget for suite plus owned profile unload')
        finalization_deadline=absolute_deadline_ns
        yield result
        verify()
    except BaseException as error:
        failure=error;report.update(status='failed',failure=f'{type(error).__name__}: {error}'[:512])
        raise
    finally:
        cleanup_error=None
        try:
            if owns_loaded:
                began=time.monotonic_ns();execution=min(absolute_deadline_ns,began+20_000_000_000)
                deadline=min(absolute_deadline_ns,execution+10_000_000_000)
                finalization_deadline=deadline
                report['unload_phase']={'started_monotonic_ns':began,'execution_deadline_ns':execution,
                                        'cleanup_deadline_ns':deadline}
                verify(deadline)
                removed=run(parser_command_v1('--remove',f'/proc/{os.getpid()}/fd/{profile_fd}'),
                            output/'unload',deadline,min(20,max(.001,(execution-time.monotonic_ns())/1e9)))
                report['unload_terminal']={key:removed[key] for key in ('returncode','capture_completed','timed_out','failure')}
                absent=not kernel_profile_present_v1(inventory(output/'unload-after',deadline),name)
                _require(removed['capture_completed'] and removed['returncode']==0 and absent and
                         time.monotonic_ns()<execution,'original owned profile removal/absence not verified within20s')
                report['unload_verified']=True
                if failure is None:report['status']='completed'
            elif report['attempted']:
                report['profile_cleanup']='no owned successful load observed; no foreign/ambiguous profile removed'
            verify(finalization_deadline)
        except BaseException as error:
            cleanup_error=error;report.update(status='failed',cleanup_failure=f'{type(error).__name__}: {error}'[:512])
        finally:
            close_errors=[]
            for _,fd,_ in reversed(pins):
                try:os.close(fd)
                except OSError as error:close_errors.append(f'{type(error).__name__}: {error}'[:128])
            report['held_fds_released']=not close_errors
            if close_errors:
                cleanup_error=cleanup_error or RuntimeError('original profile input FD retirement failed')
                report.update(status='failed',close_failures=close_errors[:4])
            if output.exists():
                try:
                    load_bytes=sum(p.stat().st_size for folder in ('load-before','load','load-after')
                                   for p in (output/folder).glob('*') if p.is_file())
                    unload_bytes=sum(p.stat().st_size for folder in ('unload','unload-after')
                                     for p in (output/folder).glob('*') if p.is_file())
                    _require(load_bytes+3072+512+4096+2048<=PHASE_LIMIT and unload_bytes+4096<=PHASE_LIMIT,
                             'CI profile load/unload facts exceed original64KiB phase bound')
                    _require(time.monotonic_ns()<finalization_deadline,
                             'original profile cleanup deadline reached before receipt-last')
                    _save(output/'profile-lifecycle.json',report,4096)
                    if time.monotonic_ns()>=finalization_deadline:
                        report.update(status='failed',late_finalization=True)
                        with (output/'late-profile.failure').open('xb') as stream:
                            stream.write(b'original profile receipt-last crossed original cleanup/job deadline\n')
                            stream.flush();os.fsync(stream.fileno())
                        raise RuntimeError('original profile receipt-last crossed original cleanup/job deadline')
                except BaseException as error:
                    report.update(status='failed',finalization_failure=f'{type(error).__name__}: {error}'[:240])
                    cleanup_error=cleanup_error or error
            if cleanup_error is not None:
                if failure is not None:failure.add_note('CI owned profile cleanup failed: '+str(cleanup_error))
                else:raise cleanup_error
