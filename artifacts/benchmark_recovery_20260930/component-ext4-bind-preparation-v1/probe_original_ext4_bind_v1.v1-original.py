"""One original exact-image read-only ext4 bind probe; no model/native/GPU grant."""
from pathlib import Path
import hashlib, json, os, selectors, signal, stat, subprocess, sys, time

ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
OUTPUT=ROOT/'artifacts/benchmark_recovery_20260930/component-ext4-bind-original-v1'
IMAGE='sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6'
RELATIVE='artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json'
EXPECTED='61874c718d6140d0d5cf745988bc301b916077af8f80e96742184f80a0805db7'
assert len(sys.argv)==2 and len(sys.argv[1])==40
COMMIT=sys.argv[1]
assert all(c in '0123456789abcdef' for c in COMMIT)
BEGAN=time.monotonic(); NORMAL=BEGAN+30; END=NORMAL+10
commands=[]; held=[]; primary=None; cleanup=[]; cid=None; removed=False
create_attempted=False; fds_released=True
NAME='vast-d27-bind-'+str(os.getpid())
LABEL='vast.component.ext4-bind-owner'
TOKEN=Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+str(os.getpid())

def epoch(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

def owner(pid):
    s=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
    return {'pid':pid,'ppid':int(s[1]),'pgid':int(s[2]),'startticks':int(s[19]),
            'uid':Path('/proc',str(pid)).stat().st_uid,'boot_id':TOKEN.split(':')[0]}

def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    assert len(raw)<=1048576
    with (OUTPUT/name).open('xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUTPUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def pin(path,sha=None):
    assert path.resolve(strict=True)==path
    for p in (path.parent,*path.parent.parents):
        assert stat.S_ISDIR(p.lstat().st_mode) and not p.is_symlink()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
        assert epoch(s)==epoch(path.lstat())
        raw=b''
        while block:=os.read(fd,65536):
            raw+=block;assert len(raw)<=64*1024*1024
        assert epoch(s)==epoch(os.fstat(fd))==epoch(path.lstat())
        digest=hashlib.sha256(raw).hexdigest()
        if sha is not None: assert digest==sha
        row={'path':str(path),'fd':fd,'epoch':epoch(s),'sha256':digest,'size_bytes':len(raw)}
        held.append(row);return row
    except BaseException:
        os.close(fd);raise

def observe(row):
    p=Path(row['path']);assert p.resolve(strict=True)==p
    assert row['epoch']==epoch(os.fstat(row['fd']))==epoch(p.lstat())
    os.lseek(row['fd'],0,os.SEEK_SET);h=hashlib.sha256();size=0
    while block:=os.read(row['fd'],65536):h.update(block);size+=len(block)
    assert h.hexdigest()==row['sha256'] and size==row['size_bytes']
    assert row['epoch']==epoch(os.fstat(row['fd']))==epoch(p.lstat())
    return {k:v for k,v in row.items() if k!='fd'}

def command(argv,deadline=NORMAL,allow_failure=False):
    assert time.monotonic()<deadline,'original bind execution deadline'
    n=len(commands);child=None;sel=selectors.DefaultSelector();record={'argv':argv,'signals':[]}
    streams={c:(OUTPUT/('command%02d.%s.raw'%(n,c))).open('xb') for c in ('stdout','stderr')}
    sizes={'stdout':0,'stderr':0};failure=None
    try:
        child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        record['owner']=owner(child.pid);write('command%02d.launch.v1.json'%n,record)
        for name,p in (('stdout',child.stdout),('stderr',child.stderr)):
            os.set_blocking(p.fileno(),False);sel.register(p,selectors.EVENT_READ,name)
        while sel.get_map() or child.poll() is None:
            if time.monotonic()>=deadline:raise TimeoutError('original bind command deadline')
            for key,_ in sel.select(min(.05,max(0,deadline-time.monotonic()))):
                block=os.read(key.fd,65536)
                if not block:sel.unregister(key.fileobj);continue
                assert sizes[key.data]+len(block)<=65536,'original command channel cap'
                streams[key.data].write(block);sizes[key.data]+=len(block)
        child.wait(timeout=max(.001,deadline-time.monotonic()))
        record['both_eof']=True
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc)[:2048]}
        if child is not None and child.poll() is None:
            record['signals'].append('SIGKILL original live CLI group')
            os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=max(.001,END-time.monotonic()))
    finally:
        sel.close()
        if child is not None:
            child.stdout.close();child.stderr.close()
        for s in streams.values():s.flush();os.fsync(s.fileno());s.close()
        record['returncode']=None if child is None else child.returncode
        record['failure']=failure
        if child is not None:
            record['original_pid_absent']=not Path('/proc',str(child.pid)).exists()
            try:os.killpg(child.pid,0);record['original_group_absent']=False
            except ProcessLookupError:record['original_group_absent']=True
        record['channels']={c:{'path':str(OUTPUT/('command%02d.%s.raw'%(n,c))),
                              'size_bytes':sizes[c],
                              'sha256':hashlib.sha256((OUTPUT/('command%02d.%s.raw'%(n,c))).read_bytes()).hexdigest()}
                           for c in streams}
        commands.append(record);write('command%02d.terminal.v1.json'%n,record)
    assert failure is None and record.get('original_group_absent') is True
    if not allow_failure:assert record['returncode']==0,'original command nonzero'
    return record,Path(record['channels']['stdout']['path']).read_bytes(),Path(record['channels']['stderr']['path']).read_bytes()

def docker(args,deadline=NORMAL,allow_failure=False):
    return command(['/usr/bin/docker','--host','unix:///run/docker.sock',*args],deadline,allow_failure)

def owned_inspect(deadline=NORMAL):
    _,raw,_=docker(['container','inspect',cid],deadline)
    rows=json.loads(raw);assert len(rows)==1
    v=rows[0];assert v['Id']==cid and v['Image']==IMAGE and v['Config']['Labels'].get(LABEL)==TOKEN
    assert v['Name']=='/'+NAME
    return v

assert ROOT.resolve(strict=True)==ROOT and ROOT.stat().st_uid==os.getuid()
assert not os.path.lexists(OUTPUT);OUTPUT.mkdir(mode=0o700,parents=True)
try:
    assert ROOT.stat().st_dev==Path('/').stat().st_dev
    assert any(line.split()[4]=='/' and line.split(' - ')[1].split()[0]=='ext4'
               for line in Path('/proc/self/mountinfo').read_text().splitlines())
    input_row=pin(ROOT/RELATIVE,EXPECTED);helper=pin(Path(__file__).absolute())
    docker_binary=pin(Path('/usr/bin/docker'))
    sock=Path('/run/docker.sock');assert sock.resolve(strict=True)==sock and stat.S_ISSOCK(sock.lstat().st_mode)
    socket_before=epoch(sock.lstat())[:4]
    _,raw,_=command(['/usr/bin/git','-c','core.longpaths=true','-C',str(ROOT),'rev-parse','HEAD'])
    assert raw==(COMMIT+'\n').encode()
    write('dispatch.v1.json',{'owner':owner(os.getpid()),'source_commit':COMMIT,'image':IMAGE,
        'target':str(ROOT),'container_name':NAME,'owner_label':{LABEL:TOKEN},'timeout_s':30,'cleanup_s':10,
        'inputs_before':[observe(r) for r in held],'socket_before':socket_before,
        'native_model_gpu_acceptance':False,'publication_ready':False})
    absent,_,err=docker(['container','inspect',NAME],allow_failure=True)
    assert absent['returncode']==1 and b'No such container: '+NAME.encode() in err
    _,raw,_=docker(['image','inspect','--format','{{.Id}}',IMAGE]);assert raw==(IMAGE+'\n').encode()
    code="import hashlib,json;from pathlib import Path;p=Path('/vast-root/"+RELATIVE+"');raw=p.read_bytes();print(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)},sort_keys=True));assert hashlib.sha256(raw).hexdigest()=='"+EXPECTED+"'"
    create_attempted=True
    _,raw,_=docker(['container','create','--name',NAME,'--label',LABEL+'='+TOKEN,
        '--read-only','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--user','1000:1000','--mount','type=bind,source='+str(ROOT)+',target=/vast-root,readonly',
        '--entrypoint','/usr/bin/python3',IMAGE,'-I','-B','-c',code])
    candidate=raw.decode().strip();assert len(candidate)==64 and all(c in '0123456789abcdef' for c in candidate)
    cid=candidate
    initial=owned_inspect();assert initial['State']['Running'] is False
    _,probe,_=docker(['container','start','--attach',cid])
    assert json.loads(probe)=={'sha256':EXPECTED,'size_bytes':input_row['size_bytes']}
    final=owned_inspect();state=final['State']
    assert state['Running'] is False and state['Pid']==0 and state['ExitCode']==0 and state['OOMKilled'] is False
    assert final['Config']['User']=='1000:1000' and final['HostConfig']['ReadonlyRootfs'] is True
    mounts=[m for m in final['Mounts'] if m['Destination']=='/vast-root']
    assert len(mounts)==1 and mounts[0]['Type']=='bind' and mounts[0]['Source']==str(ROOT) and mounts[0]['RW'] is False
    write('positive-original-container.v1.json',{'container':final,'probe_payload':json.loads(probe),
          'native_model_gpu_acceptance':False,'publication_ready':False})
    docker(['container','rm',cid]);removed=True
    gone,_,err=docker(['container','inspect',cid],allow_failure=True)
    assert gone['returncode']==1 and b'No such container: '+cid.encode() in err
    assert epoch(sock.lstat())[:4]==socket_before
    after=[observe(r) for r in held]
    assert time.monotonic()<NORMAL
except BaseException as exc:
    primary={'type':type(exc).__name__,'message':str(exc)[:2048]}
finally:
    if create_attempted and cid is None:
        try:
            lookup,raw,err=docker(['container','inspect',NAME],END,True)
            if lookup['returncode']==0:
                rows=json.loads(raw);assert len(rows)==1
                v=rows[0];candidate=v['Id']
                assert len(candidate)==64 and all(c in '0123456789abcdef' for c in candidate)
                assert v['Name']=='/'+NAME and v['Image']==IMAGE and v['Config']['Labels'].get(LABEL)==TOKEN
                cid=candidate
                write('failure-only-owned-cid-resolution.v1.json',{'container':v,'native_model_gpu_acceptance':False})
            else:
                assert lookup['returncode']==1 and b'No such container: '+NAME.encode() in err
        except BaseException as exc:cleanup.append({'type':type(exc).__name__,'message':str(exc)[:2048]})
    if cid is not None and not removed:
        try:
            owned=owned_inspect(END)
            if owned['State']['Running']:docker(['container','stop','--time','1',cid],END)
            assert owned_inspect(END)['State']['Running'] is False
            docker(['container','rm',cid],END);removed=True
            gone,_,err=docker(['container','inspect',cid],END,True)
            assert gone['returncode']==1 and b'No such container: '+cid.encode() in err
        except BaseException as exc:cleanup.append({'type':type(exc).__name__,'message':str(exc)[:2048]})
    for r in held:
        try:os.close(r['fd'])
        except BaseException as exc:
            fds_released=False
            cleanup.append({'type':type(exc).__name__,'message':str(exc)[:2048]})
    elapsed=time.monotonic()-BEGAN
    if elapsed>=END:cleanup.append({'type':'TimeoutError','message':'original 30+10s total deadline exceeded'})
    result={'status':'passed' if primary is None and not cleanup else 'failed','primary_error':primary,
        'cleanup_errors':cleanup,'elapsed_s':elapsed,'commands':commands,'container_id':cid,
        'container_removed_without_force':removed,'all_held_fds_released':fds_released,
        'bind_reachability_only':True,'model_native_gpu_acceptance':False,'publication_ready':False}
    write('execution.v1.json',result)
    if time.monotonic()>=END:
        cleanup.append({'type':'TimeoutError','message':'original 30+10s deadline after final receipt publication'})
        write('late-failure.v1.json',{'status':'failed','cleanup_errors':cleanup,'elapsed_s':time.monotonic()-BEGAN})
        result['status']='failed'
    print(json.dumps({k:result[k] for k in ('status','elapsed_s','primary_error','container_id')}),flush=True)
sys.exit(0 if primary is None and not cleanup else 78)
