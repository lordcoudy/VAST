"""Independent read-only physical join of the one original cache copy."""
import hashlib
import json
import os
import stat
import time
from pathlib import Path

HERE = Path(__file__).parent
PREP = HERE.parent / 'decision29-ext4-asset-cache-diagnosis-v1'
D = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
OUT = D.with_name(D.name + '-model-cache-copy-output')
START = time.monotonic()
FDS = []
LEAVES = []
DIRECTORIES = {}

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def identity(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid]

def pin(path, maximum, *, retain=False):
    for parent in reversed(path.parents):
        if parent not in DIRECTORIES:
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            FDS.append(fd)
            observed = identity(os.fstat(fd))
            assert observed == identity(parent.lstat())
            DIRECTORIES[parent] = (fd, observed)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    FDS.append(fd)
    before = epoch(os.fstat(fd))
    LEAVES.append((fd, path, before))
    assert stat.S_ISREG(before[2]) and before[3] == 1 and 0 < before[4] <= maximum
    assert before == epoch(path.lstat())
    hashes = {name: hashlib.new(name) for name in ('sha256', 'sha384')}
    blocks, count = [], 0
    while True:
        assert time.monotonic() - START < 30
        block = os.read(fd, min(65536, maximum - count + 1))
        if not block:
            break
        count += len(block)
        assert count <= maximum
        for value in hashes.values():
            value.update(block)
        if retain:
            blocks.append(block)
    assert count == before[4] and before == epoch(os.fstat(fd)) == epoch(path.lstat())
    return {'path': str(path), 'size_bytes': count, 'epoch': before,
        'uid': os.fstat(fd).st_uid, 'gid': os.fstat(fd).st_gid,
        **{name: value.hexdigest() for name, value in hashes.items()}}, b''.join(blocks)

def scan(pids, group):
    rows, errors = [], []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(entry.name) in pids or int(fields[2]) == group:
                status = dict(line.split(':', 1) for line in (entry / 'status').read_text().splitlines() if ':' in line)
                rows.append({'pid': int(entry.name), 'pgid': int(fields[2]), 'startticks': int(fields[19]),
                    'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'state': fields[0]})
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError) as caught:
            errors.append({'pid': int(entry.name), 'type': type(caught).__name__, 'errno': getattr(caught, 'errno', None)})
    return {'at_ns': time.time_ns(), 'members': rows, 'errors': errors,
        'original_pid_paths_absent': {str(pid): not Path('/proc', str(pid)).exists() for pid in sorted(pids)}}

fd_before = len(os.listdir('/proc/self/fd'))
first = None
facts = {}
try:
    inputs = []
    for path, size, sha in (
        (PREP / 'inventory.v1.json', 33294, 'c99b1402c4c909cb0a47421b0a0d2f872cc932e26ee99de76c9539f192684f3b'),
        (PREP / 'copy_existing_ci_model_assets_v1.py', 16532, 'fd8ce70c6e84bc29481c75aaa1071f0b3b89cd0084ab1e7830a621a8b6f384ae'),
        (OUT / 'dispatch.v1.json', 1077, '09e0431dbd0cfe39367f043de997df0bb7025f553a077ef38f575a481433453d'),
        (OUT / 'execution.v1.json', 13866, 'edd18fe1ea79b25355c17d21e18dbe910035f00f400df03fdb591d3eb969780e')):
        descriptor, raw = pin(path, 65536, retain=True)
        assert descriptor['size_bytes'] == size and descriptor['sha256'] == sha
        inputs.append((descriptor, raw))
    table = json.loads(inputs[0][1])
    dispatch = json.loads(inputs[2][1])
    execution = json.loads(inputs[3][1])
    assert dispatch['pid'] == 95706 and dispatch['pgid'] == 95705 and dispatch['uid'] == dispatch['gid'] == 1000
    assert dispatch['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert dispatch['table_sha256'] == inputs[0][0]['sha256']
    assert execution['status'] == 'setup_complete' and execution['error'] is None and execution['close_errors'] == []
    assert execution['fd_before'] == execution['fd_after'] == 6 and execution['all_handles_released'] is True
    assert execution['original_ci_accepted'] is False
    assert execution['facts']['source_commit'] == '3c025b29b3c1d5275c2ec693410e4b83700583de'
    assert execution['facts']['target_root'] == str(D) and execution['elapsed_s'] < 120
    assert not os.path.lexists(OUT / 'late-failure.v1.json')
    assert len(execution['assets']) == table['asset_count'] == 8
    assets = []
    for expected, actual in zip(table['assets'], execution['assets'], strict=True):
        assert actual['index'] == expected['index'] and actual['source'] == expected['source']
        assert actual['destination'] == str(D / expected['destination_relative'])
        assert actual['status'] == 'copied_exact_bytes' and actual['written_bytes'] == expected['expected_size_bytes']
        physical = []
        for kind, path, expected_epoch in (
            ('donor', Path(actual['source']['path']), expected['source']['epoch']),
            ('destination', Path(actual['destination']), actual['destination_epoch'])):
            descriptor, _ = pin(path, expected['expected_size_bytes'])
            assert descriptor['epoch'] == expected_epoch
            assert descriptor['uid'] == descriptor['gid'] == 1000
            assert all(descriptor[key] == actual[key] for key in ('size_bytes', 'sha256', 'sha384'))
            if kind == 'destination':
                assert stat.S_IMODE(descriptor['epoch'][2]) == 0o444
                assert descriptor['epoch'][:2] != expected['source']['epoch'][:2]
            physical.append({'role': kind, 'descriptor': descriptor})
        assets.append({'index': expected['index'], 'physical_full_hash_witnesses': physical})
    sources = []
    for expected in execution['facts']['source_pins']:
        descriptor, _ = pin(Path(expected['path']), 65536)
        assert all(descriptor[key] == expected[key] for key in ('size_bytes', 'sha256', 'sha384', 'epoch'))
        sources.append(descriptor)
    head, raw = pin(D / '.git/HEAD', 64, retain=True)
    assert raw == b'3c025b29b3c1d5275c2ec693410e4b83700583de\n'
    scans = [scan({95705, 95706}, 95705)]
    time.sleep(0.05)
    scans.append(scan({95705, 95706}, 95705))
    assert all(not row['members'] and not row['errors'] and all(row['original_pid_paths_absent'].values()) for row in scans)
    for path, (fd, expected) in DIRECTORIES.items():
        assert identity(os.fstat(fd)) == expected == identity(path.lstat())
    for fd, path, expected in LEAVES:
        assert epoch(os.fstat(fd)) == expected == epoch(path.lstat())
    assert sum(row['size_bytes'] for row in execution['assets']) == 15514597
    facts = {'inputs': [row[0] for row in inputs], 'assets': assets, 'source_pins': sources,
        'detached_HEAD': head, 'asset_count': 8, 'asset_bytes': 15514597,
        'current_full_asset_read_bytes': 2 * 15514597, 'two_original_process_scans': scans,
        'original_tool_observation': {'tool': '10b1e9', 'exit_code': 0, 'elapsed_s': 0.16081799,
            'provenance': 'ROOT original closed tool observation; not a newly reconstructed raw capture'},
        'late_failure_absent': True, 'source_and_destination_full_SHA256_SHA384_size_epochs_match': True,
        'stock_reuse_evidence': None, 'stock_full_CI_outcome': None, 'ci_acceptance': False,
        'hardware_acceptance': False, 'copy_rerun': False, 'network_or_test_or_engine_executed': False}
except BaseException as caught:
    first = {'type': type(caught).__name__, 'message': str(caught)[:2048]}
finally:
    close_errors = []
    for fd in reversed(FDS):
        try:
            os.close(fd)
        except OSError as caught:
            close_errors.append({'fd': fd, 'errno': caught.errno})
    fd_after = len(os.listdir('/proc/self/fd'))
result = {'schema_version': 1, 'kind': 'decision29_actual_exact_eight_cache_copy_physical_review_v1',
    'status': 'copy_setup_physically_verified' if first is None and not close_errors and fd_after == fd_before else 'failed',
    'error': first, 'facts': facts, 'reader_pid': os.getpid(),
    'original_reader_proc_stat': Path('/proc/self/stat').read_text(),
    'fd_before': fd_before, 'fd_after': fd_after, 'close_errors': close_errors,
    'all_reader_handles_released': not close_errors and fd_after == fd_before,
    'elapsed_s': time.monotonic() - START, 'CI_success_claimed': False}
raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
assert len(raw) <= 32768
with (HERE / 'review.v1.json').open('xb') as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({'status': result['status'], 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
    'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': result['elapsed_s']}))
raise SystemExit(0 if result['status'] == 'copy_setup_physically_verified' else 78)
