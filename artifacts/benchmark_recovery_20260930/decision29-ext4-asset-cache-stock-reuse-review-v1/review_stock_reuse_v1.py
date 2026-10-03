"""Read finished eight-asset metadata only; never read model bodies or active suite outputs."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
OUTPUT = ROOT.with_name(ROOT.name + '-original-output')
COPY_OUTPUT = ROOT.with_name(ROOT.name + '-model-cache-copy-output')
START = time.monotonic()
END = START + 60
holds = []
ancestors = {}
pins = {}
copied_metadata = []
fd_before = len(list(Path('/proc/self/fd').iterdir()))

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def read(path, cap=65536):
    assert time.monotonic() < END
    for parent in reversed(path.parents):
        if parent in ancestors:
            continue
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        before = os.fstat(fd)
        ancestors[parent] = (fd, [before.st_dev, before.st_ino, before.st_mode])
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    holds.append((path, fd, None))
    before = epoch(os.fstat(fd))
    holds[-1] = (path, fd, before)
    assert stat.S_ISREG(before[2]) and before[3] == 1 and before[4] <= cap
    assert epoch(path.lstat()) == before
    parts = []; count = 0
    while block := os.read(fd, 65536):
        count += len(block); assert count <= cap; parts.append(block)
    raw = b''.join(parts)
    assert len(raw) == before[4] and epoch(os.fstat(fd)) == before
    pin = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch': before}
    pins[str(path)] = pin
    return raw

def retain(name, path):
    raw = read(path)
    destination = HERE / name
    with destination.open('xb') as stream:
        assert stream.write(raw) == len(raw)
        stream.flush(); os.fsync(stream.fileno())
    copied_metadata.append({'path': str(destination), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                            'original': pins[str(path)], 'raw_bytes_unchanged': True})
    return json.loads(raw)

error = None
close_errors = []
facts = {}
try:
    previous_path = BASE / 'decision29-ext4-asset-cache-copy-actual-review-v1/review.v1.json'
    previous_raw = read(previous_path)
    assert len(previous_raw) == 21260 and hashlib.sha256(previous_raw).hexdigest() == '1c95e34e98acfd6f90194f17b0433dc3feb57fe5fae1525e98f233b550b5d76a'
    previous = json.loads(previous_raw)
    assert previous['status'] == 'copy_setup_physically_verified' and previous['error'] is None and previous['all_reader_handles_released'] is True
    copy_raw = read(COPY_OUTPUT / 'execution.v1.json')
    assert len(copy_raw) == 13866 and hashlib.sha256(copy_raw).hexdigest() == 'edd18fe1ea79b25355c17d21e18dbe910035f00f400df03fdb591d3eb969780e'
    copy = json.loads(copy_raw)
    assert copy['error'] is None and copy['close_errors'] == [] and copy['all_handles_released'] is True
    assert len(copy['assets']) == 8
    assert copy['facts']['source_commit'] == '3c025b29b3c1d5275c2ec693410e4b83700583de' and copy['facts']['target_root'] == str(ROOT)
    report = retain('stock-report.original.json', OUTPUT / 'model-acquisition/report.json')
    command = retain('stock-model-assets-command.original.json', OUTPUT / 'model-assets.json')
    assert command['returncode'] == 0 and command['timed_out'] is False and command['cleanup_error'] is None
    assert command['argv'] == ['/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python', '-I', '-B', str(ROOT / 'scripts/prepare_ci_model_assets.py'), '--output-dir', str(OUTPUT / 'model-acquisition')]
    assert report['status'] == 'complete' and report['hardware_acceptance'] is False and report['requires_original_exit_zero'] is True
    assert report['elapsed_s'] == 0.07897603802848607
    assert [row['index'] for row in report['assets']] == list(range(8))
    source_facts = []
    for known in copy['facts']['source_pins']:
        path = Path(known['path'])
        assert path.is_relative_to(ROOT)
        value = read(path)
        assert len(value) == known['size_bytes'] and hashlib.sha256(value).hexdigest() == known['sha256']
        assert pins[str(path)]['epoch'] == known['epoch']
        source_facts.append(pins[str(path)])
    rows = []
    for i, (summary, copied) in enumerate(zip(report['assets'], copy['assets'])):
        asset = retain('stock-asset-%02d.original.json' % i, OUTPUT / ('model-acquisition/asset-%02d.json' % i))
        assert summary['status'] == asset['status'] == 'reused'
        assert summary['index'] == asset['index'] == copied['index'] == i
        expected = {k: copied[k] for k in ('size_bytes', 'sha256', 'sha384')}
        assert {k: summary[k] for k in expected} == {k: asset['asset'][k] for k in expected} == expected
        assert summary['path'] == asset['asset']['path']
        target = ROOT / summary['path']
        assert str(target) == copied['destination']
        current = epoch(target.lstat())
        assert current == copied['destination_epoch'] and stat.S_ISREG(current[2]) and current[3] == 1
        rows.append({'index': i, 'path': summary['path'], **expected, 'stock_status': 'reused',
                     'destination_current_stat_epoch_equals_copy': current, 'donor_copy_original_epoch': copied['source']['epoch'],
                     'model_bytes_reread_by_reviewer_now': False})
    assert sum(row['size_bytes'] for row in rows) == 15514597
    for pin in report['inputs']:
        actual = pins[str(ROOT / pin['path'])]
        assert all(actual[k] == pin[k] for k in ('size_bytes', 'sha256', 'epoch'))
    for path, fd, before in holds:
        assert before is not None and epoch(os.fstat(fd)) == before and epoch(path.lstat()) == before
    for path, (fd, before) in ancestors.items():
        s = os.fstat(fd); named = path.lstat()
        assert [s.st_dev, s.st_ino, s.st_mode] == [named.st_dev, named.st_ino, named.st_mode] == before
    facts = {'prior_independent_copy_review': pins[str(previous_path)], 'actual_copy_terminal': pins[str(COPY_OUTPUT / 'execution.v1.json')],
             'stock_verifier_sources': source_facts, 'closed_stock_command': command, 'closed_stock_report': report,
             'exact_eight_reuse_joins': rows, 'retained_raw_original_metadata': copied_metadata,
             'all_small_metadata_rechecked_while_held': True}
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)}
finally:
    for _, fd, _ in reversed(holds):
        try: os.close(fd)
        except BaseException as exc: close_errors.append({'type': type(exc).__name__, 'message': str(exc)})
    for fd, _ in reversed(list(ancestors.values())):
        try: os.close(fd)
        except BaseException as exc: close_errors.append({'type': type(exc).__name__, 'message': str(exc)})
fd_after = len(list(Path('/proc/self/fd').iterdir()))
result = {'schema_version': 1, 'kind': 'closed_stock_asset_reuse_review_v1', 'reviewer': '/root/architecture_review',
          'status': 'verified' if error is None and not close_errors and fd_before == fd_after else 'failed',
          'source_commit': '3c025b29b3c1d5275c2ec693410e4b83700583de', 'facts': facts, 'error': error,
          'close_errors': close_errors, 'fd_before': fd_before, 'fd_after': fd_after, 'all_reader_handles_released': True,
          'stock_all_eight_existing_verifier_passed': error is None and not close_errors,
          'no_model_body_reads_or_network_or_CI_execution': True, 'full_local_CI_acceptance': None, 'hardware_acceptance': False,
          'limits': ['Completed acquisition metadata and its actual command are independent of the still-running full local suite.',
                     'Fresh full donor/destination hashes were checked in the prior closed copy review. This review uses the genuine unchanged stock verifier hashes and current seven-epoch stats, without rereading weights.',
                     'No active unittest/native/overall report is inspected; no full CI acceptance or final release claim.'],
          'elapsed_s': time.monotonic()-START}
raw = json.dumps(result, indent=2, sort_keys=True).encode() + b'\n'
assert len(raw) <= 65536 and time.monotonic() < END
with (HERE / 'review.v1.json').open('xb') as stream:
    assert stream.write(raw) == len(raw); stream.flush(); os.fsync(stream.fileno())
print(json.dumps({'status': result['status'], 'review': {'path': str(HERE / 'review.v1.json'), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, 'error': error}))
raise SystemExit(0 if result['status'] == 'verified' else 1)
