"""Stage the finite reviewed host renewal and its exact original evidence only."""
from pathlib import Path
import hashlib,json,os,stat,subprocess
ROOT=Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
HERE=Path(__file__).resolve().parent
OLD='2a6a42c924ae3447ceda4bd9d1b6db33765c6466'
GIT=['git','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true']
def run(args,payload=None):
    p=subprocess.run(GIT+args,cwd=ROOT,input=payload,capture_output=True,timeout=15)
    assert p.returncode==0,(args,p.returncode,p.stderr[:2048])
    assert len(p.stdout)<=16*1024*1024 and len(p.stderr)<=65536
    return p.stdout
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def review(name,size,sha):
    p=BASE/name;b=p.read_bytes();assert len(b)==size and hashlib.sha256(b).hexdigest()==sha
    v=json.loads(b);assert v['reviewable'] is True and v['blocking_findings']==[] and v['reviewer_handles_released'] is True
    return v
host=review('decision28-host-image-independent-review-v1/review.v1.json',30902,'83d27f58d5e54f1ae48c2df98bf2fa61c8f8f8e39a530bf49fbf91084166d9eb')
ext4=review('decision28-host-ext4-renewal-independent-review-v1/review.v1.json',10478,'8605b8c47799f7aacb17f0ca7ff66c4ffd8132c3df6db07b6af5bcd614202864')
controllers=review('decision28-host-cpu08-independent-source-review-v2/review.v1.json',3028,'e51563b124182dc6c5341ca4d0ea00bcc858fa93d1559483de6dfda7e7fc1405')
assert host['reviewed_commit']==ext4['reviewed_commit']==OLD
for p in host['owned_source_pins']+ext4['owned_source_pins']:
    raw=(ROOT/p['path']).read_bytes();assert len(raw)==p['size_bytes'] and hashlib.sha256(raw).hexdigest()==p['sha256']
assert run(['rev-parse','HEAD']).decode().strip()==OLD
assert run(['diff','--cached','--name-only','-z'])==b''
assert not (HERE/'checkpoint-freeze.v1.json').exists()
names=['decision28-ext4-renewal-preparation-v1','decision28-selected-original-build-copy-v1',
    'decision28-host-image-binding-v1','decision28-host-image-independent-review-v1',
    'decision28-host-ext4-renewal-preparation-v1','decision28-host-ext4-renewal-independent-review-v1',
    'decision28-host-cpu08-independent-source-review-v1','decision28-host-cpu08-independent-source-review-v2',
    'decision28-host-cpu08-renewal-preparation-v2','decision28-host-cpu08-final-binding-v1',
    'decision28-host-identity-source-checkpoint-v1']
paths=[ROOT/p['path'] for p in host['owned_source_pins']]
paths+=[ROOT/'BENCHMARK_RECOVERY_PLAN.md',BASE/'decision28-own-reassessment-working-v1.md',
    BASE/'decision28-source-checkpoint-v1/verify_committed_checkpoint_v1.py',
    BASE/'decision28-source-checkpoint-v1/committed-checkpoint-proof.v1.json',
    BASE/'decision28-selected-renewal-preparation-v2/root-independent-review-and-conditional-grant.v1.json']
for name in names:
    directory=BASE/name;assert directory.resolve(strict=True)==directory
    for p in directory.rglob('*'):
        s=p.lstat();assert not stat.S_ISLNK(s.st_mode)
        if stat.S_ISREG(s.st_mode):paths.append(p)
        else:assert stat.S_ISDIR(s.st_mode)
assert len(set(paths))==len(paths)
physical,epochs,total={},{},0
for p in sorted(paths):
    assert p.resolve(strict=True)==p and p.is_relative_to(ROOT)
    s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8*1024*1024
    raw=p.read_bytes();assert epoch(p.lstat())==epoch(s)
    total+=len(raw);assert total<=64*1024*1024
    name=p.relative_to(ROOT).as_posix();physical[name]=raw;epochs[name]=epoch(s)
errors=[]
for name,raw in physical.items():
    oid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    for setting in ('false','true'):
        clean=run(['-c','core.autocrlf='+setting,'hash-object','--path='+name,'--stdin'],raw).decode().strip()
        if clean!=oid:errors.append({'path':name,'core_autocrlf':setting,'raw_blob':oid,'clean_blob':clean})
if errors:
    with (HERE/'prospective-filter-failure.v1.json').open('xb') as s:s.write((json.dumps(errors,sort_keys=True,indent=2)+'\n').encode())
assert not errors,'prospective clean filters would change exact bytes; no Git mutation occurred'
freeze={'schema_version':1,'artifact_kind':'decision28_host_identity_exact_checkpoint_v1','previous_commit':OLD,
    'owned_files':{n:{'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch7':epochs[n]} for n,raw in physical.items()},
    'owned_total_bytes':total,'host_source_peer_sha256':'83d27f58d5e54f1ae48c2df98bf2fa61c8f8f8e39a530bf49fbf91084166d9eb',
    'ext4_successor_peer_sha256':'8605b8c47799f7aacb17f0ca7ff66c4ffd8132c3df6db07b6af5bcd614202864',
    'controller_source_peer_sha256':'e51563b124182dc6c5341ca4d0ea00bcc858fa93d1559483de6dfda7e7fc1405',
    'source_checkpoint_A_selected73_equal_current':True,'new_image_id':'sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1',
    'prospective_raw_clean_autocrlf_false_true_equal':True,'original_current_source_checkout_and_selected_build_closed':True,
    'future_host_closure_current95_CPU_GPU_and_local_fullCI_pending':True,'unrelated_dirt_preserved':True}
fp=HERE/'checkpoint-freeze.v1.json';fr=(json.dumps(freeze,sort_keys=True,indent=2)+'\n').encode();fn=fp.relative_to(ROOT).as_posix()
oid=hashlib.sha1(b'blob '+str(len(fr)).encode()+b'\0'+fr).hexdigest()
for setting in ('false','true'):assert run(['-c','core.autocrlf='+setting,'hash-object','--path='+fn,'--stdin'],fr).decode().strip()==oid
for name,raw in physical.items():assert (ROOT/name).read_bytes()==raw and epoch((ROOT/name).lstat())==epochs[name]
with fp.open('xb') as stream:stream.write(fr);stream.flush();os.fsync(stream.fileno())
physical[fn]=fr
for name,raw in physical.items():
    oid=run(['hash-object','-w','--stdin'],raw).decode().strip()
    run(['update-index','--add','--cacheinfo','100644,'+oid+','+name])
staged=set(run(['diff','--cached','--name-only','-z']).decode().split('\0'))-{''}
assert staged==set(physical)
for name,raw in physical.items():assert run(['show',':'+name])==raw==(ROOT/name).read_bytes(),name
authored=[name for name in physical if name.endswith('.py') or name in ('BENCHMARK_RECOVERY_PLAN.md','artifacts/benchmark_recovery_20260930/decision28-own-reassessment-working-v1.md')]
run(['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*authored])
print(json.dumps({'owned_files':len(physical),'physical_index_equal':True,'owned_total_bytes':total+len(fr),
    'freeze_size_bytes':len(fr),'freeze_sha256':hashlib.sha256(fr).hexdigest(),'selected73_unchanged':True,'current_hardware_accepted':False}))
