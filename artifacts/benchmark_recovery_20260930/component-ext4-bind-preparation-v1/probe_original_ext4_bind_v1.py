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
    status=dict(line.split(':',1) for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line)
    assert int(status['Pid'])==pid
    try: executable=os.readlink('/proc/'+str(pid)+'/exe');unavailable=None
    except OSError as exc: executable=None;unavailable={'type':type(exc).__name__,'message':str(exc)[:2048]}
    return {'pid':pid,'ppid':int(s[1]),'pgid':int(s[2]),'startticks':int(s[19]),
            'uid':int(status['Uid'].split()[0]),'gid':int(status['Gid'].split()[0]),
            'executable':executable,'executable_unavailable':unavailable,'boot_id':TOKEN.split(':')[0]}

def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    assert len(raw)<=1048576
    with (OUTPUT/name).open('xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUTPUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def pin(path,sha=None,deadline=NORMAL):
    global fds_released
    assert time.monotonic()<deadline,'original source pin deadline'
    assert path.resolve(strict=True)==path
    for p in (path.parent,*path.parent.parents):
        assert stat.S_ISDIR(p.lstat().st_mode) and not p.is_symlink()
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=64*1024*1024
        assert epoch(s)==epoch(path.lstat())
        h=hashlib.sha256();size=0
        while block:=os.read(fd,65536):
            assert time.monotonic()<deadline,'original source pin deadline'
            size+=len(block);assert size<=64*1024*1024
            h.update(block)
        assert time.monotonic()<deadline,'original source pin deadline'
        assert epoch(s)==epoch(os.fstat(fd))==epoch(path.lstat())
        assert size==s.st_size
        digest=h.hexdigest()
        if sha is not None: assert digest==sha
        row={'path':str(path),'fd':fd,'epoch':epoch(s),'sha256':digest,'size_bytes':size}
        held.append(row);return row
    except BaseException as exc:
        try:os.close(fd)
        except BaseException as close_error:
            fds_released=False
            cleanup.append({'type':type(close_error).__name__,'message':str(close_error)[:2048]})
            exc.add_note('source FD close failed: '+str(close_error)[:2048])
        raise

def observe(row,deadline=NORMAL):
    assert time.monotonic()<deadline,'original source verification deadline'
    p=Path(row['path']);assert p.resolve(strict=True)==p
    assert row['epoch']==epoch(os.fstat(row['fd']))==epoch(p.lstat())
    os.lseek(row['fd'],0,os.SEEK_SET);h=hashlib.sha256();size=0
    while block:=os.read(row['fd'],65536):
        assert time.monotonic()<deadline,'original source verification deadline'
        size+=len(block);assert size<=row['size_bytes'] and size<=64*1024*1024
        h.update(block)
    assert time.monotonic()<deadline,'original source verification deadline'
    assert h.hexdigest()==row['sha256'] and size==row['size_bytes']
    assert row['epoch']==epoch(os.fstat(row['fd']))==epoch(p.lstat())
    return {k:v for k,v in row.items() if k!='fd'}

def command(argv,deadline=NORMAL,allow_failure=False):
    assert time.monotonic()<deadline,'original bind execution deadline'
    n=len(commands);child=None;sel=None;record={'argv':argv,'signals':[],'eof':{'stdout':False,'stderr':False}}
    streams={};sizes={'stdout':0,'stderr':0};failure=None;first_error=None;command_cleanup=[]
    def failed(exc):
        return {'type':type(exc).__name__,'message':str(exc)[:2048]}
    def cleanup_failed(exc):
        nonlocal first_error
        command_cleanup.append(failed(exc))
        if first_error is None:first_error=exc
    try:
        sel=selectors.DefaultSelector()
        for name in ('stdout','stderr'):
            streams[name]=(OUTPUT/('command%02d.%s.raw'%(n,name))).open('xb')
        child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        record['original_pid']=child.pid
        record['owner']=owner(child.pid);write('command%02d.launch.v1.json'%n,record)
        for name,p in (('stdout',child.stdout),('stderr',child.stderr)):
            os.set_blocking(p.fileno(),False);sel.register(p,selectors.EVENT_READ,name)
        while sel.get_map() or child.poll() is None:
            if time.monotonic()>=deadline:raise TimeoutError('original bind command deadline')
            for key,_ in sel.select(min(.05,max(0,deadline-time.monotonic()))):
                try:block=os.read(key.fd,65536)
                except BlockingIOError:continue
                if not block:
                    record['eof'][key.data]=True;sel.unregister(key.fileobj);continue
                assert sizes[key.data]+len(block)<=65536,'original command channel cap'
                written=streams[key.data].write(block)
                assert written==len(block),'original channel short write'
                sizes[key.data]+=written
        child.wait(timeout=max(.001,deadline-time.monotonic()))
        record['both_eof']=True
    except BaseException as exc:
        failure=failed(exc);first_error=exc
    finally:
        if child is not None:
            try:
                if child.poll() is None:
                    record['signals'].append('SIGKILL original live CLI group attempted')
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                child.wait(timeout=max(.001,END-time.monotonic()))
            except BaseException as exc:cleanup_failed(exc)
        if sel is not None:
            try:sel.close()
            except BaseException as exc:cleanup_failed(exc)
        if child is not None:
            for pipe in (child.stdout,child.stderr):
                if pipe is not None:
                    try:pipe.close()
                    except BaseException as exc:cleanup_failed(exc)
        for stream in streams.values():
            try:stream.flush();os.fsync(stream.fileno())
            except BaseException as exc:cleanup_failed(exc)
            finally:
                try:stream.close()
                except BaseException as exc:cleanup_failed(exc)
        record['returncode']=None if child is None else child.returncode
        if child is not None:
            record['original_pid_absent']=not Path('/proc',str(child.pid)).exists()
            try:os.killpg(child.pid,0);record['original_group_absent']=False
            except ProcessLookupError:record['original_group_absent']=True
            except BaseException as exc:cleanup_failed(exc)
        record['both_eof']=all(record['eof'].values())
        record['channels']={};record['captured_bytes_counter']=sizes
        for name in ('stdout','stderr'):
            path=OUTPUT/('command%02d.%s.raw'%(n,name))
            if name not in streams:record['channels'][name]=None;continue
            try:
                assert path.stat().st_size<=65536,'original channel physical byte cap'
                raw=path.read_bytes();assert len(raw)<=65536,'original channel physical byte cap'
                record['channels'][name]={'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                assert len(raw)==sizes[name],'original captured channel byte count differs'
            except BaseException as exc:
                cleanup_failed(exc);record['channels'][name]=None
        record['failure']=failure
        record['cleanup_errors']=command_cleanup
        commands.append(record)
        try:write('command%02d.terminal.v1.json'%n,record)
        except BaseException as exc:
            cleanup_failed(exc);record['terminal_persistence_failed']=True
    if first_error is not None:raise first_error
    assert failure is None and record.get('original_group_absent') is True
    if not allow_failure:assert record['returncode']==0,'original command nonzero'
    return record,Path(record['channels']['stdout']['path']).read_bytes(),Path(record['channels']['stderr']['path']).read_bytes()

def docker(args,deadline=NORMAL,allow_failure=False):
    return command(['/usr/bin/docker','--host','unix:///run/docker.sock',*args],deadline,allow_failure)

def not_found(record,stdout,stderr,identifier):
    prefixes=('Error response from daemon: No such container: ', 'Error: No such object: ', 'Error: No such container: ')
    return (type(record['returncode']) is int and record['returncode']==1 and stdout in (b'',b'\n',b'[]\n')
            and stderr in tuple((prefix+identifier+'\n').encode('ascii') for prefix in prefixes))

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
    sock=Path('/run/docker.sock');socket_stat=sock.lstat()
    assert sock.resolve(strict=True)==sock and stat.S_ISSOCK(socket_stat.st_mode)
    socket_before=epoch(socket_stat)[:4]
    socket_owner_before={'uid':socket_stat.st_uid,'gid':socket_stat.st_gid}
    _,raw,_=command(['/usr/bin/git','-c','core.longpaths=true','-C',str(ROOT),'rev-parse','HEAD'])
    assert raw==(COMMIT+'\n').encode()
    write('dispatch.v1.json',{'owner':owner(os.getpid()),'source_commit':COMMIT,'image':IMAGE,
        'target':str(ROOT),'container_name':NAME,'owner_label':{LABEL:TOKEN},'timeout_s':30,'cleanup_s':10,
        'inputs_before':[observe(r) for r in held],'socket_before':socket_before,'socket_owner_before':socket_owner_before,
        'native_model_gpu_acceptance':False,'publication_ready':False})
    absent,out,err=docker(['container','inspect',NAME],allow_failure=True)
    assert not_found(absent,out,err,NAME)
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
    gone,out,err=docker(['container','inspect',cid],allow_failure=True)
    assert not_found(gone,out,err,cid)
    gone,out,err=docker(['container','inspect',NAME],allow_failure=True)
    assert not_found(gone,out,err,NAME)
    socket_stat=sock.lstat()
    assert sock.resolve(strict=True)==sock and stat.S_ISSOCK(socket_stat.st_mode)
    assert epoch(socket_stat)[:4]==socket_before
    assert {'uid':socket_stat.st_uid,'gid':socket_stat.st_gid}==socket_owner_before
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
                assert not_found(lookup,raw,err,NAME)
        except BaseException as exc:cleanup.append({'type':type(exc).__name__,'message':str(exc)[:2048]})
    if cid is not None and not removed:
        try:
            owned=owned_inspect(END)
            if owned['State']['Running']:docker(['container','stop','--time','1',cid],END)
            assert owned_inspect(END)['State']['Running'] is False
            docker(['container','rm',cid],END);removed=True
            gone,out,err=docker(['container','inspect',cid],END,True)
            assert not_found(gone,out,err,cid)
            gone,out,err=docker(['container','inspect',NAME],END,True)
            assert not_found(gone,out,err,NAME)
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
        'inputs_after':locals().get('after'),
        'bind_reachability_only':True,'model_native_gpu_acceptance':False,'publication_ready':False}
    write('execution.v1.json',result)
    if time.monotonic()>=END:
        cleanup.append({'type':'TimeoutError','message':'original 30+10s deadline after final receipt publication'})
        write('late-failure.v1.json',{'status':'failed','cleanup_errors':cleanup,'elapsed_s':time.monotonic()-BEGAN})
        result['status']='failed'
    print(json.dumps({k:result[k] for k in ('status','elapsed_s','primary_error','container_id')}),flush=True)
sys.exit(0 if primary is None and not cleanup and time.monotonic()<END else 78)
