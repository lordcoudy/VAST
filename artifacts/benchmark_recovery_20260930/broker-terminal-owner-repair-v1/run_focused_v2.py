"""Bounded original RED/GREEN capture; no policy, model, daemon or real namespace."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = Path(__file__).resolve().parent
PYTHON = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
NEW = ('test_normal_losing_owner_commit_cannot_write_elected_owner_terminal',
       'test_held_losing_owner_commit_cannot_write_elected_owner_terminal')

def pin(path):
    raw = path.read_bytes()
    info = path.stat()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'epoch': [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}

def write(path, value):
    with path.open('xb') as output:
        output.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        output.flush()
        os.fsync(output.fileno())

def owner(pid):
    raw = Path('/proc/%d/stat' % pid).read_text()
    fields = raw[raw.rfind(')') + 2:].split()
    info = Path('/proc/%d' % pid).stat()
    return {'pid': pid, 'ppid': int(fields[1]), 'pgid': int(fields[2]), 'startticks': int(fields[19]),
            'uid': info.st_uid, 'gid': info.st_gid, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

mode = sys.argv[1]
if mode == 'child':
    import unittest
    destination = Path(sys.argv[2])
    scope = sys.argv[3]
    sys.path.insert(0, str(ROOT / 'tests'))
    import test_backend_publication_broker_terminal_v3 as test
    test.EVIDENCE_DIR = destination / 'fixtures'
    test.EVIDENCE_DIR.mkdir()
    methods = NEW if scope in ('red', 'green') else tuple(name for name in dir(test.BackendPublicationBrokerTerminalV3Tests)
        if name.startswith('test_') and name != 'test_original_namespace_completion_still_emits_valid_durable_result')
    # The unchanged real-namespace completion unit remains mandatory in full CI;
    # this capture intentionally tests only journal/isolated-child source repair.
    ids = ['test_backend_publication_broker_terminal_v3.BackendPublicationBrokerTerminalV3Tests.' + name for name in methods]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in ids)
    before = [pin(Path(module.__file__).resolve()) for module in list(sys.modules.values())
              if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT)
              and Path(module.__file__).resolve().is_file()]
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = [pin(Path(row['path'])) for row in before]
    write(destination / 'unit-result.v1.json', {'ids': ids, 'tests_run': result.testsRun,
        'failures': [{'id': item.id(), 'traceback': error} for item, error in result.failures],
        'errors': [{'id': item.id(), 'traceback': error} for item, error in result.errors],
        'skips': [{'id': item.id(), 'reason': reason} for item, reason in result.skipped],
        'source_before': before, 'source_after': after, 'sources_unchanged': before == after,
        'omitted_actual_namespace_id': 'test_backend_publication_broker_terminal_v3.BackendPublicationBrokerTerminalV3Tests.test_original_namespace_completion_still_emits_valid_durable_result',
        'scope': 'real journal/isolated-child units; explicit injected namespace refusal; no hosted-cause or hardware grant'})
    raise SystemExit(0 if result.wasSuccessful() and before == after else 1)

assert mode in ('red', 'green')
started = time.monotonic()
out = BASE / ('attempt-03-observation-cleanup-red-unexecuted' if mode == 'red' else 'attempt-03-observation-cleanup-green')
out.mkdir()
before = [pin(ROOT / name) for name in ('scripts/backend_publication_process_supervisor_v3.py',
    'tests/test_backend_publication_broker_terminal_v3.py', 'tests/test_backend_publication_process_supervisor_v3.py')]
before.append(pin(Path(__file__).resolve()))
argv = [PYTHON, '-I', '-B', str(Path(__file__).resolve()), 'child', str(out), mode]
process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
identity = owner(process.pid)
write(out / 'launch.v1.json', {'argv': argv, 'owner': identity, 'source_before': before,
    'execution_seconds': 120, 'cleanup_seconds': 10, 'mode': mode})
flags = {'exceeded': False, 'read_errors': []}

def drain(pipe, name):
    total = 0
    try:
        with (out / name).open('xb') as output:
            while raw := pipe.read(65536):
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
children = [json.loads(path.read_bytes()) for path in out.glob('fixtures/*/*terminal.json')]
groups = {identity['pgid']} | {row['original_session'] for row in children if row.get('original_session') is not None}
scans = []
for _ in range(2):
    members, errors = [], []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            observed = owner(int(path.name))
            if observed['pgid'] in groups and observed['uid'] == identity['uid']:
                members.append(observed)
        except (FileNotFoundError, ProcessLookupError):
            pass
        except BaseException as error:
            errors.append({'pid': path.name, 'type': type(error).__name__})
    scans.append({'owned_group_members': members, 'read_errors': errors})
write(out / 'execution.v1.json', {'owner': identity, 'returncode': process.returncode, 'timed_out': timed_out,
    'elapsed_s': time.monotonic() - started, 'capture': flags, 'source_before': before, 'source_after': after,
    'stdout': pin(out / 'stdout.raw'), 'stderr': pin(out / 'stderr.raw'), 'process_scans': scans,
    'actual_child_terminals': children, 'all_capture_fds_closed': True, 'source_unchanged': before == after,
    'full_ci_invocations': 0, 'real_namespace_invocations': 0, 'hardware_acceptance': False})
assert time.monotonic() - started <= 120 and not timed_out and not flags['exceeded'] and not flags['read_errors']
assert before == after and all(not row['owned_group_members'] for row in scans)
print(json.dumps({'execution': pin(out / 'execution.v1.json'), 'original_unit_returncode': process.returncode}))
