"""Finite reviewed source/closed evidence inventory; preserve all unrelated changes."""
from pathlib import Path
import hashlib
import json
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
HERE = Path(__file__).parent
PREVIOUS = '4cb9d8313cca71256179bc3b59cc6f9137e7b8ba'
SOURCE = {
    'scripts/backend_publication_process_supervisor_v3.py': (124707, '99f772665d0d271b24d98f2393a50a0f9e0bbfe5c2840e5ccce65d89a84ed13e'),
    'tests/test_backend_publication_broker_terminal_v3.py': (22598, '1e632d43c6a8361b7483ef9d160832e5993760f48103a8a22527c3bac1cbe1fa'),
    'tests/test_publication_operational_process_custody_v1.py': (30982, '8ba4f9b93e00b368712cc3f84855b648ff98d54ff887de25f99d4208e11a97d1'),
}
PEERS = {
    'broker-terminal-owner-independent-review-v1/review.v1.json': (5924, 'aeaa5070495f3fff014c87acdc518fb130d8ed9eb46fdb9aa30549db91de9beb'),
    'capacity-fixture-independent-review-v1/review.v1.json': (7668, '1bc2bcdf226ddcd744e1176c71c7a8bbc28f6660d3c160dc4710c84edc49d16f'),
    'component-supervisor-renewal-source-independent-review-v1/review.v1.json': (11106, 'ce23c737db6974ec2be06068caf3b509beb8046d2209bd54f36ddc17567d1107'),
}
DIRECTORIES = (
    'broker-terminal-owner-independent-review-v1', 'broker-terminal-owner-repair-v1',
    'capacity-fixture-independent-review-v1', 'ci-4cb9-original-host-retention-v1',
    'ci-4cb9-two-failure-diagnosis-v1',
    'component-cpu06-windows-retention-independent-review-v1',
    'component-cpu06-windows-retention-preparation-v1',
    'component-current-source-ci-4cb9-preparation-v1',
    'component-four-arm-independent-science-preparation-v1',
    'component-four-arm-independent-science-result-review-v1',
    'component-four-arm-independent-science-source-review-v1',
    'component-gpu01-controller-independent-review-v1',
    'component-gpu01-ext4-actual-audit-closure-v1',
    'component-gpu01-ext4-dispatch-grant-v1',
    'component-gpu01-ext4-postterminal-audit-independent-review-v1',
    'component-gpu01-ext4-postterminal-audit-preparation-v1',
    'component-gpu01-ext4-readiness-v1',
    'component-gpu01-windows-retention-independent-review-v1',
    'component-gpu01-windows-retention-preparation-v1',
    'component-pair-current-task-closure-v1', 'component-runbook-independent-review-v1',
    'component-supervisor-renewal-preparation-v1',
    'component-supervisor-renewal-source-independent-review-v1',
    'decision24-ci-userns-profile-actual-independent-review-v1', 'plot-preview-v1',
)
paths = set(SOURCE)
for relative, (size, sha) in {**SOURCE, **{('artifacts/benchmark_recovery_20260930/' + p): v for p, v in PEERS.items()}}.items():
    raw = (ROOT / relative).read_bytes()
    assert len(raw) == size and hashlib.sha256(raw).hexdigest() == sha, relative
for directory in DIRECTORIES:
    folder = BASE / directory
    assert folder.is_dir(), directory
    for path in folder.rglob('*'):
        assert not path.is_symlink(), str(path)
        if path.is_file():
            assert '__pycache__' not in path.parts
            assert path.suffix.lower() not in {'.pyc', '.onnx', '.engine', '.plan', '.whl', '.rgb'}, str(path)
            if path.suffix.lower() == '.bin':
                assert directory == 'broker-terminal-owner-repair-v1' and 'fixtures' in path.parts and path.name == 'authorization.bin'
                fixture_raw = path.read_bytes()
                assert (len(fixture_raw), hashlib.sha256(fixture_raw).hexdigest()) in {
                    (36, '8ef4e6727726f1a517a110b9cb56b66f9ddae35df6b12b2d49616ad0378db8a7'),
                    (27, '77321e98ab0fe3a1aaa4550a07ad0d470d6f52954f65c50b72da07790b80c228'),
                }, str(path)
            paths.add(path.relative_to(ROOT).as_posix())
paths.update((
    'BENCHMARK_RECOVERY_PLAN.md', 'docs/gstreamer-component-benchmark-runbook.md',
    'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
    'artifacts/benchmark_recovery_20260930/owned-ci-policy-checkpoint-v1/commit-proof.v1.json',
    'artifacts/benchmark_recovery_20260930/root-architecture-self-review-v1/review.current.v2.md',
    Path(__file__).relative_to(ROOT).as_posix(),
    'artifacts/benchmark_recovery_20260930/owned-supervisor-capacity-checkpoint-v1/verify_commit_bytes_v1.py',
    'artifacts/benchmark_recovery_20260930/owned-supervisor-capacity-checkpoint-v1/inventory-attempt01.guard-failure.v1.json',
))
rows = []
for relative in sorted(paths):
    path = ROOT / relative
    info = path.lstat()
    assert path.resolve(strict=True).is_relative_to(ROOT)
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()
    raw = path.read_bytes()
    assert len(raw) <= 32 * 1024 * 1024, relative
    rows.append({'path': relative, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert sum(r['size_bytes'] for r in rows) <= 96 * 1024 * 1024
git = ['git', '-c', 'core.longpaths=true']
assert subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == PREVIOUS
assert not subprocess.check_output([*git, 'diff', '--cached', '--name-only'], cwd=ROOT)
value = {
    'previous_head': PREVIOUS, 'files': rows, 'file_count': len(rows),
    'total_bytes': sum(r['size_bytes'] for r in rows),
    'source_paths': sorted(SOURCE), 'reviewed_source_sha256': {p: v[1] for p, v in SOURCE.items()},
    'source87_changed_path': 'scripts/backend_publication_process_supervisor_v3.py',
    'selected73_image_source_changed': False,
    'scope': 'three reviewed source/test files, closed original evidence, truthful documents and reviewed unexecuted renewal helpers',
    'historical_source0ad_pairs_accepted': True, 'current_source_pairs_accepted': False,
    'full_ci_successful': False, 'unrelated_dirty_preserved': True, 'git_mutation': False,
}
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'inventory.v1.json').open('xb') as stream:
    assert stream.write(raw) == len(raw)
print(json.dumps({'files': len(rows), 'bytes': value['total_bytes'], 'inventory_size_bytes': len(raw), 'inventory_sha256': hashlib.sha256(raw).hexdigest()}))
