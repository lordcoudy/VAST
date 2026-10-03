"""Root-owned finite planning staging with a prospective raw/clean guard."""
from pathlib import Path
import hashlib, json, os, stat, subprocess, sys

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HEAD = '9d47e99b623df44816f7b0a0b73b249a940f7723'
HERE = Path(__file__).resolve().parent
peer_path = ROOT / sys.argv[1]
peer_raw = peer_path.read_bytes()
assert hashlib.sha256(peer_raw).hexdigest() == sys.argv[2]
peer = json.loads(peer_raw)
assert peer['reviewable'] and not peer['blocking_findings'] and peer['reviewer_handles_released']
assert peer['baseline_commit'] == HEAD and len(peer['owned_document_pins']) == 5
git = ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.longpaths=true']
def run(args, raw=None):
    p = subprocess.run(git + args, cwd=ROOT, input=raw, capture_output=True, timeout=15)
    assert p.returncode == 0, (args, p.returncode, p.stderr[:2048])
    assert len(p.stdout) <= 16 * 1024 * 1024 and len(p.stderr) <= 65536
    return p.stdout
assert run(['rev-parse', 'HEAD']).decode().strip() == HEAD
assert run(['diff', '--cached', '--name-only', '-z']) == b''
assert not (HERE / 'checkpoint-freeze.v1.json').exists()
physical, epochs = {}, {}
def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
for pin in peer['owned_document_pins'] + [
        {'path':str(peer_path), 'size_bytes':len(peer_raw), 'sha256':sys.argv[2]},
        {'path':str(Path(__file__).resolve())}]:
    p = Path(pin['path'])
    assert p.resolve(strict=True) == p and p.is_relative_to(ROOT)
    s = p.lstat(); assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 8 * 1024 * 1024
    b = p.read_bytes(); assert epoch(p.lstat()) == epoch(s)
    if 'sha256' in pin:
        assert len(b) == pin['size_bytes'] and hashlib.sha256(b).hexdigest() == pin['sha256'], str(p)
    name = p.relative_to(ROOT).as_posix(); assert name not in physical
    physical[name], epochs[name] = b, epoch(s)
for name, b in physical.items():
    raw_id = hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()
    for setting in ('false', 'true'):
        assert run(['-c', 'core.autocrlf=' + setting, 'hash-object', '--path=' + name, '--stdin'], b).decode().strip() == raw_id, name
for name, b in physical.items():
    assert (ROOT/name).read_bytes() == b and epoch((ROOT/name).lstat()) == epochs[name]
    oid = run(['hash-object', '-w', '--stdin'], b).decode().strip()
    run(['update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + name])
freeze = {'previous_head':HEAD, 'review':{'path':sys.argv[1], 'sha256':sys.argv[2]},
    'owned_files':{n:{'size_bytes':len(b), 'sha256':hashlib.sha256(b).hexdigest(), 'epoch':epochs[n]} for n,b in physical.items()},
    'prospective_raw_clean_equality_autocrlf_false_true':True, 'planning_only':True,
    'CPU07_accepted':False, 'hardware_or_local_CI_acceptance':False, 'unrelated_dirt_preserved':True}
raw = (json.dumps(freeze, sort_keys=True, indent=2) + '\n').encode()
path = HERE/'checkpoint-freeze.v1.json'
with path.open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
name = path.relative_to(ROOT).as_posix()
raw_id = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
for setting in ('false', 'true'):
    assert run(['-c', 'core.autocrlf=' + setting, 'hash-object', '--path=' + name, '--stdin'], raw).decode().strip() == raw_id
oid = run(['hash-object', '-w', '--stdin'], raw).decode().strip()
run(['update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + name]); physical[name] = raw
assert set(run(['diff', '--cached', '--name-only', '-z']).decode().split('\0')) - {''} == set(physical)
for name,b in physical.items():
    assert run(['show', ':' + name]) == b == (ROOT/name).read_bytes(), name
run(['diff', '--cached', '--check'])
print(json.dumps({'owned_file_count':len(physical), 'physical_index_equal':True,
    'freeze':{'path':str(path), 'size_bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}}))
