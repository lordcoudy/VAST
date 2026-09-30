"""Stage only the pinned finite owned inventory as physical bytes; no commit/push."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[3]
folder = Path(__file__).parent
inventory_path = folder / 'inventory.v1.json'
original = inventory_path.read_bytes()
assert hashlib.sha256(original).hexdigest() == 'cafb85e244cae9d43ed86de443e084b2afa2b06a60f970849c0f5c1107a849b4'
inventory = json.loads(original)
rows = inventory['files']
assert len(rows) == 277 and inventory['total_bytes'] == 10465700
git = ['git', '-c', 'core.longpaths=true']
def command(args, raw=None):
    return subprocess.check_output([*git, *args], cwd=root, input=raw)
assert command(['rev-parse', 'HEAD']).decode().strip() == inventory['previous_head']
assert command(['diff', '--cached', '--name-only']) == b''
for path in (inventory_path, Path(__file__).resolve()):
    raw = path.read_bytes()
    rows.append({'path': path.relative_to(root).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert len({r['path'] for r in rows}) == len(rows) == 279
for row in rows:
    path = root / row['path']
    assert path.resolve(strict=True).is_relative_to(root) and not path.is_symlink() and path.stat().st_nlink == 1
    raw = path.read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
    # --stdin without --path stores exact physical bytes without EOL filters.
    blob = command(['hash-object', '-w', '--stdin'], raw).decode().strip()
    command(['update-index', '--add', '--cacheinfo', '100644', blob, row['path']])
expected = {r['path'] for r in rows}
actual = set(command(['diff', '--cached', '--name-only', '-z']).decode().split('\0')) - {''}
assert actual <= expected
for row in rows:
    raw = command(['show', ':' + row['path']])
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
    assert (root / row['path']).read_bytes() == raw
value = {'owned_files': rows, 'staged_changed_count': len(actual), 'owned_count': len(rows),
         'physical_equals_index': True, 'unrelated_index_paths': [],
         'unchanged_selected_ext4_source_commit': inventory['previous_head'],
         'benchmark_source87_changed': False, 'full_ci_successful': False,
         'gpu_accepted': False, 'scope': 'exact finite CI-only source and closed evidence/doc checkpoint'}
target = folder / 'checkpoint-freeze.v1.json'
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with target.open('xb') as stream:
    stream.write(raw)
blob = command(['hash-object', '-w', '--stdin'], raw).decode().strip()
relative = target.relative_to(root).as_posix()
command(['update-index', '--add', '--cacheinfo', '100644', blob, relative])
assert command(['show', ':' + relative]) == raw
print(json.dumps({'owned_count_with_freeze': len(rows)+1, 'staged_changed_count_before_freeze': len(actual),
                  'freeze_size_bytes': len(raw), 'freeze_sha256': hashlib.sha256(raw).hexdigest(),
                  'physical_equals_index': True, 'commit_performed': False}))
