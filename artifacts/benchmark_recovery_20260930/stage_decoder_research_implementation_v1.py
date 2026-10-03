"""Freeze only closed artifact research implementation and nonpromoting evidence."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ART = 'artifacts/benchmark_recovery_20260930/'
CODE = ART + 'decoder-research-implementation-v1/'
OWNED = [CODE + name for name in ('controller.py', 'guest_consumer.py', 'research_protocol.py',
                                  'test_research_protocol.py', 'README.md')]
OWNED += [ART + 'decoder-controller-independent-prelaunch-review.v1.json',
          ART + 'decoder-experiment-prerequisites/prerequisite-recipe-ledger.v2.json',
          ART + 'byte-freeze-original-clone-quiescence.v1.json',
          ART + 'stage_decoder_research_implementation_v1.py', 'BENCHMARK_RECOVERY_PLAN.md']
for ordinal in range(1, 6):
    OWNED += [ART + f'decoder-research-controller-tests/attempt-{ordinal:02d}/' + name
              for name in ('original.stdout', 'original.stderr', 'terminal.v1.json')]


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True).stdout


assert git('rev-parse', 'HEAD').decode().strip() == '1f19a1eb8f8a9f24ba6e6e6f8e4915dc735e2085'
assert git('diff', '--cached', '--name-only', '-z') == b''
review = json.loads((ROOT / (ART + 'decoder-controller-independent-prelaunch-review.v1.json')).read_bytes())
for row in review['sources'] + [review['README']]:
    raw = (ROOT / row['path']).read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
for row in review['reviewed_planning_files']:
    path = row['path']
    if path.startswith('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/'):
        path = path.split('/fix-benchmark-preparations-spec/', 1)[1]
    raw = (ROOT / path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
assert not (ROOT / (ART + 'decoder-research-attempt-01')).exists()
before = {name: (ROOT / name).read_bytes() for name in OWNED}
git('add', '-f', '--', *OWNED)
staged = [name.decode() for name in git('diff', '--cached', '--name-only', '-z').split(b'\0') if name]
assert set(staged) == set(OWNED)
for name, raw in before.items():
    assert raw == (ROOT / name).read_bytes() == git('show', ':' + name)
print(json.dumps({'parent': git('rev-parse', 'HEAD').decode().strip(), 'exact_owned_staged_paths': staged,
                  'physical_index_bytes_equal': True, 'actual_decoder_research_started': False,
                  'accepted': False, 'publication_ready': False}))
