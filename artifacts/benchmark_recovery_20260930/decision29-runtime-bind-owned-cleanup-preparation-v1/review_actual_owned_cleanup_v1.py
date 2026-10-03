"""Narrow original-cleanup metadata/owner closure. Never invokes a target."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930')
HERE = BASE / 'decision29-runtime-bind-owned-cleanup-preparation-v1'
ORIGINAL = HERE / 'original-owned-cleanup-attempt01'
OUT = HERE / 'independent-original-cleanup-review-attempt01'
SOURCE = Path('/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1')
TARGET = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D/.publication-runtime/full-publication-cp312-v1')
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
START = time.monotonic()
held, ancestors, closes = [], {}, []
first, owned, facts = None, False, {}

def deadline():
    if time.monotonic() - START >= 20:
        raise TimeoutError('original20s cleanup metadata closure')

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def digest(fd, size):
    data, offset = [], 0
    sha = hashlib.sha256()
    while offset < size:
        deadline()
        block = os.pread(fd, min(65536, size - offset), offset)
        assert block
        offset += len(block)
        data.append(block)
        sha.update(block)
    assert not os.pread(fd, 1, size)
    return b''.join(data), sha.hexdigest()

def read_control(path, size, sha):
    deadline()
    assert 0 <= size <= 1048576
    parent, cursor = None, Path('/')
    for part in ('/',) + path.parts[1:-1]:
        cursor = Path('/') if part == '/' else cursor / part
        if cursor not in ancestors:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC) if part == '/' else os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            ancestors[cursor] = (fd, os.fstat(fd))
        parent, prior = ancestors[cursor]
        assert (prior.st_dev, prior.st_ino, prior.st_mode) == (os.lstat(cursor).st_dev, os.lstat(cursor).st_ino, os.lstat(cursor).st_mode)
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    held.append((path, fd, None))
    observed = os.fstat(fd)
    assert stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1 and observed.st_size == size
    assert epoch(observed) == epoch(os.lstat(path))
    raw, actual = digest(fd, size)
    assert actual == sha and epoch(observed) == epoch(os.fstat(fd)) == epoch(os.lstat(path))
    row = {'path': str(path), 'size_bytes': size, 'sha256': sha, 'epoch7': epoch(observed)}
    held[-1] = (path, fd, row)
    return raw, row

def owner(pid):
    p = Path('/proc') / str(pid)
    values = (p / 'stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19]), 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

def scan(actors):
    pids = {a['pid'] for a in actors}
    groups = {a['pgid'] for a in actors}
    sessions = {a['session'] for a in actors}
    matches, errors = [], []
    for path in Path('/proc').iterdir():
        deadline()
        if not path.name.isdigit():
            continue
        try:
            values = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(path.name) in pids or int(values[2]) in groups or int(values[3]) in sessions:
                matches.append(owner(int(path.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError, UnicodeError) as exc:
            errors.append({'pid': int(path.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_monotonic_ns': time.monotonic_ns(), 'original_PID_paths_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in sorted(pids)}, 'recorded_groups': sorted(groups), 'recorded_sessions': sorted(sessions), 'members': matches, 'errors': errors}

def current_mount_rows():
    fd = os.open('/proc/self/mountinfo', os.O_RDONLY | os.O_CLOEXEC)
    try:
        parts, count = [], 0
        while True:
            deadline()
            block = os.read(fd, 65536)
            if not block:
                break
            count += len(block)
            assert count <= 4194304
            parts.append(block)
    finally:
        os.close(fd)
    data = b''.join(parts)
    rows = []
    for line in data.decode().splitlines():
        fields = line.split()
        if int(fields[0]) == 2708 or fields[4] in (str(SOURCE), str(TARGET)):
            rows.append(line)
    return {'namespace': os.readlink('/proc/self/ns/mnt'), 'namespace_epoch7': epoch(os.stat('/proc/self/ns/mnt')), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'relevant_original_lines': rows}

def save(name, value):
    with (OUT / name).open('xb') as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())

signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(TimeoutError('cleanup metadata SIGTERM')))
fd_before = len(list(Path('/proc/self/fd').iterdir()))
reader = owner(os.getpid())
reader['observed_parent'] = owner(reader['ppid'])
try:
    assert sys.version_info[:3] == (3, 12, 3) and Path(sys.executable) == SOURCE / 'bin/python'
    assert reader['boot_id'] == BOOT
    OUT.mkdir(mode=0o700)
    owned = True
    raw, result_pin = read_control(ORIGINAL / 'execution.v1.json', 38407, '57f8f2ea90b1cc3ef23a8409a3e7302141fb22730ee91bb605e946ec283fa15d')
    result = json.loads(raw)
    assert result['status'] == 'verified_owned_unmount_not_acceptance' and result['source_commit_D'] == COMMIT
    assert result['all_held_FDs_closed'] is True and not result['errors'] and not result['close_errors'] and result['first_error'] is None
    assert result['fd_before'] == result['fd_after'] == 6 and result['elapsed_s'] < 40
    assert not result['directory_deletion_performed'] and result['underlying_target_directory_pre_mount_identity'] is None
    raw, command_pin = read_control(ORIGINAL / 'umount.command.v1.json', 2788, '070e501efb56c1c57eb225b65620e574a840b18f47fd0fd940e73b938a3b610b')
    command = json.loads(raw)
    assert command == result['command'] and command['argv'] == ['/usr/bin/umount', '--', str(TARGET)]
    assert command['returncode'] == 0 and command['reaped'] is True and all(command['EOF'].values()) and command['failure'] is None and not command['signals']
    raw, launch_pin = read_control(ORIGINAL / 'umount.launch.v1.json', 2644, 'cbb97501072cfa62692dd5c58d46c50f1aae11b3bf48a12f6f33664a6c4d7b6e')
    launch = json.loads(raw)
    assert launch['capture_owner'] == result['controller'] and launch['command']['owner'] == command['owner']
    raw, bound_pin = read_control(HERE / 'consumer-closure.bound.v1.json', 9530, '059f4057bf7d6f550d59064c06e4e785b687ec1998e9625dfb2c6a3c2b148cee')
    bound = json.loads(raw)
    raw, candidate_pin = read_control(HERE / 'consumer-closure.candidate.v1.json', 9531, '010c43c2f32587d8fe807fc991f2e73a97d97a91d20796a23e43df3908406600')
    candidate = json.loads(raw)
    assert candidate['cleanup_authorized'] is False
    candidate['cleanup_authorized'] = True
    assert bound == candidate and all(bound[k] is True for k in ('cleanup_authorized', 'all_D_consumers_closed', 'no_new_D_consumers_since_closure'))
    raw, grant_pin = read_control(HERE / 'root-exact-cleanup-grant.v1.json', 714, '6b25223fa488bb54faf8bbe84962e7bafd233a8f8be6a9ece99872b33d30569d')
    grant = json.loads(raw)
    assert grant['bound_sha256'] == bound_pin['sha256'] and grant['only_owned_mount2708_unmount_allowed'] is True and grant['directory_deletion_allowed'] is False
    source_ref = result['facts']['held_original_leaves_after_full_SHA_and_epoch_recheck'][0]
    _, source_pin = read_control(Path(source_ref['path']), 31423, 'e4321413fb7a9613a362bd544347de8d552c1ebd50615beb78d3b82dbce98921')
    assert source_pin['epoch7'] == source_ref['epoch7']
    for label in ('stdout', 'stderr'):
        channel = command['raw_channels'][label]
        ref = channel['stored_original_descriptor']
        _, observed = read_control(Path(ref['path']), ref['size_bytes'], ref['sha256'])
        assert observed['epoch7'] == ref['epoch7'] and ref['size_bytes'] == channel['acknowledged_bytes'] == 0
        assert channel['EOF_observed'] and channel['stored_descriptor_verified']
    creator_ref = result['facts']['creator']
    raw, creator_pin = read_control(Path(creator_ref['path']), creator_ref['size_bytes'], creator_ref['sha256'])
    creator = json.loads(raw)
    assert creator_pin['epoch7'] == creator_ref['epoch7']
    assert result['facts']['held_ancestor_identities_after_rechecked'] is True
    assert len(result['facts']['held_original_leaves_after_full_SHA_and_epoch_recheck']) == 19
    assert result['facts']['normalized_actual_consumer_owners_unknown_fields_null'] == bound['all_closed_consumer_owners']
    assert len(bound['all_closed_consumer_owners']) == 23
    for original_scan in result['facts']['consumer_owner_scans'] + command['two_owned_process_scans']:
        assert not original_scan['errors'] and not original_scan['members'] and all(original_scan['original_pid_absent'].values())
    current = current_mount_rows()
    source_rows = [r for r in result['facts']['mount_before']['rows'] if r['target'] == str(SOURCE)]
    assert len(source_rows) == 1 and source_rows[0]['mount_id'] == 331
    assert current['namespace'] == 'mnt:[4026532217]' and current['boot_id'] == BOOT
    assert current['namespace_epoch7'] == result['facts']['mount_after']['namespace_stat']
    assert current['relevant_original_lines'] == [source_rows[0]['original_line']]
    assert result['facts']['mount_after']['rows'] == source_rows and result['facts']['global_source_mount331_unchanged'] is True and result['facts']['owned_target_mount2708_absent'] is True
    assert epoch(os.lstat(SOURCE)) == creator['mount_after']['target_directory_epoch7']
    assert epoch(os.lstat(SOURCE / 'bin/python')) == result['facts']['canonical_python']['epoch7']
    assert epoch(os.lstat('/usr/bin/umount')) == result['facts']['umount_executable']['epoch7']
    target = os.lstat(TARGET)
    assert stat.S_ISDIR(target.st_mode) and epoch(target) == result['facts']['retained_target_directory_post_unmount_observation_only']['epoch7']
    with os.scandir(TARGET) as entries:
        assert next(entries, None) is None
    actors = [result['controller'], result['controller']['observed_parent'], command['owner']]
    assert sorted(a['pid'] for a in actors) == [11312, 11313, 11314] and all(a['boot_id'] == BOOT for a in actors)
    scans = [scan(actors), scan(actors)]
    assert all(not s['errors'] and not s['members'] and all(s['original_PID_paths_absent'].values()) for s in scans)
    late = ORIGINAL / 'late-or-persistence-failure.v1.json'
    assert not os.path.lexists(late)
    for path, fd, row in held:
        assert row is not None and epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
        _, actual = digest(fd, row['size_bytes'])
        assert actual == row['sha256'] and epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
    for path, (fd, before) in ancestors.items():
        current_dir = os.fstat(fd)
        named_dir = os.lstat(path)
        assert (current_dir.st_dev, current_dir.st_ino, current_dir.st_mode) == (before.st_dev, before.st_ino, before.st_mode) == (named_dir.st_dev, named_dir.st_ino, named_dir.st_mode)
    assert not os.path.lexists(late)
    facts = {'original_execution': result_pin, 'original_command': command_pin, 'original_launch': launch_pin, 'exact_root_grant': grant_pin, 'bound_control': bound_pin, 'candidate_control': candidate_pin, 'reviewed_source': source_pin, 'original_creator': creator_pin, 'actual_true_command_exit': 0, 'actual_command_EOF_both': True, 'actual_raw_channel_bytes_each': 0, 'original_19_fullSHA_sevenepoch_and_ancestor_recheck_joined': True, 'original_23_consumer_absence_scans_joined': True, 'original_capture_FD_before_after': [6, 6], 'fresh_original_capture_timeout_command_scans': scans, 'late_companion_absent': True, 'current_mount_namespace_source331_unchanged_owned2708_absent': current, 'current_source_directory_epoch7': epoch(os.lstat(SOURCE)), 'current_canonical_interpreter_epoch7': epoch(os.lstat(SOURCE / 'bin/python')), 'retained_empty_target_directory_post_only': {'path': str(TARGET), 'epoch7': epoch(target), 'pre_mount_identity_unknown': True, 'deleted': False}, 'original_elapsed_s': result['elapsed_s']}
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
result = {'schema_version': 1, 'kind': 'actual_owned_runtime_bind_cleanup_independent_metadata_review_v1', 'status': 'verified' if first is None and not closes and fd_before == fd_after else 'failed', 'source_commit': COMMIT, 'reader_pid': reader['pid'], 'reader_original': reader, 'facts': facts, 'first_failure': first, 'close_errors': closes, 'all_reader_handles_released': not closes, 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START, 'original_cleanup_tool': {'chunk': '40b69c', 'exit_code': 0, 'tool_wall_s': 1.1290933, 'basis': 'Parent genuine original terminal notification'}, 'cleanup_or_target_replayed': False, 'acceptance_claim': False, 'limits': ['Fresh absence covers only recorded capture11313/timeout11312/command11314 and their recorded groups/sessions, not global descendants.', 'Original full19 held-byte verification is joined from the producer; this reader rehashes only small controls/raw0B and observes canonical interpreter/directory epochs without replay.', 'The target directory remains empty and retained. Its original underlying pre-mount identity was never recorded; no directory deletion or restored-identity claim.', 'This live reader cannot prove its own later absence; a separate postterminal metadata closure is required.']}
if owned:
    try:
        deadline()
        save('review.v1.json', result)
        print(json.dumps({'status': result['status'], 'reader_original': reader, 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START}), flush=True)
        deadline()
    except BaseException as exc:
        result['status'] = 'failed'
        try:
            save('late-failure.v1.json', {'status': 'failed', 'first_failure': first or {'type': type(exc).__name__, 'message': str(exc)[:1024]}, 'acceptance_claim': False})
        except BaseException as failure:
            print(json.dumps({'status': 'failed', 'companion_error': str(failure)[:1024]}), flush=True)
else:
    print(json.dumps({'status': 'failed', 'output_owned': False, 'first_failure': first}), flush=True)
raise SystemExit(0 if result['status'] == 'verified' else 1)
