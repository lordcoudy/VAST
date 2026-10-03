"""Finite metadata diagnosis only; no checkout, payload rewrite or runtime call."""
import hashlib, json, os, stat, subprocess, time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
ART=HERE.parent
EXPECTED='78b869e4f8bc101413ed00776bd89d1089a8318d'
OLD_ATTR_SHA='27b8b1feaaaa51f2b01de423cfa4824d4f351613650f5b2fe137295610237c3f'
PATHS=[
 'artifacts/benchmark_recovery_20260930/ci-4cb9-original-host-retention-v1/host-download-source-review.v1.json',
 'artifacts/benchmark_recovery_20260930/component-current-source-ci-supervisor-preparation-v1/capture-literal-preparation.v1.json',
]
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(path):
 p=Path(path);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8388608
  raw=b''
  while b:=os.read(fd,65536):raw+=b
  assert len(raw)==s.st_size and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
  return raw,{'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch':epoch(s)}
 finally:os.close(fd)
def save(name,raw):
 with (HERE/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
 return pin(HERE/name)[1]
git=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
def command(suffix,data=None):
 p=subprocess.run(git+suffix,input=data,capture_output=True,check=True,timeout=20,cwd=ROOT)
 assert p.stderr==b''
 return p.stdout
assert command(['rev-parse','HEAD']).strip().decode()==EXPECTED
raw_attrs,attrs=pin(ROOT/'.gitattributes');assert attrs['sha256']==OLD_ATTR_SHA
diagnosis_path=ART/'component-supervisor-renewal-preparation-v1/failed-renewal-two-status-forensic.v1.json'
diagnosis_raw,diagnosis_pin=pin(diagnosis_path)
assert diagnosis_pin['sha256']=='c5defe652e6402fa9a01e7db42a5b335d57be6aca32614ade570705838752613'
diagnosis=json.loads(diagnosis_raw);assert [r['path'] for r in diagnosis['rows']]==PATHS
original=json.loads((ART/'forensic-raw-json-attributes-repair-v1/preedit-proposal-and-authorization.v1.json').read_bytes())
scope=set(PATHS)
inventory_pins=[]
for relative in ('owned-raw-evidence-attributes-checkpoint-v1/inventory.v1.json','owned-supervisor-capacity-checkpoint-v1/inventory.v1.json'):
 raw,ref=pin(ART/relative);inventory_pins.append(ref)
 scope.update(r['path'] for r in json.loads(raw)['files'] if Path(r['path']).suffix in ('.json','.md'))
for directory in ('component-current-source-ci-supervisor-attributes-preparation-v1','component-current-source-ci-supervisor-attributes-actual-setup-review-v1','component-current-source-ci-supervisor-attributes-independent-review-v1','component-supervisor-renewal-preparation-v1','component-supervisor-renewal-source-independent-review-v1'):
 for p in (ART/directory).rglob('*'):
  if p.is_file() and p.suffix in ('.json','.md'):scope.add(p.relative_to(ROOT).as_posix())
paths=sorted(scope)
before={};raw_oids={};raw_values={}
for relative in paths:
 raw,ref=pin(ROOT/relative);before[relative]=ref
 raw_oids[relative]=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 if relative in PATHS:raw_values[relative]=raw
clean_raw=command(['hash-object','--stdin-paths'],('\n'.join(paths)+'\n').encode())
clean_ids=clean_raw.decode().splitlines();assert len(clean_ids)==len(paths)
clean=dict(zip(paths,clean_ids,strict=True))
mismatches=[p for p in paths if raw_oids[p]!=clean[p]]
assert mismatches==sorted(PATHS),mismatches
batch=command(['cat-file','--batch'],''.join(EXPECTED+':'+p+'\n' for p in PATHS).encode());remaining=batch
findings=[]
for row in diagnosis['rows']:
 p=row['path'];header,remaining=remaining.split(b'\n',1);oid,kind,size=header.split();size=int(size)
 raw=remaining[:size];assert kind==b'blob' and remaining[size:size+1]==b'\n';remaining=remaining[size+1:]
 assert raw==raw_values[p] and oid.decode()==raw_oids[p]==row['actual_raw_git_blob_sha1']
 assert clean[p]!=raw_oids[p] and before[p]['sha256']==row['actual_sha256'] and before[p]['size_bytes']==row['actual_size_bytes']
 saved=save('original-'+str(len(findings)+1)+'.raw',raw)
 findings.append({'path':p,'git_blob_id':raw_oids[p],'clean_git_blob_id':clean[p],
  'original_git_and_primary':before[p],'saved_original_git_blob':saved,'CRLF_count':raw.count(b'\r\n'),
  'failed_renewal_actual_epoch':row['actual_epoch7'],'new_path_introduced_by_original_checkout':True})
assert remaining==b''
source_before={}
for relative in original['before_source_descriptors']:
 raw,ref=pin(ROOT/relative);source_before[relative]=ref
 assert ref['sha256']==original['before_source_descriptors'][relative]['sha256']
inputs=json.loads((ART/'component-ext4-relocation-feasibility-v1/inventory.v1.json').read_bytes())
assert not set(PATHS)&{r['path'] for r in inputs['copy_inputs']}
assert not set(PATHS)&set(source_before)
save('gitattributes.before.raw',raw_attrs)
rules=['/'+p+' -text !eol' for p in PATHS]
for relative,ref in before.items():assert pin(ROOT/relative)[1]==ref
assert pin(ROOT/'.gitattributes')[1]==attrs
value={'schema_version':1,'status':'proved_exact_two_before_mutation','source_commit':EXPECTED,
 'standing_root_authorization':'Finite follow-up attrs repair of these two actual renewal status paths; preserve first fifteen rules/all raw payloads; root explicit instruction before implementation.',
 'closed_original_failed_renewal_diagnosis':diagnosis_pin,'findings':findings,
 'before_attributes':attrs,'prefix_first15_and_original_LF_contracts_must_remain_exact':True,
 'proposed_only_mutation':{'path':'.gitattributes','append_exact_rules':rules},
 'finite_owned_scan':{'inventory_pins':inventory_pins,'paths':paths,'count':len(paths),'raw_blob_ids':raw_oids,'clean_blob_ids':clean,'only_mismatches':mismatches,'physical_before':before},
 'before_source_descriptors':source_before,'source_146_unchanged_and_two_paths_excluded':True,
 'original_selected_copy_input_count':len(inputs['copy_inputs']),'two_paths_excluded_from_original_copy_inputs':True,
 'original_failed_renewal_root_untouched':True,'benchmark_or_ci_acceptance':False,
 'next_proof':'Real finite existing-index old-tree to raw-bad-tree and then attrs-fixed-tree ordinary detached checkout; preserve every original raw blob. No full checkout/runtime retry.',
 'raw_payloads_rewritten':False,'observed_at_ns':time.time_ns()}
ref=save('preedit-proposal-and-authorization.v1.json',(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'proposal':ref,'finite_owned_scan_count':len(paths),'only_mismatches':mismatches,'source_count':len(source_before)}))
