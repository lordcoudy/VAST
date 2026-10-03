"""One small metadata/process observation after genuine original completion."""
import hashlib
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930')
READER = BASE / 'decision29-local-ci-D-prerequisite-result-review-preparation-v1'
HERE = READER / 'independent-owner-late-closure-v1'
OUT = HERE / 'original-observation-attempt01'
REPORT = READER / 'original-prerequisite-review-attempt01/review.v1.json'
WRAPPER = BASE / 'decision29-successor-ci-D-prerequisite-capture-preparation-v1/original-full-ci-prerequisite-attempt01'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
START = time.monotonic()
END = START + 20
held, ancestors, closes = [], {}, []
first, owned = None, False
facts = {}


def deadline():
    if time.monotonic() >= END:
        raise TimeoutError('original20s owner/late metadata observation')


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def ident(s):
    return (s.st_dev, s.st_ino, s.st_mode)


def pin(path, size, sha):
    deadline()
    cursor = Path('/')
    parent = None
    for part in ('/',) + path.parts[1:-1]:
        cursor = Path('/') if part == '/' else cursor / part
        if cursor not in ancestors:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC) if part == '/' else os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            ancestors[cursor] = (fd, os.fstat(fd))
        parent, prior = ancestors[cursor]
        assert ident(os.fstat(parent)) == ident(prior) == ident(os.lstat(cursor))
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    held.append((path, fd, None))
    prior = os.fstat(fd)
    assert stat.S_ISREG(prior.st_mode) and prior.st_nlink == 1 and prior.st_size == size and 0 <= size <= 1048576
    assert epoch(prior) == epoch(os.lstat(path))
    blocks, offset = [], 0
    while offset < size:
        deadline()
        block = os.pread(fd, min(65536, size - offset), offset)
        assert block, 'bounded exact payload ended early'
        blocks.append(block)
        offset += len(block)
    data = b''.join(blocks)
    assert len(data) == size and not os.pread(fd, 1, size) and hashlib.sha256(data).hexdigest() == sha
    assert epoch(prior) == epoch(os.fstat(fd)) == epoch(os.lstat(path))
    row = {'path': str(path), 'size_bytes': size, 'sha256': sha, 'epoch7': epoch(prior)}
    held[-1] = (path, fd, row)
    return json.loads(data), row


def owner(pid):
    p = Path('/proc') / str(pid)
    values = (p / 'stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19]), 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def normalize(value):
    return {key: value.get(key) for key in ('pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id')}


def scan(owners):
    pids = {r['pid'] for r in owners}
    groups = {r['pgid'] for r in owners if r['pgid'] is not None}
    sessions = {r['session'] for r in owners if r['session'] is not None}
    matches, errors = [], []
    for path in Path('/proc').iterdir():
        deadline()
        if not path.name.isdigit():
            continue
        try:
            words = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(path.name) in pids or int(words[2]) in groups or int(words[3]) in sessions:
                matches.append(owner(int(path.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError, UnicodeError) as exc:
            errors.append({'pid': int(path.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_monotonic_ns': time.monotonic_ns(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'original_PID_paths_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in sorted(pids)}, 'matched_owned_PID_PGID_session_members': matches, 'errors': errors}


def save(name, value):
    with (OUT / name).open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(TimeoutError('original observation SIGTERM')))
fd_before = len(list(Path('/proc/self/fd').iterdir()))
controller = owner(os.getpid())
controller['observed_parent'] = owner(controller['ppid'])
try:
    assert sys.version_info[:3] == (3, 12, 3) and controller['boot_id'] == BOOT
    assert Path(sys.executable) == Path('/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python')
    OUT.mkdir(mode=0o700)
    owned = True
    review, review_pin = pin(REPORT, 119285, '5a58508acf35f71d3c2934a022de1bff2e60eb44a39b6f85bd48cc3715ab7c60')
    terminal, terminal_pin = pin(WRAPPER / 'terminal.v1.json', 964, '3edd982ef6967a065fc52f1bf266fc0614fe4e69b64b6d875ccfc47ec98d658b')
    dispatch, dispatch_pin = pin(WRAPPER / 'dispatch.v1.json', 5426, '68f7184244fd4343317a75e0390ee5851110033628acf77022cdf0c819fc2bdc')
    assert review['source_commit'] == terminal['source_commit'] == dispatch['source_commit'] == COMMIT
    assert review['status'] == 'verified' and review['mandatory_local_CI_pass'] is True and review['original_full_CI_disposition'] == 'SUCCESS'
    assert review['reader_pid'] == 10965 and review['all_reader_handles_released'] is True and not review['close_errors'] and review['fd_before'] == review['fd_after'] == 6
    assert review['root_reported_original_tool_closure']['returncode'] == 0 and review['root_reported_original_tool_closure']['terminal_cell'] == '3db5dc'
    assert terminal['status'] == 'success' and terminal['returncode'] == 0 and not terminal['first_error'] and not terminal['close_errors'] and not terminal['signals']
    assert terminal['held_descriptors_released'] is True and terminal['source_before_after_equal'] is True and sorted(terminal['eof']) == ['stderr', 'stdout']
    assert review['facts']['actual_wrapper_terminal'] == terminal and review['facts']['actual_wrapper_dispatch'] == dispatch
    original_owners = [normalize(dispatch['controller']), normalize(terminal['original']), normalize(review['facts']['actual_observer']['owner']), normalize({'pid': review['reader_pid']})]
    assert [r['pid'] for r in original_owners] == [6673, 6687, 6999, 10965]
    for r in original_owners[:3]:
        assert r['boot_id'] == BOOT and r['startticks'] > 0 and r['uid'] == r['gid'] == 1000
    late_paths = [WRAPPER / 'late-failure.v1.json', REPORT.parent / 'late-failure.v1.json']
    assert all(not os.path.lexists(path) for path in late_paths)
    scans = [scan(original_owners), scan(original_owners)]
    assert all(not s['errors'] and not s['matched_owned_PID_PGID_session_members'] and all(s['original_PID_paths_absent'].values()) and s['boot_id'] == BOOT for s in scans)
    assert all(not os.path.lexists(path) for path in late_paths)
    for path, fd, row in held:
        assert row is not None and epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
        digest, offset = hashlib.sha256(), 0
        while offset < row['size_bytes']:
            deadline()
            block = os.pread(fd, min(65536, row['size_bytes'] - offset), offset)
            assert block
            digest.update(block)
            offset += len(block)
        assert digest.hexdigest() == row['sha256'] and not os.pread(fd, 1, offset)
        assert epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
    for path, (fd, before) in ancestors.items():
        assert ident(os.fstat(fd)) == ident(before) == ident(os.lstat(path))
    facts = {'review': review_pin, 'wrapper_terminal': terminal_pin, 'wrapper_dispatch': dispatch_pin, 'original_owners_from_actual_records': original_owners, 'two_fresh_process_scans': scans, 'late_companion_paths_absent': [str(path) for path in late_paths], 'actual_counts': review['facts']['actual_counts'], 'six_builds': review['facts']['six_built_targets'], 'native_success_ids': review['facts']['actual_native_success_ids'], 'source_table_rows': review['facts']['source_table_rows'], 'original_CI_disposition': review['original_full_CI_disposition'], 'mandatory_local_CI_pass': review['mandatory_local_CI_pass']}
except BaseException as exc:
    first = {'type': type(exc).__name__, 'message': str(exc)[:2048], 'errno': getattr(exc, 'errno', None)}
finally:
    for path, fd, _ in reversed(held):
        try:
            os.close(fd)
        except BaseException as exc:
            closes.append({'path': str(path), 'type': type(exc).__name__, 'message': str(exc)[:512]})
    for path, (fd, _) in reversed(list(ancestors.items())):
        try:
            os.close(fd)
        except BaseException as exc:
            closes.append({'path': str(path), 'type': type(exc).__name__, 'message': str(exc)[:512]})
fd_after = len(list(Path('/proc/self/fd').iterdir()))
result = {'schema_version': 1, 'kind': 'original_corrected_local_CI_reader_owner_late_closure_v1', 'status': 'verified' if first is None and not closes and fd_before == fd_after else 'failed', 'source_commit_D': COMMIT, 'facts': facts, 'observer': controller, 'first_error': first, 'close_errors': closes, 'all_observer_handles_released': not closes, 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START, 'original_root_tool_outcomes': {'full_CI': {'terminal_cell': '3db5dc', 'returncode': 0}, 'independent_reader': {'terminal_cell': '35ac22', 'returncode': 0}, 'basis': 'Parent genuine original completion notifications, not fabricated wrapper capture'}, 'no_CI_test_reader_engine_model_replay': True, 'hardware_acceptance': False, 'conformance_acceptance': False, 'archive_complete': False, 'limits': ['Original observer6999 session was not recorded; its actual PID/PGID/startticks/UID/GID/boot are retained and only observed fields are scanned.', 'Original independent reader10965 birth/group/session/UID/GID/boot were not recorded in its report. Both fresh scans prove its PID path absent, not an unobserved group absent.', 'Fresh scans cover only recorded original process/group/session identities; no global descendant absence claim.', 'This observer cannot prove its own absence while live; its actual owner/parent are retained for a separate parent postterminal gate.', 'Old failed local D remains failed. Actual corrected CI success does not itself accept hardware, SLO achievement, conformance, archive or merge.']}
if owned:
    try:
        deadline()
        save('closure.v1.json', result)
        print(json.dumps({'status': result['status'], 'observer': controller, 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START}), flush=True)
        deadline()
    except BaseException as exc:
        result['status'] = 'failed'
        try:
            save('late-failure.v1.json', {'status': 'failed', 'first_error': first or {'type': type(exc).__name__, 'message': str(exc)[:1024]}, 'acceptance_claim': False})
        except BaseException as failure:
            print(json.dumps({'status': 'failed', 'companion_error': str(failure)[:1024]}), flush=True)
else:
    print(json.dumps({'status': 'failed', 'output_owned': False, 'first_error': first}), flush=True)
raise SystemExit(0 if result['status'] == 'verified' else 1)
