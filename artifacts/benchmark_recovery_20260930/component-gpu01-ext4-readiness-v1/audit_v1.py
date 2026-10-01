"""One finite pure stock95 GPU readiness gate; no model/engine/native execution."""
from pathlib import Path
import ast, hashlib, json, os, stat, subprocess, sys, time
START=time.monotonic(); END=START+120
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
WINDOWS=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
COMMIT='0ad78d6abdb3c526544a17185af7fe8094716735'
CLOSURE='adbcb638a5f104e43c95b84e4d16388a8111d39321afb3e8e7a26f2ef537b498'
CONTROLLER=ROOT/'artifacts/benchmark_recovery_20260930/component-ext4-relocation-preparation-v1/run_original_gpu_component_pair_ext4_v3.py'
CONTROLLER_SHA='6200b55afd15ca2b9964a52de3fc0ae1fd4f6e72b131b50afa74fac01fad24b2'
PAIR=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-01'
DEST=PAIR.parent/'gpu-pair-01-original-controller'
CPU=WINDOWS/'artifacts/benchmark_recovery_20260930/component-cpu06-ext4-actual-audit-closure-v1/review.v1.json'
held={}; custody=None; first_error=None; close_errors=[]; report={}; baseline_fds=len(list(Path('/proc/self/fd').iterdir()))
def clock():
    if time.monotonic()>=END: raise TimeoutError('pure readiness120s')
def epoch(s): return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(path,sha=None):
    clock(); p=Path(path); assert p.resolve(strict=True)==p
    if p not in held:
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            s=os.fstat(fd); assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=64*1024*1024
            digest=hashlib.sha256(); chunks=[]
            while block:=os.read(fd,1048576): clock();digest.update(block);chunks.append(block)
            raw=b''.join(chunks); assert len(raw)==s.st_size and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
            held[p]={'fd':fd,'raw':raw,'descriptor':{'path':str(p),'size_bytes':len(raw),'sha256':digest.hexdigest()},'epoch':epoch(s)}
        except BaseException: os.close(fd);raise
    row=held[p]
    if sha is not None: assert row['descriptor']['sha256']==sha
    return row
def record(row): return {'descriptor':row['descriptor'],'epoch':row['epoch']}
def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode(); assert len(raw)<=1048576
    with (OUT/name).open('xb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def git(*args):
    clock(); argv=['/usr/bin/git','-c','core.longpaths=true','--git-dir='+str(ROOT/'.git'),'--work-tree='+str(ROOT),*args]
    value=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=min(10,END-time.monotonic()),check=True)
    assert len(value.stdout)<=1048576 and value.stderr==b''
    return {'argv':argv,'returncode':value.returncode,'stdout':value.stdout.decode()}
def scan(ids):
    members=[]; errors=[]
    for path in Path('/proc').iterdir():
        clock()
        if not path.name.isdigit(): continue
        try:
            text=(path/'stat').read_text();fields=text[text.rfind(')')+2:].split();pid=int(path.name);pgid=int(fields[2])
            if pid in ids or pgid in ids:
                owner=path.stat();members.append({'pid':pid,'pgid':pgid,'ppid':int(fields[1]),'startticks':int(fields[19]),'uid':owner.st_uid,'gid':owner.st_gid})
        except (FileNotFoundError,ProcessLookupError):
            if path.exists(): errors.append({'pid':path.name,'error':'proc leaf unavailable while directory remains'})
        except BaseException as exc: errors.append({'pid':path.name,'type':type(exc).__name__,'message':str(exc)[:512]})
    return {'at_ns':time.time_ns(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'members':members,'errors':errors,'actual_pids_absent':{str(pid):not Path('/proc',str(pid)).exists() for pid in ids}}
try:
    current=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    parent=Path('/proc',str(os.getppid()),'stat').read_text().rsplit(')',1)[1].split()
    write('audit.launch.v1.json',{'argv':sys.argv,'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),'startticks':int(current[19]),'uid':os.getuid(),'gid':os.getgid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'parent_startticks':int(parent[19]),'parent_executable':str(Path('/proc',str(os.getppid()),'exe').resolve(strict=True)),'reader_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_only_not_gpu_dispatch':True})
    assert os.getuid()==os.getgid()==1000 and ROOT.resolve(strict=True)==ROOT
    root_info=ROOT.lstat(); assert stat.S_ISDIR(root_info.st_mode) and root_info.st_uid==root_info.st_gid==1000 and stat.S_IMODE(root_info.st_mode)==0o700
    initial_root=[root_info.st_dev,root_info.st_ino,root_info.st_mode,root_info.st_uid,root_info.st_gid]
    mounts=[]
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left,right=line.split(' - ',1);parts=left.split();mount=Path(parts[4]);fs=right.split()[0]
        if ROOT==mount or mount in ROOT.parents: mounts.append((len(mount.parts),str(mount),fs))
    assert max(mounts)[2]=='ext4'
    cpu_pin=pin(CPU,'20c896c126454b17f747d2b119b6a60444f7d8bc338184782eb68ec8ab37218a');cpu=json.loads(cpu_pin['raw'])
    assert cpu['task_18_8_complete'] and cpu['benchmark_accepted_cpu_component_only'] and cpu['reviewer_metadata_fds_released'] and cpu['original_audit_fds_released'] and cpu['source_commit']==COMMIT
    controller=pin(CONTROLLER,CONTROLLER_SHA);assert controller['descriptor']['size_bytes']==15089
    tree=ast.parse(controller['raw']);expected_node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='EXPECTED')
    expected={}
    for k,v in zip(expected_node.keys,expected_node.values):
        assert isinstance(v,ast.Tuple) and len(v.elts)==2
        sha=CLOSURE if isinstance(v.elts[1],ast.Name) and v.elts[1].id=='CLOSURE_SHA256' else ast.literal_eval(v.elts[1])
        expected[ast.literal_eval(k)]=(ast.literal_eval(v.elts[0]),sha)
    assert len(expected)==6
    inputs=[pin(ROOT/relative,sha) for relative,sha in expected.values()]
    closure_path=ROOT/expected['execution_code_closure_path'][0];closure=json.loads(held[closure_path]['raw'])
    assert closure['status']=='frozen' and len(closure['project_sources'])==87 and len({r['path'] for r in closure['project_sources']})==87
    sources=[]
    for row in closure['project_sources']:
        relative=Path(row['path']);assert not relative.is_absolute() and '..' not in relative.parts
        current=pin(ROOT/relative,row['sha256']);assert current['descriptor']['size_bytes']==row['size_bytes'];sources.append(current)
    interpreter=pin(Path(sys.executable),closure['interpreter']['sha256'])
    stock95=[record(row) for row in [*inputs,*sources,interpreter,controller]];assert len(stock95)==95 and len({r['descriptor']['path'] for r in stock95})==95
    sys.path.insert(0,str(ROOT/'scripts'))
    from publication_policy_qualification_execution_code_closure_v1 import load_execution_code_closure_v1,assert_loaded_project_modules_covered_v1
    from publication_physical_io_v1 import PhysicalRootCustodyV1
    custody=PhysicalRootCustodyV1.open(ROOT,label='pure GPU predispatch root')
    loaded=load_execution_code_closure_v1(project_root=ROOT,receipt_path=closure_path)
    assert loaded['receipt']==closure and loaded['receipt_descriptor']=={'path':expected['execution_code_closure_path'][0],'size_bytes':held[closure_path]['descriptor']['size_bytes'],'sha256':CLOSURE}
    assert_loaded_project_modules_covered_v1(project_root=ROOT,receipt=loaded['receipt'])
    runtime=json.loads(held[ROOT/expected['runtime_image_receipt_path'][0]]['raw']); image=runtime['physical_identity']
    assert runtime['candidate_binding_eligible'] and runtime['blockers']==[] and image['image_id']=='sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6' and image['source_identity']['runtime_source_count']==73
    assert image['canonical_repository_digest_observed'] and image['canonical_repository_digest'] in image['observed_repository_digests']
    scratch=Path('/tmp');socket=Path('/run/docker.sock');assert scratch.resolve(strict=True)==scratch and socket.resolve(strict=True)==socket
    assert stat.S_ISDIR(scratch.lstat().st_mode) and stat.S_ISSOCK(socket.lstat().st_mode)
    scratch_identity=epoch(scratch.lstat())[:3];socket_identity=epoch(socket.lstat())[:4]+[socket.lstat().st_uid,socket.lstat().st_gid]
    assert not os.path.lexists(PAIR) and not os.path.lexists(DEST)
    git_before=git('rev-parse','HEAD');assert git_before['stdout'].strip()==COMMIT;assert git('diff','--cached','--name-only','-z')['stdout']==''
    scans=[scan([42151,42153,42412,47414,47415,47609]),scan([42151,42153,42412,47414,47415,47609])]
    assert all(not s['members'] and not s['errors'] and all(s['actual_pids_absent'].values()) for s in scans)
    for p,row in held.items():
        clock();assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat());os.lseek(row['fd'],0,os.SEEK_SET);digest=hashlib.sha256()
        while b:=os.read(row['fd'],1048576):clock();digest.update(b)
        assert digest.hexdigest()==row['descriptor']['sha256'] and epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())
    custody.verify();assert initial_root==[ROOT.lstat().st_dev,ROOT.lstat().st_ino,ROOT.lstat().st_mode,ROOT.lstat().st_uid,ROOT.lstat().st_gid]
    assert scratch_identity==epoch(scratch.lstat())[:3] and socket_identity==epoch(socket.lstat())[:4]+[socket.lstat().st_uid,socket.lstat().st_gid]
    assert git('rev-parse','HEAD')['stdout'].strip()==COMMIT and git('diff','--cached','--name-only','-z')['stdout']=='' and not os.path.lexists(PAIR) and not os.path.lexists(DEST)
    report={'schema_version':1,'artifact_kind':'vast_gpu01_ext4_pure_stock95_readiness_v1','status':'passed_source_readiness_only','source_commit':COMMIT,'root':str(ROOT),'root_identity':initial_root,'filesystem':max(mounts),'stock95_before':stock95,'stock95_after':[record(held[Path(row['descriptor']['path'])]) for row in stock95],'source87_count':87,'input_document_count':6,'stock_loader_full_physical_body_validated':True,'stock_loaded_module_coverage_passed':True,'closure_sha256':CLOSURE,'controller':record(controller),'cpu06_accepted_released_proof':record(cpu_pin),'image_receipt_ready_not_live_observation':{'image_id':image['image_id'],'runtime_source_count':73,'canonical_repository_digest':image['canonical_repository_digest']},'git_before':git_before,'two_fresh_process_scans':scans,'gpu_pair_path':str(PAIR),'gpu_controller_output':str(DEST),'gpu_namespaces_absent':True,'socket_identity':socket_identity,'scratch_identity':scratch_identity,'actual_gpu_terminal_sha256':None,'actual_gpu_cli_pid':None,'benchmark_accepted':False,'gpu_accepted':False,'publication_ready':False,'limits':['Pure source/receipt readiness only; actual stock GPU CLI must perform current model/numeric/device/worker/image/engine/socket/inference/preprocessing/ingress/cold gates.','No model weights, numeric corpus payloads, engine or image queries, namespace/profile changes, native execution, tests or benchmark dispatch.','Parent retains original GPU grant/owner/terminal; this read-only gate releases its FDs before dispatch.']}
except BaseException as exc:
    first_error={'type':type(exc).__name__,'message':str(exc)[:4096]};report={'schema_version':1,'artifact_kind':'vast_gpu01_ext4_pure_stock95_readiness_v1','status':'failed_no_readiness','first_error':first_error,'gpu_accepted':False,'benchmark_accepted':False}
finally:
    if custody is not None:
        try:custody.close()
        except BaseException as exc:close_errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
    for row in held.values():
        try:os.close(row['fd'])
        except BaseException as exc:close_errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
    report['all_review_fds_released']=not close_errors;report['close_errors']=close_errors;report['fd_count_before']=baseline_fds;report['fd_count_after_close']=len(list(Path('/proc/self/fd').iterdir()));report['elapsed_after_close_s']=time.monotonic()-START
if report['fd_count_before']!=report['fd_count_after_close']:
    if first_error is None:first_error={'type':'FdReleaseError','message':'actual postclose FD count differs from entry baseline'}
    report['status']='failed_no_readiness';report['first_error']=first_error;report['all_review_fds_released']=False
ref=write('review.v1.json',report);print(json.dumps(ref),flush=True)
late=time.monotonic()>=END
if late:write('late-failure.v1.json',{'status':'failed_no_readiness','closed_report':ref,'original_first_error':first_error,'elapsed_s':time.monotonic()-START,'readiness':False})
sys.exit(0 if first_error is None and not close_errors and not late and report['fd_count_before']==report['fd_count_after_close'] else 1)
