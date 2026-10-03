"""Stage only the finite reviewed repair checkpoint, preserving every raw byte."""
from pathlib import Path
import hashlib, json, os, stat, subprocess

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
HEAD = '958a036bc5a55821c712204577fdf4c51c2181c7'
git = ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.longpaths=true']
def run(args, payload=None):
    p = subprocess.run(git+args, cwd=ROOT, input=payload, capture_output=True, timeout=15)
    assert p.returncode == 0, (args, p.returncode, p.stderr[:2048])
    assert len(p.stdout) <= 16*1024*1024 and len(p.stderr) <= 65536
    return p.stdout
def epoch(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def read_review(name, sha, size):
    p = BASE/name; b = p.read_bytes()
    assert len(b) == size and hashlib.sha256(b).hexdigest() == sha
    value = json.loads(b)
    assert value['baseline_commit'] == HEAD and value['reviewable'] is True
    assert value['blocking_findings'] == [] and value['reviewer_handles_released'] is True
    return value
peer = read_review('decision28-source-independent-review-v2/review.v2.json',
    '7de1386fc628424e90af3cbc21aea5ecdf6e433e9f9e594a86f9f83bf1c4e662',26462)
correction = read_review('decision28-source-independent-review-v2/count-correction.v1.json',
    'fb038ad8bba5b92346f377c635c4f6a7a61522a98746df7a2e57ca643ad37343',12623)
image_peer = read_review('decision28-selected-renewal-independent-review-v2/review.v2.json',
    'b6636565266e68f8e1aa414385c75b2f80d5840d052a454306f2157af7f2a3c1',12200)
assert correction['parent_independent_review']['sha256'] == '7de1386fc628424e90af3cbc21aea5ecdf6e433e9f9e594a86f9f83bf1c4e662'
assert correction['focused_original_sidecar_plus_termination_methods'] == 53 and correction['original_native_methods'] == 21
for pin in peer['owned_source_pins'] + correction['owned_source_pins'] + image_peer['owned_source_pins']:
    b = (ROOT/pin['path']).read_bytes()
    assert len(b) == pin['size_bytes'] and hashlib.sha256(b).hexdigest() == pin['sha256'], pin['path']
assert run(['rev-parse','HEAD']).decode().strip() == HEAD
assert run(['diff','--cached','--name-only','-z']) == b''
assert not (HERE/'checkpoint-freeze.v1.json').exists()
names = ['decision28-native-failure-raw-repair-v1','decision28-sidecar-failure-observability-v1',
    'decision28-source-checkpoint-v1','decision28-source-independent-review-v2',
    'decision28-selected-renewal-preparation-v1','decision28-selected-renewal-preparation-v2',
    'decision28-selected-renewal-independent-review-v1','decision28-selected-renewal-independent-review-v2',
    'decision28-host-cpu08-renewal-preparation-v1',
    'component-cpu07-failed-boundary-independent-review-v1',
    'component-cpu07-worker-events-observation-preparation-v1',
    'component-cpu07-worker-events-independent-source-review-v1',
    'component-cpu07-worker-events-actual-independent-review-v1',
    'ci-9d47-original-host-retention-v1','ci-9d47-original-host-independent-review-v1',
    'ci-9d47-original-host-independent-source-review-v1','ci-9d47-original-host-actual-independent-review-v1',
    'native-disconnect-source-review-v1']
paths = [ROOT/pin['path'] for pin in peer['owned_source_pins']]
paths += [ROOT/'BENCHMARK_RECOVERY_PLAN.md',ROOT/'openspec/changes/fix-benchmark-preparations-spec/tasks.md']
for name in names:
    directory = BASE/name
    assert directory.resolve(strict=True) == directory
    for p in directory.rglob('*'):
        s = p.lstat()
        assert not stat.S_ISLNK(s.st_mode)
        if stat.S_ISREG(s.st_mode): paths.append(p)
        else: assert stat.S_ISDIR(s.st_mode), str(p)
assert len(set(paths)) == len(paths)
physical, epochs, total = {}, {}, 0
for p in sorted(paths):
    assert p.resolve(strict=True) == p and p.is_relative_to(ROOT)
    s = p.lstat(); assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 8*1024*1024
    b = p.read_bytes(); assert epoch(p.lstat()) == epoch(s)
    total += len(b); assert total <= 64*1024*1024
    name = p.relative_to(ROOT).as_posix()
    physical[name], epochs[name] = b,epoch(s)
tasks = physical['openspec/changes/fix-benchmark-preparations-spec/tasks.md']
assert tasks.count(b'- [x] ') == 59 and tasks.count(b'- [ ] ') == 11
assert hashlib.sha256(tasks).hexdigest() == 'a0c53df0fecda7a8d4b07d4a00fcd7914ad7dbfacc12bd697ae77d1917730d30'
assert hashlib.sha256(physical['BENCHMARK_RECOVERY_PLAN.md']).hexdigest() == 'b82ffb61402b344fce3be24da4e85e34523389e0210cfb0670b48551c98ee69f'
# All prospective clean filters are checked BEFORE any Git object/index mutation.
for name,b in physical.items():
    oid = hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    for setting in ('false','true'):
        assert run(['-c','core.autocrlf='+setting,'hash-object','--path='+name,'--stdin'],b).decode().strip() == oid, name
freeze = {'artifact_kind':'decision28_exact_source_checkpoint_freeze_v1','schema_version':1,
    'previous_head':HEAD, 'planning_commit':HEAD,
    'source_peer_sha256':'7de1386fc628424e90af3cbc21aea5ecdf6e433e9f9e594a86f9f83bf1c4e662',
    'count_addendum_sha256':'fb038ad8bba5b92346f377c635c4f6a7a61522a98746df7a2e57ca643ad37343',
    'image_helper_source_peer_sha256':'b6636565266e68f8e1aa414385c75b2f80d5840d052a454306f2157af7f2a3c1',
    'owned_files':{n:{'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'epoch7':epochs[n]} for n,b in physical.items()},
    'owned_total_bytes':total, 'prospective_raw_clean_equality_autocrlf_false_true':True,
    'only_production_changes':[p['path'] for p in peer['owned_source_pins'] if p['path'].startswith('scripts/')],
    'completed_tasks':59,'total_tasks':70,'CPU07_accepted':False,'current_hardware_or_local_fullCI_accepted':False,
    'helper_and_future_controller_preparations_unexecuted':True,'unrelated_dirt_preserved':True}
freeze_raw = (json.dumps(freeze,sort_keys=True,indent=2)+'\n').encode()
assert len(freeze_raw) <= 8*1024*1024
freeze_path = HERE/'checkpoint-freeze.v1.json'
freeze_name = freeze_path.relative_to(ROOT).as_posix()
freeze_oid = hashlib.sha1(b'blob '+str(len(freeze_raw)).encode()+b'\0'+freeze_raw).hexdigest()
for setting in ('false','true'):
    assert run(['-c','core.autocrlf='+setting,'hash-object','--path='+freeze_name,'--stdin'],freeze_raw).decode().strip() == freeze_oid
for name,b in physical.items():
    assert (ROOT/name).read_bytes() == b and epoch((ROOT/name).lstat()) == epochs[name], name
with freeze_path.open('xb') as f:
    f.write(freeze_raw); f.flush(); os.fsync(f.fileno())
physical[freeze_name] = freeze_raw
for name,b in physical.items():
    oid = run(['hash-object','-w','--stdin'],b).decode().strip()
    run(['update-index','--add','--cacheinfo','100644,'+oid+','+name])
assert set(run(['diff','--cached','--name-only','-z']).decode().split('\0'))-{''} == set(physical)
for name,b in physical.items():
    assert run(['show',':'+name]) == b == (ROOT/name).read_bytes(), name
run(['diff','--cached','--check'])
print(json.dumps({'owned_file_count':len(physical),'physical_index_equal':True,
    'total_bytes':total+len(freeze_raw),'freeze':{'path':str(freeze_path),
    'size_bytes':len(freeze_raw),'sha256':hashlib.sha256(freeze_raw).hexdigest()},'completed_tasks':59,'total_tasks':70}))
