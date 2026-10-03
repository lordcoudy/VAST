"""Original outer capture of the separately authorized once-only terminal query."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
OUT = HERE / 'original-terminal-events-observation-outer-attempt01'
PYTHON = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
SOURCE = HERE / 'observe_original_primary_worker_terminal_events_v5.py'
START = time.monotonic()
HARD = START + 40
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
FD_BEFORE = len(os.listdir('/proc/self/fd'))

def owner(pid):
    path = Path('/proc') / str(pid)
    raw = (path / 'stat').read_bytes()
    values = raw[raw.rfind(b')') + 2:].split()
    status = dict(line.split(':', 1) for line in (path / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'startticks': int(values[19]), 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': BOOT}

def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('ascii')
    with (OUT / name).open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return pin(OUT / name)

source_paths = [SOURCE, HERE / 'preparation.v4.json', HERE / 'root-one-terminal-events-grant.v1.json', HERE.parent / 'component-cpu07-worker-events-independent-source-review-v1/review.v3.json']
before = [pin(path) for path in source_paths]
assert before[0]['size_bytes'] == 15049 and before[0]['sha256'] == '312d3ea99ff396b2e9074cbc1c1f9958ef3d8ceb6dd29ec01cc57dc71a4fed1d'
assert before[1]['size_bytes'] == 8186 and before[1]['sha256'] == 'e6d57e23c7f53610a6237199b58f451f95d2e9b130c2fea7a48976ec01592bbb'
assert before[3]['size_bytes'] == 3424 and before[3]['sha256'] == '3d119d99cc00ac1e4337865d22a1ead83e28f0864d5ee4923e4d1c9c5e97d459'
assert not os.path.lexists(OUT)
OUT.mkdir(mode=0o700)
argv = ['/usr/bin/timeout', '--signal=TERM', '--kill-after=10s', '30s', PYTHON, '-I', '-B', str(SOURCE)]
controller = owner(os.getpid())
failure = None
additional = []
child = None
child_owner = None
streams = {}
caps = {'stdout': 8192, 'stderr': 2048}
counts = dict.fromkeys(caps, 0)
eof = dict.fromkeys(caps, False)
signals = []
selector = selectors.DefaultSelector()

def latch(error):
    global failure
    value = {'type': type(error).__name__, 'message': str(error)[:4096]}
    if failure is None:
        failure = value
    else:
        additional.append(value)

try:
    streams = {name: (OUT / (name + '.raw')).open('xb') for name in caps}
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    child_owner = owner(child.pid)
    save('launch.v1.json', {'argv': argv, 'at_ns': time.time_ns(), 'controller': controller, 'timeout_owner': child_owner, 'source_before': before, 'work_s': 30, 'cleanup_s': 10})
    for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
        os.set_blocking(pipe.fileno(), False)
        selector.register(pipe, selectors.EVENT_READ, name)
    while selector.get_map() or child.poll() is None:
        if time.monotonic() >= HARD:
            raise TimeoutError('outer original30+10 containment elapsed')
        for key, _ in selector.select(.02):
            raw = os.read(key.fd, 65536)
            if not raw:
                eof[key.data] = True
                selector.unregister(key.fileobj)
                continue
            room = caps[key.data] - counts[key.data]
            retained = raw[:max(0, room)]
            if retained:
                streams[key.data].write(retained)
                counts[key.data] += len(retained)
            if len(raw) > room:
                raise ValueError('outer metadata channel cap exceeded')
    child.wait(timeout=max(.001, HARD - time.monotonic()))
except BaseException as error:
    latch(error)
finally:
    if child is not None and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGKILL)
            signals.append({'signal': 'SIGKILL', 'at_ns': time.time_ns()})
            child.wait(timeout=max(.001, HARD - time.monotonic()))
        except BaseException as error:
            latch(error)
    try:
        selector.close()
    except BaseException as error:
        latch(error)
    if child is not None:
        for pipe in (child.stdout, child.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except BaseException as error:
                    latch(error)
    for stream in streams.values():
        try:
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException as error:
            latch(error)
        finally:
            try:
                stream.close()
            except BaseException as error:
                latch(error)
    after = [pin(path) for path in source_paths]
    if before != after:
        latch(ValueError('original capture sources changed'))
    fd_after = len(os.listdir('/proc/self/fd'))
    if fd_after != FD_BEFORE:
        latch(ValueError('outer file descriptor release drifted'))
    if not all(eof.values()):
        latch(ValueError('outer original EOF incomplete'))
    result = save('capture.v1.json', {'scope': 'once-only historical exact-CID terminal events original outer capture', 'argv': argv, 'controller': controller, 'owner': child_owner, 'returncode': None if child is None else child.returncode, 'failure': failure, 'additional_errors': additional, 'signals': signals, 'eof': eof, 'channels': {name: pin(OUT / (name + '.raw')) for name in streams}, 'fd_before': FD_BEFORE, 'fd_after': fd_after, 'source_before': before, 'source_after': after, 'elapsed_s': time.monotonic() - START, 'accepted': False})
    print(json.dumps({'capture': result, 'returncode': None if child is None else child.returncode, 'failure': failure}), flush=True)
    if time.monotonic() >= HARD:
        save('late-failure.v1.json', {'original_capture': result, 'elapsed_s': time.monotonic() - START, 'status': 'failed'})
        latch(TimeoutError('final original30+10 containment exceeded'))
raise SystemExit(0 if failure is None and child is not None and child.returncode == 0 else 78)
