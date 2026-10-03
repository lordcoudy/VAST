"""Genuine small Git repositories using the exact fifteen original raw blobs.
The scratch repos stay outside the finite Windows evidence namespace. No existing
source checkout, benchmark root, CI checkout, profile or engine is mutated.
"""
import hashlib,json,os,signal,subprocess,time,uuid
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
START=time.monotonic_ns();DEADLINE=START+120_000_000_000
END=DEADLINE+10_000_000_000
BOOT=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
proposal=json.loads((HERE/'preedit-proposal-and-authorization.v1.json').read_bytes())
PATHS=[r['path'] for r in proposal['findings']]
OLD=(HERE/'gitattributes.before.raw').read_bytes()
NEW=(HERE/'gitattributes.after.raw').read_bytes()
assert NEW.startswith(OLD) and (ROOT/'.gitattributes').read_bytes()==NEW
SCRATCH=Path('/var/tmp')/('vast-forensic-json-git-'+uuid.uuid4().hex)
SCRATCH.mkdir(mode=0o700)
OUT=HERE/'controlled-original-attempt01';OUT.mkdir()
records=[];children=[]
def save(name,raw):
    with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def owner(pid):
    proc=Path('/proc')/str(pid);raw=(proc/'stat').read_text();tail=raw[raw.rfind(')')+2:].split()
    info=(proc/'status').read_text();uids=next(x for x in info.splitlines() if x.startswith('Uid:')).split();gids=next(x for x in info.splitlines() if x.startswith('Gid:')).split()
    return {'pid':pid,'ppid':int(tail[1]),'pgid':int(tail[2]),'startticks':int(tail[19]),'uid':int(uids[1]),'gid':int(gids[1]),'state':tail[0],'boot_id':BOOT}
def git(root,*args,stdin=None):
    assert time.monotonic_ns()<DEADLINE
    argv=['/usr/bin/git','-c','core.longpaths=true','-C',str(root),*args]
    number=len(records)+1;start=time.monotonic_ns();p=subprocess.Popen(argv,stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    actual=None;timed=False
    try:
        actual=owner(p.pid);children.append(actual)
        out,err=p.communicate(stdin,timeout=min(15,(DEADLINE-time.monotonic_ns())/1e9))
    except BaseException:
        if p.poll() is None:
            timed=True;os.killpg(p.pid,signal.SIGKILL)
        out,err=p.communicate(timeout=max(0.01,min(10,(END-time.monotonic_ns())/1e9)))
        raise
    finally:
        assert p.poll() is not None
        if p.stdout:p.stdout.close()
        if p.stderr:p.stderr.close()
        if p.stdin:p.stdin.close()
        record={'argv':argv,'owner':actual,'elapsed_s':(time.monotonic_ns()-start)/1e9,'returncode':p.returncode,'timed_out':timed,
          'stdout':save(f'{number:03}.stdout.raw',out),'stderr':save(f'{number:03}.stderr.raw',err),'child_reaped':True,'child_proc_absent':not (Path('/proc')/str(p.pid)).exists()}
        records.append(record)
    assert p.returncode==0,record
    assert len(out)<=65536 and len(err)<=65536
    return out
def raw_file(root,relative,raw):
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
def attributes(root):
    raw=git(root,'check-attr','-z','text','eol','--stdin',stdin=('\0'.join(PATHS)+'\0').encode())
    fields=raw.decode().split('\0')[:-1]
    return [{'path':fields[i],'attribute':fields[i+1],'value':fields[i+2]} for i in range(0,len(fields),3)]
def checkout(name,commit,autocrlf):
    target=SCRATCH/name
    git(SCRATCH,'clone','--no-local','--no-checkout',str(SEED),str(target))
    git(target,'config','core.autocrlf',autocrlf)
    git(target,'config','core.longpaths','true')
    git(target,'checkout','--detach',commit)
    assert git(target,'rev-parse','HEAD').decode().strip()==commit
    return target
def observed(root):
    status=git(root,'status','--porcelain=v1','-z')
    result=[]
    for r in proposal['findings']:
        p=root/r['path'];raw=p.read_bytes();size=len(raw);sha=hashlib.sha256(raw).hexdigest()
        clean=git(root,'hash-object','--path='+r['path'],'--stdin',stdin=raw).decode().strip()
        result.append({'path':r['path'],'size_bytes':size,'sha256':sha,'original_git_blob_id':r['git_blob_id'],'actual_clean_blob_id':clean,'raw_equals_original_git':sha==r['original_git_and_primary']['sha256'] and size==r['original_git_and_primary']['size_bytes'],'clean_equals_original_git':clean==r['git_blob_id']})
    return {'status_hex':status.hex(),'status_entries':[x.decode() for x in status.split(b'\0') if x],'raw_files':result,'effective_attributes':attributes(root)}
def main():
    global SEED
    SEED=SCRATCH/'seed';SEED.mkdir()
    git(SEED,'init','-q');git(SEED,'config','core.autocrlf','false');git(SEED,'config','core.longpaths','true')
    git(SEED,'config','user.name','Finite Git fixture');git(SEED,'config','user.email','fixture.invalid@example.invalid')
    raw_file(SEED,'.gitattributes',OLD)
    attrblob=git(SEED,'hash-object','-w','--stdin',stdin=OLD).decode().strip()
    git(SEED,'update-index','--add','--cacheinfo','100644,'+attrblob+',.gitattributes')
    for row in proposal['findings']:
        source=Path(row['saved_original_git_blob']['path']);raw=source.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==row['original_git_and_primary']['sha256']
        raw_file(SEED,row['path'],raw)
        blob=git(SEED,'hash-object','-w','--stdin',stdin=raw).decode().strip();assert blob==row['git_blob_id']
        git(SEED,'update-index','--add','--cacheinfo','100644,'+blob+','+row['path'])
    git(SEED,'commit','-q','-m','Controlled RED: retain original fifteen raw forensic blobs')
    red_commit=git(SEED,'rev-parse','HEAD').decode().strip()
    redroot=checkout('red-false',red_commit,'false');red=observed(redroot)
    assert red['status_entries']==[' M '+p for p in PATHS]
    assert all(x['raw_equals_original_git'] and not x['clean_equals_original_git'] for x in red['raw_files'])
    assert all(x['value']==('set' if x['attribute']=='text' else 'lf') for x in red['effective_attributes'])
    # The only tiny repository content change is its attributes. Raw payloads
    # keep their original index objects; no normalization or renormalize occurs.
    (SEED/'.gitattributes').write_bytes(NEW)
    git(SEED,'add','--','.gitattributes')
    git(SEED,'commit','-q','-m','Controlled GREEN: fifteen exact byte preservation rules')
    green_commit=git(SEED,'rev-parse','HEAD').decode().strip()
    changed=git(SEED,'diff','--name-only','-z',red_commit,green_commit)
    assert changed==b'.gitattributes\0'
    greens=[]
    for setting in ('false','true'):
        greenroot=checkout('green-'+setting,green_commit,setting);result=observed(greenroot)
        assert result['status_entries']==[]
        assert all(x['raw_equals_original_git'] and x['clean_equals_original_git'] for x in result['raw_files'])
        assert all(x['value']==('unset' if x['attribute']=='text' else 'unspecified') for x in result['effective_attributes'])
        greens.append({'initial_autocrlf':setting,'root':str(greenroot),'observed':result})
    assert (ROOT/'.gitattributes').read_bytes()==NEW
    for row in proposal['findings']:
        raw=(ROOT/row['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['original_git_and_primary']['sha256']
    assert all(not (Path('/proc')/str(x['pid'])).exists() for x in children)
    elapsed=(time.monotonic_ns()-START)/1e9;assert elapsed<120
    result={'schema_version':1,'kind':'vast_exact_forensic_json_controlled_git_red_green_v1','status':'passed_fixture_only','controller':owner(os.getpid()),
      'source':{'path':str(Path(__file__).resolve()),'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
      'scratch_root':str(SCRATCH),'red_commit':red_commit,'green_commit':green_commit,'red':red,'green':greens,'only_changed_fixture_path':'.gitattributes',
      'actual_original_commands':records,'child_count':len(children),'all_children_reaped_and_absent':True,'all_capture_fds_closed':True,'elapsed_s':elapsed,
      'no_acceptance_claim':True,'whole_CI_or_hardware_executed':False,'original_failed_CI_root_untouched':True,'raw_payloads_unchanged':True,
      'limits':'Genuine finite fixture establishes clean/raw behavior for these fifteen actual blobs and attributes. It is not a fresh full-project checkout, CI or benchmark acceptance.'}
    ref=save('execution.v1.json',(json.dumps(result,sort_keys=True,indent=2)+'\n').encode('ascii'))
    assert (time.monotonic_ns()-START)<120_000_000_000
    print(json.dumps({'execution':ref,'elapsed_s':elapsed,'child_count':len(children),'red_dirty':15,'green_clean_initial_autocrlf':['false','true'],'scratch':str(SCRATCH)}))
try:main()
except BaseException as error:
    save('failed.v1.json',(json.dumps({'status':'failed_fixture','type':type(error).__name__,'message':str(error),'commands':records,'scratch':str(SCRATCH),'elapsed_s':(time.monotonic_ns()-START)/1e9,'accepted':False},indent=2)+'\n').encode('utf-8'))
    raise
