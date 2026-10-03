"""One original pure-child invocation, 110s execution plus10s containment."""
import hashlib
import argparse
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project-root',required=True)
parser.add_argument('--font-cache',required=True)
for resource in ('cpu','gpu'):
    parser.add_argument('--'+resource+'-original-terminal',required=True)
    parser.add_argument('--'+resource+'-original-terminal-sha256',required=True)
    parser.add_argument('--'+resource+'-original-terminal-size',required=True,type=int)
args=parser.parse_args()
BASE = Path(__file__).parent
OUT = BASE / 'attempt01'
START = time.monotonic()
EXECUTION_END, HARD_END = START + 110, START + 120
OUT.mkdir(mode=0o700, exist_ok=False)

def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def owner(pid):
    try:
        fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
        status={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line}
        return {'pid': pid, 'ppid': int(fields[1]), 'pgid': int(fields[2]), 'session': int(fields[3]),
                'startticks':int(fields[19]),'uid':int(status['Uid'].split()[0]),'gid':int(status['Gid'].split()[0]),'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None

def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    assert len(raw) <= 1048576
    with (OUT / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'path': str(OUT / name), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

source_before = {name: descriptor(BASE / name) for name in ('reduce.py','render.py','run.py')}
argv=[sys.executable,'-I','-B',str(BASE/'reduce.py'),'--project-root',args.project_root,
      '--output-dir',str(OUT),'--execution-deadline-ns',str(int(EXECUTION_END*1e9)),'--font-cache',args.font_cache]
for resource in ('cpu','gpu'):
    for suffix in ('original-terminal','original-terminal-sha256','original-terminal-size'):
        argv.extend(['--'+resource+'-'+suffix,str(getattr(args,resource+'_'+suffix.replace('-','_')))])
child = None
first, errors, timeout, overflow, observed_eof = None, [], False, False, set()
files = {name: (OUT / (name + '.raw')).open('xb') for name in ('stdout', 'stderr')}
sizes = {name: 0 for name in files}
selector = selectors.DefaultSelector()

def latch(exc):
    global first
    value = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
    if first is None:
        first = value
    elif len(errors) < 16:
        errors.append(value)

def contain():
    if child is not None and child.poll() is None:
        # This original unreaped Popen child owns its private group; the pure child may not fork.
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=max(.001, HARD_END - time.monotonic()))

try:
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    child_owner = owner(child.pid)
    save('launch.v1.json', {'argv': argv, 'observer': owner(os.getpid()), 'child': child_owner,
        'source_before': source_before, 'initial_head': '0ad78d6abdb3c526544a17185af7fe8094716735',
        'execution_budget_s': 110, 'teardown_budget_s': 10,
        'scope':'Pure closed four-arm original data reduction/render; no benchmark/model/engine calls.'})
    for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
        os.set_blocking(pipe.fileno(), False)
        selector.register(pipe, selectors.EVENT_READ, name)
    while selector.get_map() or child.poll() is None:
        if time.monotonic() >= EXECUTION_END:
            timeout = True
            contain()
        if time.monotonic() >= HARD_END:
            raise TimeoutError('original reducer capture/containment exceeded120s')
        for key, _ in selector.select(.05):
            raw = os.read(key.fd, 65536)
            if not raw:
                observed_eof.add(key.data)
                selector.unregister(key.fileobj)
                continue
            available = 1048576 - sizes[key.data]
            prefix = raw[:max(0, available)]
            files[key.data].write(prefix); sizes[key.data] += len(prefix)
            if len(prefix) != len(raw):
                overflow = True
                contain()
    child.wait(timeout=max(.001, HARD_END - time.monotonic()))
except BaseException as exc:
    latch(exc)
finally:
    try:
        contain()
    except BaseException as exc:
        latch(exc)
    try:selector.close()
    except BaseException as exc:latch(exc)
    if child is not None:
        for pipe in (child.stdout,child.stderr):
            try:pipe.close()
            except BaseException as exc:latch(exc)
    for stream in files.values():
        try:
            stream.flush(); os.fsync(stream.fileno())
        except BaseException as exc:
            latch(exc)
        finally:
            try:stream.close()
            except BaseException as exc:latch(exc)
    source_after = {name: descriptor(BASE / name) for name in source_before}
    group_members = []
    if child is not None:
        for path in Path('/proc').iterdir():
            if path.name.isdigit():
                observed = owner(int(path.name))
                if observed is not None and observed['pgid'] == child.pid:
                    group_members.append(observed)
    custody = OUT / 'custody-and-comparison.v1.json'
    custody_value = json.loads(custody.read_bytes()) if custody.exists() else None
    okay = (child is not None and child.returncode == 0 and first is None and not timeout and not overflow
            and observed_eof == set(files) and not group_members and source_before == source_after
            and custody_value is not None and custody_value['fd_holds_released']
            and custody_value['primary_error'] is None and custody_value['reduced_arms'] == 4)
    terminal = save('terminal.v1.json', {'schema_version': 1, 'scope': 'Pure sidecar reduction only; Original CPU06/GPU01 receipts required; pure reduction grants no hardware/full authority',
        'child': child_owner if child is not None else None, 'original_child_returncode': None if child is None else child.returncode,
        'timed_out': timeout, 'capture_exceeded': overflow, 'primary_error': first, 'additional_errors': errors,
        'source_before': source_before, 'source_after': source_after, 'original_child_current': None if child is None else owner(child.pid),
        'original_group_members': group_members, 'observed_eof': sorted(observed_eof),
        'outputs': {name: descriptor(OUT / (name + '.raw')) for name in files},
        'custody': descriptor(custody) if custody.exists() else None,
        'recomputed_summaries': descriptor(OUT / 'recomputed-summaries.v1.json') if (OUT / 'recomputed-summaries.v1.json').exists() else None,
        'exports':descriptor(OUT/'exports-and-interpretation.v1.json') if (OUT/'exports-and-interpretation.v1.json').exists() else None,
        'completed_pure_reduction': okay, 'measurement_acceptance': False, 'elapsed_s': time.monotonic() - START})
    if time.monotonic() > HARD_END:
        okay = False
        save('late-failure.v1.json', {'failed': True, 'original_terminal': terminal, 'reason': 'Original120s deadline exceeded', 'elapsed_s': time.monotonic() - START})
    print(json.dumps({'terminal': terminal, 'completed_pure_reduction': okay}), flush=True)
sys.exit(0 if okay else 78)
