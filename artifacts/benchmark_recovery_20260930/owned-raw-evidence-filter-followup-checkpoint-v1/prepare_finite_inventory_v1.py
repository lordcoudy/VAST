"""Prepare a finite owned checkpoint with a raw/filtered-byte guard; no Git mutation."""
from pathlib import Path
import hashlib
import json
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
HERE = Path(__file__).parent
PREVIOUS = '78b869e4f8bc101413ed00776bd89d1089a8318d'
assert len(sys.argv) == 3
peer_sha, peer_size = sys.argv[1], int(sys.argv[2])
assert len(peer_sha) == 64 and all(c in '0123456789abcdef' for c in peer_sha)
attrs = (ROOT / '.gitattributes').read_bytes()
assert len(attrs) == 16575 and hashlib.sha256(attrs).hexdigest() == 'f2a113e232566f8110dc5c282bbec1adf10499c2dc61d499e2bbf9a7fdb4b01e'
author = (BASE / 'forensic-raw-stream-attributes-repair-v1/author-review.v1.json').read_bytes()
assert len(author) == 92459 and hashlib.sha256(author).hexdigest() == '5c38bb1365192b60c86957c180e7272670d06fb56817099c100d73c9c3f10242'
peer_path = BASE / 'forensic-raw-family-attributes-independent-review-v1/review.v1.json'
peer_raw = peer_path.read_bytes()
assert len(peer_raw) == peer_size and hashlib.sha256(peer_raw).hexdigest() == peer_sha
recovery_peer = (BASE / 'component-supervisor-renewal-recovery-independent-review-v1/review.v1.json').read_bytes()
assert len(recovery_peer) == 6585 and hashlib.sha256(recovery_peer).hexdigest() == 'ed903039938688a177fba7f12c4badacb3381187a05c2ccfcffcc31bba4efe15'
recovery_source = (BASE / 'component-supervisor-renewal-recovery-preparation-v1/recover_existing_ext4_checkout_v2.py').read_bytes()
assert len(recovery_source) == 18538 and hashlib.sha256(recovery_source).hexdigest() == '897f2fb5082d1a3521bc99f8aeed6db94c5bb9c8061c2343fa1b92dfdae86b23'
git = ['git', '-c', 'core.longpaths=true', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false']
assert subprocess.check_output([*git, 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip() == PREVIOUS
assert not subprocess.check_output([*git, 'diff', '--cached', '--name-only'], cwd=ROOT)
paths = {
    '.gitattributes', 'BENCHMARK_RECOVERY_PLAN.md',
    'artifacts/benchmark_recovery_20260930/owned-raw-evidence-attributes-checkpoint-v1/commit-proof.v1.json',
    Path(__file__).relative_to(ROOT).as_posix(),
    (HERE / 'verify_commit_bytes_v1.py').relative_to(ROOT).as_posix(),
}
names = (
    'forensic-raw-stream-attributes-repair-v1',
    'forensic-raw-family-attributes-independent-review-v1',
    'forensic-raw-json-attributes-followup-v1',
    'forensic-raw-json-attributes-followup-independent-review-v1',
    'component-supervisor-renewal-preparation-v1',
    'component-supervisor-renewal-recovery-preparation-v1',
    'component-supervisor-renewal-recovery-independent-review-v1',
    'component-supervisor-renewal-actual-failure-independent-review-v1',
    'component-current-source-ci-supervisor-attributes-preparation-v1',
    'component-current-source-ci-supervisor-attributes-independent-review-v1',
    'component-current-source-ci-supervisor-attributes-actual-setup-review-v1',
    'ci-e897-original-host-retention-v1',
    'ci-e897-original-host-independent-review-v1',
    'ci-78b-original-host-retention-v1',
    'ci-78b-original-host-independent-review-v1',
    'component-current95-ci-successor-preparation-v1',
)
for name in names:
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
    oid = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    for autocrlf in ('false', 'true'):
        filtered = subprocess.check_output([*git, '-c', 'core.autocrlf=' + autocrlf, 'hash-object', '--stdin', '--path=' + relative], cwd=ROOT, input=raw).decode().strip()
        assert filtered == oid, 'owned raw/filtered Git object mismatch: ' + relative
    rows.append({'path': relative, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert sum(r['size_bytes'] for r in rows) <= 64 * 1024 * 1024
value = {
    'previous_head': PREVIOUS, 'files': rows, 'file_count': len(rows),
    'total_bytes': sum(r['size_bytes'] for r in rows),
    'source_paths': ['.gitattributes'], 'source_sha256': hashlib.sha256(attrs).hexdigest(),
    'author_sha256': hashlib.sha256(author).hexdigest(),
    'peer_size_bytes': peer_size, 'peer_sha256': peer_sha,
    'scope': 'finite2 JSON and scoped raw-stream evidence attributes and existing-index proof, preserved failed renewal/full-byte reconciliation, prepared recovery and original hosted/setup retention',
    'host87_selected73_native_worker_changed': False,
    'raw_evidence_payloads_rewritten': False,
    'all_owned_raw_filter_ids_equal_autocrlf_false_true': True,
    'checkpoint_full_ci_successful': False, 'current_source_runtime_accepted': False,
    'unrelated_dirty_preserved': True, 'git_mutation': False,
}
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'inventory.v1.json').open('xb') as stream:
    assert stream.write(raw) == len(raw)
print(json.dumps({'files': len(rows), 'bytes': value['total_bytes'], 'inventory_size_bytes': len(raw), 'inventory_sha256': hashlib.sha256(raw).hexdigest(), 'peer_sha256': peer_sha}))
