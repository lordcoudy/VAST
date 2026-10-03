"""Close the finite reviewed planning/CI checkpoint inventory; no Git mutation."""
from pathlib import Path
import hashlib, json

root = Path.cwd()
base = root / 'artifacts/benchmark_recovery_20260930'
prep = base / 'owned-cpu05-ci-checkpoint-preparation-v1'
raw = (prep / 'inventory.v2.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == '2b2ea40b120fda74e5044aa087cbd9a3abcf4c6e0475b967a41b8b48ecab5439'
inventory = json.loads(raw)
rows = {r['path']: r for r in inventory['files']}
assert len(rows) == len(inventory['files'])
for p, row in rows.items():
    data = (root / p).read_bytes()
    assert len(data) == row['size_bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'], p

def add(path, group):
    p = path.relative_to(root).as_posix()
    assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root)
    data = path.read_bytes()
    if p in rows:
        assert rows[p]['sha256'] == hashlib.sha256(data).hexdigest()
        return
    rows[p] = {'path': p, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'groups': [group]}

for relative in (
    'openspec/changes/fix-benchmark-preparations-spec/proposal.md',
    'openspec/changes/fix-benchmark-preparations-spec/design.md',
    'openspec/changes/fix-benchmark-preparations-spec/specs/benchmark-launch-preparation/spec.md',
    'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
    'openspec/changes/fix-benchmark-preparations-spec/verification-plan.md',
    'BENCHMARK_RECOVERY_PLAN.md',
):
    add(root / relative, 'decision27_closed_six_planning')
for directory in ('decision27-planning-originals-v1', 'decision27-planning-independent-review-v1'):
    for path in sorted((base / directory).rglob('*')):
        if path.is_file():
            assert '__pycache__' not in path.parts and path.suffix != '.pyc'
            add(path, directory)
for relative in ('component-ext4-relocation-feasibility-v1/inventory.v1.json',
                 'component-ext4-relocation-feasibility-v1/git-input-classification.v1.json',
                 'component-ext4-relocation-feasibility-v1/review.v1.json'):
    add(base / relative, 'closed_ext4_feasibility_not_setup')
add(Path(__file__).resolve(), 'root_finite_inventory_finalization')

for relative, size, sha in (
    ('decision27-planning-independent-review-v1/review.v1.json', 6400, 'e0b21853f8656372646d7a954534cdcec3b5e22797166fa34d5b699746ba31d1'),
    ('component-ext4-relocation-feasibility-v1/review.v1.json', 12127, '08f057794b0a4033d4b52853bbc0420e7d4cb6674b4a6fa03779e4f515b4f58e'),
):
    data = (base / relative).read_bytes()
    assert len(data) == size and hashlib.sha256(data).hexdigest() == sha
    inventory['review_pins'].append({'path': (base / relative).relative_to(root).as_posix(), 'size_bytes': size, 'sha256': sha})

inventory['files'] = [rows[p] for p in sorted(rows)]
inventory['file_count'] = len(rows)
inventory['total_bytes'] = sum(r['size_bytes'] for r in rows.values())
inventory['blocking_gates'] = []
inventory['ready_for_staging'] = True
inventory['pending_document_scope'] = []
inventory['replaces_inventory'] = {'path': 'inventory.v2.json', 'sha256': hashlib.sha256(raw).hexdigest()}
inventory['root_review'] = {
    'finite_v2_original_rows_reverified': True, 'exact_source_reviews_preserved': True,
    'decision27_independent_closed': True, 'source_filter_check_zero_differences': True,
    'all_cpu05_holds_released': True, 'original_cpu05_cli_remains_failed': True,
    'ext4_setup_started': False, 'production_source_change_is_only_reviewed_ci_flag': True,
    'extra_test_source_is_exact_reviewed_ten_fixtures_plus_ci_test': True,
    'no_scientific_reduction_v2_or_unexecuted_ext4_helpers_added_to_this_checkpoint': True,
    'original_unrelated_dirty_files_preserved': True,
}
target = prep / 'inventory.v3.json'
with target.open('xb') as stream:
    stream.write((json.dumps(inventory, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode())
print(json.dumps({'files': len(rows), 'bytes': inventory['total_bytes'], 'inventory': str(target),
                  'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'git_mutation': False}))
