"""Future bounded CPU06 ZIP retention, only after authentic GPU terminal. No authority."""
from pathlib import Path, PurePosixPath
import hashlib,json,os,stat,sys,time,zipfile,zlib
START=time.monotonic();END=START+120
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
HERE=Path(__file__).parent;OUT=HERE/'original-retention-attempt01'
BASE=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'
GPU=BASE/'gpu-pair-01-original-controller/original.terminal.v1.json'
assert len(sys.argv)==3,'packer GPU_ORIGINAL_TERMINAL_SHA256 GPU_ORIGINAL_TERMINAL_SIZE'
GPU_SHA=sys.argv[1];GPU_SIZE=int(sys.argv[2]);assert len(GPU_SHA)==64 and all(c in '0123456789abcdef' for c in GPU_SHA) and 0<GPU_SIZE<=1048576
dirs={};metadata=[];first_error=None;report={};close_errors=[]
INVENTORY_SHA='f18913e434ceddd0f65dae6ad0b7b0c642d54b6d1ff9751e2c9bb28378ba2ce0'
def clock():
    if time.monotonic()>=END:raise TimeoutError('finite output retention120s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
def descriptor(path):
    clock();p=Path(path);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=256*1024*1024
        h=hashlib.sha256();count=0
        while b:=os.read(fd,1048576):clock();h.update(b);count+=len(b)
        assert count==s.st_size and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
        return {'path':str(p),'size_bytes':count,'sha256':h.hexdigest(),'epoch7':epoch(s)}
    finally:os.close(fd)
def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=1048576
    with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return descriptor(OUT/name)
def hold_directory(path):
    p=Path(path);assert p.resolve(strict=True)==p
    if p not in dirs:
        fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd);assert stat.S_ISDIR(s.st_mode) and identity(s)==identity(p.lstat());dirs[p]=(fd,identity(s))
        except BaseException:os.close(fd);raise
def held_metadata(path,expected_sha,expected_size=None):
    p=Path(path);assert p.resolve(strict=True)==p;fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=1048576
        raw=b''
        while b:=os.read(fd,65536):clock();raw+=b
        assert len(raw)==s.st_size and hashlib.sha256(raw).hexdigest()==expected_sha and (expected_size is None or len(raw)==expected_size)
        assert epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
        desc={'path':str(p),'size_bytes':len(raw),'sha256':expected_sha,'epoch7':epoch(s)};metadata.append((fd,p,epoch(s),raw));return raw,desc
    except BaseException:os.close(fd);raise
def namespace(inventory):
    found={};directory_names=set()
    for name in inventory['namespaces']:
        for current,children,files in os.walk(BASE/name,followlinks=False):
            clock();p=Path(current);assert p.resolve(strict=True)==p;hold_directory(p);directory_names.add(p.relative_to(BASE).as_posix())
            for child in children:assert stat.S_ISDIR((p/child).lstat().st_mode) and not (p/child).is_symlink()
            for child in files:
                leaf=p/child;s=leaf.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
                found[leaf.relative_to(BASE).as_posix()]=epoch(s)
    expected={r['relative_path']:r['original_epoch7'] for r in inventory['retained_files']+inventory['excluded_input_duplicates']}
    assert found==expected and directory_names=={d['relative_path'] for d in inventory['directories']}
    for d in inventory['directories']:
        assert identity((BASE/d['relative_path']).lstat())==[d[k] for k in ['dev','ino','mode','uid','gid']]
def absent_groups(ids):
    for p in Path('/proc').iterdir():
        clock()
        if not p.name.isdigit():continue
        try:
            text=(p/'stat').read_text();f=text[text.rfind(')')+2:].split();assert int(p.name) not in ids and int(f[2]) not in ids,'original GPU/controller group remains'
        except (FileNotFoundError,ProcessLookupError):assert not p.exists()
try:
    assert os.getuid()==os.getgid()==1000 and ROOT.resolve(strict=True)==ROOT
    for anchor in (BASE,HERE):
        for ancestor in reversed((anchor,*anchor.parents)):hold_directory(ancestor)
    gpu_raw,gpu=held_metadata(GPU,GPU_SHA,GPU_SIZE)
    terminal=json.loads(gpu_raw);assert terminal['source_commit']=='0ad78d6abdb3c526544a17185af7fe8094716735' and terminal['original_cli_process_group_members']==[]
    absent_groups({terminal['owner']['pid'],terminal['owner']['ppid'],terminal['owner']['pgid']})
    inventory_raw,inventory_descriptor=held_metadata(HERE/'inventory.v1.json',INVENTORY_SHA)
    inventory=json.loads(inventory_raw);assert inventory['source_base']==str(BASE) and inventory['retained_file_count']==128 and inventory['retained_bytes']==165944632
    assert inventory['all_file_count']==129 and inventory['all_bytes']==211515337 and inventory['namespaces']==['cpu-pair-06','cpu-pair-06-original-controller']
    assert len(inventory['excluded_input_duplicates'])==1 and inventory['excluded_input_duplicates'][0]['relative_path']=='cpu-pair-06/runtime/container-engine/docker' and inventory['excluded_input_duplicates'][0]['size_bytes']==45570705
    for r in inventory['retained_files']:
        member=PurePosixPath(r['relative_path']);assert not member.is_absolute() and '..' not in member.parts and '\\' not in r['relative_path'] and member.parts[0] in inventory['namespaces']
        assert r['original_uri']==str(BASE/str(member)) and r['size_bytes']<=64*1024*1024
    for ancestor in reversed((BASE,*BASE.parents)):hold_directory(ancestor)
    namespace(inventory);OUT.mkdir(mode=0o700)
    archive=OUT/'cpu06-original-output-retention.v1.zip';rows=[]
    with archive.open('xb') as physical:
        with zipfile.ZipFile(physical,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as package:
            for r in inventory['retained_files']:
                clock();p=Path(r['original_uri']);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
                try:
                    s=os.fstat(fd);assert epoch(s)==r['original_epoch7']==epoch(p.lstat());h=hashlib.sha256();crc=0;count=0
                    with package.open(r['relative_path'],'w') as member:
                        while b:=os.read(fd,1048576):
                            clock();member.write(b);h.update(b);crc=zlib.crc32(b,crc);count+=len(b)
                    assert count==r['size_bytes'] and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
                    info=package.getinfo(r['relative_path']);assert info.file_size==count and info.CRC==crc
                    rows.append({'member':r['relative_path'],'original_uri':str(p),'size_bytes':count,'sha256':h.hexdigest(),'original_epoch7':epoch(s),'terminal_epoch7':epoch(os.fstat(fd)),'crc32':crc})
                finally:os.close(fd)
            manifest={'schema_version':1,'artifact_kind':'vast_cpu06_original_output_retention_manifest_v1','retention_is_not_authority':True,'original_files':rows,'file_count':128,'original_bytes':165944632,'excluded_input_duplicates':inventory['excluded_input_duplicates'],'cpu_acceptance_proof_sha256':inventory['cpu_acceptance_proof_sha256'],'closed_original_gpu_terminal':gpu}
            package.writestr('retention-manifest.v1.json',(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
        physical.flush();os.fsync(physical.fileno())
    namespace(inventory)
    with zipfile.ZipFile(archive) as package:
        assert len(package.infolist())==129 and set(package.namelist())=={r['member'] for r in rows}|{'retention-manifest.v1.json'}
        assert json.loads(package.read('retention-manifest.v1.json'))==manifest
        for r in rows:
            clock();h=hashlib.sha256();count=0
            with package.open(r['member']) as member:
                while b:=member.read(1048576):clock();h.update(b);count+=len(b)
            assert count==r['size_bytes'] and h.hexdigest()==r['sha256'] and package.getinfo(r['member']).CRC==r['crc32']
    for p,(fd,s) in dirs.items():assert identity(os.fstat(fd))==s==identity(p.lstat())
    for fd,p,s,original in metadata:
        assert epoch(os.fstat(fd))==s==epoch(p.lstat());os.lseek(fd,0,os.SEEK_SET);raw=b''
        while b:=os.read(fd,65536):clock();raw+=b
        assert raw==original and epoch(os.fstat(fd))==s==epoch(p.lstat())
    report={'schema_version':1,'artifact_kind':'vast_cpu06_original_output_retention_receipt_v1','status':'complete_non_authority_retention','archive':descriptor(archive),'inventory':inventory_descriptor,'original_gpu_terminal':gpu,'original_file_count':128,'original_bytes':165944632,'zip_member_count':129,'all_member_crc_and_decompressed_sha256_verified':True,'source_namespace_before_after_exact':True,'source_original_epoch7_before_after_equal':True,'copied_engine_input_excluded_bytes':45570705,'retention_is_not_benchmark_source_or_publication_authority':True,'gpu_success_or_full_ci_not_claimed':True}
except BaseException as exc:
    first_error={'type':type(exc).__name__,'message':str(exc)[:4096]};report={'schema_version':1,'status':'failed_no_retention_acceptance','first_error':first_error,'preserve_partial_archive':True}
finally:
    for fd,_,_,_ in metadata:
        try:os.close(fd)
        except BaseException as exc:close_errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
    for fd,_ in dirs.values():
        try:os.close(fd)
        except BaseException as exc:close_errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
    report['directory_fds_released']=not close_errors;report['close_errors']=close_errors
    if not OUT.exists():OUT.mkdir(mode=0o700)
    ref=write('receipt.v1.json',report);print(json.dumps(ref),flush=True)
late=time.monotonic()>=END
if late:write('late-failure.v1.json',{'status':'failed_no_retention_acceptance','closed_receipt':ref,'first_error':first_error,'elapsed_s':time.monotonic()-START})
sys.exit(0 if first_error is None and not close_errors and not late else 1)
