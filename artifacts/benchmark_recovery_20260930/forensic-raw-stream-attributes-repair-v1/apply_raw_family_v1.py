"""Append the one explicitly authorized forensic raw-stream rule; no payload rewrite."""
import hashlib,json,os,stat,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent;BASE=HERE.parent
START=time.monotonic()
APPEND=b'\n# Captured forensic raw streams are byte evidence; disable automatic EOL conversion.\n/artifacts/benchmark_recovery_20260930/**/*.raw -text !eol\n'
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(p):
 assert p.resolve(strict=True)==p;fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8*1048576
  raw=b''
  while block:=os.read(fd,65536):raw+=block;assert time.monotonic()-START<120
  assert epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat()) and len(raw)==s.st_size
  return raw,{'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch7':epoch(s)}
 finally:os.close(fd)
def save(name,value,raw=False):
 b=value if raw else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode('ascii')
 with (HERE/name).open('xb') as f:assert f.write(b)==len(b);f.flush();os.fsync(f.fileno())
 return pin(HERE/name)[1]
red_raw,red_pin=pin(HERE/'red-original-attempt01/execution.v1.json')
assert red_pin['sha256']=='47a7914fa1a46eb9e14875e4dbabbbabb9463b2b0839bf7912eda39d2782f9ae'
red=json.loads(red_raw);assert red['phase']=='red' and red['other_extension_mismatches']=={'false':[],'true':[]}
original,attrs_pin=pin(ROOT/'.gitattributes')
assert len(original)==16430 and attrs_pin['sha256']=='504ceb16d7ab7cff66925251859ccb453bfb3b0190b12f6ad0eba64ed79a9acd'
assert APPEND not in original
rejection,rejection_pin=pin(BASE/'owned-raw-evidence-filter-followup-checkpoint-v1/preflight-rejection.v1.json')
old_scope=json.loads((BASE/'forensic-raw-json-attributes-followup-v1/preedit-proposal-and-authorization.v1.json').read_bytes())
before_sources={relative:pin(ROOT/relative)[1] for relative in old_scope['before_source_descriptors']}
inventory=json.loads((BASE/'component-ext4-relocation-feasibility-v1/inventory.v1.json').read_bytes())
protected=set(inventory['controller_files'])|{p for rows in inventory['source_groups'].values() for p in rows}
assert len(protected)==180 and len(inventory['copy_inputs'])==2693
assert not {p for p in protected|{x['path'] for x in inventory['copy_inputs']} if p.startswith('artifacts/benchmark_recovery_20260930/') and p.endswith('.raw')}
protected_before={p:epoch((ROOT/p).lstat()) for p in protected}
payloads={p:pin(ROOT/p)[1] for p in red['mismatches']['true']}
proposal={'schema_version':1,'status':'proved_before_authorized_raw_family_append','standing_authorization':'Root explicitly authorizes ONE scoped /artifacts/benchmark_recovery_20260930/**/*.raw -text !eol plus comment, before edits; no raw payload rewrite, preserve entire16430 prefix/17JSON/45LF.','root_original_preflight_rejection':rejection_pin,'original_red_filter_proof':red_pin,'before_attributes':attrs_pin,'append_ascii':APPEND.decode('ascii'),'source_controller_180_metadata_before':protected_before,'before_source_146':before_sources,'raw_payloads_before':payloads,'protected_source_controller_matches':[],'original2693_input_matches':[],'no_checkout_runtime_or_model_operations':True}
proposal_pin=save('preedit-proposal-and-authorization.v1.json',proposal)
fd=os.open(ROOT/'.gitattributes',os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_CLOEXEC)
try:
 assert epoch(os.fstat(fd))==attrs_pin['epoch7']==epoch((ROOT/'.gitattributes').lstat())
 view=memoryview(APPEND)
 while view:n=os.write(fd,view);assert n>0;view=view[n:]
 os.fsync(fd)
finally:os.close(fd)
current,after=pin(ROOT/'.gitattributes');assert current==original+APPEND
for p,ref in before_sources.items():assert pin(ROOT/p)[1]==ref
for p,ref in payloads.items():assert pin(ROOT/p)[1]==ref
assert {p:epoch((ROOT/p).lstat()) for p in protected}==protected_before
save('gitattributes.before.raw',original,True);save('gitattributes.after.raw',current,True)
result={'schema_version':1,'status':'applied_one_raw_family_pending_green_and_peer','proposal':proposal_pin,'before':attrs_pin,'after':after,'rule':'/artifacts/benchmark_recovery_20260930/**/*.raw -text !eol','only_production_path':'.gitattributes','whole16430_prefix_17_json_45_lf_preserved':True,'source_146_fullbytes_epochs_unchanged':True,'source_controller_180_metadata_unchanged':True,'no2693_attribute_membership':True,'payloads_unchanged':True,'git_mutation':False,'all_fds_released':True,'elapsed_s':time.monotonic()-START}
ref=save('attributes-apply.v1.json',result);assert time.monotonic()-START<120
print(json.dumps({'result':ref,'attrs':after}),flush=True)
