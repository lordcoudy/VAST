"""Local source-boundary regression capture; no component or Docker execution."""
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUTPUT = Path(__file__).parent / sys.argv[1]
OUTPUT.mkdir(exist_ok=False)
original_path = ROOT / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04-original-controller/original.terminal.v1.json'
assert hashlib.sha256(original_path.read_bytes()).hexdigest() == '88b9c117f75b45454b8facc781e1bb291750de388b85f03c31fe7135b1496b0e'
original = json.loads(original_path.read_bytes())
EXPECTED = {row['descriptor']['path']: row['descriptor'] for row in original['pins_before']}
assert len(EXPECTED) == 95
PATHS = tuple(EXPECTED) + tuple(str(Path(__file__).parent / name) for name in
    ('run_reader.py', 'corrected_component_runtime_v1.py', 'arguments.v1.json', 'observe.py')) + (str(original_path),)
held = {}
def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
LIMIT = 1024 * 1024

def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch': epoch(path.lstat())}

def pins():
    return {path: descriptor(ROOT / path) for path in PATHS}

def owner(pid):
    try:
        text = Path('/proc', str(pid), 'stat').read_text()
        row = text[text.rfind(')') + 2:].split()
        status = Path('/proc', str(pid), 'status').read_text().splitlines()
        facts = {line.split(':', 1)[0]: line.split(':', 1)[1].split() for line in status if ':' in line}
        return {'pid': pid, 'ppid': int(row[1]), 'pgid': int(row[2]), 'startticks': int(row[19]),
                'uid': int(facts['Uid'][0]), 'gid': int(facts['Gid'][0]),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None

def group_members(pgid):
    found = []
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            fact = owner(int(path.name))
            if fact and fact['pgid'] == pgid:
                found.append(fact)
    return found

def save(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())

for path in PATHS:
    named = Path(path)
    fd = os.open(named, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    held[path] = (fd, epoch(os.fstat(fd)))
before = pins()
for path, expected in EXPECTED.items():
    assert {key: before[path][key] for key in expected} == expected, 'Original producer source bytes are not present: ' + path
for path, (fd, snapshot) in held.items():
    assert snapshot == before[path]['epoch'] == epoch(os.fstat(fd))
argv = [sys.executable, '-I', '-B', str(Path(__file__).parent / 'run_reader.py')]
started_at_ns, started = time.time_ns(), time.monotonic()
files = {name: (OUTPUT / (name + '.raw')).open('xb') for name in ('stdout', 'stderr')}
child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
child_owner = owner(child.pid)
save(OUTPUT / 'launch.v1.json', {'argv': argv, 'observer': owner(os.getpid()), 'child': child_owner,
                              'started_at_ns': started_at_ns, 'source_before': before})
selector = selectors.DefaultSelector()
for name, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
    os.set_blocking(pipe.fileno(), False)
    selector.register(pipe, selectors.EVENT_READ, name)
sizes = dict.fromkeys(files, 0)
timed_out = exceeded = False
try:
    while selector.get_map():
        now = time.monotonic()
        if now - started > 600:
            timed_out = True
            if child.poll() is None:
                child.kill()
        if now - started > 615:
            raise TimeoutError('original focused pipes did not close after containment')
        for key, _ in selector.select(0.05):
            raw = os.read(key.fileobj.fileno(), 65536)
            if not raw:
                selector.unregister(key.fileobj)
                continue
            name = key.data
            if sizes[name] + len(raw) > LIMIT:
                exceeded = True
                if child.poll() is None:
                    child.kill()
                continue
            files[name].write(raw)
            sizes[name] += len(raw)
    child.wait(timeout=5)
finally:
    try:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    finally:
        selector.close()
        child.stdout.close()
        child.stderr.close()
        for stream in files.values():
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
after = pins()
for path, (fd, snapshot) in held.items():
    assert snapshot == epoch(os.fstat(fd)) == after[path]['epoch']
    os.close(fd)
report = {'schema_version': 1, 'artifact_kind': 'vast_cpu04_corrected_cold_consumer_execution_v1',
          'argv': argv, 'child': child_owner, 'original_child_returncode': child.returncode,
          'started_at_ns': started_at_ns, 'terminal_at_ns': time.time_ns(),
          'elapsed_s': time.monotonic() - started, 'timed_out': timed_out, 'capture_exceeded': exceeded,
          'source_before': before, 'source_after': after, 'sources_stable': before == after, 'execution_budget_s': 600, 'teardown_budget_s': 15, 'original_producer_byte_pins': 95, 'separately_pinned_reader': True, 'original_cli_remains_failed': True,
          'original_child_current': owner(child.pid), 'original_group_members': group_members(child.pid),
          'outputs': {name: descriptor(OUTPUT / (name + '.raw')) for name in files},
          'scope': 'One separately pinned corrected cold consumer under original v5 producer source bytes; actual readonly image inspections and original model numeric validation are stock operations. No new native measurement/guardian/container/device probe/reserve. Original CPU04 CLI remains failed; current custody epochs are new observations, never rebound to original execution witnesses.'}
save(OUTPUT / 'terminal.v1.json', report)
print(json.dumps({'receipt': descriptor(OUTPUT / 'terminal.v1.json'), 'returncode': child.returncode,
                  'timed_out': timed_out, 'capture_exceeded': exceeded, 'sources_stable': before == after, 'execution_budget_s': 600, 'teardown_budget_s': 15, 'original_producer_byte_pins': 95, 'separately_pinned_reader': True, 'original_cli_remains_failed': True,
                  'original_group_members': report['original_group_members']}, sort_keys=True))
raise SystemExit(child.returncode or timed_out or exceeded or before != after or bool(report['original_group_members']))
