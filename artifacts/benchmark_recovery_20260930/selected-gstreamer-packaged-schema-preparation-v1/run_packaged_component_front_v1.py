"""Once-only original packaged source/front/component fixture gate; no model grant."""
import hashlib, json, os, selectors, signal, stat, subprocess, sys, time
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
COMMIT = 'a4e145b7bf32e0c870b114e303e9adb6a559d0ef'
TAG = 'vast/gstreamer-custom-publication-runtime-v3:component-release-20260930-a4e145b7'
BASE = 'sha256:b102aafc0f88f8cfad92349e6a55d0f9755a3f5bff109a70ebdb8936d4a8e84c'
DEST = ROOT / 'artifacts/benchmark_recovery_20260930/selected-gstreamer-packaged-a4e145b7-v1'
NATIVE = ROOT / 'artifacts/fix_benchmark_preparations_20260928g/native-a/native_probe.freeze.json'
START = time.monotonic()
DEADLINE = START + 420
pins = []
commands = []
failure = None
image_id = None

def epoch(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

def physical(path):
    p = Path(path); before = p.lstat(); digest = hashlib.sha256()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and not p.is_symlink()
    with p.open('rb') as stream:
        while block := stream.read(1048576):
            assert time.monotonic() < DEADLINE, 'whole original build/capture deadline'
            digest.update(block)
    assert epoch(before) == epoch(p.lstat()), 'physical input changed while hashing'
    return {'path':str(p),'size_bytes':before.st_size,'sha256':digest.hexdigest()}

def pin(path):
    p=Path(path).resolve(strict=True); fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        result=physical(p); snapshot=epoch(os.fstat(fd)); assert snapshot==epoch(p.lstat())
        row={'descriptor':result,'epoch':snapshot,'fd':fd};pins.append(row);return row
    except BaseException:
        os.close(fd);raise

def check_pins():
    for row in pins:
        p=Path(row['descriptor']['path'])
        assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())
        assert physical(p)==row['descriptor'], 'original held bytes changed'
    assert epoch(socket.lstat())==socket_epoch, 'engine socket changed'

def owner(pid):
    fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
    rows=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    result={'pid':pid,'ppid':int(fields[1]),'pgid':int(fields[2]),'startticks':int(fields[19]),
        'uid':int(rows['Uid'].split()[0]),'gid':int(rows['Gid'].split()[0]),
        'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    try:result['executable_realpath']=os.readlink(f'/proc/{pid}/exe')
    except OSError:result['executable_observation']='unavailable at original observation'
    return result

def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    with (DEST/name).open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return physical(DEST/name)

def command(name,argv,timeout,limit=1048576,pass_fds=(),acceptable_returncodes=(0,)):
    check_pins(); began=time.monotonic(); wall=time.time_ns(); timed_out=False; exceeded=False
    files={key:(DEST/(name+'.'+key+'.raw')).open('xb') for key in ('stdout','stderr')}
    child=None; own=None; rc=None; cleanup_error=None; primary=None; counts={'stdout':0,'stderr':0}
    selector=selectors.DefaultSelector()
    try:
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
    except BaseException as exc:
        primary=f'{type(exc).__name__}: {exc}'
    finally:
        cleanup_deadline=min(DEADLINE,time.monotonic()+15)
        try:
            if child is not None and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=max(0,min(1,cleanup_deadline-time.monotonic())))
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL)
                    child.wait(timeout=max(0,cleanup_deadline-time.monotonic()))
        except BaseException as exc:cleanup_error=f'{type(exc).__name__}: {exc}'
        finally:
            selector.close()
            if child is not None:
                for pipe in (child.stdout,child.stderr):pipe.close()
            for stream in files.values():stream.flush();os.fsync(stream.fileno());stream.close()
        rc=child.poll() if child is not None else None
        group_members=[]
        if own is not None:
            for p in Path('/proc').iterdir():
                if p.name.isdigit():
                    try:
                        parts=(p/'stat').read_text().rsplit(')',1)[1].split()
                        if int(parts[2])==own['pgid']:group_members.append({'pid':int(p.name),'startticks':int(parts[19]),'state':parts[0]})
                    except (OSError,ValueError):pass
        receipt={'argv':argv,'owner':own,'returncode':rc,'timed_out':timed_out,'capture_exceeded':exceeded,
            'failure':primary,'cleanup_error':cleanup_error,'started_at_ns':wall,'finished_at_ns':time.time_ns(),
            'elapsed_s':time.monotonic()-began,'process_group_members_at_terminal':group_members,
            'stdout':physical(DEST/(name+'.stdout.raw')),'stderr':physical(DEST/(name+'.stderr.raw')),
            'engine_backend_quiescence':'not inferred from original CLI status'}
        commands.append(write(name+'.terminal.v1.json',receipt))
    check_pins()
    if primary or cleanup_error or rc not in acceptable_returncodes or group_members:raise RuntimeError(name+' original failed; no retry')
    return (DEST/(name+'.stdout.raw')).read_bytes()


import re,uuid
assert subprocess.check_output(['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
    '--work-tree='+str(ROOT),'rev-parse','HEAD'],timeout=10,text=True).strip()==COMMIT
DEST.mkdir(mode=0o700)
sys.path.insert(0,str(ROOT/'scripts'))
from publication_operational_container_custody_v1 import _confirmed_absent,_state,_successful_terminal,_read_cid,PROJECTION,LABEL
BUILD=ROOT/'artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1'
LOADER=ROOT/'artifacts/benchmark_recovery_20260930/selected-gstreamer-packaged-preparation-v1/packaged_fixture_loader_v1.py'
container_id=None;state=None;removed=False;absence=False;launched=False;reservation=None
try:
    manifest=ROOT/'deploy/gstreamer_custom/publication/runtime-source-allowlist.txt'
    entries=[line for line in manifest.read_text().splitlines() if line and not line.startswith('#')]
    assert len(entries)==73
    tests=['test_checkpoint_gstreamer_analytics_sidecar','test_checkpoint_native_policy_runtime',
        'test_publication_guardian_runtime_expectations_v1','test_publication_operational_boundary_v1',
        'test_publication_guardian_component_preprocessing_contract_v1']
    inputs={ROOT/name for name in entries}
    inputs.update(ROOT/'tests'/(name+'.py') for name in tests)
    inputs.update({Path(__file__),LOADER,ROOT/'configs/analytics_execution_layer.yaml',
        ROOT/'configs/checkpoint_analytics_models_openvino.yaml',BUILD/'gstreamer_custom.runtime.freeze.json',
        BUILD/'operation.terminal.v1.json'})
    for path in sorted(inputs,key=str):pin(path)
    engine=pin('/usr/bin/docker');python=pin(sys.executable)
    socket=Path('/run/docker.sock').resolve(strict=True);socket_epoch=epoch(socket.lstat())
    assert stat.S_ISSOCK(socket.lstat().st_mode)
    ENV={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','DOCKER_HOST':'unix://'+str(socket)}
    receipt=json.loads((BUILD/'gstreamer_custom.runtime.freeze.json').read_bytes())
    original=json.loads((BUILD/'operation.terminal.v1.json').read_bytes())
    assert original['failure'] is None and receipt['candidate_binding_eligible'] is True and receipt['blockers']==[]
    image_id=receipt['physical_identity']['image_id'];assert original['image_id']==image_id
    files=dict(receipt['physical_identity']['embedded_files'])
    modules=[]
    for path in entries:
        if path.startswith('scripts/') and path.endswith('.py'):
            modules.append(Path(path).stem)
            files['/opt/vast/checkpoint/'+Path(path).name]=physical(ROOT/path)['sha256']
    assert len(modules)==62 and len(files)==71
    expectations=write('packaged-source-expectations.v1.json',{'files':files,'python_modules':modules})
    def docker(name,args,codes=(0,)):
        return command(name,[f'/proc/self/fd/{engine["fd"]}',*args],20,pass_fds=(engine['fd'],),acceptable_returncodes=codes)
    daemon=docker('daemon-before',['info','--format','{{json .ID}}'])
    actual=json.loads(docker('image-before',['image','inspect',image_id]));assert len(actual)==1
    assert actual[0]['Id']==image_id and actual[0]['RepoDigests']==[receipt['physical_identity']['canonical_repository_digest']]
    name='vast-component-fixtures-'+uuid.uuid4().hex
    reserved=time.time_ns()
    label=hashlib.sha256(json.dumps({'commit':COMMIT,'name':name,'image':image_id,'inputs':
        [row['descriptor'] for row in pins]},sort_keys=True).encode()).hexdigest()
    reservation={'name':name,'label':label,'reserved_at_ns':reserved,'container_image':{'image_id':image_id}}
    cidfile=DEST/'original.cid'
    absent=docker('name-reservation',['container','inspect','--format',PROJECTION,name],(1,))
    err=(DEST/'name-reservation.stderr.raw').read_bytes()
    assert _confirmed_absent(1,absent,err,name),'reserved name is occupied or absence unknown'
    args=['run','--name',name,'--cidfile',str(cidfile),'--label',LABEL+'='+label,
        '--network','none','--read-only','--pids-limit','256','--memory','2g','--cpus','2',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=536870912,mode=1777',
        '--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1','--env','MKL_NUM_THREADS=1','--env','NUMEXPR_NUM_THREADS=1',
        '--mount',f'type=bind,src={ROOT/"tests"},dst=/mnt/vast-tests,readonly',
        '--mount',f'type=bind,src={ROOT/"configs"},dst=/mnt/vast-configs,readonly',
        '--mount',f'type=bind,src={ROOT/"deploy/native_gst_probe"},dst=/mnt/vast-native-source,readonly',
        '--mount',f'type=bind,src={LOADER},dst=/mnt/vast-loader.py,readonly',
        '--mount',f'type=bind,src={DEST/"packaged-source-expectations.v1.json"},dst=/mnt/vast-expectations.json,readonly',
        '--entrypoint','/usr/bin/python3',image_id,'-I','-B','/mnt/vast-loader.py']
    write('prelaunch.v1.json',{'commit':COMMIT,'controller':owner(os.getpid()),'image_id':image_id,
        'build_terminal':physical(BUILD/'operation.terminal.v1.json'),'runtime_receipt':physical(BUILD/'gstreamer_custom.runtime.freeze.json'),
        'reservation':reservation,'cidfile':str(cidfile),'argv':[engine['descriptor']['path'],*args],
        'engine':engine['descriptor'],'python':python['descriptor'],'socket':{'path':str(socket),'epoch':socket_epoch},
        'inputs':[{'descriptor':p['descriptor'],'epoch':p['epoch']} for p in pins],
        'source_input_count':73,'delivered_file_count':71,'delivered_python_count':62,'test_count':19,
        'classification':'packaged real transport/component fixtures with local inference; no actual models/benchmark acceptance',
        'accepted':False,'publication_ready':False})
    launched=True
    command('packaged-component-front',[f'/proc/self/fd/{engine["fd"]}',*args],300,pass_fds=(engine['fd'],))
    container_id,_=_read_cid(cidfile)
    state_raw=docker('original-container-terminal',['container','inspect','--format',PROJECTION,container_id])
    state=_state(state_raw,reservation,container_id,time.time_ns());_successful_terminal(state,time.time_ns())
    assert not state['Running']
    removed_raw=docker('original-container-remove',['container','rm',container_id])
    assert removed_raw==(container_id+'\n').encode() and (DEST/'original-container-remove.stderr.raw').read_bytes()==b''
    removed=True
    for role,identifier in (('cid-absence',container_id),('name-absence',name)):
        out=docker(role,['container','inspect','--format',PROJECTION,identifier],(1,))
        assert _confirmed_absent(1,out,(DEST/(role+'.stderr.raw')).read_bytes(),identifier)
    absence=True
    assert docker('daemon-after',['info','--format','{{json .ID}}'])==daemon
    check_pins()
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}'
    if launched and reservation is not None and not removed:
        try:
            # Only the exact reserved name+label+image+creation-time join can
            # recover ownership if the original CLI failed before CID read.
            raw=docker('failed-original-owner',['container','inspect','--format',PROJECTION,reservation['name']])
            state=_state(raw,reservation,reservation['name'],time.time_ns());container_id=state['Id']
            if state['Running']:
                docker('failed-original-stop',['container','stop','--time','5',container_id])
                raw=docker('failed-original-terminal',['container','inspect','--format',PROJECTION,container_id])
                state=_state(raw,reservation,container_id,time.time_ns())
            assert state['Running'] is False and state['Pid']==0
            raw=docker('failed-original-remove',['container','rm',container_id]);assert raw==(container_id+'\n').encode()
            removed=True
            for role,identifier in (('failed-cid-absence',container_id),('failed-name-absence',reservation['name'])):
                out=docker(role,['container','inspect','--format',PROJECTION,identifier],(1,))
                assert _confirmed_absent(1,out,(DEST/(role+'.stderr.raw')).read_bytes(),identifier)
            absence=True
        except BaseException as cleanup_exc:
            failure+='; cleanup unknown/failed: '+type(cleanup_exc).__name__+': '+str(cleanup_exc)
finally:
    try:
        terminal=write('operation.terminal.v1.json',{'commit':COMMIT,'image_id':image_id,'failure':failure,'commands':commands,
            'container_id':container_id,'original_observed_state':state,'exact_owned_remove_completed':removed,
            'exact_cid_and_name_absence_after_remove':absence,'elapsed_s':time.monotonic()-START,
            'accepted':False,'publication_ready':False,'classification':'packaged fixture gate only; no model or benchmark acceptance'})
        print(json.dumps({'phase':'packaged_component_front_terminal','failure':failure,'receipt':terminal}),flush=True)
    finally:
        for p in pins:os.close(p['fd'])
sys.exit(0 if failure is None and time.monotonic()<DEADLINE else 78)
