from pathlib import Path
import hashlib
import json
import subprocess
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent
git = ['git', '-c', 'core.longpaths=true']
def command(args):
    return subprocess.check_output([*git, *args], cwd=ROOT)
fp = HERE / 'checkpoint-freeze.v1.json'
raw = fp.read_bytes()
freeze = json.loads(raw)
commit = command(['rev-parse', 'HEAD']).decode().strip()
assert command(['rev-parse', 'HEAD^']).decode().strip() == freeze['previous_head']
assert command(['diff', '--cached', '--name-only']) == b''
rows = list(freeze['owned_files'])
rows.append({'path': fp.relative_to(ROOT).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
for row in rows:
    physical = (ROOT / row['path']).read_bytes()
    assert physical == command(['show', ':' + row['path']]) == command(['show', commit + ':' + row['path']])
    assert len(physical) == row['size_bytes'] and hashlib.sha256(physical).hexdigest() == row['sha256']
value = {'commit': commit, 'previous_head': freeze['previous_head'], 'owned_count': len(rows),
         'owned_total_bytes': sum(r['size_bytes'] for r in rows), 'physical_equals_index_equals_commit': True,
         'index_empty': True, 'runtime_scope_changed': False, 'raw_evidence_rewritten': False,
         'scope': freeze['scope'], 'current_source_runtime_accepted': False, 'full_ci_successful': False}
b = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'commit-proof.v1.json').open('xb') as stream:
    assert stream.write(b) == len(b)
print(json.dumps({'commit': commit, 'verified_file_count': len(rows), 'proof_size_bytes': len(b), 'proof_sha256': hashlib.sha256(b).hexdigest()}))
