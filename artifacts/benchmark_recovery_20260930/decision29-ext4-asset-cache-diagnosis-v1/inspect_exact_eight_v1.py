"""Read only the fixed eight donor objects and closed original failure metadata."""
import hashlib
import json
import os
import stat
import time
from pathlib import Path

C = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29')
DONOR = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
HERE = Path(__file__).parent
START = time.monotonic()
FDS = []
DIRECTORIES = {}
LEAVES = []

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def identity(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid]

def physical_parents(path):
    for parent in reversed(path.parents):
        if parent not in DIRECTORIES:
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            FDS.append(fd)
            current = identity(os.fstat(fd))
            assert current == identity(parent.lstat())
            DIRECTORIES[parent] = (fd, current)

def read(path, maximum, *, retain=False):
    assert time.monotonic() - START < 30
    physical_parents(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    FDS.append(fd)
    before = epoch(os.fstat(fd))
    LEAVES.append((fd, path, before))
    assert stat.S_ISREG(before[2]) and before[3] == 1 and 0 < before[4] <= maximum
    assert before == epoch(path.lstat())
    hashes = {name: hashlib.new(name) for name in ('sha256', 'sha384')}
    chunks, count = [], 0
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
            chunks.append(block)
    assert count == before[4] and epoch(os.fstat(fd)) == before == epoch(path.lstat())
    return {'path': str(path), 'size_bytes': count, 'sha256': hashes['sha256'].hexdigest(),
            'sha384': hashes['sha384'].hexdigest(), 'epoch': before,
            'uid': os.fstat(fd).st_uid, 'gid': os.fstat(fd).st_gid}, b''.join(chunks)

fd_before = len(os.listdir('/proc/self/fd'))
error = None
result = {}
try:
    sources = []
    raw_by_name = {}
    for name in ('scripts/prepare_ci_model_assets.py', 'scripts/run_ci_checks.py',
                 '.ci/model-assets.v1.json', 'configs/checkpoint_analytics_models_openvino.yaml'):
        pin, raw = read(C / name, 65536, retain=True)
        sources.append(pin)
        raw_by_name[name] = raw
    metadata = json.loads(raw_by_name['.ci/model-assets.v1.json'])
    assert len(metadata['assets']) == 8
    assert metadata['manifest'] == {'path': 'configs/checkpoint_analytics_models_openvino.yaml',
        'size_bytes': len(raw_by_name['configs/checkpoint_analytics_models_openvino.yaml']),
        'sha256': hashlib.sha256(raw_by_name['configs/checkpoint_analytics_models_openvino.yaml']).hexdigest()}
    for name in ('.ci/model-assets.v1.json', 'configs/checkpoint_analytics_models_openvino.yaml'):
        pin, raw = read(DONOR / name, 65536, retain=True)
        assert raw == raw_by_name[name]
        sources.append(pin)
    assets = []
    for index, row in enumerate(metadata['assets']):
        pin, _ = read(DONOR / row['path'], row['size_bytes'])
        assert all(pin[key] == row[key] for key in ('size_bytes', 'sha256', 'sha384'))
        assets.append({'index': index, 'branch': row['branch'], 'role': row['role'],
            'destination_relative': row['path'], 'expected_size_bytes': row['size_bytes'],
            'expected_sha256': row['sha256'], 'expected_sha384': row['sha384'], 'source': pin})
    assert sum(row['expected_size_bytes'] for row in assets) <= 24 * 1024 * 1024
    roots = [DONOR] + [p for p in sorted(C.parent.glob('vast-current-source-ci-*'))
                       if p.is_dir() and not p.name.endswith('output')]
    presence = []
    for root in roots:
        states = []
        for row in metadata['assets']:
            path = root / row['path']
            try:
                s = path.lstat()
                states.append({'path': row['path'], 'exists': True, 'epoch': epoch(s),
                    'regular': stat.S_ISREG(s.st_mode), 'uid': s.st_uid, 'gid': s.st_gid})
            except FileNotFoundError:
                states.append({'path': row['path'], 'exists': False})
        presence.append({'root': str(root), 'assets': states})
    failure = {}
    original = C.with_name(C.name + '-original-output')
    for name in ('report.json', 'model-assets.json', 'model-acquisition/failed.json',
                 'model-acquisition/asset-00.json', 'model-acquisition/asset-00.terminal.json'):
        pin, raw = read(original / name, 65536, retain=True)
        document = json.loads(raw)
        if name == 'report.json':
            document = {key: document[key] for key in ('commit', 'successful', 'failure',
                'elapsed_s', 'raw_checkout_bytes_match_commit', 'changed_tracked_paths')}
        failure[name] = {'descriptor': pin, 'document': document}
    for path, (fd, expected) in DIRECTORIES.items():
        assert identity(os.fstat(fd)) == expected == identity(path.lstat())
    for fd, path, expected in LEAVES:
        assert epoch(os.fstat(fd)) == expected == epoch(path.lstat())
    result = {'schema_version': 1, 'kind': 'decision29_readonly_exact_eight_cache_diagnosis_v1',
        'source_pins': sources, 'donor': str(DONOR), 'canonical_failed_checkout': str(C),
        'successor_root': None, 'successor_commit': None, 'assets': assets,
        'asset_count': len(assets), 'asset_bytes': sum(row['expected_size_bytes'] for row in assets),
        'original_failure': failure, 'presence_only_old_ci_roots': presence,
        'hardware_acceptance': False, 'setup_copy_executed': False, 'ci_executed': False,
        'network_executed': False, 'model_inference_executed': False}
except BaseException as caught:
    error = {'type': type(caught).__name__, 'message': str(caught)[:2048]}
finally:
    close_errors = []
    for fd in reversed(FDS):
        try:
            os.close(fd)
        except OSError as caught:
            close_errors.append({'fd': fd, 'errno': caught.errno})
    result.update({'reader_pid': os.getpid(), 'fd_before': fd_before,
        'fd_after': len(os.listdir('/proc/self/fd')), 'all_read_handles_released': not close_errors,
        'close_errors': close_errors, 'error': error, 'elapsed_s': time.monotonic() - START})
raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
assert len(raw) <= 65536
with (HERE / 'inventory.v1.json').open('xb') as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({'status': 'read_only_complete' if error is None else 'failed',
    'asset_count': result.get('asset_count'), 'asset_bytes': result.get('asset_bytes'),
    'fd_before': fd_before, 'fd_after': result['fd_after'], 'elapsed_s': result['elapsed_s'],
    'inventory_size_bytes': len(raw), 'inventory_sha256': hashlib.sha256(raw).hexdigest()}))
raise SystemExit(0 if error is None and not close_errors and result['fd_after'] == fd_before else 78)
