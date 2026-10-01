"""Append only the two diagnosed forensic byte-preservation rules."""
import hashlib,json,os,stat
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
proposal_raw=(HERE/'preedit-proposal-and-authorization.v1.json').read_bytes()
assert hashlib.sha256(proposal_raw).hexdigest()=='99a5d39eb68e17edd14a4114d01fe92f1869f6a93cc37127efe1df427ca84751'
proposal=json.loads(proposal_raw);original=(HERE/'gitattributes.before.raw').read_bytes()
p=ROOT/'.gitattributes';assert p.read_bytes()==original
rules=proposal['proposed_only_mutation']['append_exact_rules'];assert len(rules)==len(set(rules))==2
assert all(r.startswith('/artifacts/benchmark_recovery_20260930/') and r.endswith('.json -text !eol') and '*' not in r and r.encode() not in original for r in rules)
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
for relative,ref in proposal['before_source_descriptors'].items():
 q=ROOT/relative;raw=q.read_bytes();assert len(raw)==ref['size_bytes'] and hashlib.sha256(raw).hexdigest()==ref['sha256'] and epoch(q.lstat())==ref['epoch']
append=b'\n# Preserve the two additional original JSON blobs exposed by existing-index checkout.\n'+('\n'.join(rules)+'\n').encode('ascii')
before=p.lstat();assert stat.S_ISREG(before.st_mode) and before.st_nlink==1
fd=os.open(p,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_CLOEXEC)
try:
 assert epoch(os.fstat(fd))==epoch(before)==epoch(p.lstat());view=memoryview(append)
 while view:n=os.write(fd,view);assert n>0;view=view[n:]
 os.fsync(fd)
finally:os.close(fd)
current=p.read_bytes();assert current==original+append
for item in proposal['findings']:
 q=ROOT/item['path'];raw=q.read_bytes();ref=item['original_git_and_primary']
 assert len(raw)==ref['size_bytes'] and hashlib.sha256(raw).hexdigest()==ref['sha256'] and epoch(q.lstat())==ref['epoch']
value={'schema_version':1,'status':'applied_exact_two_pending_controlled_transition_proof_and_peer',
 'only_production_path':'.gitattributes','before':{'size_bytes':len(original),'sha256':hashlib.sha256(original).hexdigest()},
 'after':{'size_bytes':len(current),'sha256':hashlib.sha256(current).hexdigest()},'rules':rules,
 'entire_original_prefix_first15_and_LF_contracts_unchanged':True,'raw_payloads_unchanged':True,
 'original_failed_renewal_root_untouched':True,'full_ci_or_benchmark_acceptance':False}
for name,raw in [('gitattributes.after.raw',current),('attributes-apply.v1.json',(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())]:
 with (HERE/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
print(json.dumps(value))
