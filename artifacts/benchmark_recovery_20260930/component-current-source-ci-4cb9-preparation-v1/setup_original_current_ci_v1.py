"""Execute only the reviewed finite checkout commands and prerequisite gates."""
import hashlib,importlib.metadata,json,os,shutil,stat,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).parent;OUT=HERE/'original-setup-attempt01'
RECIPE=HERE/'recipe.v1.json';COMMIT='4cb9d8313cca71256179bc3b59cc6f9137e7b8ba'
BENCH=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
START=time.monotonic();END=START+300;held=[];commands=[];failure=None;report={}
def clock():
    if time.monotonic()>=END:raise TimeoutError('original CI setup300s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
def descriptor(p):
    raw=p.read_bytes();s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
    return {'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch7':epoch(s)}
def save(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=4*1048576
    with (OUT/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def owner(pid):
    p=Path('/proc',str(pid));v=(p/'stat').read_text().rsplit(')',1)[1].split();ids=dict(l.split(':',1) for l in (p/'status').read_text().splitlines() if ':' in l)
    return {'pid':pid,'ppid':int(v[1]),'pgid':int(v[2]),'startticks':int(v[19]),'state':v[0],'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def command(argv,label,cwd=None):
    clock();started=time.monotonic();stdout=OUT/(label+'.stdout.raw');stderr=OUT/(label+'.stderr.raw')
    with stdout.open('xb') as out,stderr.open('xb') as err:
        child=subprocess.Popen(argv,cwd=cwd,stdout=out,stderr=err);observed=owner(child.pid)
        launch={'argv':argv,'owner':observed,'started_at_ns':time.time_ns(),'cwd':None if cwd is None else str(cwd)};save(label+'.launch.json',launch)
        try:code=child.wait(timeout=max(.001,END-time.monotonic()))
        except BaseException:child.kill();child.wait(timeout=5);raise
        finally:out.flush();os.fsync(out.fileno());err.flush();os.fsync(err.fileno())
    row={**launch,'returncode':code,'elapsed_s':time.monotonic()-started,'child_reaped':True,'stdout':descriptor(stdout),'stderr':descriptor(stderr)};commands.append(row);save(label+'.terminal.json',row)
    assert row['stdout']['size_bytes']<=1048576 and row['stderr']['size_bytes']<=1048576 and code==0,label+' original command failure'
    return stdout.read_bytes()
def scan(ids):
    rows=[];errors=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            v=(p/'stat').read_text().rsplit(')',1)[1].split()
            if int(p.name) in ids:rows.append(owner(int(p.name)))
        except FileNotFoundError:pass
        except (OSError,ValueError) as exc:errors.append({'pid':int(p.name),'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
    return {'at_ns':time.time_ns(),'members':rows,'errors':errors,'pids_absent':{str(p):not Path('/proc',str(p)).exists() for p in sorted(ids)}}
try:
    assert os.getuid()==os.getgid()==1000 and sys.version_info[:3]==(3,12,3) and sys.implementation.name=='cpython'
    recipe_pin=descriptor(RECIPE);assert recipe_pin['size_bytes']==6954 and recipe_pin['sha256']=='3cf7baa8a668f96753b1572f798c48d86cc15491359b9bbf1d6193e4819fb9a7'
    recipe=json.loads(RECIPE.read_bytes());assert recipe['source_commit']==COMMIT
    root=Path(recipe['checkout']);output=Path(recipe['output']);parent=root.parent
    assert parent.resolve(strict=True)==parent and parent.lstat().st_uid==1000 and not os.path.lexists(root) and not os.path.lexists(output) and not os.path.lexists(OUT)
    available=os.statvfs(parent);assert available.f_bavail*available.f_frsize>=20*1024**3
    mounts=[]
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left,right=line.split(' - ',1);mount=left.split()[4].replace('\\040',' ')
        if parent==Path(mount) or Path(mount) in parent.parents:mounts.append((len(mount),mount,right.split()[0]))
    filesystem=max(mounts);assert filesystem[2]=='ext4'
    benchmark_identity=identity(BENCH.lstat());assert BENCH.resolve(strict=True)==BENCH and benchmark_identity[3:]==[1000,1000]
    original95=json.loads((HERE.parent/'component-gpu01-ext4-postterminal-audit-preparation-v1/held-inputs-and-processes.v1.json').read_bytes())['actual_current95'];assert len(original95)==95
    for row in original95:
        p=Path(row['descriptor']['path']);assert p.resolve(strict=True)==p
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);held.append((fd,p,row['epoch']));assert epoch(os.fstat(fd))==row['epoch']==epoch(p.lstat())
    python=Path(sys.executable).resolve(strict=True);ps=python.lstat();assert stat.S_ISREG(ps.st_mode) and ps.st_nlink==1
    OUT.mkdir(mode=0o700);save('launch.v1.json',{'owner':owner(os.getpid()),'argv':sys.argv,'source':descriptor(Path(__file__)),'recipe':recipe_pin,'benchmark_root_identity':benchmark_identity,'held95_epoch_only':True,'work_limit_s':300,'cleanup_s':10})
    gitbase=['/usr/bin/git','-c','core.longpaths=true']
    bench_head=command(gitbase+['-C',str(BENCH),'rev-parse','HEAD'],'00-benchmark-head').decode().strip();assert bench_head=='0ad78d6abdb3c526544a17185af7fe8094716735'
    command(gitbase+['--git-dir=/mnt/e/STUDY/VAST/.git','cat-file','-e',COMMIT+'^{commit}'],'01-source-commit')
    for n,argv in enumerate(recipe['setup_commands']):result=command(argv,f'{n+2:02d}-setup')
    assert (OUT/'06-setup.stdout.raw').read_text().strip()==COMMIT and (OUT/'07-setup.stdout.raw').read_bytes()==b''
    assert root.resolve(strict=True)==root and root.lstat().st_uid==root.lstat().st_gid==1000
    alternates=(root/'.git/objects/info/alternates').read_text().strip();assert Path(alternates).resolve(strict=True)==Path('/mnt/e/STUDY/VAST/.git/objects').resolve(strict=True)
    assert command(gitbase+['-C',str(root),'config','--get','core.autocrlf'],'08-autocrlf').strip()==b'false'
    tree=command(gitbase+['-C',str(root),'ls-tree','-rz','HEAD'],'09-tree');entries=[]
    for row in tree.split(b'\0'):
        if not row:continue
        meta,name=row.split(b'\t',1);mode,kind,oid=meta.split();relative=os.fsdecode(name)
        assert kind==b'blob' and mode in (b'100644',b'100755') and '\n' not in relative and root.joinpath(relative).resolve(strict=True)==root/relative
        entries.append((relative,oid.decode()))
    raw_rows=[];batch_argv=gitbase+['-C',str(root),'cat-file','--batch'];batch_start=time.monotonic()
    with (OUT/'10-cat-file.stderr.raw').open('xb') as err:
        child=subprocess.Popen(batch_argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err);batch_owner=owner(child.pid)
        try:
            for relative,oid in entries:
                clock();child.stdin.write((oid+'\n').encode());child.stdin.flush();header=child.stdout.readline();assert len(header)<=160
                actual_oid,kind,size=header.rstrip(b'\n').split();size=int(size);assert actual_oid.decode()==oid and kind==b'blob'
                p=root/relative;fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
                try:
                    s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==size
                    h=hashlib.sha256();remaining=size
                    while remaining:
                        clock();chunk=child.stdout.read(min(65536,remaining));assert chunk
                        actual=os.read(fd,len(chunk));assert actual==chunk;h.update(actual);remaining-=len(chunk)
                    assert child.stdout.read(1)==b'\n' and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
                    raw_rows.append({'path':relative,'git_oid':oid,'size_bytes':size,'sha256':h.hexdigest(),'epoch7':epoch(s)})
                finally:os.close(fd)
            child.stdin.close();assert child.stdout.read(1)==b'';code=child.wait(timeout=max(.001,END-time.monotonic()));assert code==0
        except BaseException:child.kill();child.wait(timeout=5);raise
        finally:
            child.stdout.close()
            if not child.stdin.closed:child.stdin.close()
            err.flush();os.fsync(err.fileno())
    batch_row={'argv':batch_argv,'owner':batch_owner,'returncode':code,'elapsed_s':time.monotonic()-batch_start,'child_reaped':True,'streamed_raw_blob_count':len(raw_rows),'streamed_raw_blob_bytes':sum(r['size_bytes'] for r in raw_rows),'stdout_retention':'Parsed streamed Git blobs compared byte-for-byte to held new-checkout leaves; per-leaf SHA retained, not duplicate raw payloads.','stderr':descriptor(OUT/'10-cat-file.stderr.raw')};commands.append(batch_row);save('10-cat-file.terminal.json',batch_row)
    source_rows=save('tracked-raw-source.v1.json',raw_rows)
    for relative,pin in recipe['source_pins'].items():
        found=next(row for row in raw_rows if row['path']==relative);assert found['size_bytes']==pin['size_bytes'] and found['sha256']==pin['sha256']
    mismatch=[];packages=[]
    for line in (root/'.ci/requirements.txt').read_text().splitlines():
        if not line or line.startswith('#'):continue
        name,expected=line.split('==');actual=importlib.metadata.version(name);packages.append({'name':name,'expected':expected,'actual':actual})
        if actual!=expected:mismatch.append(name)
    assert not mismatch,'pinned dependency mismatch:'+','.join(mismatch)
    command([str(python),'-I','-B','-m','pip','check'],'11-pip-check')
    native_packages=['build-essential','cmake','pkg-config','libglib2.0-dev','libgstreamer1.0-dev','libgstreamer-plugins-base1.0-dev','gstreamer1.0-plugins-base','gstreamer1.0-tools']
    native=command(['/usr/bin/dpkg-query','-W','-f=${Package}\t${Version}\t${Status}\n',*native_packages],'12-native-packages').decode()
    assert len(native.splitlines())==len(native_packages) and all(row.endswith('install ok installed') for row in native.splitlines())
    tools={name:str(Path(shutil.which(name)).resolve(strict=True)) for name in ('cmake','pkg-config','g++','gst-inspect-1.0')}
    assert command(gitbase+['-C',str(BENCH),'rev-parse','HEAD'],'13-benchmark-head').decode().strip()==bench_head
    assert identity(BENCH.lstat())==benchmark_identity
    for fd,p,before in held:assert epoch(os.fstat(fd))==before==epoch(p.lstat())
    ids={row['owner']['pid'] for row in commands};scans=[scan(ids),scan(ids)];assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
    report={'schema_version':1,'artifact_kind':'vast_current_source_ext4_ci_setup_v1','status':'prepared_exact_source_and_prerequisites','source_commit':COMMIT,'root':str(root),'output_future':str(output),'actual_ci_terminal':None,'raw_committed_bytes_equal':True,'tracked_count':len(raw_rows),'tracked_bytes':sum(row['size_bytes'] for row in raw_rows),'tracked_source_inventory':source_rows,'eight_reviewed_source_pins_equal':True,'root_identity':identity(root.lstat()),'parent_filesystem':filesystem,'available_bytes_before':available.f_bavail*available.f_frsize,'shared_object_alternate':alternates,'canonical_python':descriptor(python),'python_version':sys.version,'packages':packages,'native_packages':native,'tools':tools,'commands':commands,'command_process_scans':scans,'benchmark_root_identity_unchanged':True,'benchmark_root_head_unchanged':bench_head,'benchmark95_input_epochs_unchanged':True,'retention_and_setup_not_benchmark_or_ci_acceptance':True}
except BaseException as exc:
    failure={'type':type(exc).__name__,'message':str(exc)[:4096]};report={'schema_version':1,'artifact_kind':'vast_current_source_ext4_ci_setup_v1','status':'failed_no_ci_launch','first_error':failure,'commands':commands,'source_commit':COMMIT,'retain_original_namespace':True}
finally:
    closes=[]
    for fd,_,_ in held:
        try:os.close(fd)
        except OSError as exc:closes.append({'type':type(exc).__name__,'errno':exc.errno})
    report['held95_fds_released']=not closes;report['close_errors']=closes
    if not OUT.exists():OUT.mkdir(mode=0o700)
    ref=save('execution.v1.json',report);print(json.dumps(ref),flush=True)
late=time.monotonic()>=END
if late:save('late-failure.v1.json',{'status':'failed_no_ci_launch','closed_report':ref,'first_error':failure,'elapsed_after_final_receipt_and_fdclose_s':time.monotonic()-START})
sys.exit(0 if failure is None and not closes and not late else 1)
