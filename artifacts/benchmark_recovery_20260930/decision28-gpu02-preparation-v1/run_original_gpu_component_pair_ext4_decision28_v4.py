"""One original stock GPU component CLI, bounded host capture only."""
import hashlib,json,os,selectors,signal,stat,subprocess,sys,time
from pathlib import Path
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
assert len(sys.argv)==3,'usage: driver SOURCE_COMMIT HOST_CLOSURE_EXT4_DECISION28_V4_SHA256'
COMMIT=sys.argv[1]
CLOSURE_SHA256=sys.argv[2]
assert len(COMMIT)==40 and all(char in '0123456789abcdef' for char in COMMIT)
assert len(CLOSURE_SHA256)==64 and all(char in '0123456789abcdef' for char in CLOSURE_SHA256)
IMAGE='sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1'
BASE=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'
PAIR=BASE/'gpu-pair-02'
DEST=BASE/'gpu-pair-02-original-controller'
EXPECTED={
 'capability_manifest_path':('artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/candidate/checkpoint_policy_capability_candidate_manifest.json','3c921a062345d571c836eed6e40de6b3bf4b7be798e24b792c10c1d1df3c1494'),
 'calibration_path':('artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.gstreamer_custom.v2.json','8f984df897f12f6269e68a2a1dda6ffe5fc112c5729f5f46fd9f7079bde96b15'),
 'model_parity_receipt_path':('configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json','6f50d92e74ab7750f262d2697b0fceeb979d4f221eda90a0223cce4d5ff7a169'),
 'runtime_image_receipt_path':('artifacts/benchmark_recovery_20260930/decision28-gstreamer-build-2a6a42c9-v1/gstreamer_custom.runtime.freeze.json','0b8a34e67773572a27885b931c50427de8bbd59b23eba837c5d2319ea7e9abca'),
 'worker_freeze_receipt_path':('artifacts/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json','ff7dca7f25ffa9856cf0afdf97569e9ced3292866251e2523db00aa23875ef96'),
 'execution_code_closure_path':('artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json',CLOSURE_SHA256)}
assert IMAGE is not None and all(value is not None for value in EXPECTED['runtime_image_receipt_path']), 'prepared GPU02 has no genuine new image/runtime-receipt binding; ROOT must bind actual stock capture before dispatch'
START=time.monotonic();DEADLINE=START+2250
pins=[];source_pins=[];input_pins={};primary=None;cleanup_errors=[];timed_out=False;exceeded=False
child=None;child_owner=None;argv=None;signals=[];before=[];after=[];group_members=[]
counts={'stdout':0,'stderr':0};streams={};selector=None;closure=None
EOF={'stdout':False,'stderr':False};process_scans=[];pin_closes=[];reaped=False
fd_before=fd_after=None;dest_owned=False;error_overflow=0

def fd_count():
    return len(os.listdir('/proc/self/fd'))

def scan_original_group(original, cleanup_deadline):
    observed = {'original_pid':original['pid'],'original_pgid':original['pgid'],
        'original_startticks':original.get('startticks'),'original_pid_identity':'absent',
        'members':[],'member_overflow':0,'errors':[],'error_overflow':0,
        'vanished_during_scan':0,'started_at_ns':time.time_ns()}
    def scan_error(phase, exc):
        if len(observed['errors']) < 64:
            observed['errors'].append({'phase':phase,'error':error(exc)})
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
        if time.monotonic() >= cleanup_deadline:
            scan_error('deadline',TimeoutError('original bounded cleanup deadline during group scan'))
            break
        try:
            parts = Path('/proc',entry,'stat').read_text().rsplit(')',1)[1].split()
            pid, pgid, startticks = int(entry), int(parts[2]), int(parts[19])
            if pid == original['pid']:
                observed['original_pid_identity'] = (
                    'original_present' if startticks==original.get('startticks') else 'different_startticks')
            if pgid == original['pgid']:
                if len(observed['members']) < 64:
                    observed['members'].append({'pid':pid,'startticks':startticks,'state':parts[0]})
                else:
                    observed['member_overflow'] += 1
        except (FileNotFoundError,ProcessLookupError):
            observed['vanished_during_scan'] += 1
        except BaseException as exc:
            scan_error('pid:'+entry,exc)
    observed['finished_at_ns'] = time.time_ns()
    return observed


def epoch(info):return [info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns]
def error(exc):return {'type':type(exc).__name__,'message':str(exc)[:4096]}
def clock():
    if time.monotonic()>=DEADLINE:raise TimeoutError('original outer2250s elapsed')
def descriptor(path):
    p=Path(path);info=p.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not p.is_symlink()
    digest=hashlib.sha256();size=0;fd=None;failed=None
    try:
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        assert epoch(info)==epoch(os.fstat(fd))
        while block:=os.read(fd,1048576):clock();digest.update(block);size+=len(block)
        assert epoch(info)==epoch(os.fstat(fd))==epoch(p.lstat()) and size==info.st_size
    except BaseException as exc:
        failed=exc;latch(exc)
    finally:
        if fd is not None:
            try:os.close(fd)
            except BaseException as exc:
                latch(exc)
                if failed is None:failed=exc
    if failed is not None:raise failed
    return {'path':str(p),'size_bytes':size,'sha256':digest.hexdigest()}
def write(name,value,late_metadata=False):
    if not late_metadata:clock()
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=(65536 if late_metadata else 1048576)
    stream=None;failed=None
    try:
        assert dest_owned,'controller does not own exclusive destination'
        stream=(DEST/name).open('xb')
        assert stream.write(raw)==len(raw),'short metadata write'
        stream.flush();os.fsync(stream.fileno())
    except BaseException as exc:failed=exc;latch(exc)
    finally:
        if stream is not None:
            try:stream.close()
            except BaseException as exc:
                latch(exc)
                if failed is None:failed=exc
    if failed is not None:raise failed
    if not late_metadata:clock()
    return {'path':str(DEST/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def pin(path,expected=None):
    p=Path(path).resolve(strict=True)
    row={'descriptor':None,'epoch':None,'fd':None,'path':str(p)};pins.append(row)
    row['fd']=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    row['epoch']=epoch(os.fstat(row['fd']))
    row['descriptor']=descriptor(p)
    assert row['epoch']==epoch(os.fstat(row['fd']))==epoch(p.lstat())
    if expected is not None:assert row['descriptor']['sha256']==expected,'original expected input bytes mismatch: '+str(p)
    return row
def observe(row):
    p=Path(row['descriptor']['path']);assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())
    current=descriptor(p);assert current==row['descriptor'],'original held input changed: '+str(p)
    assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())
    return {'descriptor':current,'epoch':epoch(p.lstat())}
def owner(pid):
    values=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    ids=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    return {'pid':pid,'ppid':int(values[1]),'pgid':int(values[2]),'startticks':int(values[19]),
        'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0]),
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def latch(exc):
    global primary,error_overflow
    if primary is None:primary=error(exc)
    elif len(cleanup_errors)<64:cleanup_errors.append(error(exc))
    else:error_overflow+=1

try:
    fd_before=fd_count()
    assert not os.path.lexists(PAIR) and not os.path.lexists(DEST),'original GPU namespaces already occupied'
    DEST.mkdir(mode=0o700);dest_owned=True
    selector=selectors.DefaultSelector()
    for name in ('stdout','stderr'):streams[name]=(DEST/('original.'+name+'.raw')).open('xb')
    git=['/usr/bin/git','-c','core.longpaths=true','--git-dir='+str(ROOT/'.git'),'--work-tree='+str(ROOT),'rev-parse','HEAD']
    head=subprocess.check_output(git,timeout=10,text=True).strip();assert head==COMMIT,'sourceHEAD changed before original GPU'
    for role,(relative,sha) in EXPECTED.items():input_pins[role]=pin(ROOT/relative,sha)
    closure=json.loads((ROOT/EXPECTED['execution_code_closure_path'][0]).read_bytes())
    assert closure['status']=='frozen' and len(closure['project_sources'])==87
    assert len({row['path'] for row in closure['project_sources']})==87
    for row in closure['project_sources']:
        relative=Path(row['path']);assert not relative.is_absolute() and '..' not in relative.parts
        held=pin(ROOT/relative,row['sha256']);assert held['descriptor']['size_bytes']==row['size_bytes'];source_pins.append(held)
    python=pin(sys.executable,closure['interpreter']['sha256']);self_pin=pin(Path(__file__))
    runtime=json.loads((ROOT/EXPECTED['runtime_image_receipt_path'][0]).read_bytes())
    assert runtime['candidate_binding_eligible'] is True and runtime['blockers']==[] and runtime['physical_identity']['image_id']==IMAGE
    scratch=Path('/tmp');socket=Path('/run/docker.sock')
    assert scratch.resolve(strict=True)==scratch and stat.S_ISDIR(scratch.lstat().st_mode)
    assert socket.resolve(strict=True)==socket and stat.S_ISSOCK(socket.lstat().st_mode)
    socket_identity=[socket.lstat().st_dev,socket.lstat().st_ino,socket.lstat().st_mode,socket.lstat().st_uid,socket.lstat().st_gid]
    entry='import runpy,sys;sys.path.insert(0,'+repr(str(ROOT/'scripts'))+');runpy.run_path('+repr(str(ROOT/'scripts/publication_gstreamer_component_cli_v1.py'))+",run_name='__main__')"
    argv=[sys.executable,'-I','-B','-c',entry,'--project-root',str(ROOT),'--resource','gpu','--output-dir',str(PAIR),
        '--scratch-root','/tmp','--container-engine','/usr/bin/docker','--container-engine-socket','/run/docker.sock']
    for role,(relative,_) in EXPECTED.items():argv+=['--'+role.replace('_','-'),str(ROOT/relative)]
    before=[{'descriptor':p['descriptor'],'epoch':p['epoch']} for p in pins]
    write('prelaunch.v1.json',{'source_commit':COMMIT,'sourceHEAD':head,'image_id':IMAGE,'controller':owner(os.getpid()),
        'argv':argv,'pair_output':str(PAIR),'source_count':87,'six_input_roles':list(EXPECTED),'pins_before':before,
        'interpreter':python['descriptor'],'socket_identity':socket_identity,'scratch_identity':[scratch.lstat().st_dev,scratch.lstat().st_ino,scratch.lstat().st_mode],
        'outer_budget_seconds':2250,'stock_cli_pair_budget_seconds':2100,'teardown_seconds':15,'channel_cap_bytes':1048576,
        'accepted':False,'publication_ready':False,'scope':'original CLI host capture only; CLI owns model/device/worker/container operations and acceptance'})
    clock();began=time.time_ns();child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    child_owner=owner(child.pid)
    observed=os.stat(f'/proc/{child.pid}/exe');assert (observed.st_dev,observed.st_ino)==tuple(python['epoch'][:2]),'original CPython executable differs'
    write('original.launch.v1.json',{'source_commit':COMMIT,'argv':argv,'original_child_pid':child.pid,'owner':child_owner,'started_at_ns':began,'interpreter':python['descriptor']})
    print(json.dumps({'phase':'original_gpu_component_started','owner':child_owner,'output_dir':str(PAIR),'controller_output':str(DEST)}),flush=True)
    for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
        os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,name)
    next_update=time.monotonic()+30
    while selector.get_map() or child.poll() is None:
        if time.monotonic()>=DEADLINE:timed_out=True;raise TimeoutError('original outer2250s elapsed')
        for key,_ in selector.select(.1):
            try:raw=os.read(key.fd,65536)
            except OSError as exc:latch(exc);selector.unregister(key.fileobj);continue
            if not raw:EOF[key.data]=True;selector.unregister(key.fileobj);continue
            available=1048576-counts[key.data]
            if available>0:
                retained=raw[:available]
                try:
                    assert streams[key.data].write(retained)==len(retained),'short original channel write'
                    counts[key.data]+=len(retained)
                except OSError as exc:latch(exc);counts[key.data]=1048576
            if len(raw)>available:
                exceeded=True
                if primary is None:latch(RuntimeError('original channel cap; retained bounded prefix, discarded overflow'))
        if time.monotonic()>=next_update:
            print(json.dumps({'phase':'original_gpu_component_running','pid':child.pid,'elapsed_s':round(time.monotonic()-START,1),'channels':counts}),flush=True)
            next_update=time.monotonic()+30
    child.wait(timeout=max(0,DEADLINE-time.monotonic()));reaped=True
    if child.returncode!=0:latch(RuntimeError('original stock GPU CLI nonzero: '+str(child.returncode)))
except BaseException as exc:
    latch(exc)
finally:
    cleanup_deadline=time.monotonic()+15
    try:
        if child is not None and child.poll() is None:
            # The stock CLI catches SIGINT/KeyboardInterrupt and runs its own
            # authenticated guardian cleanup. The outer never operates Docker.
            if time.monotonic()<DEADLINE:
                # A post-Popen observer failure must not interrupt valid stock
                # cleanup early; retain failed observation and wait original.
                try:child.wait(timeout=max(0,DEADLINE-time.monotonic()));reaped=True
                except subprocess.TimeoutExpired:timed_out=True
                cleanup_deadline=time.monotonic()+15
            if child.poll() is None:
                timed_out=True
                child.send_signal(signal.SIGINT);signals.append({'signal':'SIGINT','at_ns':time.time_ns()})
                try:child.wait(timeout=min(10,max(0,cleanup_deadline-time.monotonic())));reaped=True
                except subprocess.TimeoutExpired:
                    child.kill();signals.append({'signal':'SIGKILL','at_ns':time.time_ns()});child.wait(timeout=max(0,cleanup_deadline-time.monotonic()));reaped=True
    except BaseException as exc:latch(exc)
    finally:
        # Retain remaining available original pipe bytes under this same teardown
        # clock; no successful EOF/cleanup inference after forced termination.
        try:
            while selector is not None and selector.get_map() and time.monotonic()<cleanup_deadline:
                for key,_ in selector.select(.1):
                    raw=os.read(key.fd,65536)
                    if not raw:EOF[key.data]=True;selector.unregister(key.fileobj);continue
                    available=1048576-counts[key.data]
                    if available>0:
                        retained=raw[:available]
                        assert streams[key.data].write(retained)==len(retained),'short original drain write'
                        counts[key.data]+=len(retained)
                    if len(raw)>available:exceeded=True;latch(RuntimeError('original drain channel cap'))
            if selector is not None and selector.get_map():latch(RuntimeError('original channel EOF unavailable at bounded teardown'))
        except BaseException as exc:latch(exc)
        finally:
            if selector is not None:
                try:selector.close()
                except BaseException as exc:latch(exc)
            if child is not None:
                for pipe in (child.stdout,child.stderr):
                    if pipe is not None:
                        try:pipe.close()
                        except BaseException as exc:latch(exc)
                try:
                    if child.poll() is not None:
                        child.wait(timeout=max(0,cleanup_deadline-time.monotonic()));reaped=True
                except BaseException as exc:latch(exc)
            for stream in streams.values():
                for action in (stream.flush,lambda stream=stream:os.fsync(stream.fileno()),stream.close):
                    try:action()
                    except BaseException as exc:latch(exc)
    for row in pins:
        try:
            assert row['fd'] is not None and row['descriptor'] is not None and row['epoch'] is not None,'held source acquisition incomplete'
            after.append(observe(row))
        except BaseException as exc:after.append({'original_descriptor':row['descriptor'],'observation_error':error(exc)});latch(exc)
    if child is not None:
        original=child_owner or {'pid':child.pid,'pgid':child.pid,'startticks':None}
        if child_owner is None:latch(RuntimeError('original owner identity unavailable'))
        for scan_index in range(2):
            try:
                scan=scan_original_group(original,cleanup_deadline);process_scans.append(scan)
                if scan['errors'] or scan['error_overflow'] or scan['members'] or scan['member_overflow'] or scan['original_pid_identity']!='absent':
                    latch(RuntimeError('original CLI PID/group absence uncertain or not absent'))
            except BaseException as exc:latch(exc)
        group_members=process_scans[-1]['members'] if process_scans else []
        if not reaped:latch(RuntimeError('original child reap not observed'))
        if not all(EOF.values()):latch(RuntimeError('original channel EOF not observed'))
    def raw_desc(path):
        info=path.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not path.is_symlink() and info.st_size<=1048576
        fd=None;failed=None;digest=hashlib.sha256();size=0
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            assert epoch(info)==epoch(os.fstat(fd))
            while raw:=os.read(fd,65536):
                assert time.monotonic()<cleanup_deadline,'original15s cleanup deadline'
                size+=len(raw);assert size<=1048576;digest.update(raw)
            assert epoch(info)==epoch(os.fstat(fd))==epoch(path.lstat()) and size==info.st_size
        except BaseException as exc:failed=exc;latch(exc)
        finally:
            if fd is not None:
                try:os.close(fd)
                except BaseException as exc:
                    latch(exc)
                    if failed is None:failed=exc
        if failed is not None:raise failed
        return {'path':str(path),'size_bytes':size,'sha256':digest.hexdigest(),'epoch':epoch(info)}
    cli_terminal=PAIR/'component_cli_terminal.v1.json';original_cli=None;channels={}
    if cli_terminal.exists():
        try:original_cli=raw_desc(cli_terminal)
        except BaseException as exc:latch(exc)
    for name in ('stdout','stderr'):
        try:channels[name]=raw_desc(DEST/('original.'+name+'.raw'))
        except BaseException as exc:channels[name]=None;latch(exc)
    for index,row in enumerate(pins):
        if row['fd'] is None:continue
        try:
            os.close(row['fd']);row['fd']=None;pin_closes.append({'pin_index':index,'closed':True})
        except BaseException as exc:pin_closes.append({'pin_index':index,'closed':False});latch(exc)
    try:
        fd_after=fd_count()
        assert fd_before is not None and fd_after==fd_before,'owned FD baseline not restored'
        assert time.monotonic()<cleanup_deadline,'original15s cleanup deadline elapsed'
    except BaseException as exc:latch(exc)
    late=time.monotonic()>=DEADLINE
    if late:latch(TimeoutError('original outer2250s closed late'))
    terminal=None;terminal_failure=primary;terminal_error_count=len(cleanup_errors);terminal_overflow=error_overflow
    if dest_owned:
        try:
            terminal=write('original.terminal.v1.json',{'source_commit':COMMIT,'image_id':IMAGE,'argv':argv,'owner':child_owner,
                'original_child_pid':None if child is None else child.pid,'original_returncode':None if child is None else child.returncode,
                'timed_out':timed_out,'capture_exceeded':exceeded,'failure':primary,'additional_errors':cleanup_errors,'error_overflow':error_overflow,'signals':signals,
                'elapsed_s':time.monotonic()-START,'pins_before':before,'pins_after':after,'source_count':len(source_pins),'input_count':len(input_pins),
                'stdout':channels['stdout'],'stderr':channels['stderr'],'EOF':EOF,'reaped':reaped,
                'original_cli_terminal':original_cli,'original_cli_process_group_members':group_members,'process_group_scans':process_scans,
                'pin_closes':pin_closes,'all_pin_close_attempts_finished':True,'fd_before':fd_before,'fd_after':fd_after,'accepted':False,'publication_ready':False,
                'container_quiescence':'not inferred from CLI/group status; use original CLI authenticated shutdown and original container receipts'})
            print(json.dumps({'phase':'original_gpu_component_terminal','returncode':None if child is None else child.returncode,'failure':primary,'receipt':terminal}),flush=True)
        except BaseException as exc:latch(exc)
    try:
        fd_after=fd_count()
        assert fd_before is not None and fd_after==fd_before,'final metadata FD baseline not restored'
    except BaseException as exc:latch(exc)
    if time.monotonic()>=DEADLINE:
        if not late:latch(TimeoutError('original outer2250s closed late after terminal'))
        late=True
    if dest_owned and (terminal is None or primary!=terminal_failure or len(cleanup_errors)!=terminal_error_count or error_overflow!=terminal_overflow or late):
        try:
            write('failure.v4.json',{'source_commit':COMMIT,'image_id':IMAGE,'status':'failed','failure':primary,'original_terminal':terminal,
                'terminal_path':str(DEST/'original.terminal.v1.json'),'late':late,'recent_errors':cleanup_errors[-8:],'error_overflow':error_overflow,
                'fd_before':fd_before,'fd_after':fd_after,'all_pin_close_attempts_finished':True,'accepted':False,'publication_ready':False,
                'record_kind':'exclusive bounded finalization failure companion'},late_metadata=True)
        except BaseException as exc:
            latch(exc)
            try:print(json.dumps({'phase':'original_cpu_failed_finalization','failure':primary,'companion_error':error(exc)}),file=sys.stderr,flush=True)
            except BaseException as report_exc:latch(report_exc)
    if dest_owned and time.monotonic()>=DEADLINE and not late:
        late=True;latch(TimeoutError('original outer2250s closed late after final metadata'))
        try:write('late.v4.json',{'source_commit':COMMIT,'status':'failed','failure':primary,'late':True,'accepted':False,'publication_ready':False},late_metadata=True)
        except BaseException as exc:latch(exc)
    if not dest_owned:
        try:print(json.dumps({'phase':'original_cpu_failed_acquisition','failure':primary,'output_namespace_owned':False}),file=sys.stderr,flush=True)
        except BaseException as exc:latch(exc)
sys.exit(0 if child is not None and child.returncode==0 and primary is None and not timed_out and not exceeded else 78)
