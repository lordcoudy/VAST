"""Capture the original stock host closure in one reviewed fresh-root120+10 interval."""
from pathlib import Path
import hashlib, json, os, selectors, signal, stat, subprocess, sys, time

START = time.monotonic()
DEADLINE = START+120
HARD_DEADLINE = DEADLINE+10
MAX_CHANNEL = 1024*1024
ROOT = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
OUTPUT = ROOT/'artifacts/benchmark_recovery_20260930/decision28-host-closure-ext4-v3-original'
BASE = ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/host'
ORIGINAL = BASE/'execution-code-closure.ext4.v1.json'
ORIGINAL_SHA = 'adbcb638a5f104e43c95b84e4d16388a8111d39321afb3e8e7a26f2ef537b498'
assert len(sys.argv) == 2, 'usage: closure SOURCE_COMMIT'
SOURCE_COMMIT = sys.argv[1]
assert len(SOURCE_COMMIT) == 40 and all(c in '0123456789abcdef' for c in SOURCE_COMMIT)
commands = []
before, after = {}, {}
primary = None
receipt_facts = None


def clock():
    if time.monotonic() >= DEADLINE:
        raise TimeoutError('original host closure120s deadline')


def hard_clock():
    if time.monotonic() >= HARD_DEADLINE:
        raise TimeoutError('original host closure120+10s persistence/cleanup deadline')


def error(exc):
    return {'type': type(exc).__name__, 'message': str(exc)[:4096]}


def canonical_directory(path):
    assert path.is_absolute() and path.resolve(strict=True) == path
    for parent in (path, *path.parents):
        assert stat.S_ISDIR(parent.lstat().st_mode) and not parent.is_symlink()


def facts(path, maximum=MAX_CHANNEL, cleanup=False):
    check = hard_clock if cleanup else clock
    check()
    canonical_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        first = os.fstat(fd)
        assert stat.S_ISREG(first.st_mode) and first.st_nlink == 1 and first.st_size <= maximum
        first_epoch = tuple(getattr(first, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
        sha, count = hashlib.sha256(), 0
        while block := os.read(fd, 65536):
            check()
            count += len(block)
            assert count <= maximum
            sha.update(block)
        for info in (path.lstat(), os.fstat(fd)):
            assert first_epoch == tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
        canonical_directory(path.parent)
        check()
        return {'size_bytes': count, 'sha256': sha.hexdigest()}
    finally:
        os.close(fd)


def write(name, value):
    hard_clock()
    raw = (json.dumps(value, sort_keys=True, indent=2)+'\n').encode()
    assert len(raw) <= MAX_CHANNEL
    with (OUTPUT/name).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    hard_clock()


def owner(pid):
    values = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
    ids = dict(line.split(':', 1) for line in Path('/proc', str(pid), 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'startticks': int(values[19]),
            'uid': int(ids['Uid'].split()[0]), 'gid': int(ids['Gid'].split()[0]),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def command(argv, label):
    clock()
    paths = {name: OUTPUT/(label+'.'+name+'.raw') for name in ('stdout', 'stderr')}
    streams, counts = {}, {'stdout': 0, 'stderr': 0}
    child = None
    selector = selectors.DefaultSelector()
    record = {'argv': argv, 'owner': None, 'timed_out': False, 'capture_exceeded': False, 'errors': []}
    try:
        for name, path in paths.items():
            streams[name] = path.open('xb')
        child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        record['owner'] = owner(child.pid)
        write(label+'.launch.v1.json', record)
        for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while selector.get_map() or child.poll() is None:
            clock()
            for key, _ in selector.select(min(.1, max(.001, DEADLINE-time.monotonic()))):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                if len(block) > MAX_CHANNEL-counts[key.data]:
                    record['capture_exceeded'] = True
                    raise RuntimeError('original host closure command channel cap')
                streams[key.data].write(block)
                counts[key.data] += len(block)
        child.wait(timeout=max(.001, DEADLINE-time.monotonic()))
    except BaseException as exc:
        record['timed_out'] = isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
        record['errors'].append(error(exc))
    finally:
        cleanup_deadline = min(HARD_DEADLINE, time.monotonic()+10)
        if child is not None:
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                pass
            else:
                if not record['errors']:
                    record['errors'].append(error(RuntimeError('original closure command left a process group')))
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=max(.001, cleanup_deadline-time.monotonic()))
            except BaseException as exc:
                record['errors'].append(error(exc))
        selector.close()
        for pipe in (() if child is None else (child.stdout, child.stderr)):
            try:
                pipe.close()
            except BaseException as exc:
                record['errors'].append(error(exc))
        for stream in streams.values():
            try:
                hard_clock()
                stream.flush()
                os.fsync(stream.fileno())
                hard_clock()
            except BaseException as exc:
                record['errors'].append(error(exc))
            finally:
                stream.close()
        record['returncode'] = None if child is None else child.returncode
        record['original_pid_absent'] = None if child is None else not Path('/proc', str(child.pid)).exists()
        record['original_group_absent'] = None
        if child is not None:
            try:
                os.killpg(child.pid, 0)
                record['original_group_absent'] = False
            except ProcessLookupError:
                record['original_group_absent'] = True
        record['channels'] = {name: {'path': str(path), **facts(path, cleanup=True)} for name, path in paths.items() if path.is_file()}
        commands.append(record)
        write(label+'.terminal.v1.json', record)
    assert not record['errors'] and record['returncode'] == 0
    assert record['original_pid_absent'] is True and record['original_group_absent'] is True
    clock()
    return record


receipt = BASE/'execution-code-closure.ext4-decision28.v3.json'
try:
    clock()
    canonical_directory(ROOT)
    assert ROOT.stat().st_uid == os.getuid()
    assert not os.path.lexists(OUTPUT) and not os.path.lexists(receipt)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canonical_directory(OUTPUT.parent)
    OUTPUT.mkdir(mode=0o700)
    write('dispatch.v1.json', {'source_commit': SOURCE_COMMIT, 'controller': owner(os.getpid()),
          'helper': facts(Path(__file__)), 'timeout_s': 120, 'cleanup_s': 10,
          'start_monotonic': START, 'absolute_work_deadline': DEADLINE,
          'absolute_cleanup_deadline': HARD_DEADLINE, 'hardware_acceptance': False})
    head = command(['/usr/bin/git', '-c', 'core.longpaths=true', '-C', str(ROOT), 'rev-parse', 'HEAD'], 'source-head')
    assert Path(head['channels']['stdout']['path']).read_bytes() == (SOURCE_COMMIT+'\n').encode('ascii')
    assert facts(ORIGINAL)['sha256'] == ORIGINAL_SHA
    original_raw = ORIGINAL.read_bytes()
    assert len(original_raw) <= MAX_CHANNEL and hashlib.sha256(original_raw).hexdigest() == ORIGINAL_SHA
    previous = json.loads(original_raw)
    names = [row['path'] for row in previous['project_sources']]
    assert len(names) == 87 and len(set(names)) == 87
    assert all(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name for name in names)
    before = {name: facts(ROOT/name) for name in names}
    BASE.mkdir(parents=True, exist_ok=True)
    canonical_directory(BASE)
    code = 'import runpy,sys;sys.path.insert(0,'+repr(str(ROOT/'scripts'))+');runpy.run_path('+repr(str(ROOT/'scripts/publication_policy_qualification_execution_code_closure_v1.py'))+',run_name="__main__")'
    argv = [sys.executable, '-I', '-B', '-c', code, '--project-root', str(ROOT), '--receipt', str(receipt)]
    write('stock-dispatch.v1.json', {'argv': argv, 'before': before,
          'source_commit': SOURCE_COMMIT, 'historical_receipt_used_only_as_path_inventory': True,
          'original_inventory_path': str(ORIGINAL), 'original_inventory_sha256': ORIGINAL_SHA})
    command(argv, 'stock-closure')
    after = {name: facts(ROOT/name) for name in names}
    assert before == after, 'original host source byte drift'
    receipt_facts = facts(receipt)
    clock()
except BaseException as exc:
    primary = error(exc)
finally:
    result = {'source_commit': SOURCE_COMMIT, 'elapsed_s': time.monotonic()-START,
              'primary_error': primary, 'commands': commands, 'before': before, 'after': after,
              'source_before_after_equal': bool(before) and before == after,
              'receipt': receipt_facts, 'hardware_acceptance': False,
              'status': 'captured' if primary is None else 'failed'}
    if OUTPUT.is_dir():
        write('execution.v1.json', result)
    if time.monotonic() >= DEADLINE and primary is None:
        primary = error(TimeoutError('original host closure120s deadline after receipt publication'))
        write('late-failure.v1.json', {'primary_error': primary, 'status': 'failed',
              'elapsed_s': time.monotonic()-START, 'hardware_acceptance': False})
    hard_clock()
    print(json.dumps({'status': 'captured' if primary is None else 'failed',
                     'elapsed_s': time.monotonic()-START, 'primary_error': primary}), flush=True)
sys.exit(0 if primary is None else 78)

