"""Raw-blob stage of an exact finite attrs inventory; no commit or normalization."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
assert len(sys.argv) == 5
path = HERE / 'inventory.v1.json'
raw = path.read_bytes()
assert hashlib.sha256(raw).hexdigest() == sys.argv[1] and len(raw) == int(sys.argv[2])
inventory = json.loads(raw)
rows = list(inventory['files'])
assert len(rows) == int(sys.argv[3]) and sum(r['size_bytes'] for r in rows) == int(sys.argv[4])
assert inventory['source_paths'] == ['.gitattributes'] and not inventory['host87_selected73_native_worker_changed']
git = ['git', '-c', 'core.longpaths=true', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false']
def command(args, raw=None):
    return subprocess.check_output([*git, *args], cwd=ROOT, input=raw)
assert command(['rev-parse', 'HEAD']).decode().strip() == inventory['previous_head']
assert command(['diff', '--cached', '--name-only']) == b''
for p in (path, Path(__file__).resolve()):
    b = p.read_bytes()
    rows.append({'path': p.relative_to(ROOT).as_posix(), 'size_bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()})
assert len({r['path'] for r in rows}) == len(rows)
for row in rows:
    p = ROOT / row['path']
    assert p.resolve(strict=True).is_relative_to(ROOT) and not p.is_symlink() and p.stat().st_nlink == 1
    b = p.read_bytes()
    assert len(b) == row['size_bytes'] and hashlib.sha256(b).hexdigest() == row['sha256']
    raw_oid = hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()
    for autocrlf in ('false', 'true'):
        filtered_oid = command(['-c', 'core.autocrlf=' + autocrlf, 'hash-object', '--stdin', '--path=' + row['path']], b).decode().strip()
        assert filtered_oid == raw_oid, 'pre-stage raw/filtered Git object mismatch: ' + row['path']
for row in rows:
    b = (ROOT / row['path']).read_bytes()
    assert len(b) == row['size_bytes'] and hashlib.sha256(b).hexdigest() == row['sha256']
    blob = command(['hash-object', '-w', '--stdin'], b).decode().strip()
    command(['update-index', '--add', '--cacheinfo', '100644', blob, row['path']])
actual = set(command(['diff', '--cached', '--name-only', '-z']).decode().split('\0')) - {''}
assert actual <= {r['path'] for r in rows}
for row in rows:
    indexed = command(['show', ':' + row['path']])
    assert indexed == (ROOT / row['path']).read_bytes()
    assert len(indexed) == row['size_bytes'] and hashlib.sha256(indexed).hexdigest() == row['sha256']
value = {'previous_head': inventory['previous_head'], 'owned_files': rows, 'owned_count': len(rows),
         'staged_changed_count': len(actual), 'physical_equals_index': True, 'unrelated_index_paths': [],
         'scope': inventory['scope'], 'changed_source_path': '.gitattributes',
         'runtime_scope_changed': False, 'raw_evidence_rewritten': False,
         'current_source_runtime_accepted': False, 'full_ci_successful': False}
target = HERE / 'checkpoint-freeze.v1.json'
b = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with target.open('xb') as stream:
    assert stream.write(b) == len(b)
blob = command(['hash-object', '-w', '--stdin'], b).decode().strip()
relative = target.relative_to(ROOT).as_posix()
command(['update-index', '--add', '--cacheinfo', '100644', blob, relative])
assert command(['show', ':' + relative]) == b
print(json.dumps({'owned_count_with_freeze': len(rows) + 1, 'changed_before_freeze': len(actual), 'freeze_size_bytes': len(b), 'freeze_sha256': hashlib.sha256(b).hexdigest(), 'physical_equals_index': True, 'commit_performed': False}))
