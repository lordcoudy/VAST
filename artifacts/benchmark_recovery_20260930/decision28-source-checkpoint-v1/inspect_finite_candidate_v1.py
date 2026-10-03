"""Read-only prospective Git byte guard for a finite owned checkpoint."""
from pathlib import Path
import hashlib, json, os, stat, subprocess

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
NAMES = ['decision28-native-failure-raw-repair-v1', 'decision28-sidecar-failure-observability-v1',
    'decision28-source-checkpoint-v1', 'component-cpu07-failed-boundary-independent-review-v1',
    'component-cpu07-worker-events-observation-preparation-v1',
    'component-cpu07-worker-events-independent-source-review-v1',
    'component-cpu07-worker-events-actual-independent-review-v1',
    'ci-9d47-original-host-retention-v1', 'ci-9d47-original-host-independent-review-v1',
    'ci-9d47-original-host-independent-source-review-v1',
    'ci-9d47-original-host-actual-independent-review-v1', 'native-disconnect-source-review-v1']
FILES = ['.gitattributes', 'BENCHMARK_RECOVERY_PLAN.md',
    'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
    'scripts/checkpoint_gstreamer_analytics_sidecar.py', 'scripts/publication_operational_process_custody_v1.py',
    'tests/test_checkpoint_gstreamer_analytics_sidecar.py',
    'tests/test_publication_operational_process_custody_v1.py',
    'tests/test_publication_worker_termination_facts_v1.py']
git = ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.longpaths=true']
paths = [ROOT / n for n in FILES]
for name in NAMES:
    directory = BASE / name
    assert directory.resolve(strict=True) == directory
    for p in directory.rglob('*'):
        s = p.lstat()
        assert not stat.S_ISLNK(s.st_mode)
        if stat.S_ISREG(s.st_mode):
            paths.append(p)
        else:
            assert stat.S_ISDIR(s.st_mode), str(p)
assert len(paths) == len(set(paths))
rows, errors, total = [], [], 0
def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
for p in sorted(paths):
    assert p.resolve(strict=True) == p and p.is_relative_to(ROOT)
    s = p.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 8 * 1024 * 1024
    b = p.read_bytes(); assert epoch(p.lstat()) == epoch(s)
    total += len(b); assert total <= 64 * 1024 * 1024
    name = p.relative_to(ROOT).as_posix()
    oid = hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()
    ids = {}
    for setting in ('false', 'true'):
        result = subprocess.run(git + ['-c', 'core.autocrlf='+setting, 'hash-object', '--path='+name, '--stdin'],
            cwd=ROOT, input=b, capture_output=True, timeout=15)
        assert result.returncode == 0, (name, result.returncode, result.stderr[:2048])
        ids[setting] = result.stdout.decode().strip()
    row = {'path':name, 'size_bytes':len(b), 'sha256':hashlib.sha256(b).hexdigest(), 'epoch':epoch(s),
        'raw_git_blob_id':oid, 'clean_ids':ids}
    rows.append(row)
    if set(ids.values()) != {oid}:
        errors.append(row)
receipt = {'artifact_kind':'decision28_finite_candidate_raw_clean_review_v1', 'schema_version':1,
    'owned_files':rows, 'total_bytes':total, 'mismatches':errors, 'git_mutation':False,
    'prospective_raw_clean_equality_autocrlf_false_true':not errors}
raw = (json.dumps(receipt, sort_keys=True, indent=2)+'\n').encode()
with (HERE / 'finite-candidate-guard.v1.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
print(json.dumps({'file_count':len(rows), 'bytes':total, 'mismatch_count':len(errors),
    'mismatch_paths':[r['path'] for r in errors], 'receipt_size_bytes':len(raw),
    'receipt_sha256':hashlib.sha256(raw).hexdigest()}))
