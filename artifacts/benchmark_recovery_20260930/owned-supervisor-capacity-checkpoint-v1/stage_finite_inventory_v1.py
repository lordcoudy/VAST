"""Stage only an exact finite inventory, using raw blob bytes without EOL filters."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
assert len(sys.argv) == 5, 'stage INVENTORY_SHA INVENTORY_SIZE FILE_COUNT TOTAL_BYTES'
inventory_path = HERE / 'inventory.v1.json'
raw_inventory = inventory_path.read_bytes()
assert hashlib.sha256(raw_inventory).hexdigest() == sys.argv[1] and len(raw_inventory) == int(sys.argv[2])
inventory = json.loads(raw_inventory)
rows = list(inventory['files'])
assert len(rows) == int(sys.argv[3]) == inventory['file_count']
assert sum(r['size_bytes'] for r in rows) == int(sys.argv[4]) == inventory['total_bytes']
assert set(inventory['source_paths']) == {
    'scripts/backend_publication_process_supervisor_v3.py',
    'tests/test_backend_publication_broker_terminal_v3.py',
    'tests/test_publication_operational_process_custody_v1.py',
}
git = ['git', '-c', 'core.longpaths=true']
def command(args, raw=None):
    return subprocess.check_output([*git, *args], cwd=ROOT, input=raw)
assert command(['rev-parse', 'HEAD']).decode().strip() == inventory['previous_head']
assert command(['diff', '--cached', '--name-only']) == b''
for path in (inventory_path, Path(__file__).resolve()):
    raw = path.read_bytes()
    rows.append({'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert len({r['path'] for r in rows}) == len(rows)
# Verify all inventory members before the first index mutation.
for row in rows:
    path = ROOT / row['path']
    assert path.resolve(strict=True).is_relative_to(ROOT) and not path.is_symlink() and path.stat().st_nlink == 1
    raw = path.read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
for row in rows:
    raw = (ROOT / row['path']).read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    blob = command(['hash-object', '-w', '--stdin'], raw).decode().strip()
    command(['update-index', '--add', '--cacheinfo', '100644', blob, row['path']])
actual = set(command(['diff', '--cached', '--name-only', '-z']).decode().split('\0')) - {''}
assert actual <= {r['path'] for r in rows}
for row in rows:
    indexed = command(['show', ':' + row['path']])
    assert len(indexed) == row['size_bytes'] and hashlib.sha256(indexed).hexdigest() == row['sha256']
    assert (ROOT / row['path']).read_bytes() == indexed
value = {
    'previous_head': inventory['previous_head'], 'owned_files': rows,
    'owned_count': len(rows), 'staged_changed_count': len(actual),
    'physical_equals_index': True, 'unrelated_index_paths': [],
    'host87_changed_path': inventory['source87_changed_path'], 'selected73_changed': False,
    'current_source_runtime_acceptance': False, 'full_ci_successful': False,
    'scope': 'reviewed sole-owner supervisor and capacity fixture plus closed evidence and prepared renewal; no runtime waiver',
}
target = HERE / 'checkpoint-freeze.v1.json'
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with target.open('xb') as stream:
    assert stream.write(raw) == len(raw)
blob = command(['hash-object', '-w', '--stdin'], raw).decode().strip()
relative = target.relative_to(ROOT).as_posix()
command(['update-index', '--add', '--cacheinfo', '100644', blob, relative])
assert command(['show', ':' + relative]) == raw
print(json.dumps({'owned_count_with_freeze': len(rows) + 1, 'staged_changed_count_before_freeze': len(actual), 'freeze_size_bytes': len(raw), 'freeze_sha256': hashlib.sha256(raw).hexdigest(), 'physical_equals_index': True, 'commit_performed': False}))
