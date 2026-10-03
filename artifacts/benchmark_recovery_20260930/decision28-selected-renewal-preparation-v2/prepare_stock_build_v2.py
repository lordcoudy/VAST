"""Prepare immutable resource-closure successor; never import or execute it."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
OLD = ROOT/'artifacts/benchmark_recovery_20260930/decision28-selected-renewal-preparation-v1/run_original_selected_build_ext4_v1.py'
LEGACY = ROOT/'artifacts/benchmark_recovery_20260930/selected-gstreamer-image-schema-preparation-v1/run_selected_build_v1.py'
OLD_PREP = OLD.parent/'preparation.v1.json'
OLD_PEER = ROOT/'artifacts/benchmark_recovery_20260930/decision28-selected-renewal-independent-review-v1/review.v1.json'

def descriptor(path):
    raw = path.read_bytes()
    return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

assert descriptor(OLD)['sha256']=='44b0f2236379704f5e7f71ad15c1abeaeb7682ee877b096a7e8de45dd3fb9639'
assert descriptor(OLD_PREP)['sha256']=='84320fb54fa2ee5603c7b6f066970e70a100f4579737856bd9683841aace01ff'
assert descriptor(OLD_PEER)['sha256']=='b4fe14c8207672fc1f7492f0a50e3d9cba19b52110f908707cf19788986e5b91'
source = OLD.read_text(encoding='utf-8')
original_source = source
replacements = []

def replace(before, after, reason):
    global source
    assert source.count(before)==1, reason
    source = source.replace(before,after)
    replacements.append({'before':before,'after':after,'reason':reason})

def replace_function(name, after, reason):
    node = next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
    lines = source.splitlines(keepends=True)
    before = ''.join(lines[node.lineno-1:node.end_lineno])
    replace(before,after.strip()+'\n',reason)

replace('image_id = None\n','''image_id = None
error_records = []
error_record_overflow = 0
fd_before = None
fd_after = None
socket = None
socket_epoch = None

def record_error(phase, exc):
    global failure, error_record_overflow
    text = f'{type(exc).__name__}: {exc}'
    if failure is None:
        failure = text
    if len(error_records) < 64:
        error_records.append({'phase':phase,'error':text[:4096],
            'error_sha256':hashlib.sha256(text.encode()).hexdigest(),'at_ns':time.time_ns()})
    else:
        error_record_overflow += 1
    return text

def fd_count():
    return len(os.listdir('/proc/self/fd'))

def scan_original_group(original, cleanup_deadline):
    observed = {'original_pid':original['pid'],'original_pgid':original['pgid'],
        'original_startticks':original.get('startticks'),'original_pid_identity':'absent',
        'members':[],'errors':[],'error_overflow':0,'vanished_during_scan':0,
        'started_at_ns':time.time_ns()}
    def scan_error(phase, exc):
        if len(observed['errors']) < 64:
            observed['errors'].append({'phase':phase,'error':f'{type(exc).__name__}: {exc}'[:4096]})
        else:
            observed['error_overflow'] += 1
    try:
        entries = os.listdir('/proc')
    except BaseException as exc:
        scan_error('enumeration',exc)
        entries = []
    for entry in entries:
        if not entry.isdigit():
            continue
        if time.monotonic() >= min(DEADLINE,cleanup_deadline):
            scan_error('deadline',TimeoutError('original bounded cleanup deadline during group scan'))
            break
        try:
            parts = Path('/proc',entry,'stat').read_text().rsplit(')',1)[1].split()
            pid = int(entry)
            pgid = int(parts[2])
            startticks = int(parts[19])
            if pid == original['pid']:
                observed['original_pid_identity'] = (
                    'original_present' if startticks==original.get('startticks') else 'different_startticks')
            if pgid == original['pgid']:
                observed['members'].append({'pid':pid,'startticks':startticks,'state':parts[0]})
        except (FileNotFoundError,ProcessLookupError):
            observed['vanished_during_scan'] += 1
        except BaseException as exc:
            scan_error('pid:'+entry,exc)
    observed['finished_at_ns'] = time.time_ns()
    return observed
''','sticky first-error latch, actual FD counts, and explicit independent process observations')

replace_function('physical',r'''
def physical(path, late_metadata=False):
    p = Path(path); before = p.lstat(); digest = hashlib.sha256()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and not p.is_symlink()
    if late_metadata:
        assert before.st_size <= 65536, 'bounded final failure companion'
    stream=None;primary=None
    try:
        stream=p.open('rb')
        while block := stream.read(1048576):
            if not late_metadata:
                assert time.monotonic() < DEADLINE, 'whole original build/capture deadline'
            digest.update(block)
    except BaseException as exc:
        primary=exc;record_error('physical:'+str(p),exc)
    finally:
        if stream is not None:
            try:stream.close()
            except BaseException as exc:
                record_error('physical_close:'+str(p),exc)
                if primary is None:primary=exc
    if primary is not None:
        raise primary
    assert epoch(before) == epoch(p.lstat()), 'physical input changed while hashing'
    return {'path':str(p),'size_bytes':before.st_size,'sha256':digest.hexdigest()}
''','default source full hash/7-epoch remains; only <=64KiB nonauthorizing final metadata may be verified after deadline')

replace_function('pin',r'''
def pin(path):
    p=Path(path).resolve(strict=True)
    row={'descriptor':None,'epoch':None,'fd':None}
    pins.append(row)
    row['fd']=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    row['descriptor']=physical(p)
    row['epoch']=epoch(os.fstat(row['fd']))
    assert row['epoch']==epoch(p.lstat())
    return row
''','register partially acquired source FD for protected operation-wide retirement without replacing its original acquisition error')

replace_function('write',r'''
def write(name,value,late_metadata=False):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    assert len(raw) <= (65536 if late_metadata else 1048576), 'bounded metadata receipt'
    stream=None; primary=None
    try:
        stream=(DEST/name).open('xb')
        assert stream.write(raw)==len(raw), 'short metadata receipt write'
        stream.flush();os.fsync(stream.fileno())
    except BaseException as exc:
        primary=exc;record_error('write:'+name,exc)
    finally:
        if stream is not None:
            try:
                stream.close()
            except BaseException as exc:
                record_error('close:'+name,exc)
                if primary is None:
                    primary=exc
    if primary is not None:
        raise primary
    return physical(DEST/name,late_metadata=late_metadata)
''','receipt acquisition and close protected; original write/flush/fsync error wins; exclusive bounded late companion supported')

replace_function('command',r'''
def command(name,argv,timeout,limit=1048576,pass_fds=()):
    check_pins(); began=time.monotonic(); wall=time.time_ns(); timed_out=False; exceeded=False
    files={}; selector=None; child=None; own=None; rc=None; primary=None
    cleanup_errors=[]; scans=[]; counts={'stdout':0,'stderr':0}
    def cleanup_error(phase,exc):
        text=record_error(name+':'+phase,exc)
        if len(cleanup_errors)<64:
            cleanup_errors.append({'phase':phase,'error':text[:4096]})
    try:
        for key in ('stdout','stderr'):
            files[key]=(DEST/(name+'.'+key+'.raw')).open('xb')
        selector=selectors.DefaultSelector()
        child=subprocess.Popen(argv,cwd=ROOT,env=ENV,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,pass_fds=pass_fds)
        own=owner(child.pid)
        write(name+'.launch.v1.json',{'argv':argv,'owner':own,'started_at_ns':wall,'commit':COMMIT})
        print(json.dumps({'phase':name+'_started','owner':own,'output_dir':str(DEST)}),flush=True)
        for key,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
            os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,key)
        next_update=began+30
        while selector.get_map():
            now=time.monotonic()
            if now>=min(DEADLINE,began+timeout):timed_out=True;raise TimeoutError('original bounded command deadline')
            for key,_ in selector.select(.1):
                raw=os.read(key.fd,65536)
                if not raw:selector.unregister(key.fileobj);continue
                available=limit-counts[key.data]
                if available>0:files[key.data].write(raw[:available]);counts[key.data]+=min(len(raw),available)
                if len(raw)>available:exceeded=True;raise RuntimeError('original channel cap; retained prefix')
            if now>=next_update:
                print(json.dumps({'phase':name+'_running','pid':child.pid,'elapsed_s':round(now-began,1),'channels':counts}),flush=True)
                next_update=now+30
        rc=child.wait(timeout=max(0,min(DEADLINE,began+timeout)-time.monotonic()))
        if rc!=0:
            raise RuntimeError(name+' original exited rc='+str(rc)+'; no retry')
    except BaseException as exc:
        primary=record_error(name+':body',exc)
    finally:
        cleanup_deadline=min(DEADLINE,time.monotonic()+15)
        if child is not None:
            running=True
            try:running=child.poll() is None
            except BaseException as exc:cleanup_error('owned_process_initial_poll',exc)
            if running:
                try:os.killpg(child.pid,signal.SIGTERM)
                except BaseException as exc:cleanup_error('owned_process_SIGTERM',exc)
                reaped=False
                try:
                    child.wait(timeout=max(0,min(1,cleanup_deadline-time.monotonic())));reaped=True
                except subprocess.TimeoutExpired:
                    pass
                except BaseException as exc:cleanup_error('owned_process_TERM_wait',exc)
                if not reaped:
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except BaseException as exc:cleanup_error('owned_process_SIGKILL',exc)
                    try:child.wait(timeout=max(0,cleanup_deadline-time.monotonic()))
                    except BaseException as exc:cleanup_error('owned_process_KILL_wait',exc)
        if selector is not None:
            try:selector.close()
            except BaseException as exc:cleanup_error('selector_close',exc)
        if child is not None:
            for key,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
                if pipe is not None:
                    try:pipe.close()
                    except BaseException as exc:cleanup_error(key+'_pipe_close',exc)
            try:rc=child.poll()
            except BaseException as exc:cleanup_error('child_poll',exc)
        for key,stream in files.items():
            try:stream.flush()
            except BaseException as exc:cleanup_error(key+'_flush',exc)
            try:os.fsync(stream.fileno())
            except BaseException as exc:cleanup_error(key+'_fsync',exc)
            try:stream.close()
            except BaseException as exc:cleanup_error(key+'_close',exc)
        if child is not None:
            original=own or {'pid':child.pid,'pgid':child.pid,'startticks':None}
            if own is None:
                cleanup_error('owner_identity',RuntimeError('original process owner identity unavailable'))
            for scan_index in range(2):
                try:
                    scan=scan_original_group(original,cleanup_deadline);scans.append(scan)
                    if scan['errors'] or scan['error_overflow']:
                        cleanup_error('group_scan_'+str(scan_index),RuntimeError('original group absence scan is uncertain'))
                    if scan['original_pid_identity']=='original_present' or scan['members']:
                        cleanup_error('group_scan_'+str(scan_index),RuntimeError('original PID or process group remains'))
                except BaseException as exc:
                    cleanup_error('group_scan_'+str(scan_index),exc)
        channels={}
        for key in ('stdout','stderr'):
            try:channels[key]=physical(DEST/(name+'.'+key+'.raw'))
            except BaseException as exc:
                channels[key]=None;cleanup_error(key+'_physical',exc)
        if time.monotonic()>=cleanup_deadline:
            cleanup_error('cleanup_deadline',TimeoutError('original bounded15s cleanup deadline'))
        receipt={'argv':argv,'owner':own,'returncode':rc,'timed_out':timed_out,'capture_exceeded':exceeded,
            'failure':primary,'cleanup_errors':cleanup_errors,'started_at_ns':wall,'finished_at_ns':time.time_ns(),
            'elapsed_s':time.monotonic()-began,'process_group_scans':scans,
            'process_group_members_at_terminal':scans[-1]['members'] if scans else None,
            'stdout':channels['stdout'],'stderr':channels['stderr'],
            'engine_backend_quiescence':'not inferred from original CLI status'}
        try:commands.append(write(name+'.terminal.v1.json',receipt))
        except BaseException as exc:cleanup_error('terminal_persist',exc)
    check_pins()
    if primary or cleanup_errors or rc!=0 or len(scans)!=2:
        raise RuntimeError(name+' original failed; no retry; first failure='+str(failure))
    return (DEST/(name+'.stdout.raw')).read_bytes()
''','protected acquisitions and independent retirement, sticky primary before cleanup, two explicit original PID/group absence observations')

replace('DEST.mkdir(mode=0o700)\ntry:\n','DEST.mkdir(mode=0o700)\ntry:\n    fd_before=fd_count()\n','FD baseline before any held source pins')
old_final = '''except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}'
finally:
    try:
        terminal=write('operation.terminal.v1.json',{'commit':COMMIT,'image_id':image_id,'tag':TAG,'failure':failure,
            'commands':commands,'elapsed_s':time.monotonic()-START,'accepted':False,'publication_ready':False,
            'classification':'original selected offline image build/capture only; no model/hardware/scientific acceptance'})
        print(json.dumps({'phase':'selected_build_capture_terminal','failure':failure,'receipt':terminal}),flush=True)
    finally:
        for p in pins:os.close(p['fd'])
sys.exit(0 if failure is None and time.monotonic()<DEADLINE else 78)
'''
new_final = r'''
except BaseException as exc:
    record_error('operation_body',exc)
finally:
    source_checks=[]; pin_closes=[]
    for index,p in enumerate(pins):
        if p['descriptor'] is None or p['epoch'] is None or p['fd'] is None:
            source_checks.append({'pin_index':index,'verified':False,'reason':'acquisition incomplete'})
            continue
        try:
            path=Path(p['descriptor']['path'])
            assert epoch(os.fstat(p['fd']))==p['epoch']==epoch(path.lstat())
            assert physical(path)==p['descriptor'], 'original held bytes changed at finalization'
            source_checks.append({'pin_index':index,'verified':True})
        except BaseException as exc:
            source_checks.append({'pin_index':index,'verified':False})
            record_error('source_final_check:'+str(index),exc)
    if socket is not None and socket_epoch is not None:
        try:assert epoch(socket.lstat())==socket_epoch, 'engine socket changed at finalization'
        except BaseException as exc:record_error('socket_final_check',exc)
    for index,p in enumerate(pins):
        if p['fd'] is None:
            continue
        try:
            os.close(p['fd']);p['fd']=None
            pin_closes.append({'pin_index':index,'closed':True})
        except BaseException as exc:
            pin_closes.append({'pin_index':index,'closed':False})
            record_error('pin_close:'+str(index),exc)
    try:
        fd_after=fd_count()
        assert fd_before is not None and fd_after==fd_before, 'owned source/command FD baseline was not restored'
    except BaseException as exc:
        record_error('final_fd_count',exc)
    before_receipt=time.monotonic()
    late=before_receipt>=DEADLINE
    if late:
        record_error('whole_deadline_before_terminal',TimeoutError('whole original build/capture deadline'))
    terminal=None
    terminal_failure=failure
    terminal_error_count=len(error_records)
    terminal_error_overflow=error_record_overflow
    try:
        terminal=write('operation.terminal.v1.json',{'commit':COMMIT,'image_id':image_id,'tag':TAG,'failure':failure,
            'commands':commands,'elapsed_s':time.monotonic()-START,'accepted':False,'publication_ready':False,
            'source_checks':source_checks,'pin_closes':pin_closes,
            'fd_before':fd_before,'fd_after':fd_after,'fd_delta':None if fd_before is None or fd_after is None else fd_after-fd_before,
            'error_records':error_records,'error_record_overflow':error_record_overflow,
            'deadline_reached_before_terminal':late,'all_pin_close_attempts_finished':True,
            'classification':'original selected offline image build/capture only; no model/hardware/scientific acceptance'})
        print(json.dumps({'phase':'selected_build_capture_terminal','failure':failure,'receipt':terminal}),flush=True)
    except BaseException as exc:
        record_error('operation_terminal_persist_or_report',exc)
    try:
        fd_after=fd_count()
        assert fd_before is not None and fd_after==fd_before, 'final metadata FD baseline was not restored'
    except BaseException as exc:
        record_error('post_terminal_fd_count',exc)
    if time.monotonic()>=DEADLINE:
        late=True
        record_error('whole_deadline_after_terminal',TimeoutError('whole original build/capture deadline at actual finalization'))
    if terminal is None or failure!=terminal_failure or len(error_records)!=terminal_error_count or error_record_overflow!=terminal_error_overflow or late:
        try:
            write('operation.failure.v2.json',{'commit':COMMIT,'tag':TAG,'failure':failure,'terminal':terminal,
                'terminal_path':str(DEST/'operation.terminal.v1.json'),'late':late,
                'fd_before':fd_before,'fd_after':fd_after,'all_pin_close_attempts_finished':True,
                'recent_error_records':error_records[-8:],'error_record_overflow':error_record_overflow,
                'accepted':False,'publication_ready':False,'record_kind':'bounded exclusive finalization failure companion'},late_metadata=True)
        except BaseException as exc:
            record_error('failure_companion_persist',exc)
            try:
                print(json.dumps({'phase':'selected_build_capture_failed_finalization','failure':failure[:4096],
                    'companion_error':f'{type(exc).__name__}: {exc}'[:4096],'accepted':False}),file=sys.stderr,flush=True)
            except BaseException as report_exc:
                record_error('failure_companion_report',report_exc)
    if time.monotonic()>=DEADLINE and not late:
        late=True
        record_error('whole_deadline_after_companion',TimeoutError('whole original build/capture deadline after final metadata'))
        try:
            write('operation.late.v2.json',{'commit':COMMIT,'tag':TAG,'failure':failure,'late':True,
                'accepted':False,'publication_ready':False,'record_kind':'bounded exclusive late finalization companion'},late_metadata=True)
        except BaseException as exc:
            record_error('late_companion_persist',exc)
            try:print(json.dumps({'phase':'selected_build_capture_late_unpersisted','failure':failure[:4096],'accepted':False}),file=sys.stderr,flush=True)
            except BaseException as report_exc:record_error('late_companion_report',report_exc)
sys.exit(0 if failure is None else 78)
'''
replace(old_final,new_final.lstrip(),'all source checks and independent FD retirement before actual terminal; explicit sticky late/failure companions')

# Static-only proof: no target import, compile, execution, build, engine, or model calls.
old_ast=ast.parse(original_source)
new_ast=ast.parse(source)
old_functions={n.name:ast.dump(n,include_attributes=False) for n in old_ast.body if isinstance(n,ast.FunctionDef)}
new_functions={n.name:ast.dump(n,include_attributes=False) for n in new_ast.body if isinstance(n,ast.FunctionDef)}
unchanged=sorted(k for k in old_functions if old_functions[k]==new_functions[k])
changed=sorted(k for k in old_functions if old_functions[k]!=new_functions[k])
assert unchanged==['check_pins','epoch','owner']
assert changed==['command','physical','pin','write']
old_operation=next(n for n in old_ast.body if isinstance(n,ast.Try))
new_operation=next(n for n in new_ast.body if isinstance(n,ast.Try))
assert [ast.dump(n,include_attributes=False) for n in old_operation.body]==[
    ast.dump(n,include_attributes=False) for n in new_operation.body[1:]]
old_command=next(n for n in old_ast.body if isinstance(n,ast.FunctionDef) and n.name=='command')
new_command=next(n for n in new_ast.body if isinstance(n,ast.FunctionDef) and n.name=='command')
old_popen=next(n for n in ast.walk(old_command) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Popen')
new_popen=next(n for n in ast.walk(new_command) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Popen')
assert ast.dump(old_popen,include_attributes=False)==ast.dump(new_popen,include_attributes=False)
restored=source
for replacement in reversed(replacements):
    assert restored.count(replacement['after'])==1,replacement['reason']
    restored=restored.replace(replacement['after'],replacement['before'])
assert restored==original_source
legacy=LEGACY.read_text(encoding='utf-8')
legacy_replacements=json.loads(OLD_PREP.read_text(encoding='utf-8'))['literal_replacements']
legacy_restored=restored
for before,after in reversed(list(legacy_replacements.items())):
    assert legacy_restored.count(after)==1,before
    legacy_restored=legacy_restored.replace(after,before)
assert legacy_restored==legacy
new_path=HERE/'run_original_selected_build_ext4_v2.py'
with new_path.open('xb') as stream:
    stream.write(source.encode())
diff=''.join(difflib.unified_diff(original_source.splitlines(keepends=True),source.splitlines(keepends=True),
    fromfile='immutable-v1/run_original_selected_build_ext4_v1.py',tofile='prepared-v2/run_original_selected_build_ext4_v2.py'))
diff_path=HERE/'source.v1-to-v2.diff'
with diff_path.open('xb') as stream:
    stream.write(diff.encode())
prep={'schema_version':1,'status':'prepared_unexecuted_pending_exact_source_commit_and_independent_peer_grant',
    'source':descriptor(new_path),'preparer':descriptor(Path(__file__).resolve()),'exact_diff':descriptor(diff_path),
    'immutable_inputs':[descriptor(p) for p in (OLD,OLD_PREP,OLD_PEER,LEGACY)],
    'old_function_ASTs_unchanged':unchanged,'old_function_ASTs_changed_only_for_required_closure':changed,
    'added_module_functions':sorted(set(new_functions)-set(old_functions)),
    'engine_operation_body_AST_unchanged_after_FD_baseline':True,'original_Popen_AST_unchanged':True,
    'exact_v2_to_v1_inverse':True,'exact_v2_to_legacy_inverse_after_original_five_relocations':True,
    'replacement_reasons':[r['reason'] for r in replacements],
    'bounds':{'whole_s':1200,'stock_two_build_s':900,'stock_capture_s':180,'other_engine_s':60,
        'ordinary_capture_bytes':1048576,'build_capture_bytes':16777216,'cleanup_s':15,
        'late_failure_companion_bytes':65536,'diagnostic_error_records':64},
    'author_review':[
        'All channel files and selector are acquired inside command try; held pin row is registered before fd acquisition.',
        'Original body/write failure is latched before independent selector, pipe, flush, fsync, channel, and pin close attempts.',
        'Two independent process observations retain real scan/read/parse errors and count proc disappearance races; uncertain absence blocks and each scan is clamped by the original15s cleanup and whole1200 deadline.',
        'Full held-source hashes and all seven stat epochs remain mandatory; default physical source checks keep the global1200 deadline.',
        'Operation terminal follows final source checks, every pin close attempt, and actual FD count equality to the pre-pin baseline.',
        'A late deadline or final terminal persistence/report error is sticky and produces an exclusive <=64KiB nonauthorizing companion where persistence is possible.',
        'Existing stock two-build/capture/query argv, future exact40lowerhex COMMIT, TAG, DEST, base image, and all old time/channel bounds are unchanged.',
        'No engine backend quiescence, image binding, model grant, benchmark success, readiness, or acceptance is inferred.'
    ],
    'source_commit_argument':None,'future_image_receipt':None,'future_original_owner':None,
    'engine_commands_executed':0,'target_imported_or_executed':False,
    'production_source_tests_CI_or_Git_mutated':False,'reviewer_handles_released':True,
    'scope':'immutable minimal original selected deterministic two-build/capture helper repair; prepared only',
    'next_gate':'independent exact-source peer review and ROOT grant at actual future source commit before one original selected build'}
prep_path=HERE/'preparation.v2.json'
with prep_path.open('xb') as stream:
    stream.write((json.dumps(prep,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'source':descriptor(new_path),'preparation':descriptor(prep_path),'diff':descriptor(diff_path)}))
