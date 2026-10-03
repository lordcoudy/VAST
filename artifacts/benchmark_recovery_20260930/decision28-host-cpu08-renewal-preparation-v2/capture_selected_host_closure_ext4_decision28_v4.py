"""Capture the original stock host closure in one reviewed fresh-root120+10 interval."""
from pathlib import Path
import hashlib, json, os, selectors, signal, stat, subprocess, sys, time

START = time.monotonic()
DEADLINE = START+120
HARD_DEADLINE = DEADLINE+10
MAX_CHANNEL = 1024*1024
ROOT = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
OUTPUT = ROOT/'artifacts/benchmark_recovery_20260930/decision28-host-closure-ext4-v4-original'
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
pins = []
pin_checks, pin_closes = [], []
cleanup_errors = []
error_overflow = 0
fd_before = fd_after = None
output_owned = False

def latch(exc):
    global primary, error_overflow
    if primary is None:
        primary = error(exc)
    elif len(cleanup_errors) < 64:
        cleanup_errors.append(error(exc))
    else:
        error_overflow += 1

def fd_count():
    return len(os.listdir('/proc/self/fd'))

def scan_original_group(original, cleanup_deadline):
    observed = {'original_pid':original['pid'],'original_pgid':original['pgid'],
        'original_startticks':original.get('startticks'),'original_pid_identity':'absent',
        'members':[],'member_overflow':0,'errors':[],'error_overflow':0,
        'vanished_during_scan':0,'started_at_ns':time.time_ns()}
    def scan_error(phase, exc):
        if len(observed['errors']) < 64:
            observed['errors'].append({'phase':phase,'error':error(exc)})
        else:
            observed['error_overflow'] += 1
    try:
        entries = os.listdir('/proc')
    except BaseException as exc:
        scan_error('enumeration',exc)
        entries = []
    for entry in entries:
        if not entry.isdigit():
            continue
        if time.monotonic() >= cleanup_deadline:
            scan_error('deadline',TimeoutError('original bounded cleanup deadline during group scan'))
            break
        try:
            parts = Path('/proc',entry,'stat').read_text().rsplit(')',1)[1].split()
            pid, pgid, startticks = int(entry), int(parts[2]), int(parts[19])
            if pid == original['pid']:
                observed['original_pid_identity'] = (
                    'original_present' if startticks==original.get('startticks') else 'different_startticks')
            if pgid == original['pgid']:
                if len(observed['members']) < 64:
                    observed['members'].append({'pid':pid,'startticks':startticks,'state':parts[0]})
                else:
                    observed['member_overflow'] += 1
        except (FileNotFoundError,ProcessLookupError):
            observed['vanished_during_scan'] += 1
        except BaseException as exc:
            scan_error('pid:'+entry,exc)
    observed['finished_at_ns'] = time.time_ns()
    return observed



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
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
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
    except BaseException as exc:
        latch(exc)
        raise
    finally:
        try:
            os.close(fd)
        except BaseException as exc:
            latch(exc)


def write(name, value, late_metadata=False):
    if not late_metadata:
        hard_clock()
    raw = (json.dumps(value, sort_keys=True, indent=2)+'\n').encode()
    assert len(raw) <= (65536 if late_metadata else MAX_CHANNEL)
    stream = None
    failed = None
    try:
        assert output_owned, 'this invocation does not own the exclusive output namespace'
        stream = (OUTPUT/name).open('xb')
        assert stream.write(raw) == len(raw), 'short metadata write'
        stream.flush()
        os.fsync(stream.fileno())
    except BaseException as exc:
        failed = exc
        latch(exc)
    finally:
        if stream is not None:
            try:
                stream.close()
            except BaseException as exc:
                latch(exc)
                if failed is None:
                    failed = exc
    if failed is not None:
        raise failed
    if not late_metadata:
        hard_clock()
    return {'path':str(OUTPUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def pin(path, maximum=MAX_CHANNEL):
    row = {'path':str(path),'fd':None,'epoch':None,'descriptor':None,'maximum':maximum}
    pins.append(row)
    canonical_directory(path.parent)
    row['fd'] = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    row['epoch'] = tuple(getattr(os.fstat(row['fd']),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    row['descriptor'] = facts(path,maximum=maximum)
    assert row['epoch'] == tuple(getattr(path.lstat(),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    assert row['epoch'] == tuple(getattr(os.fstat(row['fd']),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    return row


def observe(row, cleanup=False):
    path = Path(row['path'])
    assert row['epoch'] == tuple(getattr(path.lstat(),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    assert row['epoch'] == tuple(getattr(os.fstat(row['fd']),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    current = facts(path,maximum=row['maximum'],cleanup=cleanup)
    assert current == row['descriptor'], 'original held source full byte drift'
    assert row['epoch'] == tuple(getattr(path.lstat(),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    assert row['epoch'] == tuple(getattr(os.fstat(row['fd']),key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
    return {'descriptor':current,'epoch':row['epoch']}


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
    selector = None
    command_fd_before = fd_count()
    record = {'argv': argv, 'owner': None, 'timed_out': False, 'capture_exceeded': False, 'errors': [],
              'error_overflow':0,'EOF':{'stdout':False,'stderr':False},'process_group_scans':[],'reaped':False}
    def command_error(exc):
        latch(exc)
        if len(record['errors']) < 64:
            record['errors'].append(error(exc))
        else:
            record['error_overflow'] += 1
    try:
        selector = selectors.DefaultSelector()
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
                    record['EOF'][key.data] = True
                    selector.unregister(key.fileobj)
                    continue
                if len(block) > MAX_CHANNEL-counts[key.data]:
                    record['capture_exceeded'] = True
                    raise RuntimeError('original host closure command channel cap')
                assert streams[key.data].write(block) == len(block), 'short original channel write'
                counts[key.data] += len(block)
        child.wait(timeout=max(.001, DEADLINE-time.monotonic()))
        if child.returncode != 0:
            raise RuntimeError('original stock command nonzero: '+str(child.returncode))
    except BaseException as exc:
        record['timed_out'] = isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
        command_error(exc)
    finally:
        cleanup_deadline = min(HARD_DEADLINE, time.monotonic()+10)
        if child is not None:
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                pass
            except BaseException as exc:
                command_error(exc)
            else:
                command_error(RuntimeError('original closure command left a process group'))
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except BaseException as exc:
                    command_error(exc)
            try:
                child.wait(timeout=max(.001, cleanup_deadline-time.monotonic()))
                record['reaped'] = True
            except BaseException as exc:
                command_error(exc)
        if selector is not None:
            try:
                selector.close()
            except BaseException as exc:
                command_error(exc)
        for pipe in (() if child is None else (child.stdout, child.stderr)):
            if pipe is not None:
                try:
                    pipe.close()
                except BaseException as exc:
                    command_error(exc)
        for stream in streams.values():
            for action in (stream.flush, lambda stream=stream:os.fsync(stream.fileno()), stream.close):
                try:
                    action()
                except BaseException as exc:
                    command_error(exc)
        record['returncode'] = None if child is None else child.returncode
        if child is not None:
            original = record['owner'] or {'pid':child.pid,'pgid':child.pid,'startticks':None}
            if record['owner'] is None:
                command_error(RuntimeError('original process owner identity unavailable'))
            for scan_index in range(2):
                try:
                    scan = scan_original_group(original,cleanup_deadline)
                    record['process_group_scans'].append(scan)
                    if scan['errors'] or scan['error_overflow'] or scan['members'] or scan['member_overflow'] or scan['original_pid_identity'] != 'absent':
                        command_error(RuntimeError('original PID/group absence uncertain or not absent'))
                except BaseException as exc:
                    command_error(exc)
        record['original_pid_absent'] = len(record['process_group_scans'])==2 and all(scan['original_pid_identity']=='absent' and not scan['errors'] and not scan['error_overflow'] for scan in record['process_group_scans'])
        record['original_group_absent'] = len(record['process_group_scans'])==2 and all(not scan['members'] and not scan['member_overflow'] and not scan['errors'] and not scan['error_overflow'] for scan in record['process_group_scans'])
        if not all(record['EOF'].values()):
            command_error(RuntimeError('original channel EOF unavailable'))
        record['channels'] = {}
        for name,path in paths.items():
            try:
                record['channels'][name] = {'path':str(path),**facts(path,cleanup=True)}
            except BaseException as exc:
                record['channels'][name] = None
                command_error(exc)
        try:
            record['fd_before'] = command_fd_before
            record['fd_after'] = fd_count()
            assert record['fd_after'] == command_fd_before, 'command FD baseline not restored'
            assert time.monotonic() < cleanup_deadline, 'original10s cleanup deadline elapsed'
        except BaseException as exc:
            command_error(exc)
        commands.append(record)
        try:
            write(label+'.terminal.v1.json', record)
        except BaseException as exc:
            command_error(exc)
    assert not record['errors'] and not record['error_overflow'] and record['returncode'] == 0
    assert record['reaped'] is True and record['original_pid_absent'] is True and record['original_group_absent'] is True
    assert primary is None, 'original first failure retained'
    clock()
    return record


receipt = BASE/'execution-code-closure.ext4-decision28.v4.json'
try:
    fd_before = fd_count()
    clock()
    canonical_directory(ROOT)
    assert ROOT.stat().st_uid == os.getuid()
    assert not os.path.lexists(OUTPUT) and not os.path.lexists(receipt)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canonical_directory(OUTPUT.parent)
    OUTPUT.mkdir(mode=0o700)
    output_owned = True
    pin(Path(__file__))
    interpreter_path = Path(sys.executable).resolve(strict=True)
    pin(interpreter_path, maximum=interpreter_path.lstat().st_size)
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
    before = {name: pin(ROOT/name)['descriptor'] for name in names}
    BASE.mkdir(parents=True, exist_ok=True)
    canonical_directory(BASE)
    code = 'import runpy,sys;sys.path.insert(0,'+repr(str(ROOT/'scripts'))+');runpy.run_path('+repr(str(ROOT/'scripts/publication_policy_qualification_execution_code_closure_v1.py'))+',run_name="__main__")'
    argv = [sys.executable, '-I', '-B', '-c', code, '--project-root', str(ROOT), '--receipt', str(receipt)]
    write('stock-dispatch.v1.json', {'argv': argv, 'before': before,
          'source_commit': SOURCE_COMMIT, 'historical_receipt_used_only_as_path_inventory': True,
          'original_inventory_path': str(ORIGINAL), 'original_inventory_sha256': ORIGINAL_SHA})
    command(argv, 'stock-closure')
    after = {name: observe(pins[index+2])['descriptor'] for index,name in enumerate(names)}
    assert before == after, 'original host source byte drift'
    receipt_facts = facts(receipt)
    clock()
except BaseException as exc:
    latch(exc)
finally:
    for index,row in enumerate(pins):
        try:
            assert row['fd'] is not None and row['epoch'] is not None and row['descriptor'] is not None, 'held source acquisition incomplete'
            pin_checks.append({'pin_index':index,'verified':True,**observe(row,cleanup=True)})
        except BaseException as exc:
            pin_checks.append({'pin_index':index,'verified':False,'path':row['path']})
            latch(exc)
    for index,row in enumerate(pins):
        if row['fd'] is None:
            continue
        try:
            os.close(row['fd'])
            row['fd'] = None
            pin_closes.append({'pin_index':index,'closed':True})
        except BaseException as exc:
            pin_closes.append({'pin_index':index,'closed':False})
            latch(exc)
    try:
        fd_after = fd_count()
        assert fd_before is not None and fd_after == fd_before, 'controller FD baseline not restored'
    except BaseException as exc:
        latch(exc)
    late = time.monotonic() >= DEADLINE
    if late:
        latch(TimeoutError('original host closure120s deadline at finalization'))
    terminal = None
    terminal_error = primary
    terminal_error_count, terminal_overflow = len(cleanup_errors), error_overflow
    if output_owned:
        try:
            terminal = write('execution.v1.json', {'source_commit':SOURCE_COMMIT,'elapsed_s':time.monotonic()-START,
                'primary_error':primary,'additional_errors':cleanup_errors,'error_overflow':error_overflow,
                'commands':commands,'before':before,'after':after,'source_before_after_equal':bool(before) and before==after,
                'receipt':receipt_facts,'held_source_checks':pin_checks,'pin_closes':pin_closes,
                'fd_before':fd_before,'fd_after':fd_after,'all_pin_close_attempts_finished':True,
                'hardware_acceptance':False,'status':'captured' if primary is None else 'failed'})
            hard_clock()
            print(json.dumps({'status':'captured' if primary is None else 'failed','elapsed_s':time.monotonic()-START,
                              'primary_error':primary,'terminal':terminal}),flush=True)
        except BaseException as exc:
            latch(exc)
    try:
        fd_after = fd_count()
        assert fd_before is not None and fd_after == fd_before, 'final metadata FD baseline not restored'
    except BaseException as exc:
        latch(exc)
    if time.monotonic() >= DEADLINE:
        if not late:
            latch(TimeoutError('original host closure120s deadline after terminal'))
        late = True
    if output_owned and (terminal is None or primary != terminal_error or len(cleanup_errors)!=terminal_error_count or error_overflow!=terminal_overflow or late):
        try:
            write('failure.v4.json', {'source_commit':SOURCE_COMMIT,'primary_error':primary,'terminal':terminal,
                'terminal_path':str(OUTPUT/'execution.v1.json'),'late':late,'fd_before':fd_before,'fd_after':fd_after,
                'all_pin_close_attempts_finished':True,'recent_errors':cleanup_errors[-8:],'error_overflow':error_overflow,
                'hardware_acceptance':False,'status':'failed','record_kind':'exclusive bounded finalization failure companion'},late_metadata=True)
        except BaseException as exc:
            latch(exc)
            try:
                print(json.dumps({'status':'failed','primary_error':primary,'companion_error':error(exc)}),file=sys.stderr,flush=True)
            except BaseException as report_exc:
                latch(report_exc)
    if output_owned and time.monotonic() >= DEADLINE and not late:
        late = True
        latch(TimeoutError('original host closure120s deadline after final metadata'))
        try:
            write('late.v4.json',{'source_commit':SOURCE_COMMIT,'primary_error':primary,'late':True,'hardware_acceptance':False,'status':'failed'},late_metadata=True)
        except BaseException as exc:
            latch(exc)
    if not output_owned:
        try:
            print(json.dumps({'status':'failed','primary_error':primary,'output_namespace_owned':False}),file=sys.stderr,flush=True)
        except BaseException as exc:
            latch(exc)
sys.exit(0 if primary is None else 78)
