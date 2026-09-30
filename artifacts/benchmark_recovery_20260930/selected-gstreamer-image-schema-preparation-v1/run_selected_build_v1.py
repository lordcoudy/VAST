"""Once-only original stock selected build/capture; no model/benchmark grant."""
import hashlib, json, os, selectors, signal, stat, subprocess, sys, time
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
COMMIT = 'a4e145b7bf32e0c870b114e303e9adb6a559d0ef'
TAG = 'vast/gstreamer-custom-publication-runtime-v3:component-release-20260930-a4e145b7'
BASE = 'sha256:b102aafc0f88f8cfad92349e6a55d0f9755a3f5bff109a70ebdb8936d4a8e84c'
DEST = ROOT / 'artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1'
NATIVE = ROOT / 'artifacts/fix_benchmark_preparations_20260928g/native-a/native_probe.freeze.json'
START = time.monotonic()
DEADLINE = START + 1200
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

def command(name,argv,timeout,limit=1048576,pass_fds=()):
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
    if primary or cleanup_error or rc!=0 or group_members:raise RuntimeError(name+' original failed; no retry')
    return (DEST/(name+'.stdout.raw')).read_bytes()

assert subprocess.check_output(['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
    '--work-tree='+str(ROOT),'rev-parse','HEAD'],timeout=10,text=True).strip()==COMMIT
DEST.mkdir(mode=0o700)
try:
    inputs={NATIVE,Path(__file__),ROOT/'scripts/build_gstreamer_custom_publication_runtime_v3.sh',
        ROOT/'scripts/publication_qualification_image_refreeze_v1.py',ROOT/'scripts/publication_image_build_v1.py',
        ROOT/'configs/publication_image_build_v1.json',ROOT/'configs/publication_qualification_image_refreeze_v1.json'}
    for name in ('runtime-source-allowlist.txt','runtime-dependency-allowlist.txt','runtime-build-context-allowlist.txt'):
        manifest=ROOT/'deploy/gstreamer_custom/publication'/name;inputs.add(manifest)
        inputs.update(ROOT/line for line in manifest.read_text().splitlines() if line and not line.startswith('#'))
    for p in sorted(inputs,key=str):pin(p)
    engine=pin('/usr/bin/docker');shell=pin('/usr/bin/bash');python=pin(sys.executable)
    socket=Path('/run/docker.sock').resolve(strict=True);socket_epoch=epoch(socket.lstat())
    assert stat.S_ISSOCK(socket.lstat().st_mode)
    ENV={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','DOCKER_HOST':'unix://'+str(socket),
        'VAST_OPENVINO_NATIVE_PROBE_IMAGE':'vast/openvino-native-probe:dlstreamer-2026.1',
        'VAST_OPENVINO_NATIVE_PROBE_IMAGE_ID':BASE,'VAST_GSTREAMER_RUNTIME_IMAGE':TAG}
    write('prelaunch.v1.json',{'commit':COMMIT,'controller':owner(os.getpid()),'environment':ENV,
        'engine':engine['descriptor'],'shell':shell['descriptor'],'python':python['descriptor'],
        'socket':{'path':str(socket),'epoch':socket_epoch},'inputs':[{'descriptor':p['descriptor'],'epoch':p['epoch']} for p in pins],
        'deadline_monotonic_s':DEADLINE,'accepted':False,'publication_ready':False})
    def docker(name,args):return command(name,[f'/proc/self/fd/{engine["fd"]}',*args],60,pass_fds=(engine['fd'],))
    daemon=docker('daemon-before',['info','--format','{{json .ID}}'])
    base=json.loads(docker('base-before',['image','inspect','vast/openvino-native-probe:dlstreamer-2026.1']))
    assert len(base)==1 and base[0]['Id']==BASE
    for i,ref in enumerate((TAG,TAG+'-determinism-a',TAG+'-determinism-b')):
        assert docker('tag-reservation-'+str(i),['image','ls','--filter','reference='+ref,'--format','{{json .}}'])==b'', 'candidate tag occupied'
    build=command('stock-two-build',['/usr/bin/bash',str(ROOT/'scripts/build_gstreamer_custom_publication_runtime_v3.sh')],900,16*1048576)
    fields=dict(line.split('=',1) for line in build.decode().splitlines() if '=' in line)
    image_id=fields['image_id'];assert fields['image_ref']==TAG and fields['base_image_id']==BASE
    assert image_id.startswith('sha256:') and len(image_id)==71
    current=json.loads(docker('image-after',['image','inspect',TAG,TAG+'-determinism-a',TAG+'-determinism-b']))
    assert len(current)==3 and all(row['Id']==image_id for row in current)
    capture=[sys.executable,'-B',str(ROOT/'scripts/publication_qualification_image_refreeze_v1.py'),'capture',
        '--project-root',str(ROOT),'--registry',str(ROOT/'configs/publication_qualification_image_refreeze_v1.json'),
        '--system','gstreamer_custom','--native-receipt',str(NATIVE),'--candidate-final-reference',TAG,
        '--receipt-output',str(DEST/'gstreamer_custom.runtime.freeze.json'),'--docker','/usr/bin/docker']
    command('stock-selected-capture',capture,180,1048576)
    receipt=json.loads((DEST/'gstreamer_custom.runtime.freeze.json').read_bytes())
    assert receipt['candidate_binding_eligible'] is True and receipt['blockers']==[]
    assert receipt['physical_identity']['image_id']==image_id
    assert docker('candidate-container-terminal',['container','ls','--all','--filter','ancestor='+image_id,'--format','{{json .}}'])==b''
    assert docker('daemon-after',['info','--format','{{json .ID}}'])==daemon
    check_pins()
except BaseException as exc:
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
