"""Verify the committed finite freeze without changing Git or unrelated files."""
from pathlib import Path
import hashlib
import json
import subprocess
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
git = ['git', '-c', 'core.longpaths=true']
def command(args):
    return subprocess.check_output([*git, *args], cwd=ROOT)
freeze_path = HERE / 'checkpoint-freeze.v1.json'
freeze_raw = freeze_path.read_bytes()
freeze = json.loads(freeze_raw)
commit = command(['rev-parse', 'HEAD']).decode().strip()
assert command(['rev-parse', 'HEAD^']).decode().strip() == freeze['previous_head']
assert command(['diff', '--cached', '--name-only']) == b''
rows = list(freeze['owned_files'])
rows.append({'path': freeze_path.relative_to(ROOT).as_posix(), 'size_bytes': len(freeze_raw), 'sha256': hashlib.sha256(freeze_raw).hexdigest()})
for row in rows:
    physical = (ROOT / row['path']).read_bytes()
    indexed = command(['show', ':' + row['path']])
    committed = command(['show', commit + ':' + row['path']])
    assert physical == indexed == committed, row['path']
    assert len(committed) == row['size_bytes'] and hashlib.sha256(committed).hexdigest() == row['sha256']
value = {
    'commit': commit, 'previous_head': freeze['previous_head'], 'owned_file_count': len(rows),
    'owned_total_bytes': sum(r['size_bytes'] for r in rows),
    'freeze_sha256': hashlib.sha256(freeze_raw).hexdigest(),
    'physical_equals_index_equals_commit': True, 'index_empty': True,
    'source87_changed_path': 'scripts/backend_publication_process_supervisor_v3.py',
    'selected73_image_sources_changed': False, 'unrelated_changes_preserved': True,
    'current_source_runtime_acceptance': False, 'full_ci_successful': False,
    'scope': 'exact reviewed source/closed evidence/prepared renewal checkpoint; genuine current host/measurement/CI gates still pending',
}
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'commit-proof.v1.json').open('xb') as stream:
    assert stream.write(raw) == len(raw)
print(json.dumps({'commit': commit, 'verified_file_count': len(rows), 'proof_size_bytes': len(raw), 'proof_sha256': hashlib.sha256(raw).hexdigest()}))
