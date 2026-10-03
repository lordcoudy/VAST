"""Stage exactly the reviewed CPU slice and its closed nonacceptance evidence."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ART = 'artifacts/benchmark_recovery_20260930/'
OWNED = (
    '.github/workflows/ci.yml', '.ci/requirements.txt', 'scripts/run_ci_checks.py',
    'tests/test_run_ci_checks.py', 'BENCHMARK_RECOVERY_PLAN.md',
    ART + 'cpu-ci-slice-independent-review.v1.json',
    ART + 'record_cpu_ci_preflight_v1.py', ART + 'stage_cpu_ci_slice_v1.py',
    ART + 'cpu-ci-preflight-v1/original-terminal.v1.json',
    ART + 'cpu-ci-preflight-v1/original.stdout', ART + 'cpu-ci-preflight-v1/original.stderr',
)


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True).stdout


assert git('rev-parse', 'HEAD').decode().strip() == '79ff17832cf7293f3ff3321af537f687072a1d52'
assert git('diff', '--cached', '--name-only', '-z') == b''
review = json.loads((ROOT / (ART + 'cpu-ci-slice-independent-review.v1.json')).read_bytes())
for row in review['reviewed_files']:
    raw = (ROOT / row['relative_path']).read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
preflight = json.loads((ROOT / (ART + 'cpu-ci-preflight-v1/original-terminal.v1.json')).read_bytes())
assert preflight['scoped_successful'] and preflight['original_returncode'] == 0
assert preflight['source_unchanged'] and not preflight['hardware_acceptance']
before = {name: (ROOT / name).read_bytes() for name in OWNED}
git('add', '-f', '--', *OWNED)
staged = [name.decode() for name in git('diff', '--cached', '--name-only', '-z').split(b'\0') if name]
assert set(staged) == set(OWNED)
for name, raw in before.items():
    assert (ROOT / name).read_bytes() == raw == git('show', ':' + name)
print(json.dumps({'parent': git('rev-parse', 'HEAD').decode().strip(),
                  'exact_owned_staged_paths': staged, 'physical_index_bytes_equal': True,
                  'hosted_workflow_executed': False, 'hardware_acceptance': False}))
