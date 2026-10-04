"""One bounded original V6 capture; review this separate source before dispatch.

This tool owns its CPython child and raw logs. Docker cleanup remains an inner
controller fact. A failed prefix never authorizes retry or research promotion.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import time

PYTHON = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
PLANNING = '3aa35c3b2eedc05d22cf16ba37d470143d080f6b'
PHYSICAL = '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec'
RECOVERY = 'artifacts/benchmark_recovery_20260930'
RUNTIME = RECOVERY + '/decoder-research-implementation-v6/'
OBSERVER = RECOVERY + '/decoder-independent-v6/cold_reader.py'
CHANNEL = 1024 * 1024
PLANNING_FILES = {
    'proposal.md': (2948, 'e77529520f6467d9deca20fcfe1a891f13c6a882cbf74f36ec948c8a3edcd177'),
    'design.md': (28405, '814a9593f53854195f5eba408a7f737f7b51b9fd7665ef142ea8e9e559d786a6'),
    'tasks.md': (10948, '73f0c1ee5acd1e105a681a0dfbd80e76e50cd522e6a6894f4518799fc9daeb92'),
    'specs/benchmark-launch-preparation/spec.md': (15625, '7aac212b3904bc1b42eb8a93f72e03c28503a8bee8c5f2ef4989aadf8a7ec64e'),
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


def close_fd(fd, primary=None):
    """Attempt retirement once without replacing an already observed cause."""
    try:
        os.close(fd)
    except BaseException as exc:
        if primary is None:
            raise
        text = 'owned FD retirement: ' + type(exc).__name__ + ': ' + str(exc)
        primary.add_note(text)
        primary.original_capture_cleanup_errors = [
            *getattr(primary, 'original_capture_cleanup_errors', []), text]


def bounded_read(path, limit=CHANNEL):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    primary = None
    try:
        chunks, count = [], 0
        while True:
            raw = os.read(fd, min(65536, limit + 1 - count))
            if not raw:
                return b''.join(chunks)
            chunks.append(raw)
            count += len(raw)
            require(count <= limit, 'bounded original read exceeded cap: ' + str(path))
    except BaseException as exc:
        primary = exc
        raise
    finally:
        close_fd(fd, primary)


def owner(pid):
    suffix = bounded_read(f'/proc/{pid}/stat').decode().rsplit(')', 1)[1].split()
    rows = bounded_read(f'/proc/{pid}/status').decode().splitlines()
    fields = {row.split(':', 1)[0]: row.split()[1:] for row in rows if ':' in row}
    return {'pid': pid, 'ppid': int(suffix[1]), 'starttime_ticks': int(suffix[19]),
            'uid': int(fields['Uid'][0]), 'gid': int(fields['Gid'][0]),
            'boot_id': bounded_read('/proc/sys/kernel/random/boot_id', 128).decode().strip(),
            'process_group_id': os.getpgid(pid), 'session_id': os.getsid(pid)}


def descriptor(path, limit=CHANNEL):
    raw = bounded_read(path, limit)
    return {'path': str(path), 'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def write_all(fd, raw):
    view = memoryview(raw)
    while view:
        count = os.write(fd, view)
        require(count > 0, 'original write made no progress')
        view = view[count:]


def document(path, value):
    raw = canonical(dict(value, sha256=hashlib.sha256(canonical(value)).hexdigest())) + b'\n'
    require(len(raw) <= 65536, 'external original metadata64KiB cap')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    primary = None
    try:
        write_all(fd, raw)
        os.fsync(fd)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        close_fd(fd, primary)
    return descriptor(path, 65536)


def capture(argv, deadline, limits, executable_fd=None, output_fds=None,
            on_start=None, canceled=None):
    """Drain both original pipes with streaming admission, then close/reap.

    Failure containment uses at most15s total and signals only the positively
    observed exact child. It grants no extra successful operation time.
    """
    process = None
    child = None
    streams = {}
    saved = {'stdout': bytearray(), 'stderr': bytearray()}
    eof = {'stdout': False, 'stderr': False}
    counts = {'stdout': 0, 'stderr': 0}
    digests = {'stdout': hashlib.sha256(), 'stderr': hashlib.sha256()}
    failures, close_errors, exceeded = [], [], []
    containment = None
    timed_out = False
    began = time.monotonic()
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            executable=None if executable_fd is None else f'/proc/self/fd/{executable_fd}',
            pass_fds=() if executable_fd is None else (executable_fd,))
        # Register pipe ownership before any fallible owner/callback observation.
        streams = {'stdout': process.stdout, 'stderr': process.stderr}
        child = owner(process.pid)
        require(child['ppid'] == os.getpid() and child['process_group_id'] == process.pid
                and child['session_id'] == process.pid, 'original child custody mismatch')
        if on_start is not None:
            on_start(child)
        for stream in streams.values():
            os.set_blocking(stream.fileno(), False)
        while not all(eof.values()) or process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                raise RuntimeError('original operation deadline exceeded')
            require(canceled is None or not canceled(), 'original operation signaled')
            pending = {stream.fileno(): name for name, stream in streams.items() if not eof[name]}
            ready = select.select(list(pending), [], [], min(0.05, deadline - time.monotonic()))[0]
            for fd in ready:
                name = pending[fd]
                remaining = limits[name] - counts[name]
                try:
                    raw = os.read(fd, min(65536, remaining + 1))
                except BlockingIOError:
                    continue
                if not raw:
                    eof[name] = True
                    continue
                retained = raw[:remaining]
                if retained:
                    if output_fds is None:
                        saved[name].extend(retained)
                    else:
                        write_all(output_fds[name], retained)
                    counts[name] += len(retained)
                    digests[name].update(retained)
                if len(raw) > remaining:
                    exceeded.append({'channel': name, 'retained_bytes': counts[name],
                                     'observed_unretained_bytes': len(raw) - remaining,
                                     'observed_unretained_sha256': hashlib.sha256(raw[remaining:]).hexdigest()})
                    raise RuntimeError('original streaming channel cap exceeded')
        require(process.returncode == 0, 'original child returned nonzero')
    except BaseException as exc:
        failures.append(type(exc).__name__ + ': ' + str(exc))
        close_errors.extend(getattr(exc, 'original_capture_cleanup_errors', []))
    finally:
        if process is not None and process.poll() is None:
            stop = time.monotonic()
            stop_deadline = stop + 15
            actions, errors = [], []
            try:
                current = owner(process.pid)
                require(child is not None and current == child,
                        'original child owner unavailable/changed; no signal')
                os.kill(process.pid, signal.SIGTERM)
                actions.append('SIGTERM exact original child PID')
                try:
                    process.wait(timeout=max(0.001, min(13, stop_deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    require(owner(process.pid) == child, 'original child owner changed before kill')
                    os.kill(process.pid, signal.SIGKILL)
                    actions.append('SIGKILL exact original child PID')
                    process.wait(timeout=max(0.001, stop_deadline - time.monotonic()))
            except BaseException as exc:
                errors.append(type(exc).__name__ + ': ' + str(exc))
                failures.append('original failed containment: ' + errors[-1])
                close_errors.extend(getattr(exc, 'original_capture_cleanup_errors', []))
            containment = {'started_monotonic_s': stop, 'finished_monotonic_s': time.monotonic(),
                           'actions': actions, 'errors': errors,
                           'returncode': process.returncode,
                           'scope': 'Exact direct-child failed containment only; no Docker/descendant quiescence claim'}
            if time.monotonic() > stop_deadline:
                failures.append('original failed containment15s exceeded')
        for name, stream in streams.items():
            try:
                stream.close()
            except BaseException as exc:
                close_errors.append(name + ': ' + type(exc).__name__ + ': ' + str(exc))
        if time.monotonic() >= deadline:
            timed_out = True
            if 'original operation final close deadline exceeded' not in failures:
                failures.append('original operation final close deadline exceeded')
    return {'argv': argv, 'original_child': child,
            'returncode': None if process is None else process.returncode,
            'stdout_bytes': bytes(saved['stdout']), 'stderr_bytes': bytes(saved['stderr']),
            'channels': {name: {'size_bytes': counts[name], 'sha256': digests[name].hexdigest()}
                         for name in counts}, 'log_eof': eof, 'close_errors': close_errors,
            'all_streams_closed': not close_errors and len(streams) == 2,
            'capture_exceeded': exceeded, 'timed_out': timed_out,
            'containment': containment, 'failures': failures,
            'elapsed_s': time.monotonic() - began}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--review-repository-root', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--mode', required=True, choices=('metadata-only', 'research'))
    parser.add_argument('--capture-source-sha256', required=True)
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.source_commit), 'exact reviewed source commit required')
    require(re.fullmatch('[0-9a-f]{64}', args.capture_source_sha256), 'exact reviewed capture hash required')
    require(sys.version_info[:3] == (3, 12, 3) and sys.executable == PYTHON
            and sys.flags.isolated == 1 and sys.dont_write_bytecode,
            'invoke only pinned CPython3.12.3 -I -B')
    root = Path(args.project_root).resolve(strict=True)
    review = Path(args.review_repository_root).resolve(strict=True)
    require(str(root) == PHYSICAL, 'frozen physical prerequisite root required')
    recovery = root / RECOVERY
    require(recovery.is_dir() and not recovery.is_symlink(), 'original recovery root unavailable')
    prefix = 'decoder-research-v6-clock-fixed-metadata-preflight' if args.mode == 'metadata-only' else 'decoder-research-v6-clock-fixed'
    attempt = recovery / (prefix + '-attempt-01')
    original_parent = recovery / (prefix + '-original-controller')
    require(not attempt.exists() and not original_parent.exists(), 'once-only namespace consumed; no resume/retry')
    began = time.monotonic()
    deadline = began + 600
    started_at = time.time_ns()
    original_parent.mkdir(mode=0o700)
    destination = original_parent / 'attempt-01'
    destination.mkdir(mode=0o700)
    held, directories, sources, observations = [], {}, [], []
    close_errors, failures, signals = [], [], []
    outputs = {}
    result = None
    dispatch = launch = argv = interpreter = None
    current_checkout = None
    sources_after = []
    all_rechecked = False
    signal.signal(signal.SIGTERM, lambda number, frame: signals.append(number))
    signal.signal(signal.SIGINT, lambda number, frame: signals.append(number))

    def alive_budget():
        require(time.monotonic() < deadline and not signals, 'original whole600s deadline/signal')

    def hold(path, expected=None):
        alive_budget()
        require(path.is_absolute() and not path.is_symlink(), 'original source actual absolute leaf required')
        for parent in reversed(path.parents):
            if parent not in directories:
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                directories[parent] = (fd, None)
                info = os.fstat(fd)
                directories[parent] = (fd, (info.st_dev, info.st_ino, info.st_mode))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and 0 < info.st_size <= 64 * CHANNEL, 'original source regular single-link64MiB bound')
            digest, count = hashlib.sha256(), 0
            while raw := os.pread(fd, 65536, count):
                alive_budget()
                digest.update(raw)
                count += len(raw)
                require(count <= info.st_size, 'original source grew during hash')
            require(count == info.st_size and epoch(info) == epoch(os.fstat(fd)) == epoch(path.lstat()),
                    'original source named/held epoch differs')
            row = {'descriptor': {'path': str(path), 'size_bytes': count, 'sha256': digest.hexdigest()},
                   'epoch': epoch(info)}
            if expected is not None:
                require((count, row['descriptor']['sha256']) == expected, 'original source differs from reviewed bytes')
            held.append((path, fd, row))
            return row, fd
        except BaseException as exc:
            close_fd(fd, exc)
            raise

    def verify():
        for path, fd, row in held:
            alive_budget()
            require(epoch(os.fstat(fd)) == row['epoch'] == epoch(path.lstat()), 'original source epoch changed')
            digest, count = hashlib.sha256(), 0
            while raw := os.pread(fd, 65536, count):
                alive_budget()
                digest.update(raw)
                count += len(raw)
                require(count <= row['descriptor']['size_bytes'], 'original source grew during final hash')
            require(count == row['descriptor']['size_bytes'] and digest.hexdigest() == row['descriptor']['sha256'],
                    'original source bytes changed')
        for path, (fd, identity) in directories.items():
            require(identity is not None, 'original ancestor observation unavailable')
            for info in (os.fstat(fd), path.lstat()):
                require((info.st_dev, info.st_ino, info.st_mode) == identity, 'original source ancestor changed')

    def git(tail, stdout_limit=CHANNEL, expected_rc=0):
        alive_budget()
        command = ['/usr/bin/git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
                   '-c', 'core.longpaths=true', '--no-replace-objects', '-C', str(review)] + tail
        value = capture(command, min(deadline, time.monotonic() + 5),
                        {'stdout': stdout_limit, 'stderr': 65536}, executable_fd=git_fd,
                        canceled=lambda: bool(signals))
        observations.append({key: value[key] for key in (
            'argv', 'original_child', 'returncode', 'channels', 'log_eof', 'close_errors',
            'all_streams_closed', 'capture_exceeded', 'timed_out', 'containment', 'failures', 'elapsed_s')})
        require(value['returncode'] == expected_rc and not value['failures'] and not value['close_errors']
                and all(value['log_eof'].values()) and value['stderr_bytes'] == b'',
                'original supported Git observation failed')
        return value['stdout_bytes']

    try:
        for channel in ('stdout', 'stderr'):
            outputs[channel] = os.open(destination / ('original.' + channel),
                                       os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        interpreter, python_fd = hold(Path(PYTHON).resolve(strict=True))
        _, git_fd = hold(Path('/usr/bin/git').resolve(strict=True))
        dispatch, _ = hold(Path(__file__).resolve(strict=True))
        require(dispatch['descriptor']['sha256'] == args.capture_source_sha256,
                'separately reviewed original capture source hash differs')
        require(git(['rev-parse', '--show-toplevel'], 4096).decode().rstrip('\n') == str(review),
                'actual review Git top-level differs')
        for commit in (PLANNING, args.source_commit):
            require(git(['rev-parse', '--verify', commit + '^{commit}'], 64) == commit.encode() + b'\n',
                    'reviewed exact commit unavailable')
        git(['merge-base', '--is-ancestor', PLANNING, args.source_commit], 64)
        current_checkout = git(['rev-parse', 'HEAD'], 64).decode().strip()
        require(re.fullmatch('[0-9a-f]{40}', current_checkout), 'current checkout not exact commit')
        git(['merge-base', '--is-ancestor', args.source_commit, current_checkout], 64)
        planning_total = 0
        for name, expected in PLANNING_FILES.items():
            relative = 'openspec/changes/fix-decoder-preflight/' + name
            size = git(['cat-file', '-s', PLANNING + ':' + relative], 64)
            require(size == str(expected[0]).encode() + b'\n', 'reviewed P raw blob size differs')
            raw = git(['cat-file', 'blob', PLANNING + ':' + relative])
            planning_total += len(raw)
            require(planning_total <= 4 * CHANNEL and (len(raw), hashlib.sha256(raw).hexdigest()) == expected,
                    'reviewed P raw blob bytes differ')
        for relative in [RUNTIME + name for name in ('controller.py', 'guest_consumer.py', 'research_protocol.py')] + [OBSERVER]:
            raw_size = git(['cat-file', '-s', args.source_commit + ':' + relative], 64)
            require(re.fullmatch(rb'[1-9][0-9]*\n', raw_size), 'S source blob size malformed')
            size = int(raw_size)
            require(size <= CHANNEL, 'S runtime/observer source1MiB cap')
            raw = git(['cat-file', 'blob', args.source_commit + ':' + relative], size)
            require(len(raw) == size, 'S raw blob size changed')
            row, _ = hold(review / relative, (size, hashlib.sha256(raw).hexdigest()))
            sources.append(row)
        verify()
        alive_budget()
        require(not attempt.exists(), 'original operation namespace consumed before child launch')
        argv = [PYTHON, '-I', '-B', str(review / RUNTIME / 'controller.py'),
                '--project-root', str(root), '--review-repository-root', str(review),
                '--source-commit', args.source_commit, '--mode', args.mode, '--output-dir', str(attempt)]
        launch = document(destination / 'launch.v1.json', {
            'schema_version': 1, 'artifact_kind': 'vast_decoder_research_external_original_controller_launch_v1',
            'mode': args.mode, 'argv': argv, 'source_commit': args.source_commit,
            'planning_commit': PLANNING, 'current_checkout_commit': current_checkout,
            'project_root': str(root), 'review_repository_root': str(review),
            'controller': owner(os.getpid()), 'started_at_ns': started_at,
            'single_deadline_monotonic_s': deadline, 'sources': sources, 'dispatch_source': dispatch,
            'interpreter': interpreter, 'git_observations': observations,
            'accepted': False, 'publication_ready': False})

        def started(child):
            document(destination / 'process-start.v1.json', {
                'schema_version': 1, 'artifact_kind': 'vast_decoder_research_external_original_controller_started_v1',
                'mode': args.mode, 'argv': argv, 'source_commit': args.source_commit,
                'planning_commit': PLANNING, 'child': child, 'controller': owner(os.getpid()),
                'observed_at_ns': time.time_ns(), 'accepted': False})

        result = capture(argv, deadline, {'stdout': CHANNEL, 'stderr': CHANNEL},
                         executable_fd=python_fd, output_fds=outputs, on_start=started,
                         canceled=lambda: bool(signals))
        failures.extend(result['failures'])
        close_errors.extend(result['close_errors'])
    except BaseException as exc:
        failures.append(type(exc).__name__ + ': ' + str(exc))
        close_errors.extend(getattr(exc, 'original_capture_cleanup_errors', []))
    finally:
        for channel, fd in reversed(list(outputs.items())):
            try:
                os.fsync(fd)
            except BaseException as exc:
                close_errors.append('raw fsync ' + channel + ': ' + str(exc))
            finally:
                try:
                    os.close(fd)
                except BaseException as exc:
                    close_errors.append('raw close ' + channel + ': ' + str(exc))
        try:
            verify()
            sources_after = [dict(row) for row in sources]
            all_rechecked = True
        except BaseException as exc:
            failures.append('original final custody: ' + type(exc).__name__ + ': ' + str(exc))
            close_errors.extend(getattr(exc, 'original_capture_cleanup_errors', []))
        for _, fd, _ in reversed(held):
            try:
                os.close(fd)
            except BaseException as exc:
                close_errors.append('original held source close: ' + str(exc))
        for fd, _ in reversed(list(directories.values())):
            try:
                os.close(fd)
            except BaseException as exc:
                close_errors.append('original ancestor close: ' + str(exc))
    timed_out = time.monotonic() >= deadline or (result is not None and result['timed_out'])
    successful = (result is not None and result['returncode'] == 0 and not failures
                  and not close_errors and not signals and not timed_out and all_rechecked
                  and all(result['log_eof'].values()) and result['all_streams_closed'])
    terminal = document(destination / 'terminal.v1.json', {
        'schema_version': 1, 'artifact_kind': 'vast_decoder_research_external_original_controller_terminal_v1',
        'mode': args.mode, 'source_commit': args.source_commit, 'planning_commit': PLANNING,
        'current_checkout_commit': current_checkout, 'project_root': str(root),
        'review_repository_root': str(review), 'argv': argv, 'controller': owner(os.getpid()),
        'original_child': None if result is None else result['original_child'],
        'original_controller_returncode': None if result is None else result['returncode'],
        'started_at_ns': started_at, 'finished_at_ns': time.time_ns(), 'elapsed_s': time.monotonic() - began,
        'single_deadline_monotonic_s': deadline, 'timed_out': timed_out,
        'capture_exceeded': [] if result is None else result['capture_exceeded'],
        'signals': signals, 'failures': failures, 'close_errors': close_errors,
        'log_eof': {'stdout': False, 'stderr': False} if result is None else result['log_eof'],
        'all_streams_closed': result is not None and result['all_streams_closed'] and not close_errors,
        'containment': None if result is None else result['containment'],
        'launch': launch, 'sources_before': sources, 'sources_after': sources_after,
        'dispatch_source': dispatch, 'dispatch_source_after': dispatch if all_rechecked else None,
        'interpreter_after': interpreter if all_rechecked else None,
        'all_source_epochs_rechecked': all_rechecked,
        'stdout': descriptor(destination / 'original.stdout'), 'stderr': descriptor(destination / 'original.stderr'),
        'external_capture_completed': successful, 'container_cleanup_verified': None,
        'container_oom_observed': None, 'provisional_until_owner_final_close': True,
        'scope': 'Original direct-child custody and closed raw logs/source FDs only; independent inner Docker/cold evidence required',
        'accepted': False, 'publication_ready': False, 'research_conclusion_authorized': False})
    late = None
    if time.monotonic() >= deadline:
        successful = False
        late = document(destination / 'receipt-time-limit-failure.v1.json', {
            'schema_version': 1, 'artifact_kind': 'vast_decoder_research_external_original_controller_late_terminal_v1',
            'original_terminal': terminal, 'observed_after_close_monotonic_s': time.monotonic(),
            'single_deadline_monotonic_s': deadline, 'failed': True, 'accepted': False, 'publication_ready': False})
    print(canonical({'receipt': terminal, 'external_capture_completed': successful,
                     'late_terminal': late, 'close_errors': close_errors}).decode(), flush=True)
    # The final original tool return is the authority for this last flush/close
    # boundary. A receipt body cannot retroactively certify its own stdout.
    return 0 if successful and not signals and time.monotonic() < deadline else 1


if __name__ == '__main__':
    sys.exit(main())
