"""Finite capture of the two reviewed stock commands; no mount implementation."""
import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-runtime-bind-prerequisite-capture-preparation-v1')
OUT = HERE / 'original-bind-attempt01'
ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
SOURCE = Path('/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1')
PYTHON = SOURCE / 'bin/python'
SCRIPT = ROOT / 'scripts/mount_publication_runtime_wsl.sh'
TARGET = ROOT / '.publication-runtime/full-publication-cp312-v1'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
CP_SHA = '1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118'
CP_EPOCH = [2096, 87545, 33261, 1, 8020928, 1787574148546271435, 1787574148546271435]
SCRIPT_SHA = '5f68ab843ba5022b78242ce50de708f9b387bc817ee3a81cc2cc6f37096a0e6c'
CHANNEL_CAP = 1048576
MOUNT_CAP = 4194304
START = time.monotonic()
WORK_END = START + 120
HARD_END = START + 130
errors = []
close_errors = []
handles = []
directory_holds = []
leaf_holds = []
commands = []
owned_output = False


def interrupted(signum, _frame):
    raise TimeoutError('original capture received signal' + str(signum))


signal.signal(signal.SIGTERM, interrupted)


def fault(exc):
    row = {'type': type(exc).__name__, 'message': str(exc)[:2048], 'errno': getattr(exc, 'errno', None)}
    if len(errors) < 32:
        errors.append(row)
    return row


def gate_time():
    if time.monotonic() >= WORK_END:
        raise TimeoutError('original capture work exceeded120s')


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def raw(name, data):
    with (OUT / name).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save(name, value):
    raw(name, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8'))


def digest_fd(fd, limit):
    digest = hashlib.sha256()
    position = 0
    while True:
        gate_time()
        block = os.pread(fd, min(1048576, limit + 1 - position), position)
        if not block:
            break
        position += len(block)
        if position > limit:
            raise ValueError('held file exceeds exact bound')
        digest.update(block)
    return position, digest.hexdigest()


def hold(path, limit, expected_sha=None, expected_epoch=None):
    cursor = Path('/')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    handles.append((str(cursor), parent))
    directory_holds.append((cursor, parent, os.fstat(parent)))
    for part in path.parts[1:-1]:
        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        cursor /= part
        handles.append((str(cursor), child))
        observed = os.fstat(child)
        assert stat.S_ISDIR(observed.st_mode)
        assert (observed.st_dev, observed.st_ino, observed.st_mode) == (os.lstat(cursor).st_dev, os.lstat(cursor).st_ino, os.lstat(cursor).st_mode)
        directory_holds.append((cursor, child, observed))
        parent = child
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    handles.append((str(path), fd))
    observed = os.fstat(fd)
    assert stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1
    assert epoch(os.lstat(path)) == epoch(observed)
    size, sha = digest_fd(fd, limit)
    assert size == observed.st_size and epoch(os.fstat(fd)) == epoch(observed) == epoch(os.lstat(path))
    if expected_sha is not None:
        assert sha == expected_sha, 'held original SHA differs'
    if expected_epoch is not None:
        assert epoch(observed) == expected_epoch, 'original B95 Python epoch differs'
    row = {'path': str(path), 'size_bytes': size, 'sha256': sha, 'epoch7': epoch(observed)}
    leaf_holds.append((path, fd, row))
    return row, fd


def owner(pid):
    location = Path('/proc') / str(pid)
    values = (location / 'stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in (location / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19]), 'state': values[0], 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'argv': (location / 'cmdline').read_bytes().rstrip(b'\0').decode('utf-8').split('\0')}


def scan(ids):
    rows, failed = [], []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            values = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(entry.name) in ids or int(values[2]) in ids or int(values[3]) in ids:
                rows.append(owner(int(entry.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError, UnicodeError) as exc:
            failed.append({'pid': int(entry.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_ns': time.time_ns(), 'members': rows, 'errors': failed, 'original_pid_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in sorted(ids)}}


def mount_observation(label):
    with open('/proc/self/mountinfo', 'rb') as stream:
        data = stream.read(MOUNT_CAP + 1)
    assert len(data) <= MOUNT_CAP
    raw(label + '.mountinfo.raw', data)
    rows = []
    for line in data.decode('utf-8').splitlines():
        fields, extra = line.split(' - ', 1)
        left, right = fields.split(), extra.split()
        decode = lambda text: text.replace('\\040', ' ').replace('\\011', '\t').replace('\\012', '\n').replace('\\134', '\\')
        if decode(left[4]) in (str(SOURCE), str(TARGET)):
            rows.append({'mount_id': int(left[0]), 'parent_mount_id': int(left[1]), 'device': left[2], 'root': decode(left[3]), 'target': decode(left[4]), 'options': left[5].split(','), 'optional': left[6:], 'filesystem': right[0], 'source': decode(right[1]), 'superblock_options': right[2].split(','), 'original_line': line})
    return {'namespace': os.readlink('/proc/self/ns/mnt'), 'namespace_stat': epoch(os.stat('/proc/self/ns/mnt')), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'mountinfo_size_bytes': len(data), 'mountinfo_sha256': hashlib.sha256(data).hexdigest(), 'rows': rows}


def source_row(observation):
    rows = [row for row in observation['rows'] if row['target'] == str(SOURCE)]
    assert len(rows) == 1 and rows[0]['mount_id'] == 331
    row = rows[0]
    assert row['parent_mount_id'] == 80 and row['device'] == '8:48' and row['root'] == str(SOURCE)
    assert row['filesystem'] == 'ext4' and row['source'] == '/dev/sdd' and 'ro' in row['options']
    return row


def command(label, check_only):
    argv = ['/usr/bin/timeout', '--signal=TERM', '--kill-after=10s', '30s', '/usr/bin/bash', str(SCRIPT)]
    if check_only:
        argv.append('--check-only')
    argv += ['--source-runtime', str(SOURCE), '--project-root', str(ROOT), '--project-runtime-mount', '.publication-runtime/full-publication-cp312-v1']
    row = {'label': label, 'argv': argv, 'started_at_ns': time.time_ns(), 'work_s': 30, 'cleanup_s': 10, 'owner': None, 'observed_descendants': [], 'returncode': None, 'EOF': {'stdout': False, 'stderr': False}, 'signals': [], 'failure': None, 'reaped': False}
    commands.append(row)
    begin = time.monotonic()
    cleanup_end = min(begin + 40, HARD_END)
    child, selector = None, None
    streams = []
    digests = {'stdout': hashlib.sha256(), 'stderr': hashlib.sha256()}
    totals = {'stdout': 0, 'stderr': 0}
    try:
        for channel in ('stdout', 'stderr'):
            stream = (OUT / (label + '.' + channel + '.raw')).open('xb')
            streams.append((channel, stream))
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        row['owner'] = owner(child.pid)
        save(label + '.launch.v1.json', {'argv': argv, 'capture_owner': controller, 'child_owner': row['owner'], 'started_at_ns': row['started_at_ns']})
        selector = selectors.DefaultSelector()
        for channel, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, channel)
        observed = set()
        while selector.get_map() or child.poll() is None:
            now = time.monotonic()
            if now >= begin + 30 and child.poll() is None and row['failure'] is None:
                raise TimeoutError('original stock command work exceeded30s')
            if now >= cleanup_end:
                raise TimeoutError('original stock command exceeded30+10s')
            try:
                children = Path('/proc', str(child.pid), 'task', str(child.pid), 'children').read_text().split()
                for pid in children:
                    if int(pid) not in observed:
                        try:
                            row['observed_descendants'].append(owner(int(pid)))
                            observed.add(int(pid))
                        except FileNotFoundError:
                            pass
            except FileNotFoundError:
                pass
            for key, _ in selector.select(min(.01, max(0, cleanup_end - now))):
                channel = key.data
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    row['EOF'][channel] = True
                    selector.unregister(key.fileobj)
                    continue
                permitted = min(len(block), CHANNEL_CAP - totals[channel])
                if permitted:
                    dict(streams)[channel].write(block[:permitted])
                    totals[channel] += permitted
                    digests[channel].update(block[:permitted])
                if permitted != len(block):
                    raise ValueError('original ' + channel + ' exceeded1MiB')
        row['returncode'] = child.wait(timeout=max(.001, cleanup_end - time.monotonic()))
        row['reaped'] = True
    except BaseException as exc:
        row['failure'] = fault(exc)
        if child is not None:
            try:
                if child.poll() is None:
                    row['signals'].append('SIGKILL')
                    os.killpg(child.pid, signal.SIGKILL)
                row['returncode'] = child.wait(timeout=max(.001, cleanup_end - time.monotonic()))
                row['reaped'] = True
            except BaseException as cleanup_exc:
                fault(cleanup_exc)
    finally:
        if child is not None:
            for channel, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
                if pipe is not None:
                    try:
                        if row['reaped'] and not row['EOF'][channel]:
                            while time.monotonic() < cleanup_end:
                                block = os.read(pipe.fileno(), 65536)
                                if not block:
                                    row['EOF'][channel] = True
                                    break
                                permitted = min(len(block), CHANNEL_CAP - totals[channel])
                                if permitted:
                                    dict(streams)[channel].write(block[:permitted])
                                    totals[channel] += permitted
                                    digests[channel].update(block[:permitted])
                                if permitted != len(block):
                                    raise ValueError('cleanup raw channel cap exceeded')
                    except BaseException as exc:
                        fault(exc)
                    try:
                        pipe.close()
                    except BaseException as exc:
                        close_errors.append(fault(exc))
        if selector is not None:
            try:
                selector.close()
            except BaseException as exc:
                close_errors.append(fault(exc))
        for channel, stream in streams:
            try:
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException as exc:
                fault(exc)
            finally:
                try:
                    stream.close()
                except BaseException as exc:
                    close_errors.append(fault(exc))
        row['channels'] = {channel: {'path': str(OUT / (label + '.' + channel + '.raw')), 'size_bytes': totals[channel], 'sha256': digests[channel].hexdigest()} for channel in ('stdout', 'stderr')}
        row['elapsed_s'] = time.monotonic() - begin
        if row['owner'] is not None:
            ids = {row['owner']['pid']} | {item['pid'] for item in row['observed_descendants']}
            row['process_scans'] = [scan(ids), scan(ids)]
            if any(item['members'] or item['errors'] or not all(item['original_pid_absent'].values()) for item in row['process_scans']):
                fault(RuntimeError('original command closure uncertain'))
        save(label + '.terminal.v1.json', row)
    assert row['returncode'] == 0 and row['failure'] is None and row['reaped'] and all(row['EOF'].values()), 'stock command failed'
    assert row['elapsed_s'] < 40 and not errors, 'stock command closure failed'
    assert json.loads((OUT / (label + '.stdout.raw')).read_bytes()) == {'artifact_kind': 'vast_publication_runtime_mount_v1', 'status': 'verified' if check_only else 'materialized', 'source_read_only': True, 'target_read_only': True}


before = after = controller = None
fd_before = len(os.listdir('/proc/self/fd'))
try:
    assert sys.version_info[:3] == (3, 12, 3) and os.getuid() == 0 and os.getgid() == 0
    assert not sys.argv[1:], 'capture has no arbitrary arguments'
    OUT.mkdir()
    owned_output = True
    controller = owner(os.getpid())
    controller['observed_parent'] = owner(controller['ppid'])
    script_pin, _ = hold(SCRIPT, 6112, SCRIPT_SHA)
    head_pin, head_fd = hold(ROOT / '.git/HEAD', 41, hashlib.sha256((COMMIT + '\n').encode('ascii')).hexdigest())
    assert os.pread(head_fd, 42, 0) == (COMMIT + '\n').encode('ascii')
    python_pin, _ = hold(PYTHON, 8020928, CP_SHA, CP_EPOCH)
    assert epoch(os.stat('/proc/self/exe')) == CP_EPOCH, 'current process is not canonical held Python'
    root_stat, source_stat = os.lstat(ROOT), os.lstat(SOURCE)
    assert stat.S_ISDIR(root_stat.st_mode) and root_stat.st_uid == root_stat.st_gid == 1000
    assert stat.S_ISDIR(source_stat.st_mode) and (source_stat.st_dev, source_stat.st_ino) == (2096, 71429)
    assert not os.path.lexists(TARGET.parent) and not os.path.lexists(TARGET)
    before = mount_observation('before')
    source_row(before)
    assert not [row for row in before['rows'] if row['target'] == str(TARGET)]
    save('dispatch.v1.json', {'controller': controller, 'source_commit': COMMIT, 'source_pins': [script_pin, head_pin, python_pin], 'root_epoch7': epoch(root_stat), 'source_directory_epoch7': epoch(source_stat), 'mount_before': before, 'limits': {'command_work_s': 30, 'command_cleanup_s': 10, 'capture_work_s': 120, 'capture_cleanup_s': 10, 'channel_bytes': CHANNEL_CAP, 'mountinfo_bytes': MOUNT_CAP}})
    command('01-materialize', False)
    command('02-check-only', True)
except BaseException as exc:
    fault(exc)
finally:
    if owned_output:
        try:
            after = mount_observation('after')
            if before is not None:
                assert before['namespace'] == after['namespace'] and before['namespace_stat'][:4] == after['namespace_stat'][:4]
                assert before['boot_id'] == after['boot_id'] and source_row(before) == source_row(after)
            for path, fd, expected in leaf_holds:
                assert epoch(os.fstat(fd)) == expected['epoch7'] == epoch(os.lstat(path))
                size, sha = digest_fd(fd, expected['size_bytes'])
                assert (size, sha) == (expected['size_bytes'], expected['sha256'])
                assert epoch(os.fstat(fd)) == expected['epoch7'] == epoch(os.lstat(path))
            for path, fd, initial in directory_holds:
                actual, named = os.fstat(fd), os.lstat(path)
                assert (actual.st_dev, actual.st_ino, actual.st_mode) == (initial.st_dev, initial.st_ino, initial.st_mode) == (named.st_dev, named.st_ino, named.st_mode)
            if not errors:
                assert epoch(os.lstat(SOURCE)) == epoch(source_stat)
                root_now = os.lstat(ROOT)
                assert (root_now.st_dev, root_now.st_ino, root_now.st_mode, root_now.st_uid, root_now.st_gid) == (root_stat.st_dev, root_stat.st_ino, root_stat.st_mode, root_stat.st_uid, root_stat.st_gid)
                target_rows = [row for row in after['rows'] if row['target'] == str(TARGET)]
                assert len(target_rows) == 1 and target_rows[0]['filesystem'] == 'ext4' and 'ro' in target_rows[0]['options']
                assert target_rows[0]['mount_id'] != 331
                assert all(target_rows[0][field] == source_row(after)[field] for field in ('device', 'root', 'filesystem', 'source'))
                target_stat = os.lstat(TARGET)
                assert (target_stat.st_dev, target_stat.st_ino, target_stat.st_mode) == (source_stat.st_dev, source_stat.st_ino, source_stat.st_mode)
                target_python, _ = hold(TARGET / 'bin/python', 8020928, CP_SHA, CP_EPOCH)
                after['target_python'] = target_python
                after['target_directory_epoch7'] = epoch(target_stat)
            for path, fd, expected in leaf_holds:
                assert epoch(os.fstat(fd)) == expected['epoch7'] == epoch(os.lstat(path))
        except BaseException as exc:
            fault(exc)
    released = []
    for name, fd in reversed(handles):
        try:
            os.close(fd)
            released.append({'path': name, 'closed': True})
        except BaseException as exc:
            close_errors.append(fault(exc))
            released.append({'path': name, 'closed': False})
    fd_after = len(os.listdir('/proc/self/fd'))
    if fd_after != fd_before:
        fault(RuntimeError('capture FD baseline differs'))
    if owned_output:
        terminal = {'schema_version': 1, 'artifact_kind': 'stock_D_runtime_bind_prerequisite_capture_v1', 'status': 'verified' if not errors else 'failed', 'source_commit': COMMIT, 'controller': controller, 'commands': commands, 'mount_before': before, 'mount_after': after, 'held_original_source_pins': [item[2] for item in leaf_holds], 'fd_before': fd_before, 'fd_after': fd_after, 'all_held_FDs_closed': all(item['closed'] for item in released), 'independent_close_attempts': released, 'first_error': errors[0] if errors else None, 'errors': errors, 'close_errors': close_errors, 'elapsed_s': time.monotonic() - START, 'full_CI_acceptance': False, 'fresh95_gate': None, 'canonical_test_gate': None, 'limits': ['Stock suppressed rollback is not proof of rollback; exact after mount observation is retained even on failure.', 'Controller PID absence and outer true EOF/reaping require the independent postterminal root scan.', 'Underlying target directory identity is covered by its mount and is not invented for future removal.']}
        try:
            save('execution.v1.json', terminal)
            if time.monotonic() >= WORK_END:
                fault(TimeoutError('final receipt/FD closure exceeded120s'))
                save('late-failure.v1.json', {'first_error': errors[0], 'errors': errors, 'elapsed_s': time.monotonic() - START, 'acceptance': False})
            print(json.dumps({'path': str(OUT / 'execution.v1.json'), 'status': 'failed' if errors else 'verified', 'elapsed_s': time.monotonic() - START}), flush=True)
            if time.monotonic() >= WORK_END and not os.path.lexists(OUT / 'late-failure.v1.json'):
                fault(TimeoutError('final output exceeded120s'))
                save('late-failure.v1.json', {'first_error': errors[0], 'errors': errors, 'elapsed_s': time.monotonic() - START, 'acceptance': False})
        except BaseException as exc:
            fault(exc)
            if not os.path.lexists(OUT / 'late-failure.v1.json'):
                try:
                    save('late-failure.v1.json', {'first_error': errors[0], 'errors': errors, 'acceptance': False})
                except BaseException:
                    pass
sys.exit(0 if owned_output and not errors and time.monotonic() < WORK_END else 78)
