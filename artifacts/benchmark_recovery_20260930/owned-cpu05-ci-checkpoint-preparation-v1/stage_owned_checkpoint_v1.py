"""Prepare or stage ONLY the exact reviewed finite checkpoint. Root owns execution."""
from pathlib import Path
import argparse, hashlib, json, subprocess
p = argparse.ArgumentParser()
p.add_argument('--project-root', type=Path, required=True)
p.add_argument('--inventory', type=Path, required=True)
p.add_argument('--inventory-sha256', required=True)
p.add_argument('--stage', action='store_true')
a = p.parse_args()
root = a.project_root.resolve(strict=True)
raw_inventory = a.inventory.read_bytes()
assert hashlib.sha256(raw_inventory).hexdigest() == a.inventory_sha256
inventory = json.loads(raw_inventory)
owned = inventory['files']
assert len({row['path'] for row in owned}) == len(owned)
physical = {}
for row in owned:
    path = Path(row['path'])
    assert not path.is_absolute() and '..' not in path.parts and path.as_posix() == row['path']
    absolute = root / path
    assert absolute.resolve(strict=True).is_relative_to(root) and not absolute.is_symlink()
    raw = absolute.read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
    physical[row['path']] = raw
assert a.inventory.resolve().is_relative_to(root)
physical[a.inventory.resolve().relative_to(root).as_posix()] = raw_inventory
if not a.stage:
    print(json.dumps({'scope': 'Preparation only; no Git mutation', 'files': len(physical),
                      'bytes': sum(map(len, physical.values())), 'blocked': inventory['blocking_gates']}))
    raise SystemExit(0)
assert not inventory['blocking_gates'], 'Required exact closed source/document reviews are missing'
for gate in inventory['review_pins']:
    raw = (root / gate['path']).read_bytes()
    assert len(raw) == gate['size_bytes'] and hashlib.sha256(raw).hexdigest() == gate['sha256'], gate['path']
git = ['git', '-c', 'core.longpaths=true']
assert subprocess.check_output(git + ['rev-parse', 'HEAD'], cwd=root, text=True).strip() == inventory['previous_head']
assert not subprocess.check_output(git + ['diff', '--cached', '--name-only'], cwd=root)
paths = sorted(physical)
subprocess.run(git + ['add', '-f', '--pathspec-from-file=-', '--pathspec-file-nul'], cwd=root,
               input=b''.join(path.encode() + b'\0' for path in paths), check=True)
def blobs():
    raw = subprocess.check_output(git + ['cat-file', '--batch'], cwd=root,
                                  input=''.join(':' + path + '\n' for path in paths).encode())
    position, values = 0, {}
    for path in paths:
        end = raw.index(b'\n', position)
        header = raw[position:end].split()
        assert len(header) == 3 and header[1] == b'blob'
        count = int(header[2]); position = end + 1
        values[path] = raw[position:position + count]; position += count
        assert raw[position:position + 1] == b'\n'; position += 1
    assert position == len(raw)
    return values
carriers = []
for path, raw in blobs().items():
    if raw != physical[path]:
        assert path.startswith('artifacts/'), path
        oid = subprocess.check_output(git + ['hash-object', '-w', '--stdin'], cwd=root,
                                      input=physical[path]).decode().strip()
        subprocess.run(git + ['update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + path],
                       cwd=root, check=True)
        carriers.append(path)
assert blobs() == physical
changed = set(subprocess.check_output(git + ['diff', '--cached', '--name-only', '-z'], cwd=root)
              .decode().rstrip('\0').split('\0')) - {''}
assert changed.issubset(paths)
source_paths = [path for path in paths if not path.startswith('artifacts/')]
subprocess.run(git + ['-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
                     'diff', '--cached', '--check', '--', *source_paths], cwd=root, check=True)
freeze = a.inventory.with_name('checkpoint-freeze.v1.json')
assert not freeze.exists()
freeze.write_bytes((json.dumps({'previous_head': inventory['previous_head'], 'inventory_sha256': a.inventory_sha256,
    'owned_files': {path: {'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for path, raw in physical.items()},
    'changed_paths': sorted(changed), 'unfiltered_artifacts': carriers, 'physical_index_equal': True,
    'unrelated_dirty_files_preserved': True, 'benchmark_accepted': False, 'full_ci_successful': False,
    'original_cpu05_cli_status': 'failed'}, sort_keys=True, separators=(',', ':')) + '\n').encode())
freeze_path = freeze.resolve().relative_to(root).as_posix()
subprocess.run(git + ['add', '-f', '--', freeze_path], cwd=root, check=True)
assert subprocess.check_output(git + ['show', ':' + freeze_path], cwd=root) == freeze.read_bytes()
print(json.dumps({'owned_files': len(paths) + 1, 'changed_files': len(changed) + 1, 'physical_index_equal': True}))
