"""Finite metadata closure of the once-only failed historical events query."""
import collections
import hashlib
import json
import os
from pathlib import Path
import stat
import time

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/component-cpu07-worker-events-observation-preparation-v1')
START = time.monotonic()
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
FD_BEFORE = len(os.listdir('/proc/self/fd'))
held = []
witnesses = []

def epoch(value):
    return [value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns]

def read(relative):
    path = BASE / relative
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 100000
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    held.append((path, fd, epoch(before)))
    assert epoch(os.fstat(fd)) == epoch(before)
    raw = os.read(fd, 100001)
    assert len(raw) == before.st_size
    assert epoch(os.fstat(fd)) == epoch(path.lstat()) == epoch(before)
    descriptor = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    witnesses.append({'descriptor': descriptor, 'epoch': epoch(before)})
    return raw

def load(relative):
    return json.loads(read(relative))

def proc(pid):
    path = Path('/proc') / str(pid) / 'stat'
    raw = path.read_bytes()
    split = raw.rfind(b')')
    assert split > 0
    fields = raw[split + 2:].split()
    value = path.stat()
    return {'pid': pid, 'state': fields[0].decode('ascii'), 'ppid': int(fields[1]), 'pgid': int(fields[2]), 'startticks': int(fields[19]), 'uid': value.st_uid, 'gid': value.st_gid, 'boot_id': BOOT}

def scan(owners):
    matches = []
    errors = []
    current = {}
    pids = {owner['pid'] for owner in owners}
    groups = {owner['pgid'] for owner in owners}
    for name in os.listdir('/proc'):
        if not name.isdecimal():
            continue
        pid = int(name)
        try:
            observed = proc(pid)
        except FileNotFoundError:
            continue
        except Exception as error:
            errors.append({'pid': pid, 'type': type(error).__name__, 'message': str(error)})
            continue
        if pid in pids:
            current[pid] = observed
        if observed['pgid'] in groups:
            matches.append(observed)
    return {'at_ns': time.time_ns(), 'boot_id': BOOT, 'owners': [{'original': owner, 'original_pid_path_absent': owner['pid'] not in current, 'observed_at_numeric_pid': current.get(owner['pid'])} for owner in owners], 'group_members': matches, 'scan_errors': errors}

outer = load('original-observation-outer-attempt01/capture.v1.json')
outer_launch = load('original-observation-outer-attempt01/launch.v1.json')
inner = load('original-observation-attempt01/execution.v1.json')
inner_launch = load('original-observation-attempt01/launch.v1.json')
dispatch = load('original-observation-attempt01/dispatch.v1.json')
grant = load('root-one-primary-events-grant.v1.json')
preparation = load('preparation.v3.json')
source = read('observe_original_primary_worker_events_v4.py')
raw = read('original-observation-attempt01/stdout.raw')
stderr = read('original-observation-attempt01/stderr.raw')
outer_stdout = read('original-observation-outer-attempt01/stdout.raw')
outer_stderr = read('original-observation-outer-attempt01/stderr.raw')
assert outer['returncode'] == 78 and outer['failure'] is None and outer['fd_before'] == outer['fd_after'] == 6
assert inner['returncode'] == -9 and inner['overflow'] is True and inner['timed_out'] is False
assert inner['fd_before'] == inner['fd_after'] == 4 and all(inner['eof'].values())
assert outer['source_before'] == outer['source_after']
assert hashlib.sha256(source).hexdigest() == 'dfe892ea547de7fa8c4a1f24b2da0d9299ab2cad6deb8ef7212c6b7117583d5a'
assert len(raw) == 8192 and not stderr and not outer_stderr
assert hashlib.sha256(raw).hexdigest() == inner['channels']['stdout']['sha256']
assert hashlib.sha256(outer_stdout).hexdigest() == outer['channels']['stdout']['sha256']
late_paths = [BASE / 'original-observation-attempt01/late-failure.v1.json', BASE / 'original-observation-outer-attempt01/late-failure.v1.json']
assert not any(path.exists() for path in late_paths)
parts = raw.split(b'\n')
complete = [json.loads(part) for part in parts[:-1]]
assert len(complete) == 24 and len(parts[-1]) == 20
name = 'vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu'
cid = '893b2b02a18906c5d7f840e2515e8f2fb8253c396cf4c2a3756efd1513f166aa'
image = dispatch['names'][name]['image_id']
assert all(item['type'] == 'container' and item['name'] == name and item['id'] == cid and item['image'] == image and dispatch['start_ns'] <= item['time_ns'] <= dispatch['end_ns'] for item in complete)
owners = [outer['controller'], outer['owner'], dispatch['controller'], inner['owner']]
assert all(owner['boot_id'] == BOOT and owner['uid'] == owner['gid'] == 1000 for owner in owners)
assert outer_launch['controller'] == outer['controller'] and outer_launch['timeout_owner'] == outer['owner']
assert inner_launch['owner'] == inner['owner']
scans = [scan(owners)]
time.sleep(0.05)
scans.append(scan(owners))
assert all(not item['group_members'] and not item['scan_errors'] and all(owner['original_pid_path_absent'] for owner in item['owners']) for item in scans)
for path, fd, initial in held:
    assert epoch(os.fstat(fd)) == epoch(path.lstat()) == initial
    os.lseek(fd, 0, os.SEEK_SET)
    reread = os.read(fd, 100001)
    match = next(item for item in witnesses if item['descriptor']['path'] == str(path))
    assert hashlib.sha256(reread).hexdigest() == match['descriptor']['sha256']
close_errors = []
for path, fd, initial in reversed(held):
    try:
        os.close(fd)
    except Exception as error:
        close_errors.append({'path': str(path), 'type': type(error).__name__, 'message': str(error)})
assert not close_errors
fd_after = len(os.listdir('/proc/self/fd'))
assert fd_after == FD_BEFORE
report = {'schema_version': 1, 'scope': 'metadata-only closure of original failed historical query; no repeated Docker command', 'query_accepted': False, 'metadata_closure_passed': True, 'observed_worker_cause': None, 'scanner': proc(os.getpid()), 'fd_before': FD_BEFORE, 'fd_after': fd_after, 'all_held_fds_released': True, 'close_errors': close_errors, 'input_witnesses': witnesses, 'process_scans': scans, 'late_failure_absent': [str(path) for path in late_paths], 'original_outer_returncode': outer['returncode'], 'original_query_returncode': inner['returncode'], 'original_query_failure': inner['failure'], 'original_query_additional_errors': inner['additional_errors'], 'failure_ordering_limitation': 'The inner cleanup drain latched its cap error before the outer handler latched the earlier query cap error; both original errors are retained. No correct first-cause ordering claim.', 'retained_prefix': {'bytes': len(raw), 'complete_rows': len(complete), 'truncated_tail_bytes': len(parts[-1]), 'name': name, 'container_id': cid, 'image_id': image, 'first_event_at_ns': complete[0]['time_ns'], 'last_complete_event_at_ns': complete[-1]['time_ns'], 'actions': dict(collections.Counter(item['action'] for item in complete)), 'events': complete}, 'limitations': ['The prefix stops before the original inference failure; no absence or OOM conclusion is possible.', 'Only later historical daemon events were queried; original contemporaneous worker terminal raw bytes are unavailable.', 'The daemon retains at most 256 events; filtered future absence would not prove original absence.', 'The outer inline capture source was not saved before dispatch; original argv/channel/owner/source facts are retained in its actual capture.'], 'elapsed_s': time.monotonic() - START}
assert report['elapsed_s'] < 30
target = BASE / 'original-observation-closure-review.v1.json'
encoded = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
with target.open('xb') as output:
    output.write(encoded)
    output.flush()
    os.fsync(output.fileno())
assert time.monotonic() - START < 30
print(json.dumps({'path': str(target), 'size_bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest(), 'scanner_pid': os.getpid(), 'metadata_closure_passed': True, 'query_accepted': False}))
