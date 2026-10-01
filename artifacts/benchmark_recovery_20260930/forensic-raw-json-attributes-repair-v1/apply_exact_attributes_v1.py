"""Apply only the fifteen diagnosed raw forensic JSON exceptions."""
import hashlib,json,os,stat
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
proposal_path=HERE/'preedit-proposal-and-authorization.v1.json'
raw=proposal_path.read_bytes();assert hashlib.sha256(raw).hexdigest()=='c379701c2eb4797ba97f415a8f7547640ccf7c47dbc5094c5ac02f9470e1f371'
proposal=json.loads(raw);original=(HERE/'gitattributes.before.raw').read_bytes()
p=ROOT/'.gitattributes';assert p.read_bytes()==original
rules=proposal['proposed_only_mutation']['append_exact_rules'];assert len(rules)==15 and len(set(rules))==15
assert all(r.startswith('/artifacts/benchmark_recovery_20260930/') and r.endswith('.json -text !eol') and '*' not in r for r in rules)
append=b'\n# Preserve these exact retained forensic JSON blobs; automatic clean must not normalize them.\n'+('\n'.join(rules)+'\n').encode('ascii')
assert all(r.encode('ascii') not in original for r in rules)
def ep(i):return [i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns]
before=p.lstat();assert stat.S_ISREG(before.st_mode) and before.st_nlink==1
fd=os.open(p,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW|os.O_CLOEXEC)
try:
    assert ep(os.fstat(fd))==ep(before)==ep(p.lstat())
    view=memoryview(append)
    while view:
        n=os.write(fd,view);assert n>0;view=view[n:]
    os.fsync(fd)
finally:os.close(fd)
current=p.read_bytes();assert current==original+append
for item in proposal['findings']:
    path=ROOT/item['path'];data=path.read_bytes();expected=item['original_git_and_primary']
    assert len(data)==expected['size_bytes'] and hashlib.sha256(data).hexdigest()==expected['sha256'] and ep(path.lstat())==expected['epoch']
for relative,expected in proposal['before_source_descriptors'].items():
    path=ROOT/relative;data=path.read_bytes()
    assert len(data)==expected['size_bytes'] and hashlib.sha256(data).hexdigest()==expected['sha256'] and ep(path.lstat())==expected['epoch']
for name,value in [('gitattributes.after.raw',current),('attributes-apply.v1.json',(json.dumps({'schema_version':1,'status':'applied_finite15_pending_controlled_proof_peer','only_production_path':'.gitattributes','before':{'size_bytes':len(original),'sha256':hashlib.sha256(original).hexdigest()},'after':{'size_bytes':len(current),'sha256':hashlib.sha256(current).hexdigest()},'prefix_bytes_unchanged':True,'original_LF_contracts_unchanged':True,'JSON_payload_bytes_and_epochs_unchanged':True,'source_146_bytes_and_epochs_unchanged':True,'original_failed_CI_checkout_not_modified':True,'rules':rules,'no_acceptance_claim':True},sort_keys=True,indent=2)+'\n').encode('ascii'))]:
    with (HERE/name).open('xb') as f:f.write(value);f.flush();os.fsync(f.fileno())
print(json.dumps({'path':'.gitattributes','size_bytes':len(current),'sha256':hashlib.sha256(current).hexdigest(),'original_payloads':15,'source_members_unchanged':146}))
