"""Finite .gitattributes repair and closed preparation evidence; no Git mutation."""
from pathlib import Path
import hashlib
import json
import stat
import subprocess
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
HERE = Path(__file__).parent
PREVIOUS = 'e897514dbefe3015756995d05f924aa44dd39552'
raw = (ROOT / '.gitattributes').read_bytes()
assert len(raw) == 16082 and hashlib.sha256(raw).hexdigest() == '27b8b1feaaaa51f2b01de423cfa4824d4f351613650f5b2fe137295610237c3f'
author_raw = (BASE / 'forensic-raw-json-attributes-repair-v1/author-review.v1.json').read_bytes()
assert len(author_raw) == 224525 and hashlib.sha256(author_raw).hexdigest() == '18d4314cc317880cc9ee373875e3c36a074aa2fe8ebebc3f7dc550ef3ae89de4'
peer_path = BASE / 'forensic-raw-json-attributes-independent-review-v1/review.v1.json'
assert peer_path.is_file(), 'closed independent source/effect gate required'
peer_raw = peer_path.read_bytes()
assert len(peer_raw) == 6506 and hashlib.sha256(peer_raw).hexdigest() == 'b2971a507c6bebacaefcf1f09cf49b558d002f59109bdbf738966734254b15cc'
peer = json.loads(peer_raw)
paths = {
    '.gitattributes', 'BENCHMARK_RECOVERY_PLAN.md',
    'artifacts/benchmark_recovery_20260930/owned-supervisor-capacity-checkpoint-v1/commit-proof.v1.json',
    'artifacts/benchmark_recovery_20260930/component-supervisor-renewal-preparation-v1/pair-audit-adaptation.pending.v1.json',
    Path(__file__).relative_to(ROOT).as_posix(),
    'artifacts/benchmark_recovery_20260930/owned-raw-evidence-attributes-checkpoint-v1/verify_commit_bytes_v1.py',
}
for name in (
    'forensic-raw-json-attributes-repair-v1', 'forensic-raw-json-attributes-independent-review-v1',
    'component-current-source-ci-supervisor-preparation-v1',
    'component-current-source-ci-supervisor-independent-review-v1',
    'current-conformance-preparation-v1',
):
    directory = BASE / name
    assert directory.is_dir(), name
    for path in directory.rglob('*'):
        assert not path.is_symlink() and '.git' not in path.parts
        if path.is_file():
            assert '__pycache__' not in path.parts
            assert path.suffix.lower() not in {'.pyc', '.onnx', '.engine', '.plan', '.bin', '.whl', '.rgb'}
            paths.add(path.relative_to(ROOT).as_posix())
rows = []
for relative in sorted(paths):
    path = ROOT / relative
    s = path.lstat()
    assert path.resolve(strict=True).is_relative_to(ROOT) and stat.S_ISREG(s.st_mode) and s.st_nlink == 1
    raw = path.read_bytes()
    assert len(raw) <= 8 * 1024 * 1024
    rows.append({'path': relative, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert sum(r['size_bytes'] for r in rows) <= 64 * 1024 * 1024
git = ['git', '-c', 'core.longpaths=true']
assert subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == PREVIOUS
assert not subprocess.check_output([*git, 'diff', '--cached', '--name-only'], cwd=ROOT)
value = {
    'previous_head': PREVIOUS, 'files': rows, 'file_count': len(rows), 'total_bytes': sum(r['size_bytes'] for r in rows),
    'source_paths': ['.gitattributes'], 'source_sha256': '27b8b1feaaaa51f2b01de423cfa4824d4f351613650f5b2fe137295610237c3f',
    'author_sha256': hashlib.sha256(author_raw).hexdigest(),
    'peer_size_bytes': len(peer_raw), 'peer_sha256': hashlib.sha256(peer_raw).hexdigest(),
    'scope': 'finite15 raw evidence attributes, genuine Git effect/source peer, retained failed setup and prepared CI/conformance',
    'host87_selected73_native_worker_changed': False, 'raw_evidence_payloads_rewritten': False,
    'full_ci_successful': False, 'current_source_runtime_accepted': False,
    'unrelated_dirty_preserved': True, 'git_mutation': False,
}
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'inventory.v1.json').open('xb') as stream:
    assert stream.write(raw) == len(raw)
print(json.dumps({'files': len(rows), 'bytes': value['total_bytes'], 'inventory_size_bytes': len(raw), 'inventory_sha256': hashlib.sha256(raw).hexdigest(), 'peer_sha256': value['peer_sha256']}))
