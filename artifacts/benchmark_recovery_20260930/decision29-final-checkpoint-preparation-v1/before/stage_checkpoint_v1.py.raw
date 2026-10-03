"""Finite test-only current-image checkpoint; every original byte verified before index mutation."""
from pathlib import Path
import hashlib,json,os,stat,subprocess
ROOT=Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
OLD='04a5d1c7b90274af71f4ff2456ec3013107c2bb3'
GIT=['git','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true']
def run(args,payload=None):
 p=subprocess.run(GIT+args,cwd=ROOT,input=payload,capture_output=True,timeout=15)
 assert p.returncode==0,(args,p.returncode,p.stderr[:2048])
 assert len(p.stdout)<=16*1048576 and len(p.stderr)<=65536
 return p.stdout
def epoch(s):return[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
assert run(['rev-parse','HEAD']).decode().strip()==OLD and run(['diff','--cached','--name-only','-z'])==b''
test=ROOT/'tests/test_publication_runtime_frozen_identity_constants_v1.py'
assert hashlib.sha256(test.read_bytes()).hexdigest()=='216b2b76686c396a88fdd6a51d404d3ea01856abbe3cdb982c29d791644386e1'
review=json.loads((HERE.parent/'decision29-selected-image-test-independent-review-v1/review.v1.json').read_bytes())
assert review['reviewable'] is True and review['blocking_findings']==[]
v=json.loads((HERE/'green01/execution.v1.json').read_bytes());u=json.loads((HERE/'green01/unit-result.v1.json').read_bytes())
assert v['returncode']==0 and v['failure'] is None and v['source_stable'] is True and v['fd_before']==v['fd_after'] and v['readers_alive'] is False
assert u['tests_run']==1 and u['failures']==u['errors']==u['skips']==[] and u['source_stable'] is True
assert not(HERE/'green01/late-failure.v1.json').exists()
paths=[test,ROOT/'BENCHMARK_RECOVERY_PLAN.md',HERE.parent/'decision29-selected-image-test-independent-review-v1/review.v1.json']
for p in HERE.rglob('*'):
 s=p.lstat();assert not stat.S_ISLNK(s.st_mode)
 if stat.S_ISREG(s.st_mode):paths.append(p)
 else:assert stat.S_ISDIR(s.st_mode)
assert len(paths)==len(set(paths))
physical={};epochs={};total=0
for p in sorted(paths):
 assert p.resolve(strict=True)==p and p.is_relative_to(ROOT)
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=1048576
 raw=p.read_bytes();assert epoch(p.lstat())==epoch(s)
 total+=len(raw);assert total<=8*1048576
 name=p.relative_to(ROOT).as_posix();physical[name]=raw;epochs[name]=epoch(s)
errors=[]
for name,raw in physical.items():
 oid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 for setting in('false','true'):
  clean=run(['-c','core.autocrlf='+setting,'hash-object','--path='+name,'--stdin'],raw).decode().strip()
  if clean!=oid:errors.append({'path':name,'setting':setting,'raw':oid,'clean':clean})
assert not errors,errors
freeze={'schema_version':1,'previous_commit':OLD,'owned_files':{n:{'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'epoch7':epochs[n]} for n,b in physical.items()},'owned_total_bytes':total,'prospective_raw_clean_false_true_equal':True,'only_test_binding_source_change':True,'benchmark_B_runtime95_selected73_native3_worker2_untouched':True,'latest_complete_CI_conformance_archive_final_review_merge_pending':True,'unrelated_dirt_preserved':True}
fp=HERE/'checkpoint-freeze.v1.json';raw=(json.dumps(freeze,sort_keys=True,indent=2)+'\n').encode();name=fp.relative_to(ROOT).as_posix();oid=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
for setting in('false','true'):assert run(['-c','core.autocrlf='+setting,'hash-object','--path='+name,'--stdin'],raw).decode().strip()==oid
for n,b in physical.items():assert(ROOT/n).read_bytes()==b and epoch((ROOT/n).lstat())==epochs[n]
with fp.open('xb') as s:s.write(raw);s.flush();os.fsync(s.fileno())
physical[name]=raw
previous=run(['ls-tree','-r','HEAD']).decode().splitlines();oids={line.split('\t',1)[1]:line.split()[2] for line in previous};changed=set()
for n,b in physical.items():
 oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
 if oids.get(n)==oid:continue
 changed.add(n);assert run(['hash-object','-w','--stdin'],b).decode().strip()==oid
 run(['update-index','--add','--cacheinfo','100644,'+oid+','+n])
assert set(run(['diff','--cached','--name-only','-z']).decode().split('\0'))-{''}==changed
for n,b in physical.items():assert run(['show',':'+n])==b==(ROOT/n).read_bytes(),n
run(['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*[n for n in changed if n.endswith('.py') or n=='BENCHMARK_RECOVERY_PLAN.md']])
print(json.dumps({'owned_files':len(physical),'changed_staged_files':len(changed),'owned_total_bytes':total+len(raw),'physical_index_equal':True,'latest_complete_CI_pending':True}))
