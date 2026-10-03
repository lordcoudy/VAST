"""One original stock GPU component CLI, bounded host capture only."""
import hashlib,json,os,selectors,signal,stat,subprocess,sys,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
assert len(sys.argv)==3,'usage: driver SOURCE_COMMIT HOST_CLOSURE_V6_SHA256'
COMMIT=sys.argv[1]
CLOSURE_SHA256=sys.argv[2]
assert len(COMMIT)==40 and all(char in '0123456789abcdef' for char in COMMIT)
assert len(CLOSURE_SHA256)==64 and all(char in '0123456789abcdef' for char in CLOSURE_SHA256)
IMAGE='sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6'
BASE=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'
PAIR=BASE/'gpu-pair-01'
DEST=BASE/'gpu-pair-01-original-controller'
EXPECTED={
 'capability_manifest_path':('artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/candidate/checkpoint_policy_capability_candidate_manifest.json','3c921a062345d571c836eed6e40de6b3bf4b7be798e24b792c10c1d1df3c1494'),
 'calibration_path':('artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.gstreamer_custom.v2.json','8f984df897f12f6269e68a2a1dda6ffe5fc112c5729f5f46fd9f7079bde96b15'),
 'model_parity_receipt_path':('configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json','6f50d92e74ab7750f262d2697b0fceeb979d4f221eda90a0223cce4d5ff7a169'),
 'runtime_image_receipt_path':('artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json','61874c718d6140d0d5cf745988bc301b916077af8f80e96742184f80a0805db7'),
 'worker_freeze_receipt_path':('artifacts/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json','ff7dca7f25ffa9856cf0afdf97569e9ced3292866251e2523db00aa23875ef96'),
 'execution_code_closure_path':('artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.v6.json',CLOSURE_SHA256)}
START=time.monotonic();DEADLINE=START+2250
pins=[];source_pins=[];input_pins={};primary=None;cleanup_errors=[];timed_out=False;exceeded=False
child=None;child_owner=None;argv=None;signals=[];before=[];after=[];group_members=[]
counts={'stdout':0,'stderr':0};streams={};selector=selectors.DefaultSelector();closure=None

def epoch(info):return [info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns]
def error(exc):return {'type':type(exc).__name__,'message':str(exc)[:4096]}
def clock():
    if time.monotonic()>=DEADLINE:raise TimeoutError('original outer2250s elapsed')
def descriptor(path):
    p=Path(path);info=p.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not p.is_symlink()
    digest=hashlib.sha256();size=0
    with p.open('rb') as f:
        while block:=f.read(1048576):clock();digest.update(block);size+=len(block)
    assert epoch(info)==epoch(p.lstat()) and size==info.st_size
    return {'path':str(p),'size_bytes':size,'sha256':digest.hexdigest()}
def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=1048576
    with (DEST/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(DEST/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def pin(path,expected=None):
    p=Path(path).resolve(strict=True);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        desc=descriptor(p);info=epoch(os.fstat(fd));assert info==epoch(p.lstat())
        if expected is not None:assert desc['sha256']==expected,'original expected input bytes mismatch: '+str(p)
        row={'descriptor':desc,'epoch':info,'fd':fd};pins.append(row);return row
    except BaseException:os.close(fd);raise
def observe(row):
    p=Path(row['descriptor']['path']);assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())
    current=descriptor(p);assert current==row['descriptor'],'original held input changed: '+str(p)
    return {'descriptor':current,'epoch':epoch(p.lstat())}
def owner(pid):
    values=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    ids=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    return {'pid':pid,'ppid':int(values[1]),'pgid':int(values[2]),'startticks':int(values[19]),
        'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0]),
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def latch(exc):
    global primary
    if primary is None:primary=error(exc)
    else:cleanup_errors.append(error(exc))

assert not os.path.lexists(PAIR) and not os.path.lexists(DEST),'original GPU namespaces already occupied'
DEST.mkdir(mode=0o700)
for name in ('stdout','stderr'):streams[name]=(DEST/('original.'+name+'.raw')).open('xb')
try:
    git=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT),'rev-parse','HEAD']
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
            if not raw:selector.unregister(key.fileobj);continue
            available=1048576-counts[key.data]
            if available>0:
                retained=raw[:available]
                try:streams[key.data].write(retained);counts[key.data]+=len(retained)
                except OSError as exc:latch(exc);counts[key.data]=1048576
            if len(raw)>available:
                exceeded=True
                if primary is None:latch(RuntimeError('original channel cap; retained bounded prefix, discarded overflow'))
        if time.monotonic()>=next_update:
            print(json.dumps({'phase':'original_gpu_component_running','pid':child.pid,'elapsed_s':round(time.monotonic()-START,1),'channels':counts}),flush=True)
            next_update=time.monotonic()+30
    child.wait(timeout=max(0,DEADLINE-time.monotonic()))
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
                try:child.wait(timeout=max(0,DEADLINE-time.monotonic()))
                except subprocess.TimeoutExpired:timed_out=True
                cleanup_deadline=time.monotonic()+15
            if child.poll() is None:
                timed_out=True
                child.send_signal(signal.SIGINT);signals.append({'signal':'SIGINT','at_ns':time.time_ns()})
                try:child.wait(timeout=min(10,max(0,cleanup_deadline-time.monotonic())))
                except subprocess.TimeoutExpired:
                    child.kill();signals.append({'signal':'SIGKILL','at_ns':time.time_ns()});child.wait(timeout=max(0,cleanup_deadline-time.monotonic()))
    except BaseException as exc:latch(exc)
    finally:
        # Retain remaining available original pipe bytes under this same teardown
        # clock; no successful EOF/cleanup inference after forced termination.
        try:
            while selector.get_map() and time.monotonic()<cleanup_deadline:
                for key,_ in selector.select(.1):
                    raw=os.read(key.fd,65536)
                    if not raw:selector.unregister(key.fileobj);continue
                    available=1048576-counts[key.data]
                    if available>0:streams[key.data].write(raw[:available]);counts[key.data]+=min(len(raw),available)
                    if len(raw)>available:exceeded=True;latch(RuntimeError('original drain channel cap'))
            if selector.get_map():latch(RuntimeError('original channel EOF unavailable at bounded teardown'))
        except BaseException as exc:latch(exc)
        finally:
            selector.close()
            if child is not None:
                for pipe in (child.stdout,child.stderr):pipe.close()
            for stream in streams.values():
                try:stream.flush();os.fsync(stream.fileno())
                except OSError as exc:latch(exc)
                finally:stream.close()
    for row in pins:
        try:after.append(observe(row))
        except BaseException as exc:after.append({'original_descriptor':row['descriptor'],'observation_error':error(exc)});latch(exc)
    if child_owner is not None:
        for path in Path('/proc').iterdir():
            if path.name.isdigit():
                try:
                    vals=(path/'stat').read_text().rsplit(')',1)[1].split()
                    if int(vals[2])==child_owner['pgid']:group_members.append({'pid':int(path.name),'startticks':int(vals[19]),'state':vals[0]})
                except (OSError,ValueError):pass
    if group_members:latch(RuntimeError('original CLI process group remains; container cleanup unknown'))
    def raw_desc(path):
        info=path.lstat();raw=path.read_bytes();assert len(raw)<=1048576
        return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    cli_terminal=PAIR/'component_cli_terminal.v1.json';original_cli=None
    if cli_terminal.exists():
        try:original_cli=raw_desc(cli_terminal)
        except BaseException as exc:latch(exc)
    try:
        terminal=write('original.terminal.v1.json',{'source_commit':COMMIT,'image_id':IMAGE,'argv':argv,'owner':child_owner,
            'original_child_pid':None if child is None else child.pid,'original_returncode':None if child is None else child.returncode,
            'timed_out':timed_out,'capture_exceeded':exceeded,'failure':primary,'additional_errors':cleanup_errors,'signals':signals,
            'elapsed_s':time.monotonic()-START,'pins_before':before,'pins_after':after,'source_count':len(source_pins),'input_count':len(input_pins),
            'stdout':raw_desc(DEST/'original.stdout.raw'),'stderr':raw_desc(DEST/'original.stderr.raw'),
            'original_cli_terminal':original_cli,'original_cli_process_group_members':group_members,'accepted':False,'publication_ready':False,
            'container_quiescence':'not inferred from CLI/group status; use original CLI authenticated shutdown and original container receipts'})
        print(json.dumps({'phase':'original_gpu_component_terminal','returncode':None if child is None else child.returncode,'failure':primary,'receipt':terminal}),flush=True)
    finally:
        for row in pins:os.close(row['fd'])
    if time.monotonic()>=DEADLINE:
        write('late-limit-failure.v1.json',{'source_commit':COMMIT,'status':'failed','elapsed_s':time.monotonic()-START,'original_terminal':terminal,
            'reason':'whole outer2250s closed late; any forced containment is failed and container cleanup remains separately observed'})
        if primary is None:primary={'type':'TimeoutError','message':'original outer2250s closed late'}
sys.exit(0 if child is not None and child.returncode==0 and primary is None and not timed_out and not exceeded else 78)
