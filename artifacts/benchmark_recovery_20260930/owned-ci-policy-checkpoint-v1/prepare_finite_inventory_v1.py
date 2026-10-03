"""Inventory only closed, explicitly owned CI source and original evidence; no Git writes."""
from pathlib import Path
import hashlib
import json
import stat
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
base = root / 'artifacts/benchmark_recovery_20260930'
author_path = base / 'decision24-ci-userns-profile-v1/author-review.v3.json'
author_raw = author_path.read_bytes()
assert len(author_raw) == 55354
assert hashlib.sha256(author_raw).hexdigest() == '5846118e7f59a3326d61e8c3088abdcd963142319a105c20cd237c7268d50651'
author = json.loads(author_raw)
assert author['behavioral_green06']['successes'] == author['behavioral_green06']['tests_run'] == 74
assert author['behavioral_green06']['skips'] == 0
assert author['source_membership']['all_7_paths_absent_host87_selected73_all_9_runtime_source_contexts_copy2693']
assert len(sys.argv) == 4, 'usage: inventory PEER_RELATIVE_PATH PEER_SHA256 PEER_SIZE'
peer = root / sys.argv[1]
peer_raw = peer.read_bytes()
assert peer.resolve(strict=True).is_relative_to(base)
assert len(peer_raw) == int(sys.argv[3]) and hashlib.sha256(peer_raw).hexdigest() == sys.argv[2]
paths = {row['path'] for row in author['owned_paths']}
assert len(paths) == 7
for row in author['owned_paths']:
    raw = (root / row['path']).read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
directories = (
    'decision24-ci-userns-profile-v1',
    'ci-0ad78d-original-host-retention-v1',
    'ci-0ad78d-readonly-failure-diagnosis-v1',
    'component-cpu06-ext4-dispatch-grant-v1',
    'component-cpu06-ext4-postterminal-audit-preparation-v1',
    'component-cpu06-ext4-postterminal-audit-independent-review-v1',
    'component-cpu06-ext4-actual-audit-closure-v1',
    'component-ext4-setup-original-v1',
    'component-ext4-setup-original-v1-outer',
    'component-ext4-setup-physical-review-v1',
    'component-ext4-setup-physical-review-v2',
    'component-ext4-bind-actual-independent-review-v1',
    'component-ext4-host-closure-original-v1-outer',
    'component-ext4-host-closure-physical-review-v1',
    'component-ext4-original-retention-v1',
)
for name in directories:
    directory = base / name
    assert directory.is_dir(), name
    for path in directory.rglob('*'):
        assert not path.is_symlink(), str(path)
        if path.is_file():
            assert '__pycache__' not in path.parts
            assert path.suffix.lower() not in {'.pyc', '.onnx', '.engine', '.plan', '.bin', '.whl', '.rgb'}, str(path)
            paths.add(path.relative_to(root).as_posix())
for path in peer.parent.rglob('*'):
    assert not path.is_symlink()
    if path.is_file():
        assert '__pycache__' not in path.parts and path.suffix != '.pyc'
        paths.add(path.relative_to(root).as_posix())
paths.update((
    'BENCHMARK_RECOVERY_PLAN.md',
    'docs/gstreamer-component-benchmark-runbook.md',
    'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
    Path(__file__).relative_to(root).as_posix(),
))
rows = []
for relative in sorted(paths):
    path = root / relative
    info = path.lstat()
    assert path.resolve(strict=True).is_relative_to(root)
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()
    raw = path.read_bytes()
    assert len(raw) <= 8 * 1024 * 1024, relative
    rows.append({'path': relative, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert sum(row['size_bytes'] for row in rows) <= 64 * 1024 * 1024
git = ['git', '-c', 'core.longpaths=true']
head = subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
assert head == '0ad78d6abdb3c526544a17185af7fe8094716735'
assert not subprocess.check_output([*git, 'diff', '--cached', '--name-only'], cwd=root)
value = {
    'previous_head': head, 'files': rows, 'file_count': len(rows),
    'total_bytes': sum(row['size_bytes'] for row in rows),
    'author_review_sha256': hashlib.sha256(author_raw).hexdigest(),
    'independent_review': {'path': sys.argv[1], 'size_bytes': len(peer_raw), 'sha256': sys.argv[2]},
    'focused_test_successes': 74, 'full_ci_successful': False,
    'cpu06_accepted': True, 'gpu_accepted': False,
    'scope': 'seven reviewed CI paths, closed original CI/CPU/preparation evidence and truthful plan/task/runbook; benchmark source87 and selected73 unchanged',
    'unrelated_dirty_preserved': True, 'git_mutation': False,
}
target = Path(__file__).parent / 'inventory.v1.json'
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with target.open('xb') as stream:
    stream.write(raw)
print(json.dumps({'files': len(rows), 'bytes': value['total_bytes'], 'inventory_sha256': hashlib.sha256(raw).hexdigest()}))
