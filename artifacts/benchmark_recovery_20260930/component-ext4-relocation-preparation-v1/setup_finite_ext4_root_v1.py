"""Unexecuted finite Decision27 setup observer; no image/model/runtime operations.

Creates one fresh shared-object Git checkout and copies only the exact original
untracked inputs. This is preparation evidence, never benchmark acceptance.
The source Git object database must remain available while this clone is used.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time

SOURCE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
COMMON = Path('/mnt/e/STUDY/VAST')
TARGET = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
INVENTORY = SOURCE / 'artifacts/benchmark_recovery_20260930/component-ext4-relocation-feasibility-v1/inventory.v1.json'
INVENTORY_SHA = '8a03751c4f3e18a2590d04874496559cc77dab7ffebc8184269c0b9bb81dc364'
CLASSIFICATION = INVENTORY.with_name('git-input-classification.v1.json')
CLASSIFICATION_SHA = 'ed2858413c0dca784f05bff2ca4551b0d6f7879baf6624d07a54c1227a320e3c'
OUTPUT = SOURCE / 'artifacts/benchmark_recovery_20260930/component-ext4-setup-original-v1'
assert len(sys.argv) == 3, 'usage: setup SOURCE_COMMIT REVIEWED_PLANNING_COMMIT'
COMMIT, PLANNING = sys.argv[1:]
assert all(len(x) == 40 and all(c in '0123456789abcdef' for c in x) for x in (COMMIT, PLANNING))
START = time.monotonic()
DEADLINE = START + 600
HARD_DEADLINE = DEADLINE + 10
MAX_CHANNEL = 1024 * 1024
held = []
directory_pins = {}
copied = []
retained = []
commands = []
primary = None
cleanup_errors = []


def clock():
    if time.monotonic() >= DEADLINE:
        raise TimeoutError('original finite setup600s deadline')


def hard_clock():
    if time.monotonic() >= HARD_DEADLINE:
        raise TimeoutError('original finite setup600+10s persistence/cleanup deadline')


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def failure(exc):
    return {'type': type(exc).__name__, 'message': str(exc)[:4096]}


def write(name, value):
    hard_clock()
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    assert len(raw) <= 8 * 1024 * 1024, 'bounded setup metadata'
    with (OUTPUT / name).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    hard_clock()
    return {'path': str(OUTPUT / name), 'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def canonical_directory(path):
    assert path.is_absolute() and path.resolve(strict=True) == path
    for current in (path, *path.parents):
        info = current.lstat()
        assert stat.S_ISDIR(info.st_mode) and not current.is_symlink()
    return epoch(path.lstat())[:3]


def directory_barrier(path):
    # Directory entries legitimately grow during clone/copy. Preserve actual
    # directory FD/name/inode/mode/owner identity, not an immutable nlink/mtime.
    for current in reversed((path, *path.parents)):
        key = str(current)
        if key not in directory_pins:
            info = current.lstat()
            assert stat.S_ISDIR(info.st_mode) and not current.is_symlink()
            fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            observed = os.fstat(fd)
            identity = [observed.st_dev, observed.st_ino, observed.st_mode,
                        observed.st_uid, observed.st_gid]
            assert identity == [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]
            directory_pins[key] = {'fd': fd, 'identity': identity}
        row = directory_pins[key]
        actual = os.fstat(row['fd'])
        named = current.lstat()
        assert not current.is_symlink()
        assert row['identity'] == [actual.st_dev, actual.st_ino, actual.st_mode,
                                   actual.st_uid, actual.st_gid]
        assert row['identity'] == [named.st_dev, named.st_ino, named.st_mode,
                                   named.st_uid, named.st_gid], 'held ancestor identity drift'


source_identity = canonical_directory(SOURCE)
target_parent_identity = canonical_directory(TARGET.parent)
assert TARGET.parent.stat().st_uid == os.getuid()
assert not os.path.lexists(TARGET) and not os.path.lexists(OUTPUT)
canonical_directory(OUTPUT.parent)
assert any(line.split()[4] == '/' and line.split(' - ')[1].split()[0] == 'ext4'
           for line in Path('/proc/self/mountinfo').read_text().splitlines())
assert TARGET.parent.stat().st_dev == Path('/').stat().st_dev
available = os.statvfs(TARGET.parent)
available_bytes = available.f_bavail * available.f_frsize
# Copy payload, a conservatively bounded tracked checkout, and the unchanged
# original20GiB reservation must fit without relying on future cleanup.
assert available_bytes >= 4311301443 + 256 * 1024 * 1024 + 20 * 1024**3
# Compute the complete retained descriptor requirement before creating either
# observation or target namespace. No inherited resource limit is changed.
preflight_inventory_raw = INVENTORY.read_bytes()
assert len(preflight_inventory_raw) <= 4*1024*1024
assert hashlib.sha256(preflight_inventory_raw).hexdigest() == INVENTORY_SHA
preflight_inputs = json.loads(preflight_inventory_raw)['copy_inputs']
assert len(preflight_inputs) == 2693
required_directories = set()
for path in [INVENTORY, CLASSIFICATION,
             *[root/row['path'] for root in (SOURCE, TARGET) for row in preflight_inputs]]:
    for directory in path.parent.parents:
        required_directories.add(str(directory))
    required_directories.add(str(path.parent))
baseline_open_fds = len(os.listdir('/proc/self/fd'))
observed_soft_limit, observed_hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
required_leaf_fds = 2*len(preflight_inputs)+2
required_minimum_fds = required_leaf_fds+len(required_directories)+baseline_open_fds+64
assert observed_soft_limit == resource.RLIM_INFINITY or observed_soft_limit >= required_minimum_fds, 'inherited RLIMIT_NOFILE is too low before setup namespace creation'
fd_budget = {'observed_soft_limit': observed_soft_limit, 'observed_hard_limit': observed_hard_limit,
             'required_leaf_fds': required_leaf_fds, 'required_ancestor_fds': len(required_directories),
             'baseline_open_fds': baseline_open_fds, 'temporary_overhead_reserve_fds': 64,
             'required_minimum_fds': required_minimum_fds, 'resource_limit_changed': False}
OUTPUT.mkdir(mode=0o700)


def path_for(root, relative, create_parents=False):
    value = PurePosixPath(relative)
    assert type(relative) is str and value.as_posix() == relative
    assert not value.is_absolute() and '..' not in value.parts and '\\' not in relative
    assert value.parts and value.parts[0] != '.git'
    current = root
    for part in value.parts[:-1]:
        current = current / part
        if create_parents and not os.path.lexists(current):
            current.mkdir(mode=0o755)
        info = current.lstat()
        assert stat.S_ISDIR(info.st_mode) and not current.is_symlink()
    return root / relative


def namespace_files(root, expected):
    """Check only this fresh tracked tree plus the explicit original copy set."""
    wanted_directories = {'.'}
    for relative in expected:
        value = PurePosixPath(relative)
        assert value.as_posix() == relative and not value.is_absolute()
        assert value.parts and value.parts[0] != '.git' and '..' not in value.parts and '\\' not in relative
        wanted_directories.update(parent.as_posix() for parent in value.parents)
    observed_files, observed_directories = set(), {'.'}
    for parent, directories, files in os.walk(root, followlinks=False):
        clock()
        parent = Path(parent)
        assert not parent.is_symlink() and stat.S_ISDIR(parent.lstat().st_mode)
        if parent == root:
            assert '.git' in directories and not (root/'.git').is_symlink()
            directories.remove('.git')
        for name in directories:
            path = parent/name
            assert not path.is_symlink() and stat.S_ISDIR(path.lstat().st_mode)
            observed_directories.add(path.relative_to(root).as_posix())
        for name in files:
            path = parent/name
            info = path.lstat()
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()
            observed_files.add(path.relative_to(root).as_posix())
    assert observed_files == expected, 'fresh target contains missing or unlisted file names'
    assert observed_directories == wanted_directories, 'fresh target contains missing or unlisted directories'
    return {'file_count': len(observed_files), 'directory_count': len(observed_directories),
            'sorted_paths_sha256': hashlib.sha256(('\n'.join(sorted(observed_files))+'\n').encode()).hexdigest()}


def tracked_snapshot(root, objects):
    """Raw checkout bytes must equal every exact Git blob, without filters."""
    observed, mismatches = {}, []
    for relative, declared in objects.items():
        clock()
        path = path_for(root, relative)
        canonical_directory(path.parent)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            before = epoch(info)
            assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            sha = hashlib.sha256()
            blob = hashlib.sha1(('blob '+str(info.st_size)+'\0').encode('ascii'))
            size = 0
            while block := os.read(fd, 1024*1024):
                clock()
                sha.update(block)
                blob.update(block)
                size += len(block)
            assert before == epoch(os.fstat(fd)) == epoch(path.lstat())
            canonical_directory(path.parent)
            row = {'size_bytes': size, 'sha256': sha.hexdigest(), 'git_blob_sha1': blob.hexdigest(),
                   'epoch': before, 'git_mode': declared['mode']}
            observed[relative] = row
            if blob.hexdigest() != declared['object'] or bool(info.st_mode & stat.S_IXUSR) != (declared['mode'] == '100755'):
                mismatches.append({'path': relative, 'expected': declared, 'actual': row})
        finally:
            os.close(fd)
    return observed, mismatches


def pin(path, expected=None):
    directory_barrier(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        observed = epoch(info)
        assert observed == epoch(path.lstat())
        directory_barrier(path.parent)
        if expected is not None:
            assert info.st_size == expected['size_bytes']
            assert observed == expected['current_epoch'], 'original input epoch drift'
        row = {'path': str(path), 'fd': fd, 'epoch': observed}
        held.append(row)
        return row
    except BaseException:
        os.close(fd)
        raise


def digest(row, expected):
    clock()
    directory_barrier(Path(row['path']).parent)
    assert epoch(os.fstat(row['fd'])) == row['epoch'] == epoch(Path(row['path']).lstat())
    os.lseek(row['fd'], 0, os.SEEK_SET)
    result = hashlib.sha256()
    size = 0
    while block := os.read(row['fd'], 1024 * 1024):
        clock()
        result.update(block)
        size += len(block)
        assert size <= expected['size_bytes']
    assert size == expected['size_bytes'] and result.hexdigest() == expected['sha256']
    assert epoch(os.fstat(row['fd'])) == row['epoch'] == epoch(Path(row['path']).lstat())
    directory_barrier(Path(row['path']).parent)


def read_plan(path, sha256):
    row = pin(path)
    assert row['epoch'][4] <= 4*1024*1024
    blocks = []
    size = 0
    while block := os.read(row['fd'], 65536):
        clock()
        size += len(block)
        assert size <= 4*1024*1024
        blocks.append(block)
    raw = b''.join(blocks)
    assert hashlib.sha256(raw).hexdigest() == sha256
    row['metadata_descriptor'] = {'size_bytes': len(raw), 'sha256': sha256}
    digest(row, row['metadata_descriptor'])
    return raw


def copy_original(src, dst, expected):
    assert not os.path.lexists(dst), 'original untracked target is occupied'
    directory_barrier(dst.parent)
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    try:
        os.lseek(src['fd'], 0, os.SEEK_SET)
        size = 0
        sha = hashlib.sha256()
        while block := os.read(src['fd'], 1024 * 1024):
            clock()
            size += len(block)
            assert size <= expected['size_bytes']
            sha.update(block)
            view = memoryview(block)
            while view:
                clock()
                count = os.write(fd, view)
                assert count > 0
                view = view[count:]
        assert size == expected['size_bytes'] and sha.hexdigest() == expected['sha256']
        os.fsync(fd)
        written_epoch = epoch(os.fstat(fd))
        assert written_epoch == epoch(dst.lstat()) and written_epoch[3] == 1
        assert epoch(os.fstat(src['fd'])) == src['epoch'] == epoch(Path(src['path']).lstat())
        directory_barrier(Path(src['path']).parent)
        directory_barrier(dst.parent)
    finally:
        os.close(fd)
    target = pin(dst)
    assert target['epoch'] == written_epoch
    digest(target, expected)
    parent_fd = os.open(dst.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return target


def owner(pid):
    values = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
    ids = dict(line.split(':', 1) for line in Path('/proc', str(pid), 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'startticks': int(values[19]),
            'uid': int(ids['Uid'].split()[0]), 'gid': int(ids['Gid'].split()[0]),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def command(argv):
    clock()
    ordinal = len(commands)
    paths = {channel: OUTPUT / ('command%02d.%s.raw' % (ordinal, channel)) for channel in ('stdout', 'stderr')}
    streams = {name: path.open('xb') for name, path in paths.items()}
    child = None
    selector = selectors.DefaultSelector()
    counts = {'stdout': 0, 'stderr': 0}
    errors = []
    record = {'argv': argv, 'owner': None, 'timed_out': False, 'capture_exceeded': False}
    try:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        record['owner'] = owner(child.pid)
        write('command%02d.launch.v1.json' % ordinal, record)
        for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map() or child.poll() is None:
            clock()
            for key, _ in selector.select(.1):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                remaining = MAX_CHANNEL - counts[key.data]
                if len(block) > remaining:
                    record['capture_exceeded'] = True
                    raise RuntimeError('original setup command channel cap')
                streams[key.data].write(block)
                counts[key.data] += len(block)
        child.wait(timeout=max(.001, DEADLINE-time.monotonic()))
    except BaseException as exc:
        record['timed_out'] = isinstance(exc, TimeoutError)
        errors.append(failure(exc))
    finally:
        # One original absolute cleanup deadline, never a fresh grace after
        # each action. Even launch-persistence/owner failure contains the child.
        cleanup_deadline = min(HARD_DEADLINE, time.monotonic()+10)
        if child is not None:
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                pass
            else:
                if not errors:
                    errors.append(failure(RuntimeError('original setup command left a process group')))
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=max(.001, cleanup_deadline-time.monotonic()))
            except BaseException as exc:
                errors.append(failure(exc))
        selector.close()
        for pipe in (() if child is None else (child.stdout, child.stderr)):
            try:
                pipe.close()
            except BaseException as exc:
                errors.append(failure(exc))
        for stream in streams.values():
            try:
                hard_clock()
                stream.flush()
                os.fsync(stream.fileno())
                hard_clock()
            except BaseException as exc:
                errors.append(failure(exc))
            finally:
                stream.close()
        record['returncode'] = None if child is None else child.returncode
        record['errors'] = errors
        if child is not None:
            record['original_pid_absent'] = not Path('/proc', str(child.pid)).exists()
            try:
                os.killpg(child.pid, 0)
                record['original_group_absent'] = False
            except ProcessLookupError:
                record['original_group_absent'] = True
        record['channels'] = {name: {'path': str(path), 'size_bytes': path.stat().st_size,
                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in paths.items()}
        commands.append(record)
        write('command%02d.terminal.v1.json' % ordinal, record)
    assert not errors and record['returncode'] == 0 and record.get('original_group_absent') is True
    return record


def original_source_head():
    record = command(['/usr/bin/git', '-c', 'core.longpaths=true', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
                      '--work-tree='+str(SOURCE), 'rev-parse', 'HEAD'])
    raw = Path(record['channels']['stdout']['path']).read_bytes()
    assert raw == (COMMIT+'\n').encode('ascii'), 'original source commit drift'


try:
    inventory_raw = read_plan(INVENTORY, INVENTORY_SHA)
    classification_raw = read_plan(CLASSIFICATION, CLASSIFICATION_SHA)
    inventory, classification = json.loads(inventory_raw), json.loads(classification_raw)
    inputs = inventory['copy_inputs']
    tracked = {row['path'] for row in classification['tracked_inputs']}
    assert len(inputs) == 2693 and sum(row['size_bytes'] for row in inputs) == 4379009017
    assert len(tracked) == 189 and classification['untracked_input_count'] == 2504
    write('dispatch.v1.json', {'source_commit': COMMIT, 'planning_commit': PLANNING,
          'controller': owner(os.getpid()), 'target': str(TARGET), 'inventory_sha256': INVENTORY_SHA,
          'classification_sha256': CLASSIFICATION_SHA, 'timeout_s': 600, 'cleanup_s': 10,
          'available_bytes': available_bytes, 'source_root_identity': source_identity,
          'target_parent_identity': target_parent_identity, 'fd_budget': fd_budget,
          'accepted': False, 'publication_ready': False})
    original_source_head()
    command(['/usr/bin/git', '-c', 'core.longpaths=true', '-C', str(COMMON), 'merge-base', '--is-ancestor', PLANNING, COMMIT])
    command(['/usr/bin/git', '-c', 'core.longpaths=true', '-c', 'core.hooksPath=/dev/null', 'clone', '--shared', '--no-checkout', str(COMMON), str(TARGET)])
    assert TARGET.stat().st_uid == os.getuid()
    os.chmod(TARGET, 0o700)
    target_identity = canonical_directory(TARGET)
    assert TARGET.stat().st_dev == TARGET.parent.stat().st_dev
    alternates_path = TARGET / '.git/objects/info/alternates'
    alternates_raw = alternates_path.read_bytes()
    assert alternates_raw == (str(COMMON / '.git/objects')+'\n').encode('ascii')
    write('shared-object-dependency.v1.json', {'path': str(alternates_path),
          'size_bytes': len(alternates_raw), 'sha256': hashlib.sha256(alternates_raw).hexdigest(),
          'alternate_object_root': str(COMMON / '.git/objects'),
          'limitation': 'This clone retains an original common Git object database dependency; no independent full-history copy is claimed.'})
    command(['/usr/bin/git', '-c', 'core.longpaths=true', '-C', str(TARGET), 'config', '--local', 'core.autocrlf', 'false'])
    command(['/usr/bin/git', '-c', 'core.longpaths=true', '-c', 'core.hooksPath=/dev/null', '-C', str(TARGET), 'checkout', '--detach', COMMIT])
    assert canonical_directory(TARGET) == target_identity
    tracked_record = command(['/usr/bin/git', '-c', 'core.longpaths=true', '-C', str(TARGET), 'ls-tree', '-r', '-z', COMMIT])
    tracked_raw = Path(tracked_record['channels']['stdout']['path']).read_bytes()
    assert tracked_raw.endswith(b'\0')
    tracked_objects = {}
    for entry in tracked_raw[:-1].split(b'\0'):
        declaration, raw_path = entry.split(b'\t', 1)
        mode, kind, object_sha = declaration.decode('ascii').split()
        relative = raw_path.decode('utf-8')
        assert kind == 'blob' and mode in ('100644', '100755')
        assert len(object_sha) == 40 and all(c in '0123456789abcdef' for c in object_sha)
        assert relative not in tracked_objects
        tracked_objects[relative] = {'mode': mode, 'object': object_sha}
    assert tracked.issubset(tracked_objects)
    initial_namespace = namespace_files(TARGET, set(tracked_objects))
    write('initial-namespace.v1.json', initial_namespace)
    tracked_before, tracked_mismatches = tracked_snapshot(TARGET, tracked_objects)
    write('initial-tracked-raw.v1.json', {'source_commit': COMMIT, 'files': tracked_before,
          'mismatches': tracked_mismatches, 'eol_normalization_accepted': False})
    assert not tracked_mismatches, 'fresh tracked raw bytes differ from exact Git blobs'
    for expected in inputs:
        clock()
        assert canonical_directory(SOURCE) == source_identity
        assert canonical_directory(TARGET) == target_identity
        assert canonical_directory(TARGET.parent) == target_parent_identity
        src = pin(path_for(SOURCE, expected['path']), expected)
        dst = path_for(TARGET, expected['path'], create_parents=True)
        if expected['path'] in tracked:
            assert os.path.lexists(dst), 'expected tracked target is missing'
            target = pin(dst)
            digest(src, expected)
            digest(target, expected)
            retained.append({'descriptor': {k: expected[k] for k in ('path', 'size_bytes', 'sha256')},
                             'source_epoch': src['epoch'], 'target_epoch': target['epoch']})
            continue
        target = copy_original(src, dst, expected)
        copied.append({'descriptor': {k: expected[k] for k in ('path', 'size_bytes', 'sha256')},
                       'source_epoch': src['epoch'], 'target_epoch': target['epoch']})
    assert len(copied) == 2504 and len(retained) == 189
    final_namespace = namespace_files(TARGET, set(tracked_objects) | {row['path'] for row in inputs})
    write('final-namespace.v1.json', final_namespace)
    tracked_after, tracked_mismatches = tracked_snapshot(TARGET, tracked_objects)
    write('final-tracked-raw.v1.json', {'source_commit': COMMIT, 'files': tracked_after,
          'mismatches': tracked_mismatches, 'before_after_equal': tracked_before == tracked_after,
          'eol_normalization_accepted': False})
    assert not tracked_mismatches and tracked_before == tracked_after, 'fresh tracked raw identity drift'
    # Full original source and new target byte checks under the still-held FDs.
    indexed = {row['path']: row for row in inputs}
    for row in held:
        if 'metadata_descriptor' in row:
            digest(row, row['metadata_descriptor'])
            continue
        root = SOURCE if Path(row['path']).is_relative_to(SOURCE) else TARGET
        digest(row, indexed[Path(row['path']).relative_to(root).as_posix()])
    assert canonical_directory(SOURCE) == source_identity
    assert canonical_directory(TARGET) == target_identity
    assert canonical_directory(TARGET.parent) == target_parent_identity
    assert {suffix: sum(1 for p in (TARGET/'models').rglob('*')
                       if p.is_file() and not p.is_symlink() and p.suffix.lower() == suffix)
            for suffix in ('.onnx', '.xml', '.bin', '.engine', '.plan')} == {
                '.onnx': 4, '.xml': 8, '.bin': 8, '.engine': 4, '.plan': 0}
    original_source_head()
    clock()
except BaseException as exc:
    primary = failure(exc)
finally:
    for row in held:
        try:
            os.close(row['fd'])
            hard_clock()
        except BaseException as exc:
            cleanup_errors.append(failure(exc))
    for row in directory_pins.values():
        try:
            os.close(row['fd'])
            hard_clock()
        except BaseException as exc:
            cleanup_errors.append(failure(exc))
    report = {'source_commit': COMMIT, 'planning_commit': PLANNING, 'target': str(TARGET),
              'elapsed_s': time.monotonic()-START, 'primary_error': primary, 'cleanup_errors': cleanup_errors,
              'cleanup_absolute_limit_s': 610, 'fd_budget': fd_budget,
              'commands': commands, 'copied': copied, 'retained_tracked': retained,
              'accepted': False, 'publication_ready': False, 'model_gpu_native_acceptance': False,
              'status': 'prepared' if primary is None and not cleanup_errors else 'failed',
              'shared_git_object_dependency': str(COMMON / '.git/objects'),
              'new_host_closure_required': True, 'new_project_bind_reachability_unverified': True}
    write('execution.v1.json', report)
    if time.monotonic() >= DEADLINE and primary is None:
        primary = failure(TimeoutError('original setup600s deadline after receipt publication'))
        write('late-failure.v1.json', {'primary_error': primary, 'status': 'failed',
              'elapsed_s': time.monotonic()-START, 'accepted': False, 'publication_ready': False})
    print(json.dumps({'status': 'failed' if primary is not None or cleanup_errors else 'prepared',
                     'elapsed_s': time.monotonic()-START, 'primary_error': primary, 'target': str(TARGET)}), flush=True)
sys.exit(0 if primary is None and not cleanup_errors else 78)
