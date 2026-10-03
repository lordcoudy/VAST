"""Stage the finite reviewed CI clock repair and closed current evidence and its exact original evidence only."""
from pathlib import Path
import hashlib,json,os,stat,subprocess
ROOT=Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
HERE=Path(__file__).resolve().parent
OLD='56dd56bcc80519b99357546a49dbd65377e0db22'
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

assert run(['rev-parse','HEAD']).decode().strip()==OLD
assert run(['diff','--cached','--name-only','-z'])==b''
ci=review('decision29-ci-clock-independent-source-review-v1/review.v1.json',9951,'835bf6c7c991c78062adc39459b34f51eab7c598c71185a7b00fe777f62f9d6d')
for p in ci['owned_source_pins']:
    raw=(ROOT/p['path']).read_bytes();assert len(raw)==p['size_bytes'] and hashlib.sha256(raw).hexdigest()==p['sha256']
review('decision28-four-arm-science-independent-source-review-v1/review.v1.json',6710,'0742fc2c3d88f2f658d9ba2d062213ac82cd442f6d641b3198878a2742d50a53')
names=['decision28-host-identity-source-checkpoint-v1','decision28-host-ext4-renewal-preparation-v1','decision28-stock-host-original-copy-v1','decision28-current95-preparation-v1','decision28-cpu08-independent-audit-v1','decision28-cpu08-root-source-review-v1','decision28-cpu07-current-worker-absence-v1','decision28-gpu02-preparation-v1','decision28-gpu02-independent-source-review-v1','decision28-gpu02-independent-audit-v1','decision28-gpu02-root-source-review-v1','decision28-four-arm-science-preparation-v1','decision28-four-arm-science-independent-source-review-v1','decision29-planning-checkpoint-v1','decision29-ci-clock-repair-v1','decision29-namespace-tests-author-v1','decision29-namespace-tests-root-review-v1','decision29-ci-clock-independent-source-review-v1','decision29-source-checkpoint-v1']
paths=[ROOT/n for n in ('scripts/ci_namespace_diagnostic_v1.py','scripts/ci_userns_profile_v1.py','tests/test_ci_namespace_diagnostic_v1.py','tests/test_ci_userns_profile_v1.py','BENCHMARK_RECOVERY_PLAN.md','openspec/changes/fix-benchmark-preparations-spec/tasks.md')]
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
freeze={'schema_version':1,'previous_commit':OLD,'benchmark_commit_untouched':'a00aa57f7d9534f8e7920f14f70d6a75a23570ed','owned_files':{n:{'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch7':epochs[n]} for n,raw in physical.items()},'owned_total_bytes':total,'prospective_raw_clean_autocrlf_false_true_equal':True,'CI_source_review_sha256':'835bf6c7c991c78062adc39459b34f51eab7c598c71185a7b00fe777f62f9d6d','CI_ONLY_source_impact_proven_all95_selected73_native3_worker2_unchanged':True,'original_CPU08_GPU02_and_four_arm_science_closed':True,'original_focused_GREEN_51_closed':True,'latest_full_CI_conformance_archive_final_review_merge_pending':True,'unrelated_dirt_preserved':True}
fp=HERE/'checkpoint-freeze.v1.json';fr=(json.dumps(freeze,sort_keys=True,indent=2)+'\n').encode();fn=fp.relative_to(ROOT).as_posix()
oid=hashlib.sha1(b'blob '+str(len(fr)).encode()+b'\0'+fr).hexdigest()
for setting in ('false','true'):assert run(['-c','core.autocrlf='+setting,'hash-object','--path='+fn,'--stdin'],fr).decode().strip()==oid
for name,raw in physical.items():assert (ROOT/name).read_bytes()==raw and epoch((ROOT/name).lstat())==epochs[name]
with fp.open('xb') as stream:stream.write(fr);stream.flush();os.fsync(stream.fileno())
physical[fn]=fr
previous=run(['ls-tree','-r','HEAD']).decode().splitlines();oids={line.split('\t',1)[1]:line.split()[2] for line in previous}
changed=set()
for name,raw in physical.items():
    rawoid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if oids.get(name)==rawoid:continue
    changed.add(name);oid=run(['hash-object','-w','--stdin'],raw).decode().strip();assert oid==rawoid
    run(['update-index','--add','--cacheinfo','100644,'+oid+','+name])
staged=set(run(['diff','--cached','--name-only','-z']).decode().split('\0'))-{''};assert staged==changed
for name,raw in physical.items():assert run(['show',':'+name])==raw==(ROOT/name).read_bytes(),name
authored=[name for name in changed if name.endswith('.py') or name in ('BENCHMARK_RECOVERY_PLAN.md','openspec/changes/fix-benchmark-preparations-spec/tasks.md')]
run(['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*authored])
print(json.dumps({'owned_files':len(physical),'changed_staged_files':len(changed),'physical_index_equal':True,'owned_total_bytes':total+len(fr),'freeze_sha256':hashlib.sha256(fr).hexdigest(),'latest_full_CI_pending':True}))
