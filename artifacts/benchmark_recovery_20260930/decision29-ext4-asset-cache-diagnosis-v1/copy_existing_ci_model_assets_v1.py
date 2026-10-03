"""Setup-only exclusive raw copies; the unchanged CI verifier remains mandatory.

Required outer containment: 120 seconds plus 10 seconds teardown. This helper
does not invoke CI, a model, a network client, Git, Docker or a kernel policy.
Failed partial destination files are retained, never repaired or replaced.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
TABLE_SHA256 = 'c99b1402c4c909cb0a47421b0a0d2f872cc932e26ee99de76c9539f192684f3b'
DONOR = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
TARGET = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
NAMESPACE_BYTES = 24 * 1024 * 1024
START = time.monotonic()
FDS = []
DIRECTORIES = {}
INPUTS = []

def clock():
    if time.monotonic() - START >= 120:
        raise TimeoutError('original setup-copy 120-second deadline exceeded')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]

def identity(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]

def directories(path, *, create=False):
    """Hold each named physical ancestor; sibling creation changes no identity."""
    require(path.is_absolute() and '..' not in path.parts, 'noncanonical absolute directory')
    current = Path('/')
    if current not in DIRECTORIES:
        fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        FDS.append(fd)
        DIRECTORIES[current] = (fd, identity(os.fstat(fd)))
    for component in path.parts[1:]:
        clock()
        parent_fd = DIRECTORIES[current][0]
        current = current / component
        if current not in DIRECTORIES:
            if create:
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent_fd)
            FDS.append(fd)
            expected = identity(os.fstat(fd))
            require(expected == identity(os.stat(component, dir_fd=parent_fd, follow_symlinks=False)),
                    'directory name does not bind original descriptor')
            DIRECTORIES[current] = (fd, expected)
    return DIRECTORIES[path][0]

def directory_barrier():
    for path, (fd, expected) in DIRECTORIES.items():
        clock()
        require(identity(os.fstat(fd)) == expected == identity(path.lstat()),
                'physical ancestor changed or became an alias')

def open_input(path, maximum, *, expected_epoch=None):
    parent_fd = directories(path.parent)
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                 dir_fd=parent_fd)
    FDS.append(fd)
    observed = epoch(os.fstat(fd))
    INPUTS.append((fd, path, observed))
    require(stat.S_ISREG(observed[2]) and observed[3] == 1 and 0 < observed[4] <= maximum,
            'input is not bounded regular single-link bytes')
    require(observed == epoch(path.lstat()), 'input name does not bind original descriptor')
    require(expected_epoch is None or observed == expected_epoch,
            'donor source differs from genuine collected seven-field epoch')
    return fd, observed

def digest(fd, maximum, *, retain=False):
    os.lseek(fd, 0, os.SEEK_SET)
    hashes = {name: hashlib.new(name) for name in ('sha256', 'sha384')}
    blocks, size = [], 0
    while True:
        clock()
        block = os.read(fd, min(65536, maximum - size + 1))
        if not block:
            break
        size += len(block)
        require(size <= maximum, 'file exceeds its exact byte cap')
        for value in hashes.values():
            value.update(block)
        if retain:
            blocks.append(block)
    return {'size_bytes': size, **{name: value.hexdigest() for name, value in hashes.items()}}, b''.join(blocks)

def input_barrier():
    directory_barrier()
    for fd, path, expected in INPUTS:
        clock()
        require(epoch(os.fstat(fd)) == expected == epoch(path.lstat()),
                'declared input changed or was replaced')

def save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    require(len(raw) <= 65536, 'copy observation exceeds 64KiB metadata cap')
    local_fds = []
    first_error = None
    try:
        parent = Path('/')
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        local_fds.append(directory_fd)
        held_directories = [(directory_fd, parent, identity(os.fstat(directory_fd)))]
        for component in path.parent.parts[1:]:
            parent = parent / component
            directory_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                os.O_CLOEXEC, dir_fd=directory_fd)
            local_fds.append(directory_fd)
            observed = identity(os.fstat(directory_fd))
            require(observed == identity(parent.lstat()), 'observation parent became an alias')
            if parent in DIRECTORIES:
                require(observed == DIRECTORIES[parent][1], 'original observation ancestor was replaced')
            held_directories.append((directory_fd, parent, observed))
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o400, dir_fd=directory_fd)
        local_fds.append(fd)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        require(os.fstat(fd).st_nlink == 1, 'observation became an alias')
        os.fsync(directory_fd)
        for directory, name, expected in held_directories:
            require(identity(os.fstat(directory)) == expected == identity(name.lstat()),
                    'observation directory changed during persistence')
    except BaseException as caught:
        first_error = caught
    finally:
        for descriptor in reversed(local_fds):
            try:
                os.close(descriptor)
            except OSError as caught:
                if first_error is None:
                    first_error = caught
    if first_error is not None:
        raise first_error
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--target-root', required=True, type=Path)
parser.add_argument('--expected-commit', required=True)
parser.add_argument('--output-dir', required=True, type=Path)
args = parser.parse_args()
fd_before = len(os.listdir('/proc/self/fd'))
output_owned = False
primary = None
close_errors = []
copied = []
facts = {}
try:
    require(os.getuid() == os.getgid() == 1000, 'expected original unprivileged UID/GID1000')
    require(re.fullmatch('[0-9a-f]{40}', args.expected_commit) is not None, 'exact commit is required')
    require(args.target_root == TARGET and args.expected_commit == COMMIT,
            'copy is bound only to the original D successor and reviewed exact commit')
    for path in (args.target_root, args.output_dir):
        require(path.is_absolute() and path == Path(os.path.normpath(path)), 'noncanonical caller path')
    table_fd, _ = open_input(HERE / 'inventory.v1.json', 65536)
    table_fact, raw = digest(table_fd, 65536, retain=True)
    require(table_fact['sha256'] == TABLE_SHA256, 'immutable exact-eight table bytes changed')
    table = json.loads(raw)
    require(table['error'] is None and table['asset_count'] == 8 and table['donor'] == str(DONOR),
            'original donor inspection did not complete')
    previous_roots = {Path(row['root']) for row in table['presence_only_old_ci_roots']}
    require(args.target_root not in previous_roots and
            args.target_root.parent == Path('/home/s-a-balashov/work') and
            args.target_root.name.startswith('vast-current-source-ci-'),
            'target must be a new CI successor, never a retained original root')
    require(not any(args.output_dir.is_relative_to(root) for root in previous_roots | {args.target_root}),
            'observation output must be outside every original and successor checkout')
    directories(DONOR)
    directories(args.target_root)
    require(args.target_root.lstat().st_uid == args.target_root.lstat().st_gid == 1000,
            'successor checkout is not owned by original unprivileged principal')
    head_fd, _ = open_input(args.target_root / '.git/HEAD', 64)
    _, head = digest(head_fd, 64, retain=True)
    require(head == (args.expected_commit + '\n').encode(), 'successor is not detached at exact supplied commit')
    current_source = []
    for pin in table['source_pins'][:4]:
        relative = Path(pin['path']).relative_to(Path(table['canonical_failed_checkout']))
        fd, observed = open_input(args.target_root / relative, 65536)
        fact, _ = digest(fd, 65536)
        require(fact['size_bytes'] == pin['size_bytes'] and fact['sha256'] == pin['sha256'],
                'successor stock verifier, runner or fixed metadata bytes differ')
        current_source.append({'path': str(args.target_root / relative), **fact, 'epoch': observed})
    rows = table['assets']
    require(len(rows) == 8 and {row['index'] for row in rows} == set(range(8)), 'exact-eight index domain differs')
    require(sum(row['expected_size_bytes'] for row in rows) == table['asset_bytes'] <= NAMESPACE_BYTES,
            'exact copy namespace exceeds original24MiB cap')
    held_assets = []
    for row in rows:
        relative = Path(row['destination_relative'])
        require(not relative.is_absolute() and '..' not in relative.parts and
                relative.parts[:4] == ('models', 'openvino', 'public', 'intel'), 'foreign destination')
        require(Path(row['source']['path']) == DONOR / relative, 'foreign donor source')
        fd, observed = open_input(DONOR / relative, row['expected_size_bytes'], expected_epoch=row['source']['epoch'])
        fact, _ = digest(fd, row['expected_size_bytes'])
        require(fact == {key: row['source'][key] for key in ('size_bytes', 'sha256', 'sha384')},
                'donor raw size/SHA256/SHA384 no longer matches genuine table')
        held_assets.append((row, fd, observed))
    input_barrier()
    directories(args.output_dir.parent)
    os.mkdir(args.output_dir, 0o700)
    output_owned = True
    directories(args.output_dir)
    save(args.output_dir / 'dispatch.v1.json', {'argv': sys.argv, 'pid': os.getpid(),
        'pgid': os.getpgrp(), 'uid': os.getuid(), 'gid': os.getgid(),
        'original_proc_stat': Path('/proc/self/stat').read_text(),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'work_seconds': 120, 'external_teardown_seconds': 10, 'table_sha256': TABLE_SHA256})
    for row, source_fd, original_epoch in held_assets:
        input_barrier()
        destination = args.target_root / row['destination_relative']
        parent_fd = directories(destination.parent, create=True)
        destination_fd = os.open(destination.name, os.O_RDWR | os.O_CREAT | os.O_EXCL |
            os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=parent_fd)
        FDS.append(destination_fd)  # Register before any assertion or metadata observation.
        record = {'index': row['index'], 'source': row['source'], 'destination': str(destination),
                  'status': 'partial', 'written_bytes': 0, 'destination_epoch': None}
        copied.append(record)
        require(stat.S_ISREG(os.fstat(destination_fd).st_mode) and os.fstat(destination_fd).st_nlink == 1,
                'exclusive destination is not regular single-link bytes')
        os.lseek(source_fd, 0, os.SEEK_SET)
        while record['written_bytes'] < row['expected_size_bytes']:
            clock()
            block = os.read(source_fd, min(65536, row['expected_size_bytes'] - record['written_bytes']))
            require(bool(block), 'source became short while copying')
            offset = 0
            while offset < len(block):
                clock()
                size = os.write(destination_fd, block[offset:])
                require(size > 0, 'destination write made no progress')
                offset += size
                record['written_bytes'] += size
        require(os.read(source_fd, 1) == b'', 'source grew beyond its exact cap')
        os.fsync(destination_fd)
        os.fchmod(destination_fd, 0o444)
        final_epoch = epoch(os.fstat(destination_fd))
        require(final_epoch[3] == 1 and final_epoch == epoch(destination.lstat()),
                'new destination name was replaced or linked')
        fact, _ = digest(destination_fd, row['expected_size_bytes'])
        require(fact == {key: row['source'][key] for key in ('size_bytes', 'sha256', 'sha384')},
                'new destination differs from exact original bytes')
        require(final_epoch == epoch(os.fstat(destination_fd)) == epoch(destination.lstat()),
                'destination drifted during raw verification')
        source_fact, _ = digest(source_fd, row['expected_size_bytes'])
        require(source_fact == fact and original_epoch == epoch(os.fstat(source_fd)) ==
                epoch(Path(row['source']['path']).lstat()), 'original donor changed')
        os.fsync(parent_fd)
        record.update({'status': 'copied_exact_bytes', 'destination_epoch': final_epoch, **fact})
    input_barrier()
    for record in copied:
        require(record['destination_epoch'] == epoch(Path(record['destination']).lstat()),
                'copied destination was replaced before completion')
    facts = {'source_commit': args.expected_commit, 'target_root': str(args.target_root),
        'source_pins': current_source, 'asset_count': len(copied),
        'asset_bytes': sum(row['written_bytes'] for row in copied), 'table_sha256': TABLE_SHA256,
        'network_executed': False, 'model_inference_executed': False, 'ci_executed': False,
        'requires_unchanged_stock_ci_eight_existing_verifier': True, 'hardware_acceptance': False}
except BaseException as caught:
    primary = {'type': type(caught).__name__, 'message': str(caught)[:2048]}
finally:
    for fd in reversed(FDS):
        try:
            os.close(fd)
        except OSError as caught:
            close_errors.append({'fd': fd, 'errno': caught.errno})
    if primary is None and close_errors:
        primary = {'type': 'CloseError', 'message': 'original handles did not all close'}
    fd_after = len(os.listdir('/proc/self/fd'))
    if primary is None and fd_after != fd_before:
        primary = {'type': 'HandleLeak', 'message': 'original descriptor count did not return'}
    result = {'status': 'setup_complete' if primary is None else 'failed', 'error': primary,
        'facts': facts, 'assets': copied, 'close_errors': close_errors,
        'fd_before': fd_before, 'fd_after': fd_after, 'all_handles_released': not close_errors and fd_after == fd_before,
        'elapsed_s': time.monotonic() - START, 'original_ci_accepted': False}
    if output_owned:
        try:
            save(args.output_dir / 'execution.v1.json', result)
        except BaseException as caught:
            if primary is None:
                primary = {'type': type(caught).__name__, 'message': str(caught)[:2048]}
    final_elapsed = time.monotonic() - START
    if final_elapsed >= 120:
        late = {'status': 'failed', 'type': 'FinalDeadlineExceeded', 'elapsed_s': final_elapsed,
                'first_error': primary, 'original_execution_retained': output_owned}
        if output_owned:
            try:
                save(args.output_dir / 'late-failure.v1.json', late)
            except BaseException as caught:
                late['persistence_error'] = {'type': type(caught).__name__, 'message': str(caught)[:2048]}
        if primary is None:
            primary = {'type': late['type'], 'message': '120-second acceptance bound exceeded after final persistence'}
    print(json.dumps({'status': 'setup_complete' if primary is None else 'failed',
        'error': primary, 'elapsed_s': final_elapsed, 'output_owned': output_owned}))
raise SystemExit(0 if primary is None else 78)
