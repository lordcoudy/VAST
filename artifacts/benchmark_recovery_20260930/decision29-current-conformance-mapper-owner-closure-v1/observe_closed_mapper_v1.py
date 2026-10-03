"""Finite postterminal mapper metadata/proc observation; no mapper replay.

Also records the actual root-owned umount binary for future cleanup binding.
It never invokes that binary or any target/engine/test/contract.
"""
import hashlib
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930')
HERE = BASE / 'decision29-current-conformance-mapper-owner-closure-v1'
OUT = HERE / 'original-observation-attempt01'
MAPPER = BASE / 'decision29-current-conformance-preparation-v1/attempt01'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
START = time.monotonic()
END = START + 20
held, ancestors, closes = [], {}, []
first, owned, facts = None, False, {}


def deadline():
    if time.monotonic() >= END:
        raise TimeoutError('original20s mapper owner metadata observation')


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def ident(s):
    return (s.st_dev, s.st_ino, s.st_mode)


def digest(fd, size):
    chunks, offset = [], 0
    value = hashlib.sha256()
    while offset < size:
        deadline()
        block = os.pread(fd, min(65536, size - offset), offset)
        assert block, 'bounded held leaf ended early'
        chunks.append(block)
        value.update(block)
        offset += len(block)
    assert not os.pread(fd, 1, size)
    return b''.join(chunks), value.hexdigest()


def pin(path, size=None, sha=None, limit=2097152):
    deadline()
    parent, cursor = None, Path('/')
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
    assert stat.S_ISREG(prior.st_mode) and prior.st_nlink == 1 and 0 <= prior.st_size <= limit
    assert epoch(prior) == epoch(os.lstat(path))
    if size is not None:
        assert prior.st_size == size
    data, actual = digest(fd, prior.st_size)
    if sha is not None:
        assert actual == sha
    assert epoch(prior) == epoch(os.fstat(fd)) == epoch(os.lstat(path))
    row = {'path': str(path), 'size_bytes': prior.st_size, 'sha256': actual, 'epoch7': epoch(prior), 'uid': prior.st_uid, 'gid': prior.st_gid}
    held[-1] = (path, fd, row)
    return data, row, fd


def owner(pid):
    p = Path('/proc') / str(pid)
    values = (p / 'stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19]), 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def scan():
    matches, errors = [], []
    for path in Path('/proc').iterdir():
        deadline()
        if not path.name.isdigit():
            continue
        try:
            values = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(path.name) in (11033, 11034) or int(values[2]) == 11033:
                matches.append(owner(int(path.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError, UnicodeError) as exc:
            errors.append({'pid': int(path.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_monotonic_ns': time.monotonic_ns(), 'current_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'original_PID_paths_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in (11033, 11034)}, 'known_original_PGID': 11033, 'original_session': None, 'original_birth': None, 'matched_original_PID_or_known_PGID_members': matches, 'errors': errors}


def save(name, value):
    with (OUT / name).open('xb') as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
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
    data, terminal_pin, _ = pin(MAPPER / 'terminal.v1.json', 1419, 'ffa350ef8061a69a12bd019a5a5c5e41b15b74ba8a4f8000bc5d665da1ec3d52')
    terminal = json.loads(data)
    assert terminal['source_commit'] == COMMIT and terminal['status'] == 'metadata_preparation_complete_not_acceptance'
    assert terminal['original_pid'] == 11034 and terminal['original_ppid'] == terminal['original_pgid'] == 11033
    assert terminal['FD_holds_released'] is True and not terminal['close_errors'] and terminal['first_failure'] is None and terminal['fd_before'] == terminal['fd_after'] == 6
    assert terminal['conformance_accepted'] is False and terminal['archive_complete'] is False
    data, custody_pin, _ = pin(MAPPER / 'input-custody.v1.json', 145106, 'ae767c3fcfa51a31efecae0b3b8c56008362344832ea21d29c0258cac9111028')
    custody = json.loads(data)
    assert custody['FD_holds_released'] is True and not custody['close_errors'] and custody['fd_before'] == custody['fd_after'] == 6
    assert custody['leaf_fullSHA_and_seven_epochs_rechecked'] is True and terminal['outputs']['inventory']['sha256'] == custody_pin['sha256']
    # Real binary metadata only. No --help/parser test or umount execution.
    _, umount_pin, umount_fd = pin(Path('/usr/bin/umount'))
    binary = os.fstat(umount_fd)
    assert binary.st_uid == binary.st_gid == 0 and binary.st_mode & 0o111 and not binary.st_mode & 0o022
    late = MAPPER / 'persistence-or-late-failure.v1.json'
    assert not os.path.lexists(late)
    scans = [scan(), scan()]
    assert all(not s['errors'] and not s['matched_original_PID_or_known_PGID_members'] and all(s['original_PID_paths_absent'].values()) and s['current_boot_id'] == BOOT for s in scans)
    assert not os.path.lexists(late)
    for path, fd, row in held:
        assert row is not None and epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
        _, actual = digest(fd, row['size_bytes'])
        assert actual == row['sha256'] and epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
    for path, (fd, before) in ancestors.items():
        assert ident(os.fstat(fd)) == ident(before) == ident(os.lstat(path))
    facts = {'terminal': terminal_pin, 'input_custody': custody_pin, 'original_terminal_outputs_not_reduced_or_replayed': terminal['outputs'], 'mapper_PID_actual': 11034, 'mapper_PPID_PGID_actual': 11033, 'mapper_birth_session_UID_GID_boot_not_recorded': True, 'two_fresh_actual_process_scans': scans, 'late_companion_absent': True, 'late_companion_path': str(late), 'umount_executable_actual_full_SHA_and_seven_epochs': umount_pin, 'original_mapper_FD_before_after': [terminal['fd_before'], terminal['fd_after']], 'original_input_leaf_count': len(custody['files']), 'original_input_aggregate_bytes': custody['aggregate_bytes_read'], 'original_ancestor_count': custody['ancestor_count']}
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
result = {'schema_version': 1, 'kind': 'actual_current_conformance_mapper_owner_late_closure_v1', 'status': 'verified' if first is None and not closes and fd_before == fd_after else 'failed', 'source_commit_D': COMMIT, 'facts': facts, 'observer': controller, 'first_error': first, 'close_errors': closes, 'all_observer_handles_released': not closes, 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START, 'original_mapper_tool_completion': {'terminal_cell': 'a0fdba', 'returncode': 0, 'tool_elapsed_s': 2.404, 'basis': 'Parent genuine original completion notification'}, 'no_mapper_CI_contract_test_engine_model_replay': True, 'conformance_acceptance': False, 'archive_complete': False, 'hardware_acceptance': False, 'limits': ['Mapper11034/parent11033 original birth/session/UID/GID/boot were not recorded; no fields retroactively inferred.', 'Fresh absence covers mapper/parent PID paths and observed PGID11033 only; no original-session or global descendant claim.', 'Only terminal and input-custody metadata bodies are read; original mapping/body/test evidence is not rerun or semantically accepted.', 'Live observer retains its own actual owner/parent for later parent closure.']}
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
