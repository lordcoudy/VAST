"""Execute only the reviewed finite checkout commands and prerequisite gates."""
import hashlib,importlib.metadata,json,os,shutil,stat,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).parent;OUT=HERE/'original-setup-attempt01'
RECIPE=HERE/'recipe.bound.v1.json';COMMIT=None;BENCHMARK_COMMIT='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
BENCH=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
START=time.monotonic();END=START+300;held=[];commands=[];failure=None;report={};manifest_fd=None;manifest_before=None;manifest_parent_before=None
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
    assert len(sys.argv)==3,'usage: setup ACTUAL_RECIPE_SIZE ACTUAL_RECIPE_SHA256'
    expected_recipe_size=int(sys.argv[1]);expected_recipe_sha=sys.argv[2]
    assert 0<expected_recipe_size<=1048576 and len(expected_recipe_sha)==64 and all(c in '0123456789abcdef' for c in expected_recipe_sha)
    recipe_pin=descriptor(RECIPE);assert recipe_pin['size_bytes']==expected_recipe_size and recipe_pin['sha256']==expected_recipe_sha
    recipe=json.loads(RECIPE.read_bytes());COMMIT=recipe['source_commit']
    assert type(COMMIT) is str and len(COMMIT)==40 and all(c in '0123456789abcdef' for c in COMMIT)
    assert recipe['benchmark_root_commit_untouched']==BENCHMARK_COMMIT and COMMIT!=BENCHMARK_COMMIT
    assert recipe['benchmark_source_impact_review']=={'path': '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-ci-clock-independent-source-review-v1/review.v1.json', 'size_bytes': 9951, 'sha256': '835bf6c7c991c78062adc39459b34f51eab7c598c71185a7b00fe777f62f9d6d'}
    assert recipe['benchmark_source_impact_inventory']=={'path': '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-ci-clock-independent-source-review-v1/source-impact.v1.json', 'size_bytes': 160709, 'sha256': 'dcdc63621620f579653574d0a1380baac2d683c117d83b8b194b46e67abb2a41'}
    assert recipe['reviewed_ci_path_pins']=={'scripts/ci_namespace_diagnostic_v1.py': {'size_bytes': 25359, 'sha256': 'bc69cdd5db314b7421d87fdaeb3a88d9411ae0f2e29713f75bc8909dfe8b0292'}, 'scripts/ci_userns_profile_v1.py': {'size_bytes': 28890, 'sha256': '5bd7622130c41d8bef03d2da87f87c987738478a5b77412857fd85f24c73cf43'}, 'tests/test_ci_namespace_diagnostic_v1.py': {'size_bytes': 33264, 'sha256': '5c8519ff1a1d600ba6ed72051498dd0da62f68d89e29b48079f546315bb7ac64'}, 'tests/test_ci_userns_profile_v1.py': {'size_bytes': 41955, 'sha256': 'dbcea702679255fd64bb223875385fc1800ed0946958e83ceefda59a0fdc2695'}}
    root=Path(recipe['checkout']);output=Path(recipe['output']);parent=root.parent
    assert parent.resolve(strict=True)==parent and parent.lstat().st_uid==1000 and not os.path.lexists(root) and not os.path.lexists(output) and not os.path.lexists(OUT)
    available=os.statvfs(parent);assert available.f_bavail*available.f_frsize>=20*1024**3
    mounts=[]
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left,right=line.split(' - ',1);mount=left.split()[4].replace('\\040',' ')
        if parent==Path(mount) or Path(mount) in parent.parents:mounts.append((len(mount),mount,right.split()[0]))
    filesystem=max(mounts);assert filesystem[2]=='ext4'
    benchmark_identity=identity(BENCH.lstat());assert BENCH.resolve(strict=True)==BENCH and benchmark_identity[3:]==[1000,1000]
    manifest_expected=recipe['current95_manifest'];assert set(manifest_expected)=={'path','size_bytes','sha256'}
    manifest_path=HERE.parent/'decision28-current95-preparation-v1/decision28-current95-original-attempt01/current95-inputs.v1.json'
    assert manifest_expected['path']==str(manifest_path) and type(manifest_expected['size_bytes']) is int and 0<manifest_expected['size_bytes']<=1048576
    assert manifest_path.resolve(strict=True)==manifest_path and manifest_path.parent.resolve(strict=True)==manifest_path.parent
    manifest_parent_before=identity(manifest_path.parent.lstat())
    manifest_fd=os.open(manifest_path,os.O_RDONLY|os.O_NOFOLLOW);manifest_before=epoch(os.fstat(manifest_fd))
    assert stat.S_ISREG(os.fstat(manifest_fd).st_mode) and os.fstat(manifest_fd).st_nlink==1 and manifest_before==epoch(manifest_path.lstat())
    manifest_raw=os.read(manifest_fd,manifest_expected['size_bytes']+1)
    assert len(manifest_raw)==manifest_expected['size_bytes'] and hashlib.sha256(manifest_raw).hexdigest()==manifest_expected['sha256']
    current95=json.loads(manifest_raw)
    assert current95['schema_version']==1 and current95['artifact_kind']=='vast_current_selected_setup95_metadata_v1'
    assert current95['source_commit']==BENCHMARK_COMMIT and current95['project_root']==str(BENCH) and current95['all_collection_fds_released'] is True
    assert current95['composition']=={'role_documents':6,'fresh_project_sources':87,'canonical_interpreter':1,'exact_current_controller':1,'unique_total':95}
    assert current95['fresh_stock_closure_descriptor']==recipe['fresh_stock_closure_descriptor'] and current95['current_controller_descriptor']==recipe['current_controller_descriptor']
    original95=current95['actual_current95'];assert len(original95)==len({r['descriptor']['path'] for r in original95})==95
    for row in original95:
        p=Path(row['descriptor']['path']);assert p.resolve(strict=True)==p
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);held.append((fd,p,row['epoch']));assert epoch(os.fstat(fd))==row['epoch']==epoch(p.lstat())
    python=Path(sys.executable).resolve(strict=True);ps=python.lstat();assert stat.S_ISREG(ps.st_mode) and ps.st_nlink==1
    OUT.mkdir(mode=0o700);save('launch.v1.json',{'owner':owner(os.getpid()),'argv':sys.argv,'source':descriptor(Path(__file__)),'recipe':recipe_pin,'benchmark_root_identity':benchmark_identity,'held95_epoch_only':True,'work_limit_s':300,'cleanup_s':10})
    gitbase=['/usr/bin/git','-c','core.longpaths=true']
    bench_head=command(gitbase+['-C',str(BENCH),'rev-parse','HEAD'],'00-benchmark-head').decode().strip();assert bench_head==BENCHMARK_COMMIT
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
    for relative,pin in [*recipe['source_pins'].items(),*recipe['reviewed_ci_path_pins'].items()]:
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
    os.lseek(manifest_fd,0,os.SEEK_SET);assert os.read(manifest_fd,manifest_expected['size_bytes']+1)==manifest_raw
    assert manifest_before==epoch(os.fstat(manifest_fd))==epoch(manifest_path.lstat()) and manifest_path.resolve(strict=True)==manifest_path
    assert identity(manifest_path.parent.lstat())==manifest_parent_before and manifest_path.parent.resolve(strict=True)==manifest_path.parent
    ids={row['owner']['pid'] for row in commands};scans=[scan(ids),scan(ids)];assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
    report={'schema_version':1,'artifact_kind':'vast_current_source_ext4_ci_setup_v1','status':'prepared_exact_source_and_prerequisites','source_commit':COMMIT,'root':str(root),'output_future':str(output),'actual_ci_terminal':None,'raw_committed_bytes_equal':True,'tracked_count':len(raw_rows),'tracked_bytes':sum(row['size_bytes'] for row in raw_rows),'tracked_source_inventory':source_rows,'eight_reviewed_source_pins_equal':True,'root_identity':identity(root.lstat()),'parent_filesystem':filesystem,'available_bytes_before':available.f_bavail*available.f_frsize,'shared_object_alternate':alternates,'canonical_python':descriptor(python),'python_version':sys.version,'packages':packages,'native_packages':native,'tools':tools,'commands':commands,'command_process_scans':scans,'benchmark_root_identity_unchanged':True,'benchmark_root_head_unchanged':bench_head,'benchmark_root_commit':BENCHMARK_COMMIT,'ci_checkpoint_distinct_from_benchmark':COMMIT!=BENCHMARK_COMMIT,'benchmark95_input_epochs_unchanged':True,'retention_and_setup_not_benchmark_or_ci_acceptance':True}
except BaseException as exc:
    failure={'type':type(exc).__name__,'message':str(exc)[:4096]};report={'schema_version':1,'artifact_kind':'vast_current_source_ext4_ci_setup_v1','status':'failed_no_ci_launch','first_error':failure,'commands':commands,'source_commit':COMMIT,'retain_original_namespace':True}
finally:
    closes=[]
    for fd,_,_ in held:
        try:os.close(fd)
        except OSError as exc:closes.append({'type':type(exc).__name__,'errno':exc.errno})
    if manifest_fd is not None:
        try:os.close(manifest_fd);manifest_fd=None
        except OSError as exc:closes.append({'type':type(exc).__name__,'errno':exc.errno})
    report['current95_manifest_fd_released']=manifest_fd is None
    report['held95_fds_released']=not closes;report['close_errors']=closes
    if not OUT.exists():OUT.mkdir(mode=0o700)
    ref=save('execution.v1.json',report);print(json.dumps(ref),flush=True)
late=time.monotonic()>=END
if late:save('late-failure.v1.json',{'status':'failed_no_ci_launch','closed_report':ref,'first_error':failure,'elapsed_after_final_receipt_and_fdclose_s':time.monotonic()-START})
sys.exit(0 if failure is None and not closes and not late else 1)
