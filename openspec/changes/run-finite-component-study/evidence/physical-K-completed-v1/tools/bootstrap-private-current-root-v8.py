"""Amendment11: attempt K (human decision) in a NEW exclusive namespace with its own 4h clock, after corrected CI."""
import argparse,hashlib,json,os,selectors,signal,stat,subprocess,sys,tarfile,time
from pathlib import Path,PurePosixPath

p=argparse.ArgumentParser()
p.add_argument('--commit',required=True)
p.add_argument('--ci-proof',required=True,type=Path)
p.add_argument('--project-root',required=True,type=Path)
p.add_argument('--source-root',required=True,type=Path)
p.add_argument('--attempt-id',required=True,choices=('K',))
a=p.parse_args()
LABEL='timens-offsets:monotonic=0,0;boottime=0,0'
def clock_domain_label():
    own,child=os.readlink('/proc/self/ns/time'),os.readlink('/proc/self/ns/time_for_children')
    rows=[r.split() for r in Path('/proc/self/timens_offsets').read_text().splitlines()]
    assert own==child and rows==[['monotonic','0','0'],['boottime','0','0']],'amendment4 clock domain is not the zero-offset initial clock'
    return LABEL
assert len(a.commit)==40 and all(c in '0123456789abcdef' for c in a.commit)
ci_raw=a.ci_proof.read_bytes();ci=json.loads(ci_raw)
assert ci['run']['head_sha']==a.commit and ci['run']['status']=='completed' and ci['run']['conclusion']=='success'
assert len(ci['jobs']['jobs'])==2 and all(j['conclusion']=='success' and j['run_id']==ci['run']['id'] for j in ci['jobs']['jobs'])
root=a.project_root
assert root.is_absolute() and root.parent.resolve(strict=True)==root.parent and not os.path.lexists(root)
started=time.monotonic_ns()
clock={'clock':'CLOCK_MONOTONIC','started_monotonic_ns':started,'deadline_monotonic_ns':started+14_400_000_000_000,
    'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'time_namespace':clock_domain_label(),
    'time_namespace_inode':os.readlink('/proc/self/ns/time'),'attempt_id':a.attempt_id,'accepted_attempt':True,'human_decision':'2026-10-06 investigate J and run exactly one attempt K; J pilot data sealed, not combined',
    'retained_failed_attempts':{'D':'openspec/changes/run-finite-component-study/evidence/physical-D-failed-v1/retention.original.json',
        'E':'openspec/changes/run-finite-component-study/evidence/physical-E-failed-v1/retention.original.json',
        'F':'openspec/changes/run-finite-component-study/evidence/physical-F-failed-v1/retention.original.json',
        'G':'openspec/changes/run-finite-component-study/evidence/physical-G-failed-v1/retention.original.json',
        'H':'openspec/changes/run-finite-component-study/evidence/physical-H-failed-v1/retention.original.json',
        'I':'openspec/changes/run-finite-component-study/evidence/physical-I-failed-v1/retention.original.json',
        'J':'openspec/changes/run-finite-component-study/evidence/physical-J-failed-v1/retention.original.json'},
    'previous_attempt_clock':{'attempt_id':'J','started_monotonic_ns':765741763390656,'failed_closed_monotonic_ns':766591495475219}}
assert started>766591495475219,'attempt K must start after failed attempt J closed'
root.mkdir(mode=0o700);control=root/'b';control.mkdir(mode=0o700)
def remaining():
    left=(clock['deadline_monotonic_ns']-time.monotonic_ns())/1e9
    assert left>15,'original preparation deadline expired during bootstrap'
    return left-15
def save(path,value,*,failure_diagnostic=False):
    if not failure_diagnostic:remaining()
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
    assert len(raw)<=16*1024**2
    with path.open('xb') as out:assert out.write(raw)==len(raw);out.flush();os.fsync(out.fileno())
    if not failure_diagnostic:remaining()
    return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
clock_ref=save(control/'preparation-clock.original.json',clock)
ci_ref=save(control/'source-ci.original.json',{'provider_metadata':str(a.ci_proof),'size_bytes':len(ci_raw),
    'sha256':hashlib.sha256(ci_raw).hexdigest(),'run_id':ci['run']['id'],'source_commit':a.commit,'conclusion':'success','hardware_acceptance':False})
git=['/mnt/c/Program Files/Git/cmd/git.exe','-C','C:/Users/s-a-balashov/.codex/worktrees/finite-component-study/VAST']
records=[]
def run(command,label):
    remaining();stdout=control/(label+'.stdout.original');stderr=control/(label+'.stderr.original')
    child=None;primary=None;row={'argv':command,'stdout':str(stdout),'stderr':str(stderr),'owned_child_reaped':False,'cleanup_errors':[]}
    try:
        with stdout.open('xb') as out,stderr.open('xb') as err,selectors.DefaultSelector() as ready:
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            row['pid']=child.pid;row['pgid']=os.getpgid(child.pid);assert row['pgid']==child.pid
            counts={};limits={child.stdout:1024**3,child.stderr:16*1024**2}
            for stream,destination in ((child.stdout,out),(child.stderr,err)):
                os.set_blocking(stream.fileno(),False);counts[stream]=0;ready.register(stream,selectors.EVENT_READ,destination)
            while ready.get_map():
                left=remaining();assert left>0,'original child command deadline expired'
                for key,_ in ready.select(min(0.2,left)):
                    try:raw=os.read(key.fileobj.fileno(),65536)
                    except BlockingIOError:continue
                    if not raw:ready.unregister(key.fileobj);continue
                    assert counts[key.fileobj]+len(raw)<=limits[key.fileobj],(label,'actual child output cap exceeded')
                    counts[key.fileobj]+=len(raw);assert key.data.write(raw)==len(raw)
            child.wait(timeout=remaining());row['owned_child_reaped']=True;row['returncode']=child.returncode
            out.flush();err.flush();os.fsync(out.fileno());os.fsync(err.fileno())
        assert child.returncode==0,(label,'original child failed; see retained logs')
    except BaseException as error:
        primary=error
        row['first_error']=type(error).__name__+':'+str(error)
        if child is not None:
            try:
                try:os.killpg(child.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:pass
                # The original owned group may outlive its exited leader.
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=3)
            except BaseException as cleanup:
                row['cleanup_errors'].append(type(cleanup).__name__+':'+str(cleanup));error.add_note(row['cleanup_errors'][-1])
        if child is not None:row['returncode']=child.returncode;row['owned_child_reaped']=child.returncode is not None
        raise
    finally:
        if child is not None:
            for stream in (child.stdout,child.stderr):
                try:
                    if stream is not None and not stream.closed:stream.close()
                except BaseException as cleanup:
                    row['cleanup_errors'].append(type(cleanup).__name__+':'+str(cleanup))
                    if primary is not None:primary.add_note(row['cleanup_errors'][-1])
        row['closed_monotonic_ns']=time.monotonic_ns();records.append(row)
        if row['cleanup_errors'] and primary is None:raise RuntimeError('bootstrap child close failed: '+str(row['cleanup_errors']))
    remaining();return stdout
try:
    observed=run([*git,'rev-parse','HEAD'],'git-head').read_text().strip();assert observed==a.commit
    tree=run([*git,'ls-tree','-r','-l','-z','--full-tree',a.commit],'git-tree').read_bytes()
    leaves={}
    for row in tree.split(b'\0'):
        if not row:continue
        header,name=row.split(b'\t',1);mode,kind,oid,size=header.split();name=name.decode('utf-8')
        path=PurePosixPath(name)
        assert str(path)==name and not path.is_absolute() and '..' not in path.parts
        assert kind==b'blob' and mode in (b'100644',b'100755') and name not in leaves
        leaves[name]=(int(size),oid.decode(),int(mode,8)&0o777)
    assert 1<=len(leaves)<=10000 and sum(x[0] for x in leaves.values())<=512*1024**2
    archive=run([*git,'archive','--format=tar',a.commit],'git-archive')
    manifest=[];seen=set()
    with tarfile.open(archive,'r:') as tar:
        assert tar.pax_headers.get('comment')==a.commit
        for member in tar:
            remaining();name=member.name.rstrip('/')
            path=PurePosixPath(name)
            assert str(path)==name and not path.is_absolute() and '..' not in path.parts
            destination=root.joinpath(*path.parts)
            if member.isdir():destination.mkdir(mode=0o700,parents=True,exist_ok=True);continue
            assert member.isfile() and name in leaves and name not in seen
            size,oid,mode=leaves[name];assert member.size==size and size<=64*1024**2
            destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            sha1=hashlib.sha1(b'blob '+str(size).encode()+b'\0');sha256=hashlib.sha256();count=0
            with tar.extractfile(member) as source,destination.open('xb') as out:
                while chunk:=source.read(1024**2):
                    remaining();count+=len(chunk);assert count<=size
                    sha1.update(chunk);sha256.update(chunk);assert out.write(chunk)==len(chunk)
                out.flush();os.fsync(out.fileno())
            assert count==size and sha1.hexdigest()==oid,(name,'Git blob bytes differ')
            destination.chmod(0o700 if mode&0o111 else 0o600)
            check=hashlib.sha256();actual=0
            with destination.open('rb') as transferred:
                while chunk:=transferred.read(1024**2):remaining();actual+=len(chunk);check.update(chunk)
            assert actual==size and check.digest()==sha256.digest() and destination.lstat().st_nlink==1
            seen.add(name);manifest.append({'path':name,'size_bytes':size,'git_blob_id':oid,'sha256':sha256.hexdigest()})
    assert seen==set(leaves),'archive omitted or added source files'
    archive_digest=hashlib.sha256()
    with archive.open('rb') as archive_input:
        while chunk:=archive_input.read(1024**2):remaining();archive_digest.update(chunk)
    source_ref=save(control/'source-transfer.original.json',{'source_commit':a.commit,'ci':ci_ref,'clock':clock,
        'git_archive_sha256':archive_digest.hexdigest(),'files':manifest,
        'complete_git_tree_bytes_verified':True,'git_checkout':False,'accepted':False})
    before=archive.lstat();assert stat.S_ISREG(before.st_mode) and before.st_nlink==1
    archive.unlink()
    copier=Path(__file__).with_name('bootstrap-copy-model-bundle-v3.py')
    run([sys.executable,'-I','-B',str(copier),'--source-root',str(a.source_root),'--project-root',str(root),'--clock',clock_ref['path']],'model-transfer')
    entry="import runpy,sys;root=sys.argv.pop(1);sys.path.insert(0,root+'/scripts');runpy.run_path(root+'/scripts/publication_policy_qualification_execution_code_closure_v1.py',run_name='__main__')"
    closure=control/'current-code-closure.original.json'
    run([sys.executable,'-I','-B','-c',entry,str(root),'--project-root',str(root),'--receipt',str(closure)],'current-code-closure')
    ref=save(control/'bootstrap-closed.original.json',{'kind':'finite-study-bootstrap-closed','clock':clock,'source':source_ref,
        'ci':ci_ref,'commands':records,'code_closure':str(closure),'closed_monotonic_ns':time.monotonic_ns(),
        'preparation_elapsed_s':(time.monotonic_ns()-started)/1e9,'model_acceptance':False,'canonical_study_complete':False})
    remaining();print(json.dumps(ref),flush=True)
except BaseException as error:
    save(control/'bootstrap-failed.original.json',{'first_error':type(error).__name__+':'+str(error),'commands':records,
        'clock':clock,'canonical_study_complete':False},failure_diagnostic=True)
    raise
