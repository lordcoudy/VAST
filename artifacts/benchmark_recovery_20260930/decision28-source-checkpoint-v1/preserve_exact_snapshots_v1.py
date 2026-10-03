"""Preserve the two immutable original source snapshots without rewriting them."""
from pathlib import Path
import hashlib, json, os, subprocess

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
guard_raw = (HERE / 'finite-candidate-guard.v1.json').read_bytes()
assert hashlib.sha256(guard_raw).hexdigest() == '401cdc536d0f83ab6d54a5273322dcba21a4abd40d2fee73b3d0d57fdf2c76ee'
guard = json.loads(guard_raw)
expected = {
    'artifacts/benchmark_recovery_20260930/decision28-sidecar-failure-observability-v1/before/scripts/checkpoint_gstreamer_analytics_sidecar.py':
        (296398, '0a0ff1d67e536d42258d8d53f8ed511283db478aba30442411b607bb849970ef'),
    'artifacts/benchmark_recovery_20260930/decision28-sidecar-failure-observability-v1/before/tests/test_publication_worker_termination_facts_v1.py':
        (3296, '698c118aa705f66b3f58e97e29392ab4be7d371c15a489068991b5567242b55e')}
assert {r['path']:(r['size_bytes'],r['sha256']) for r in guard['mismatches']} == expected
original = (HERE / 'original-attributes.raw').read_bytes()
assert hashlib.sha256(original).hexdigest() == 'f2a113e232566f8110dc5c282bbec1adf10499c2dc61d499e2bbf9a7fdb4b01e'
test_rule = (b'\n# Preserve this reviewed CRLF test source exactly under either checkout setting.\n'
             b'/tests/test_publication_worker_termination_facts_v1.py -text !eol\n')
attrs_path = ROOT / '.gitattributes'
before_attrs = attrs_path.read_bytes()
assert before_attrs == original + test_rule
raws = {}
for name, (size, sha) in expected.items():
    b = (ROOT/name).read_bytes()
    assert len(b) == size and hashlib.sha256(b).hexdigest() == sha
    raws[name] = b
addition = b'\n# Preserve the two immutable original sidecar source snapshots exactly.\n'
for name in sorted(expected):
    assert name.encode() not in before_attrs
    addition += ('/'+name+' -text !eol\n').encode()
assert not (HERE/'exact-snapshot-byte-preservation.v1.json').exists()
with attrs_path.open('wb') as f:
    f.write(before_attrs+addition); f.flush(); os.fsync(f.fileno())
git = ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.longpaths=true']
after = {}
for name, b in raws.items():
    oid = hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    after[name] = {}
    for setting in ('false','true'):
        p = subprocess.run(git+['-c','core.autocrlf='+setting,'hash-object','--path='+name,'--stdin'],
            cwd=ROOT, input=b, capture_output=True, timeout=15)
        assert p.returncode == 0
        after[name][setting] = p.stdout.decode().strip()
    assert set(after[name].values()) == {oid} and (ROOT/name).read_bytes() == b
assert attrs_path.read_bytes() == before_attrs+addition
receipt = {'artifact_kind':'decision28_exact_snapshot_byte_preservation_v1', 'schema_version':1,
    'first_read_only_guard_sha256':hashlib.sha256(guard_raw).hexdigest(),
    'original_attributes_prefix_unchanged':True, 'added_exact_rules':addition.decode(),
    'final_attributes':{'size_bytes':len(before_attrs+addition), 'sha256':hashlib.sha256(before_attrs+addition).hexdigest()},
    'immutable_snapshot_bytes_unchanged':True, 'after_clean_ids':after,
    'staging_or_commit':False, 'source_test_or_CI_semantics_changed':False, 'independent_review_pending':True}
raw = (json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
with (HERE/'exact-snapshot-byte-preservation.v1.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
print(json.dumps({'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(), 'final_attributes':receipt['final_attributes']}))
