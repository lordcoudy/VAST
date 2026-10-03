"""Preserve one already tested physical CRLF source; never normalize it."""
from pathlib import Path
import hashlib, json, os, subprocess

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
HEAD = '958a036bc5a55821c712204577fdf4c51c2181c7'
NAME = 'tests/test_publication_worker_termination_facts_v1.py'
EXPECTED = '149127245376786f398234edefbb197e03656cb11f98a6e7f6f86cb1ce98afd3'
ATTRS = 'f2a113e232566f8110dc5c282bbec1adf10499c2dc61d499e2bbf9a7fdb4b01e'
GIT = ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.longpaths=true']

def git(args, payload=None):
    p = subprocess.run(GIT + args, cwd=ROOT, input=payload, capture_output=True, timeout=15)
    assert p.returncode == 0, (args, p.returncode, p.stderr[:2048])
    return p.stdout

assert git(['rev-parse', 'HEAD']).decode().strip() == HEAD
assert git(['diff', '--cached', '--name-only', '-z']) == b''
source = ROOT / NAME
raw = source.read_bytes()
assert len(raw) == 6599 and hashlib.sha256(raw).hexdigest() == EXPECTED
raw_id = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
before = {s:git(['-c', 'core.autocrlf='+s, 'hash-object', '--path='+NAME, '--stdin'], raw).decode().strip()
          for s in ('false', 'true')}
assert before['false'] == raw_id and before['true'] != raw_id
attrs_path = ROOT / '.gitattributes'
attrs = attrs_path.read_bytes()
assert len(attrs) == 16575 and hashlib.sha256(attrs).hexdigest() == ATTRS
addition = (b'\n# Preserve this reviewed CRLF test source exactly under either checkout setting.\n'
            b'/tests/test_publication_worker_termination_facts_v1.py -text !eol\n')
assert NAME.encode() not in attrs
assert not (HERE / 'exact-test-byte-preservation.v1.json').exists()
with (HERE / 'original-attributes.raw').open('xb') as f:
    f.write(attrs); f.flush(); os.fsync(f.fileno())
with attrs_path.open('wb') as f:
    f.write(attrs + addition); f.flush(); os.fsync(f.fileno())
after = {s:git(['-c', 'core.autocrlf='+s, 'hash-object', '--path='+NAME, '--stdin'], raw).decode().strip()
         for s in ('false', 'true')}
assert set(after.values()) == {raw_id} and source.read_bytes() == raw
assert attrs_path.read_bytes() == attrs + addition
receipt = {'artifact_kind':'decision28_exact_test_byte_preservation_v1', 'schema_version':1,
    'baseline_commit':HEAD, 'single_exact_added_rule':addition.decode(),
    'original_attributes':{'size_bytes':len(attrs), 'sha256':ATTRS},
    'candidate_attributes':{'size_bytes':len(attrs+addition), 'sha256':hashlib.sha256(attrs+addition).hexdigest()},
    'test':{'path':NAME, 'size_bytes':len(raw), 'sha256':EXPECTED,
            'physical_bytes_unchanged':True, 'crlf':raw.count(b'\r\n'), 'bare_lf':raw.count(b'\n')-raw.count(b'\r\n')},
    'raw_git_blob_id':raw_id, 'before_clean_ids':before, 'after_clean_ids':after,
    'original_attribute_prefix_unchanged':True, 'staging_or_commit':False,
    'authority':'Existing exact physical source preservation requirement; no production/test semantics changed.',
    'review_pending':True, 'runtime_image_or_hardware_execution':False}
receipt_raw = (json.dumps(receipt, sort_keys=True, indent=2)+'\n').encode()
with (HERE / 'exact-test-byte-preservation.v1.json').open('xb') as f:
    f.write(receipt_raw); f.flush(); os.fsync(f.fileno())
print(json.dumps({'size_bytes':len(receipt_raw), 'sha256':hashlib.sha256(receipt_raw).hexdigest(),
                  'source_bytes_unchanged':True, 'prospective_raw_clean_both_equal':True}))
