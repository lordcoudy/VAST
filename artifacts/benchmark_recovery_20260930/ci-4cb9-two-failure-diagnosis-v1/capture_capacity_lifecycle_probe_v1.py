"""One bounded original small-subprocess unit, no namespace/model/engine work."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

BASE = Path(__file__).resolve().parent
OUT = BASE / 'capacity-controlled-lifecycle-attempt01'
ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261001-4cb9d831')
PYTHON = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
CHILD = BASE / 'probe_capacity_lifecycle_child_v1.py'
SOURCES = ('scripts/publication_operational_process_custody_v1.py',
           'tests/test_publication_operational_process_custody_v1.py',
           'scripts/publication_operational_request_domain_v1.py',
           'scripts/publication_child_evidence_materializer_v1.py')
started = time.monotonic()
OUT.mkdir()

def pin(path):
    raw = path.read_bytes()
    info = path.lstat()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'epoch': [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}

def write(name, value):
    with (OUT / name).open('xb') as output:
        output.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        output.flush()
        os.fsync(output.fileno())

def owner(pid):
    raw = Path('/proc/%d/stat' % pid).read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    info = Path('/proc/%d' % pid).stat()
    return {'pid': pid, 'ppid': int(fields[1]), 'pgid': int(fields[2]), 'startticks': int(fields[19]),
        'uid': info.st_uid, 'gid': info.st_gid, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

before = [pin(ROOT / name) for name in SOURCES] + [pin(CHILD), pin(Path(__file__).resolve())]
head = subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(ROOT), 'rev-parse', 'HEAD'],
    capture_output=True, timeout=10, check=True).stdout.decode().strip()
assert head == '4cb9d8313cca71256179bc3b59cc6f9137e7b8ba'
argv = [PYTHON, '-I', '-B', str(CHILD), str(OUT)]
process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
identity = owner(process.pid)
write('launch.v1.json', {'argv': argv, 'source_before': before, 'source_head': head,
                        'owner': identity, 'deadline_s': 120, 'cleanup_s': 10,
                        'scope': 'three controlled real-child lifecycle cases; no hosted-cause claim'})
flags = {'exceeded': False, 'read_errors': []}

def drain(pipe, name):
    total = 0
    try:
        with (OUT / name).open('xb') as output:
            while True:
                raw = pipe.read(65536)
                if not raw:
                    break
                total += len(raw)
                if total > 1024 * 1024:
                    flags['exceeded'] = True
                    os.killpg(process.pid, signal.SIGTERM)
                    break
                output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    except BaseException as error:
        flags['read_errors'].append(type(error).__name__ + ': ' + str(error))
    finally:
        pipe.close()

threads = [threading.Thread(target=drain, args=(process.stdout, 'stdout.raw')),
           threading.Thread(target=drain, args=(process.stderr, 'stderr.raw'))]
for thread in threads:
    thread.start()
timed_out = False
try:
    process.wait(timeout=max(.001, 120 - (time.monotonic() - started)))
except subprocess.TimeoutExpired:
    timed_out = True
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
for thread in threads:
    thread.join(timeout=max(.001, 130 - (time.monotonic() - started)))
assert not any(thread.is_alive() for thread in threads)
after = [pin(Path(row['path'])) for row in before]
assert after == before
scans = []
for _ in range(2):
    members = []
    errors = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fact = owner(int(path.name))
            if fact['pgid'] == identity['pgid'] and fact['uid'] == identity['uid']:
                members.append(fact)
        except (FileNotFoundError, ProcessLookupError):
            pass
        except BaseException as error:
            errors.append({'pid': path.name, 'type': type(error).__name__})
    scans.append({'group_members': members, 'read_errors': errors})
write('terminal.v1.json', {'owner': identity, 'returncode': process.returncode, 'timed_out': timed_out,
    'elapsed_s': time.monotonic() - started, 'capture': flags, 'source_before': before, 'source_after': after,
    'stdout': pin(OUT / 'stdout.raw'), 'stderr': pin(OUT / 'stderr.raw'), 'process_scans': scans,
    'all_capture_fds_closed': True, 'source_mutation': False, 'full_ci_invocations': 0,
    'hardware_acceptance': False})
assert time.monotonic() - started <= 120
assert not timed_out and not flags['exceeded'] and not flags['read_errors']
assert all(not row['group_members'] for row in scans)
print(json.dumps({'terminal': pin(OUT / 'terminal.v1.json'), 'original_unit_returncode': process.returncode}))
