"""One CI-only observation of unchanged stock namespace setup; no policy remedy."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RAW_LIMIT = 40 * 1024
REPORT_LIMIT = 16 * 1024 - 256
DENIAL_LIMIT = 8 * 1024


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def _label():
    try:
        with open('/proc/self/attr/current', 'rb') as stream:
            raw = stream.read(257)
        if len(raw) > 256:
            raise ValueError('label exceeds256B')
        return {'path': '/proc/self/attr/current', 'value': raw.decode('utf8').strip()}
    except (OSError, ValueError) as error:
        return {'path': '/proc/self/attr/current', 'unavailable': f'{type(error).__name__}: {error}'[:240]}


def _errno(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, OSError):
            return error.errno
        error = error.__cause__ or error.__context__
    return None


@contextmanager
def instrument_namespace_calls(stock, emit, *, original_pid):
    """Wrappers delegate original calls exactly once and restore every binding."""
    original = {name: getattr(stock.os, name, None) for name in
                ('unshare', 'open', 'write', 'close', 'pipe2', 'fork')}
    mount = stock._linux_mount_v3
    mapped_fds = {}

    def call(syscall, function, *args, **facts):
        base = {'syscall': syscall, 'original_pid': original_pid, 'pid': os.getpid(),
                'wall_time_ns': time.time_ns(), 'monotonic_ns': time.monotonic_ns(), **facts}
        emit({'event': 'syscall_started', **base})
        try:
            result = function(*args)
        except BaseException as error:
            emit({'event': 'syscall_failed', **base, 'terminal_wall_time_ns': time.time_ns(),
                  'terminal_monotonic_ns': time.monotonic_ns(), 'errno': _errno(error),
                  'error_type': type(error).__name__, 'error': str(error)[:240],
                  'stock_tolerated_missing_setgroups': syscall == 'open'
                    and facts.get('path') == '/proc/self/setgroups' and isinstance(error, FileNotFoundError)})
            raise
        emit({'event': 'syscall_completed', **base,
              'terminal_monotonic_ns': time.monotonic_ns()})
        return result

    def open_control(path, flags, *args, **kwargs):
        if path not in ('/proc/self/setgroups', '/proc/self/uid_map', '/proc/self/gid_map'):
            return original['open'](path, flags, *args, **kwargs)
        fd = call('open', lambda: original['open'](path, flags, *args, **kwargs), path=path, flags=flags)
        mapped_fds[fd] = path
        return fd

    def write_control(fd, payload):
        if fd not in mapped_fds:
            return original['write'](fd, payload)
        return call('write', original['write'], fd, payload, path=mapped_fds[fd], payload_size_bytes=len(payload))

    def close_control(fd):
        mapped_fds.pop(fd, None)
        return original['close'](fd)

    try:
        if original['unshare'] is not None:
            stock.os.unshare = lambda flags: call('unshare', original['unshare'], flags, flags=flags)
        stock.os.open = open_control
        stock.os.write = write_control
        stock.os.close = close_control
        if original['pipe2'] is not None:
            stock.os.pipe2 = lambda flags: call('pipe2', original['pipe2'], flags, flags=flags)
        if original['fork'] is not None:
            stock.os.fork = lambda: call('fork', original['fork'])
        stock._linux_mount_v3 = lambda source, target, filesystem, flags: call(
            'mount', mount, source, target, filesystem, flags,
            source=os.fsdecode(source) if source else None, target=os.fsdecode(target),
            filesystem=os.fsdecode(filesystem) if filesystem else None, flags=flags)
        yield
    finally:
        for name, function in original.items():
            if function is not None:
                setattr(stock.os, name, function)
        stock._linux_mount_v3 = mount


def _group_members(pgid):
    members = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path/'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == pgid:
                members.append(int(path.name))
        except (OSError, ValueError, IndexError):
            continue
    return sorted(members)


def capture_original_child(argv, output_dir, absolute_deadline_ns, *, execution_s=20, cleanup_s=10,
                           start_gate=False):
    """Keep bounded original channels and only the original private process group."""
    if not (0 < execution_s <= 20 and 0 < cleanup_s <= 10):
        raise ValueError('namespace diagnostic20s/10s limits exceeded')
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic_ns()
    began_wall = time.time_ns()
    execution_deadline = min(absolute_deadline_ns, began + int(execution_s*1e9))
    final_deadline = min(absolute_deadline_ns, execution_deadline + int(cleanup_s*1e9))
    if began >= execution_deadline:
        raise RuntimeError('original job deadline already elapsed')
    gate_r, gate_w = os.pipe()
    streams = {}
    process = None
    pidfd = None
    owner = None
    error = None
    total = 0
    eof = {'stdout': False, 'stderr': False}
    timed_out = False
    capture_exceeded = False
    cleanup_deadline = None
    selector = selectors.DefaultSelector()
    try:
        for name in eof:
            streams[name] = (output/(name+'.raw')).open('xb')
        command = [*argv, '--start-gate-fd', str(gate_r)] if start_gate else list(argv)
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, pass_fds=(gate_r,) if start_gate else ())
        os.close(gate_r); gate_r = -1
        try:
            pidfd = os.pidfd_open(process.pid, 0)
            observer_spec = importlib.util.spec_from_file_location('ci_owner', ROOT/'scripts/ci_external_test_observer_v1.py')
            observer = importlib.util.module_from_spec(observer_spec); observer_spec.loader.exec_module(observer)
            owner = observer._owner(process.pid)
        except OSError as failure:
            error = f'original owner/pidfd unavailable: {type(failure).__name__}: {failure}'
        if start_gate and error is None:
            os.write(gate_w, b'1')
        os.close(gate_w); gate_w = -1
        for name, pipe in [('stdout',process.stdout), ('stderr',process.stderr)]:
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map() or process.poll() is None:
            now = time.monotonic_ns()
            if cleanup_deadline is None and (error or process.poll() is not None or now >= execution_deadline):
                cleanup_deadline = min(final_deadline, now + int(cleanup_s*1e9))
                final_deadline = cleanup_deadline
            if process.poll() is not None and _group_members(process.pid):
                error = error or 'original diagnostic child exited with remaining owned descendants'
            if now >= final_deadline:
                error = error or 'original diagnostic cleanup deadline reached'
                break
            if now >= execution_deadline or error:
                timed_out = timed_out or now >= execution_deadline
                if process.poll() is None or _group_members(process.pid):
                    # The still-owned unreaped child/private group cannot be reused.
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                if now >= final_deadline:
                    error = error or 'original diagnostic cleanup deadline reached'
                    break
            for key, _ in selector.select(min(.02, max(0, (final_deadline-now)/1e9))):
                block = os.read(key.fileobj.fileno(), 4096)
                name = key.data
                if not block:
                    eof[name] = True
                    selector.unregister(key.fileobj)
                    continue
                allowed = max(0, RAW_LIMIT-total)
                retained = block[:allowed]
                if retained:
                    if streams[name].write(retained) != len(retained):
                        raise OSError('incomplete original diagnostic write')
                    total += len(retained)
                if len(block) > allowed:
                    capture_exceeded = True
                    error = error or 'original namespace capture exceeds40KiB'
        if process.poll() is None:
            process.wait(timeout=max(0, (final_deadline-time.monotonic_ns())/1e9))
    except BaseException as failure:
        error = error or f'{type(failure).__name__}: {failure}'[:512]
    finally:
        if cleanup_deadline is None:
            cleanup_deadline = min(final_deadline, time.monotonic_ns() + int(cleanup_s*1e9))
            final_deadline = cleanup_deadline
        if process is not None and (process.poll() is None or _group_members(process.pid)):
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: process.wait(timeout=max(0, (final_deadline-time.monotonic_ns())/1e9))
            except subprocess.TimeoutExpired: error = error or 'original child unreaped'
        selector.close()
        for fd in (gate_r, gate_w):
            if fd is not None and fd >= 0:
                os.close(fd)
        if process is not None:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None: pipe.close()
        for stream in streams.values():
            try:
                stream.flush(); os.fsync(stream.fileno())
            except OSError as failure:
                error = error or f'original channel close failed: {type(failure).__name__}: {failure}'[:512]
            finally:
                try: stream.close()
                except OSError as failure:
                    error = error or f'original channel close failed: {type(failure).__name__}: {failure}'[:512]
    remaining = _group_members(process.pid) if process is not None else None
    while remaining and time.monotonic_ns() < final_deadline:
        time.sleep(min(.01, max(0, (final_deadline-time.monotonic_ns())/1e9)))
        remaining = _group_members(process.pid)
    if pidfd is not None:
        os.close(pidfd)
    report = {'argv': command if process is not None else list(argv), 'owner': owner,
              'returncode': process.returncode if process is not None else None,
              'timed_out': timed_out, 'capture_exceeded': capture_exceeded,
              'failure': error, 'eof': eof, 'original_group_members': remaining,
              'original_group_absent': remaining == [], 'started_monotonic_ns': began,
              'started_wall_time_ns': began_wall, 'terminal_wall_time_ns': time.time_ns(),
              'execution_deadline_ns': execution_deadline, 'cleanup_deadline_ns': final_deadline,
              'elapsed_s': (time.monotonic_ns()-began)/1e9,
              'capture_completed': not error and not timed_out and not capture_exceeded
                and all(eof.values()) and remaining == []}
    if time.monotonic_ns() >= final_deadline:
        report['capture_completed'] = False
        report['failure'] = report['failure'] or 'original diagnostic deadline exceeded'
    raw = _json(report)
    if len(raw) > REPORT_LIMIT:
        raise RuntimeError('namespace report exceeds16KiB')
    with (output/'capture.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if time.monotonic_ns() >= final_deadline:
        report['capture_completed'] = False
        report['failure'] = report['failure'] or 'original report closed after diagnostic deadline'
        (output/'late-report.failure').write_bytes(b'original namespace report closed late\n')
    return report


def namespace_worker(start_gate_fd):
    """The only production namespace invocation; tests never call this entrypoint."""
    if os.read(start_gate_fd, 1) != b'1':
        raise RuntimeError('original diagnostic parent unavailable')
    os.close(start_gate_fd)
    sys.path.insert(0, str(ROOT/'scripts'))
    import backend_publication_process_supervisor_v3 as stock
    original_pid = os.getpid()
    original_write = os.write
    emitted = 0
    def emit(value):
        nonlocal emitted
        raw = _json(value)
        emitted += len(raw)
        if emitted > 32*1024:
            raise RuntimeError('original syscall observations exceed32KiB')
        if original_write(1, raw) != len(raw):
            raise RuntimeError('incomplete original syscall observation')
    emit({'event':'original_ready', 'original_pid':original_pid,
          'executable':str(Path(sys.executable).resolve(strict=True)), 'label':_label(),
          'wall_time_ns':time.time_ns(), 'monotonic_ns':time.monotonic_ns()})
    try:
        with instrument_namespace_calls(stock, emit, original_pid=original_pid):
            pid, liveness = stock._enter_linux_pid_namespace_v3()
        if pid == 0:
            emit({'event':'namespace_init_verified', 'original_pid':original_pid,
                  'pid':os.getpid(), 'monotonic_ns':time.monotonic_ns()})
            os._exit(0)
        try:
            _, status = os.waitpid(pid, 0)
        finally:
            os.close(liveness)
        emit({'event':'namespace_original_terminal', 'original_pid':original_pid,
              'namespace_init_pid':pid, 'namespace_init_wait_status':status,
              'monotonic_ns':time.monotonic_ns()})
        return 0 if status == 0 else 1
    except BaseException as error:
        emit({'event':'namespace_setup_failed', 'original_pid':original_pid,
              'error_type':type(error).__name__, 'errno':_errno(error),
              'error':str(error)[:512], 'monotonic_ns':time.monotonic_ns()})
        return 1


def observe_namespace_setup_v1(*, output_dir, python, absolute_deadline_ns):
    # An unprivileged, nonblocking source may be unavailable. Retain that fact;
    # the bounded read-only query below never changes policy or infers a denial.
    kernel_fd = None
    denial = {'path':'/dev/kmsg', 'records':[], 'policy_denial_proven':False}
    try:
        kernel_fd = os.open('/dev/kmsg', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        os.lseek(kernel_fd, 0, os.SEEK_END)
    except OSError as error:
        denial['unavailable'] = f'{type(error).__name__}: {error}'[:240]
        if kernel_fd is not None:
            os.close(kernel_fd); kernel_fd = None
    try:
        result = capture_original_child([python, '-I', '-B', str(Path(__file__).resolve()), '--worker'],
                                       output_dir, absolute_deadline_ns, start_gate=True)
        if kernel_fd is not None:
            consumed = 0
            while consumed < DENIAL_LIMIT and time.monotonic_ns() < result['cleanup_deadline_ns']:
                try: raw = os.read(kernel_fd, min(4096, DENIAL_LIMIT-consumed))
                except BlockingIOError: break
                except OSError as error:
                    denial['unavailable'] = f'{type(error).__name__}: {error}'[:240]; break
                if not raw: break
                consumed += len(raw)
                pid = (result.get('owner') or {}).get('pid')
                if pid and b'apparmor="DENIED"' in raw and b'userns' in raw and (
                        ('pid='+str(pid)).encode() in raw):
                    if re.search(rb'\bpid='+str(pid).encode()+rb'(?=\s|$)', raw):
                        denial['records'].append({'raw':os.fsdecode(raw), 'observed_monotonic_ns':time.monotonic_ns()})
            denial['consumed_bytes'] = consumed
            denial['bounded_interval_only'] = True
            if not denial['records']:
                denial['unavailable'] = denial.get('unavailable', 'No exact interpreter PID userns-denial record observed in this bounded interval.')
    finally:
        if kernel_fd is not None: os.close(kernel_fd)
    rows = []
    for raw in (Path(output_dir)/'stdout.raw').read_bytes().splitlines():
        try: rows.append(json.loads(raw))
        except (ValueError, UnicodeError):
            result['capture_completed'] = False
            result['failure'] = result['failure'] or 'incomplete original syscall JSON line'
    failures = [row for row in rows if row.get('event') == 'syscall_failed'
                and not row.get('stock_tolerated_missing_setgroups')]
    result['first_failed_syscall'] = failures[0] if failures else None
    result['namespace_succeeded'] = result['capture_completed'] and result['returncode'] == 0
    result['original_setup_observations'] = rows
    # A single noninteractive read-only kernel query may recover the original
    # interval when /dev/kmsg was unavailable. Never retry namespace setup.
    if not denial['records'] and time.monotonic_ns()+3_000_000_000 < result['cleanup_deadline_ns']:
        sudo, journal = Path('/usr/bin/sudo'), Path('/usr/bin/journalctl')
        if sudo.is_file() and journal.is_file():
            start = result['started_wall_time_ns']//1_000_000_000-1
            end = result['terminal_wall_time_ns']//1_000_000_000+1
            argv = [str(sudo.resolve(strict=True)), '-n', '--', str(journal.resolve(strict=True)),
                '--kernel', '--since', '@'+str(start), '--until', '@'+str(end), '--no-pager',
                '--output=json', '--lines=32', '--grep=apparmor=.*DENIED.*(userns|unshare)']
            log = capture_original_child(argv, Path(output_dir)/'kernel-query',
                                         result['cleanup_deadline_ns'], execution_s=2, cleanup_s=1)
            denial['original_kernel_query'] = log
            if log['capture_completed'] and log['returncode'] == 0:
                for line in (Path(output_dir)/'kernel-query/stdout.raw').read_bytes().splitlines():
                    try:
                        record = json.loads(line)
                        message = record.get('MESSAGE', '')
                        pid = (result.get('owner') or {}).get('pid')
                        if pid and isinstance(message, str) and re.search(
                                r'\bpid='+str(pid)+r'(?=\s|$)', message):
                            denial['records'].append({'original_journal_record':record})
                    except (ValueError, UnicodeError, AttributeError):
                        denial['unavailable'] = 'Original journal response was not complete JSON metadata.'
            else:
                denial['unavailable'] = 'Original read-only kernel query failed or capture was incomplete; see original channels/status.'
        else:
            denial['unavailable'] = denial.get('unavailable', 'Read-only kernel tools unavailable.')
    # Query capture metadata is separately retained, leaving only relevant
    # original records and its exact physical status reference in this8KiB leaf.
    query = denial.get('original_kernel_query')
    if query is not None:
        denial['original_kernel_query'] = {'path':'kernel-query/capture.json',
            'returncode':query['returncode'], 'capture_completed':query['capture_completed'],
            'started_wall_time_ns':query['started_wall_time_ns'],
            'terminal_wall_time_ns':query['terminal_wall_time_ns']}
    raw = _json(denial)
    if len(raw) > DENIAL_LIMIT:
        raise RuntimeError('relevant kernel denial facts exceed8KiB')
    with (Path(output_dir)/'kernel-denial.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if time.monotonic_ns() >= result['cleanup_deadline_ns']:
        result['capture_completed'] = False
        result['failure'] = result['failure'] or 'original diagnostic denial evidence closed late'
    result['policy_denial'] = denial
    result['hardware_acceptance'] = False
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', required=True)
    parser.add_argument('--start-gate-fd', type=int, required=True)
    args = parser.parse_args()
    raise SystemExit(namespace_worker(args.start_gate_fd))
