"""One cold consumer, original source FD custody,600s plus15s owned teardown."""
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

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = Path(__file__).parent
OUTPUT = BASE / 'attempt01'
START = time.monotonic()
EXECUTION_DEADLINE = START + 600
HARD_DEADLINE = EXECUTION_DEADLINE + 15
deadline = EXECUTION_DEADLINE
CAP = 1048576
held, before, after, files = {}, {}, {}, {}
counts = {'stdout': 0, 'stderr': 0}
child = child_owner = None
selector = selectors.DefaultSelector()
primary, additional, signals = None, [], []
additional_overflow = 0
timed_out = exceeded = False
terminal_ref = None
terminal_attempted = False

def error(exc):
    return {'type': type(exc).__name__, 'message': str(exc)[:4096]}

def latch(exc):
    global primary, additional_overflow
    if primary is None:
        primary = error(exc)
    elif len(additional) < 64:
        additional.append(error(exc))
    else:
        additional_overflow += 1

def remaining():
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError('original cold consumer phase deadline elapsed')
    return value

def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]

def owner(pid):
    try:
        values = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]),
                'startticks': int(values[19]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None

def groups(pgid):
    found = []
    for path in Path('/proc').iterdir():
        remaining()
        if path.name.isdigit():
            observed = owner(int(path.name))
            if observed is not None and observed['pgid'] == pgid:
                found.append(observed)
    return found

def descriptor(path, fd=None):
    remaining()
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()
    assert 0 <= info.st_size <= 256 * 1024 * 1024
    digest, size = hashlib.sha256(), 0
    if fd is not None:
        assert epoch(info) == epoch(os.fstat(fd))
        os.lseek(fd, 0, os.SEEK_SET)
        while block := os.read(fd, 1048576):
            remaining(); digest.update(block); size += len(block)
    else:
        with path.open('rb') as stream:
            while block := stream.read(1048576):
                remaining(); digest.update(block); size += len(block)
    remaining()
    assert size == info.st_size and epoch(info) == epoch(path.lstat())
    return {'path': str(path), 'size_bytes': size, 'sha256': digest.hexdigest(), 'epoch': epoch(info)}

def save(name, value):
    remaining()
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
    assert len(raw) <= CAP
    path = OUTPUT / name
    with path.open('xb') as stream:
        stream.write(raw); remaining(); stream.flush(); remaining(); os.fsync(stream.fileno()); remaining()
    remaining()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def drain(timeout):
    global exceeded
    remaining()
    for key, _ in selector.select(min(timeout, remaining())):
        raw = os.read(key.fd, 65536)
        remaining()
        if not raw:
            selector.unregister(key.fileobj)
            continue
        available = CAP - counts[key.data]
        retained = raw[:max(0, available)]
        if retained:
            files[key.data].write(retained); counts[key.data] += len(retained); remaining()
        if len(raw) > available:
            exceeded = True
            raise RuntimeError('original channel overflow; bounded original prefix retained')

assert not os.path.lexists(OUTPUT), 'corrected reader observer namespace is occupied'
OUTPUT.mkdir(mode=0o700)
try:
    for name in counts:
        files[name] = (OUTPUT / (name + '.raw')).open('xb')
    original_path = ROOT / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04-original-controller/original.terminal.v1.json'
    original = descriptor(original_path)
    assert original['sha256'] == '88b9c117f75b45454b8facc781e1bb291750de388b85f03c31fe7135b1496b0e'
    source = json.loads(original_path.read_bytes())
    expected = {row['descriptor']['path']: row['descriptor'] for row in source['pins_before']}
    assert len(expected) == 95
    paths = tuple(expected) + tuple(str(BASE / name) for name in
        ('run_reader.py', 'corrected_component_runtime_v1.py', 'arguments.v1.json', 'observe_v2.py')) + (str(original_path),)
    assert len(set(paths)) == 100
    for name in paths:
        remaining()
        path = Path(name)
        assert path.resolve(strict=True) == path
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        held[name] = (fd, epoch(os.fstat(fd)))
        before[name] = descriptor(path, fd)
        assert before[name]['epoch'] == held[name][1]
        if name in expected:
            assert {key: before[name][key] for key in expected[name]} == expected[name], 'original producer bytes differ: ' + name
    argv = [sys.executable, '-I', '-B', str(BASE / 'run_reader.py')]
    remaining()
    began = time.time_ns()
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True)
    child_owner = owner(child.pid)
    assert child_owner is not None and child_owner['pgid'] == child.pid
    save('launch.v1.json', {'argv': argv, 'observer': owner(os.getpid()), 'child': child_owner,
        'started_at_ns': began, 'source_before': before, 'execution_budget_s': 600, 'teardown_budget_s': 15,
        'scope': 'New consumer custody epochs; original CPU04 failed producer witnesses/status remain unchanged.'})
    for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
        os.set_blocking(pipe.fileno(), False); selector.register(pipe, selectors.EVENT_READ, name)
    print(json.dumps({'phase': 'corrected_cold_consumer_started', 'owner': child_owner}), flush=True)
    next_update = time.monotonic() + 30
    while selector.get_map() or child.poll() is None:
        drain(.1)
        if time.monotonic() >= next_update:
            print(json.dumps({'phase': 'corrected_cold_consumer_running', 'elapsed_s': time.monotonic() - START,
                             'channels': counts}), flush=True)
            next_update = time.monotonic() + 30
    child.wait(timeout=remaining())
    if child.returncode != 0:
        raise RuntimeError('original corrected cold consumer nonzero: ' + str(child.returncode))
except BaseException as exc:
    timed_out = isinstance(exc, TimeoutError)
    latch(exc)
finally:
    # This single cleanup clock covers containment, reap,drain,verification and publication.
    deadline = min(HARD_DEADLINE, time.monotonic() + 15)
    try:
        if child is not None and child.poll() is None:
            # Unreaped direct Popen child prevents reuse of this original private PGID.
            remaining(); os.killpg(child.pid, signal.SIGINT); signals.append('SIGINT')
            try:
                child.wait(timeout=min(5, remaining()))
            except subprocess.TimeoutExpired:
                remaining(); os.killpg(child.pid, signal.SIGKILL); signals.append('SIGKILL')
                child.wait(timeout=remaining())
        while selector.get_map():
            try:
                drain(.05)
            except RuntimeError as exc:
                latch(exc)
        remaining()
    except BaseException as exc:
        latch(exc)
    finally:
        selector.close()
        if child is not None:
            for pipe in (child.stdout, child.stderr):
                try:
                    pipe.close(); remaining()
                except BaseException as exc:
                    latch(exc)
        for stream in files.values():
            try:
                remaining(); stream.flush(); remaining(); os.fsync(stream.fileno()); remaining()
            except BaseException as exc:
                latch(exc)
            finally:
                stream.close()
    group_members = []
    try:
        if child_owner is not None:
            group_members = groups(child_owner['pgid'])
            if group_members:
                raise RuntimeError('original consumer group remains; cleanup failed')
        for name, (fd, snapshot) in held.items():
            current = descriptor(Path(name), fd)
            assert current['epoch'] == snapshot
            after[name] = current
        assert before == after, 'original consumer source changed'
    except BaseException as exc:
        latch(exc)
    finally:
        for fd, _ in held.values():
            try:
                os.close(fd); remaining()
            except BaseException as exc:
                latch(exc)
    try:
        outputs = {name: descriptor(OUTPUT / (name + '.raw')) for name in files}
        terminal_attempted = True
        terminal_ref = save('terminal.v1.json', {'artifact_kind': 'vast_cpu04_corrected_cold_consumer_execution_v2',
            'original_child_returncode': None if child is None else child.returncode, 'child': child_owner,
            'source_before': before, 'source_after': after, 'sources_stable': before == after,
            'original_child_current': None if child is None else owner(child.pid), 'original_group_members': group_members,
            'primary_error': primary, 'additional_errors': additional, 'timed_out': timed_out,
            'additional_error_overflow': additional_overflow,
            'capture_exceeded': exceeded, 'signals': signals, 'outputs': outputs, 'elapsed_s': time.monotonic() - START,
            'execution_budget_s': 600, 'teardown_budget_s': 15, 'deadline_absolute_monotonic_s': deadline,
            'new_native_measurements': 0, 'original_cli_remains_failed': True,
            'scope': 'Separately pinned corrected stock cold consumer; current FD epochs do not rebind original CPU04 witnesses.'})
        remaining()
    except BaseException as exc:
        latch(exc)
        # Existing receipt cannot become success after publication crosses the limit.
        if terminal_attempted:
            raw = (json.dumps({'failed': True, 'original_terminal': terminal_ref, 'failure': error(exc),
                               'terminal_path_unverified': str(OUTPUT / 'terminal.v1.json'),
                               'complete_descriptor_verified': terminal_ref is not None,
                               'elapsed_s': time.monotonic() - START}) + '\n').encode()
            try:
                with (OUTPUT / 'late-or-persistence-failure.v1.json').open('xb') as stream:
                    stream.write(raw)
            except OSError:
                pass
print(json.dumps({'phase': 'corrected_cold_consumer_terminal', 'receipt': terminal_ref,
                  'failure': primary, 'elapsed_s': time.monotonic() - START}), flush=True)
sys.exit(0 if child is not None and child.returncode == 0 and primary is None else 78)
