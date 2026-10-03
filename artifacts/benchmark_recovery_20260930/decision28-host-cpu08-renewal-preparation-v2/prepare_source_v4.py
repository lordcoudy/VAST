"""Offline literal authoring/audit only; never import or execute the prepared helpers."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
OLD = OUT.parent / 'decision28-host-cpu08-renewal-preparation-v1'
REPLACEMENTS = {}

def replace(text, old, new, kind):
    assert text.count(old) == 1, (kind, old[:100], text.count(old))
    REPLACEMENTS.setdefault(kind, []).append([old, new])
    return text.replace(old, new, 1)

SCAN = '''def fd_count():
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

'''

host_old = (OLD/'capture_selected_host_closure_ext4_decision28_v3.py').read_bytes()
host = host_old.decode()
host = replace(host, 'decision28-host-closure-ext4-v3-original', 'decision28-host-closure-ext4-v4-original', 'host')
host = replace(host, 'execution-code-closure.ext4-decision28.v3.json', 'execution-code-closure.ext4-decision28.v4.json', 'host')
host = replace(host, 'receipt_facts = None\n', '''receipt_facts = None
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

'''+SCAN, 'host')
host = replace(host, 'fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)', 'fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)', 'host')
host = replace(host, '''    finally:
        os.close(fd)


def write(name, value):
    hard_clock()
    raw = (json.dumps(value, sort_keys=True, indent=2)+'\\n').encode()
    assert len(raw) <= MAX_CHANNEL
    with (OUTPUT/name).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    hard_clock()
''', '''    except BaseException as exc:
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
    raw = (json.dumps(value, sort_keys=True, indent=2)+'\\n').encode()
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
''', 'host')
host = replace(host, '''    selector = selectors.DefaultSelector()
    record = {'argv': argv, 'owner': None, 'timed_out': False, 'capture_exceeded': False, 'errors': []}
    try:
''', '''    selector = None
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
''', 'host')
host = replace(host, '''                if not block:
                    selector.unregister(key.fileobj)
''', '''                if not block:
                    record['EOF'][key.data] = True
                    selector.unregister(key.fileobj)
''', 'host')
host = replace(host, "                streams[key.data].write(block)\n", "                assert streams[key.data].write(block) == len(block), 'short original channel write'\n", 'host')
host = replace(host, '        child.wait(timeout=max(.001, DEADLINE-time.monotonic()))\n', "        child.wait(timeout=max(.001, DEADLINE-time.monotonic()))\n        if child.returncode != 0:\n            raise RuntimeError('original stock command nonzero: '+str(child.returncode))\n", 'host')
start = host.index('    except BaseException as exc:\n        record[\'timed_out\']')
end = host.index('\n\nreceipt = BASE/', start)
host = replace(host, host[start:end], '''    except BaseException as exc:
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
''', 'host')
host = replace(host, '''try:
    clock()
    canonical_directory(ROOT)
''', '''try:
    fd_before = fd_count()
    clock()
    canonical_directory(ROOT)
''', 'host')
host = replace(host, '''    OUTPUT.mkdir(mode=0o700)
    write('dispatch.v1.json',''', '''    OUTPUT.mkdir(mode=0o700)
    output_owned = True
    pin(Path(__file__))
    interpreter_path = Path(sys.executable).resolve(strict=True)
    pin(interpreter_path, maximum=interpreter_path.lstat().st_size)
    write('dispatch.v1.json',''', 'host')
host = replace(host, "    before = {name: facts(ROOT/name) for name in names}\n", "    before = {name: pin(ROOT/name)['descriptor'] for name in names}\n", 'host')
host = replace(host, "    after = {name: facts(ROOT/name) for name in names}\n", "    after = {name: observe(pins[index+2])['descriptor'] for index,name in enumerate(names)}\n", 'host')
start = host.index('except BaseException as exc:\n    primary = error(exc)\nfinally:')
host = replace(host, host[start:], '''except BaseException as exc:
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
''', 'host')

cpu_old = (OLD/'run_original_cpu_component_pair_ext4_decision28_v3.pending.py').read_bytes()
cpu = cpu_old.decode()
cpu = replace(cpu, 'HOST_CLOSURE_EXT4_DECISION28_V3_SHA256','HOST_CLOSURE_EXT4_DECISION28_V4_SHA256','cpu')
cpu = replace(cpu, 'execution-code-closure.ext4-decision28.v3.json','execution-code-closure.ext4-decision28.v4.json','cpu')
cpu = replace(cpu, "counts={'stdout':0,'stderr':0};streams={};selector=selectors.DefaultSelector();closure=None\n", "counts={'stdout':0,'stderr':0};streams={};selector=None;closure=None\nEOF={'stdout':False,'stderr':False};process_scans=[];pin_closes=[];reaped=False\nfd_before=fd_after=None;dest_owned=False;error_overflow=0\n\n"+SCAN,'cpu')
start=cpu.index('def descriptor(path):')
end=cpu.index('def observe(row):',start)
cpu = replace(cpu,cpu[start:end],'''def descriptor(path):
    p=Path(path);info=p.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not p.is_symlink()
    digest=hashlib.sha256();size=0;fd=None;failed=None
    try:
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        assert epoch(info)==epoch(os.fstat(fd))
        while block:=os.read(fd,1048576):clock();digest.update(block);size+=len(block)
        assert epoch(info)==epoch(os.fstat(fd))==epoch(p.lstat()) and size==info.st_size
    except BaseException as exc:
        failed=exc;latch(exc)
    finally:
        if fd is not None:
            try:os.close(fd)
            except BaseException as exc:
                latch(exc)
                if failed is None:failed=exc
    if failed is not None:raise failed
    return {'path':str(p),'size_bytes':size,'sha256':digest.hexdigest()}
def write(name,value,late_metadata=False):
    if not late_metadata:clock()
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\\n').encode();assert len(raw)<=(65536 if late_metadata else 1048576)
    stream=None;failed=None
    try:
        assert dest_owned,'controller does not own exclusive destination'
        stream=(DEST/name).open('xb')
        assert stream.write(raw)==len(raw),'short metadata write'
        stream.flush();os.fsync(stream.fileno())
    except BaseException as exc:failed=exc;latch(exc)
    finally:
        if stream is not None:
            try:stream.close()
            except BaseException as exc:
                latch(exc)
                if failed is None:failed=exc
    if failed is not None:raise failed
    if not late_metadata:clock()
    return {'path':str(DEST/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def pin(path,expected=None):
    p=Path(path).resolve(strict=True)
    row={'descriptor':None,'epoch':None,'fd':None,'path':str(p)};pins.append(row)
    row['fd']=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    row['epoch']=epoch(os.fstat(row['fd']))
    row['descriptor']=descriptor(p)
    assert row['epoch']==epoch(os.fstat(row['fd']))==epoch(p.lstat())
    if expected is not None:assert row['descriptor']['sha256']==expected,'original expected input bytes mismatch: '+str(p)
    return row
''','cpu')
cpu = replace(cpu,"    global primary\n    if primary is None:primary=error(exc)\n    else:cleanup_errors.append(error(exc))\n", "    global primary,error_overflow\n    if primary is None:primary=error(exc)\n    elif len(cleanup_errors)<64:cleanup_errors.append(error(exc))\n    else:error_overflow+=1\n",'cpu')
cpu = replace(cpu,"    current=descriptor(p);assert current==row['descriptor'],'original held input changed: '+str(p)\n    return {'descriptor':current,'epoch':epoch(p.lstat())}\n", "    current=descriptor(p);assert current==row['descriptor'],'original held input changed: '+str(p)\n    assert epoch(os.fstat(row['fd']))==row['epoch']==epoch(p.lstat())\n    return {'descriptor':current,'epoch':epoch(p.lstat())}\n",'cpu')
cpu = replace(cpu,'''assert not os.path.lexists(PAIR) and not os.path.lexists(DEST),'original CPU namespaces already occupied'
DEST.mkdir(mode=0o700)
for name in ('stdout','stderr'):streams[name]=(DEST/('original.'+name+'.raw')).open('xb')
try:
''','''try:
    fd_before=fd_count()
    assert not os.path.lexists(PAIR) and not os.path.lexists(DEST),'original CPU namespaces already occupied'
    DEST.mkdir(mode=0o700);dest_owned=True
    selector=selectors.DefaultSelector()
    for name in ('stdout','stderr'):streams[name]=(DEST/('original.'+name+'.raw')).open('xb')
''','cpu')
cpu=replace(cpu,"            except OSError as exc:latch(exc);selector.unregister(key.fileobj);continue\n            if not raw:selector.unregister(key.fileobj);continue\n", "            except OSError as exc:latch(exc);selector.unregister(key.fileobj);continue\n            if not raw:EOF[key.data]=True;selector.unregister(key.fileobj);continue\n",'cpu')
cpu=replace(cpu,"                try:streams[key.data].write(retained);counts[key.data]+=len(retained)\n", "                try:\n                    assert streams[key.data].write(retained)==len(retained),'short original channel write'\n                    counts[key.data]+=len(retained)\n",'cpu')
cpu=replace(cpu,"    child.wait(timeout=max(0,DEADLINE-time.monotonic()))\n", "    child.wait(timeout=max(0,DEADLINE-time.monotonic()));reaped=True\n",'cpu')
# Preserve the stock SIGINT/SIGKILL containment block exactly; only mark reaping after its original wait.
cpu=replace(cpu,"                try:child.wait(timeout=max(0,DEADLINE-time.monotonic()))\n", "                try:child.wait(timeout=max(0,DEADLINE-time.monotonic()));reaped=True\n",'cpu')
cpu=replace(cpu,"                try:child.wait(timeout=min(10,max(0,cleanup_deadline-time.monotonic())))\n", "                try:child.wait(timeout=min(10,max(0,cleanup_deadline-time.monotonic())));reaped=True\n",'cpu')
cpu=replace(cpu,"                    child.kill();signals.append({'signal':'SIGKILL','at_ns':time.time_ns()});child.wait(timeout=max(0,cleanup_deadline-time.monotonic()))\n", "                    child.kill();signals.append({'signal':'SIGKILL','at_ns':time.time_ns()});child.wait(timeout=max(0,cleanup_deadline-time.monotonic()));reaped=True\n",'cpu')
start=cpu.index('        try:\n            while selector.get_map() and time.monotonic()<cleanup_deadline:')
cpu=replace(cpu,cpu[start:],'''        try:
            while selector is not None and selector.get_map() and time.monotonic()<cleanup_deadline:
                for key,_ in selector.select(.1):
                    raw=os.read(key.fd,65536)
                    if not raw:EOF[key.data]=True;selector.unregister(key.fileobj);continue
                    available=1048576-counts[key.data]
                    if available>0:
                        retained=raw[:available]
                        assert streams[key.data].write(retained)==len(retained),'short original drain write'
                        counts[key.data]+=len(retained)
                    if len(raw)>available:exceeded=True;latch(RuntimeError('original drain channel cap'))
            if selector is not None and selector.get_map():latch(RuntimeError('original channel EOF unavailable at bounded teardown'))
        except BaseException as exc:latch(exc)
        finally:
            if selector is not None:
                try:selector.close()
                except BaseException as exc:latch(exc)
            if child is not None:
                for pipe in (child.stdout,child.stderr):
                    if pipe is not None:
                        try:pipe.close()
                        except BaseException as exc:latch(exc)
                try:
                    if child.poll() is not None:
                        child.wait(timeout=max(0,cleanup_deadline-time.monotonic()));reaped=True
                except BaseException as exc:latch(exc)
            for stream in streams.values():
                for action in (stream.flush,lambda stream=stream:os.fsync(stream.fileno()),stream.close):
                    try:action()
                    except BaseException as exc:latch(exc)
    for row in pins:
        try:
            assert row['fd'] is not None and row['descriptor'] is not None and row['epoch'] is not None,'held source acquisition incomplete'
            after.append(observe(row))
        except BaseException as exc:after.append({'original_descriptor':row['descriptor'],'observation_error':error(exc)});latch(exc)
    if child is not None:
        original=child_owner or {'pid':child.pid,'pgid':child.pid,'startticks':None}
        if child_owner is None:latch(RuntimeError('original owner identity unavailable'))
        for scan_index in range(2):
            try:
                scan=scan_original_group(original,cleanup_deadline);process_scans.append(scan)
                if scan['errors'] or scan['error_overflow'] or scan['members'] or scan['member_overflow'] or scan['original_pid_identity']!='absent':
                    latch(RuntimeError('original CLI PID/group absence uncertain or not absent'))
            except BaseException as exc:latch(exc)
        group_members=process_scans[-1]['members'] if process_scans else []
        if not reaped:latch(RuntimeError('original child reap not observed'))
        if not all(EOF.values()):latch(RuntimeError('original channel EOF not observed'))
    def raw_desc(path):
        info=path.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and not path.is_symlink() and info.st_size<=1048576
        fd=None;failed=None;digest=hashlib.sha256();size=0
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            assert epoch(info)==epoch(os.fstat(fd))
            while raw:=os.read(fd,65536):
                assert time.monotonic()<cleanup_deadline,'original15s cleanup deadline'
                size+=len(raw);assert size<=1048576;digest.update(raw)
            assert epoch(info)==epoch(os.fstat(fd))==epoch(path.lstat()) and size==info.st_size
        except BaseException as exc:failed=exc;latch(exc)
        finally:
            if fd is not None:
                try:os.close(fd)
                except BaseException as exc:
                    latch(exc)
                    if failed is None:failed=exc
        if failed is not None:raise failed
        return {'path':str(path),'size_bytes':size,'sha256':digest.hexdigest(),'epoch':epoch(info)}
    cli_terminal=PAIR/'component_cli_terminal.v1.json';original_cli=None;channels={}
    if cli_terminal.exists():
        try:original_cli=raw_desc(cli_terminal)
        except BaseException as exc:latch(exc)
    for name in ('stdout','stderr'):
        try:channels[name]=raw_desc(DEST/('original.'+name+'.raw'))
        except BaseException as exc:channels[name]=None;latch(exc)
    for index,row in enumerate(pins):
        if row['fd'] is None:continue
        try:
            os.close(row['fd']);row['fd']=None;pin_closes.append({'pin_index':index,'closed':True})
        except BaseException as exc:pin_closes.append({'pin_index':index,'closed':False});latch(exc)
    try:
        fd_after=fd_count()
        assert fd_before is not None and fd_after==fd_before,'owned FD baseline not restored'
        assert time.monotonic()<cleanup_deadline,'original15s cleanup deadline elapsed'
    except BaseException as exc:latch(exc)
    late=time.monotonic()>=DEADLINE
    if late:latch(TimeoutError('original outer2250s closed late'))
    terminal=None;terminal_failure=primary;terminal_error_count=len(cleanup_errors);terminal_overflow=error_overflow
    if dest_owned:
        try:
            terminal=write('original.terminal.v1.json',{'source_commit':COMMIT,'image_id':IMAGE,'argv':argv,'owner':child_owner,
                'original_child_pid':None if child is None else child.pid,'original_returncode':None if child is None else child.returncode,
                'timed_out':timed_out,'capture_exceeded':exceeded,'failure':primary,'additional_errors':cleanup_errors,'error_overflow':error_overflow,'signals':signals,
                'elapsed_s':time.monotonic()-START,'pins_before':before,'pins_after':after,'source_count':len(source_pins),'input_count':len(input_pins),
                'stdout':channels['stdout'],'stderr':channels['stderr'],'EOF':EOF,'reaped':reaped,
                'original_cli_terminal':original_cli,'original_cli_process_group_members':group_members,'process_group_scans':process_scans,
                'pin_closes':pin_closes,'all_pin_close_attempts_finished':True,'fd_before':fd_before,'fd_after':fd_after,'accepted':False,'publication_ready':False,
                'container_quiescence':'not inferred from CLI/group status; use original CLI authenticated shutdown and original container receipts'})
            print(json.dumps({'phase':'original_cpu_component_terminal','returncode':None if child is None else child.returncode,'failure':primary,'receipt':terminal}),flush=True)
        except BaseException as exc:latch(exc)
    try:
        fd_after=fd_count()
        assert fd_before is not None and fd_after==fd_before,'final metadata FD baseline not restored'
    except BaseException as exc:latch(exc)
    if time.monotonic()>=DEADLINE:
        if not late:latch(TimeoutError('original outer2250s closed late after terminal'))
        late=True
    if dest_owned and (terminal is None or primary!=terminal_failure or len(cleanup_errors)!=terminal_error_count or error_overflow!=terminal_overflow or late):
        try:
            write('failure.v4.json',{'source_commit':COMMIT,'image_id':IMAGE,'status':'failed','failure':primary,'original_terminal':terminal,
                'terminal_path':str(DEST/'original.terminal.v1.json'),'late':late,'recent_errors':cleanup_errors[-8:],'error_overflow':error_overflow,
                'fd_before':fd_before,'fd_after':fd_after,'all_pin_close_attempts_finished':True,'accepted':False,'publication_ready':False,
                'record_kind':'exclusive bounded finalization failure companion'},late_metadata=True)
        except BaseException as exc:
            latch(exc)
            try:print(json.dumps({'phase':'original_cpu_failed_finalization','failure':primary,'companion_error':error(exc)}),file=sys.stderr,flush=True)
            except BaseException as report_exc:latch(report_exc)
    if dest_owned and time.monotonic()>=DEADLINE and not late:
        late=True;latch(TimeoutError('original outer2250s closed late after final metadata'))
        try:write('late.v4.json',{'source_commit':COMMIT,'status':'failed','failure':primary,'late':True,'accepted':False,'publication_ready':False},late_metadata=True)
        except BaseException as exc:latch(exc)
    if not dest_owned:
        try:print(json.dumps({'phase':'original_cpu_failed_acquisition','failure':primary,'output_namespace_owned':False}),file=sys.stderr,flush=True)
        except BaseException as exc:latch(exc)
sys.exit(0 if child is not None and child.returncode==0 and primary is None and not timed_out and not exceeded else 78)
''','cpu')

def descriptor(path,raw=None):
    raw=path.read_bytes() if raw is None else raw
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

checks=[]
for kind,old,new,filename in [('host',host_old,host,'capture_selected_host_closure_ext4_decision28_v4.py'),('cpu',cpu_old,cpu,'run_original_cpu_component_pair_ext4_decision28_v4.pending.py')]:
    raw=new.encode();inverse=new
    for before,after in reversed(REPLACEMENTS[kind]):
        assert inverse.count(after)==1,(kind,after[:100],inverse.count(after))
        inverse=inverse.replace(after,before,1)
    assert inverse.encode()==old
    before_ast,after_ast=ast.parse(old.decode()),ast.parse(new)
    funcs=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    old_funcs,new_funcs=funcs(before_ast),funcs(after_ast)
    subprocess_calls=lambda tree:[ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('Popen','check_output')]
    assert subprocess_calls(before_ast)==subprocess_calls(after_ast)
    def core_assignments(tree):
        return [ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,(ast.Assign,ast.AugAssign)) and any(isinstance(x,ast.Name) and x.id in ('argv','git','code','entry') for x in (n.targets if isinstance(n,ast.Assign) else [n.target]))]
    assert core_assignments(before_ast)==core_assignments(after_ast)
    checks.append({'kind':kind,'exact_raw_inverse_to_pending_v3':True,'literal_replacements':len(REPLACEMENTS[kind]),
        'unchanged_original_functions':[name for name,value in old_funcs.items() if new_funcs.get(name)==value],
        'changed_original_functions':[name for name,value in old_funcs.items() if new_funcs.get(name)!=value],
        'added_functions':[name for name in new_funcs if name not in old_funcs],
        'original_subprocess_call_ASTs_unchanged':True,'core_argv_assignments_unchanged':True})
    with (OUT/filename).open('xb') as f:f.write(raw)
    diff=''.join(difflib.unified_diff(old.decode().splitlines(True),new.splitlines(True),fromfile='immutable-pending-v3',tofile='custody-successor-v4')).encode()
    with (OUT/(kind+'.v3-to-v4.diff')).open('xb') as f:f.write(diff)
with (OUT/'literal-replacements.v1.json').open('xb') as f:f.write((json.dumps(REPLACEMENTS,sort_keys=True,indent=2)+'\n').encode())
sources=[descriptor(OUT/name) for name in ('capture_selected_host_closure_ext4_decision28_v4.py','run_original_cpu_component_pair_ext4_decision28_v4.pending.py')]
oldprep=json.loads((OLD/'preparation.v1.json').read_bytes())
prep={'schema_version':1,'scope':'Source-only custody successor of frozen blocked pending-v3 stock87 collector and CPU08 controller; unexecuted.',
    'planning_commit':'958a036bc5a55821c712204577fdf4c51c2181c7','source_checkpoint_A':'2a6a42c924ae3447ceda4bd9d1b6db33765c6466',
    'source_descriptors':sources,'origins':[descriptor(OLD/name) for name in ('capture_selected_host_closure_ext4_decision28_v3.py','run_original_cpu_component_pair_ext4_decision28_v3.pending.py')],
    'blocked_review':descriptor(OUT.parent/'decision28-host-cpu08-independent-source-review-v1/review.v1.json'),
    'budgets_unchanged':oldprep['budgets_unchanged'],'bound_runtime_fields':{key:None for key in oldprep['bound_runtime_fields']},
    'future_host_receipt':{'path':'artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json','sha256':None,'size_bytes':None,'owner':None,'terminal':None},
    'future_current95_manifest':None,'CPU08_owner':None,'CPU08_terminal':None,'CPU08_cold_descriptor':None,
    'stock_command_pending':[oldprep['stock_command_pending'][0],'-I','-B',oldprep['stock_command_pending'][3].replace('preparation-v1/capture_selected_host_closure_ext4_decision28_v3.py','preparation-v2/capture_selected_host_closure_ext4_decision28_v4.py'),None],
    'CPU08_command_pending':[oldprep['cpu08_command_pending'][0],'-I','-B',oldprep['cpu08_command_pending'][3].replace('preparation-v1/run_original_cpu_component_pair_ext4_decision28_v3.pending.py','preparation-v2/run_original_cpu_component_pair_ext4_decision28_v4.pending.py'),None,None],
    'stock_output_namespace':'artifacts/benchmark_recovery_20260930/decision28-host-closure-ext4-v4-original',
    'CPU08_namespaces':['artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08','artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08-original-controller'],
    'CPU08_null_guard_before_all_acquisitions':True,'six_input_roles':oldprep['six_input_roles'],
    'four_existing_capability_calibration_model_worker_pins_unchanged':True,'runtime_and_host_binding_remain_null':True,
    'failure_companion_bytes':65536,'original_normal_metadata_channel_bytes':1048576,
    'stock_host_held_files':'87 source files plus physical controller/interpreter across capture; count87 loader scope unchanged',
    'CPU08_held_files':'Original six roles+87 source files+interpreter+controller=95; incomplete acquisitions remain registered for release.',
    'closure_changes':['First cause latched before cleanup; finite secondary errors.','Every partial acquisition registered inside protected try; exclusive output owner required.','Every flush/fsync/selector/pipe/stream/pin close attempted independently.','Full SHA and seven-field held/named epochs checked through finalization.','Actual FD baseline restored before terminal and after metadata.','Per-channel actual EOF, original child reap, two error-aware process scans; uncertain absence fails.','Terminal follows held-pin release; exclusive <=64KiB failure/late companion retains late/metadata errors.'],
    'dispatch_grant':False,'target_import_compile_execution':False,'tests_engines_models_Git_hardware_operations':False,
    'status':'prepared_unexecuted_requires_independent_source_review_and_actual_future_bindings'}
with (OUT/'preparation.v1.json').open('xb') as f:f.write((json.dumps(prep,sort_keys=True,indent=2)+'\n').encode())
audit={'schema_version':1,'scope':'Finite author static AST/raw-literal audit; not independent approval.','source_descriptors':sources,'checks':checks,
    'literal_inverse_receipt':descriptor(OUT/'literal-replacements.v1.json'),'preparation':descriptor(OUT/'preparation.v1.json'),
    'source_checkpoint_A':'2a6a42c924ae3447ceda4bd9d1b6db33765c6466','runtime_image_and_receipt_and_B_and_newhost_unknown':True,
    'original_scientific_argv_and_bounds_preserved':True,'target_helpers_imported_compiled_or_executed':False,
    'tests_engine_Git_models_hardware_operations':False,'metadata_handles_released':True,'peer_review':'required; author cannot certify independent approval'}
with (OUT/'author-review.v1.json').open('xb') as f:f.write((json.dumps(audit,sort_keys=True,indent=2)+'\n').encode())
for path,raw in [(OLD/'capture_selected_host_closure_ext4_decision28_v3.py',host_old),(OLD/'run_original_cpu_component_pair_ext4_decision28_v3.pending.py',cpu_old)]:
    assert path.read_bytes()==raw,'immutable pending source changed during authoring'
print(json.dumps({'sources':sources,'checks':checks,'preparation':descriptor(OUT/'preparation.v1.json'),'author':descriptor(OUT/'author-review.v1.json')},indent=2))
