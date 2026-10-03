"""One original stock90-minute exact-source CPU lane; retain raw channels and ownership."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

HERE = Path(__file__).parent
OUT = HERE / 'original-full-ci-attempt01'
ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
RESULT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D-original-output')
assert len(sys.argv) == 4, 'usage: capture ACTUAL_COMMIT ACTUAL_RECIPE_SIZE ACTUAL_RECIPE_SHA256'
COMMIT = sys.argv[1]
assert len(COMMIT) == 40 and all(c in '0123456789abcdef' for c in COMMIT)
RECIPE_SIZE = int(sys.argv[2])
RECIPE_SHA = sys.argv[3]
assert 0 < RECIPE_SIZE <= 1024 * 1024 and len(RECIPE_SHA) == 64 and all(c in '0123456789abcdef' for c in RECIPE_SHA)
START_NS = time.monotonic_ns()
END_NS = START_NS + 5400 * 10**9
HARD_NS = END_NS + 10 * 10**9
MAX_CHANNEL = 4 * 1024 * 1024
PINS = {}
child = None
primary = None
closes = []
signals = []
counts = {'stdout': 0, 'stderr': 0}
eof = set()
original = None
output_owned = False
streams = {}
selector = selectors.DefaultSelector()

def clock(cleanup=False):
    if time.monotonic_ns() >= (HARD_NS if cleanup else END_NS):
        raise TimeoutError('original full CI5400+10 bound')

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def err(e):
    return {'type': type(e).__name__, 'message': str(e)[:4096]}

def owner(pid):
    p = Path('/proc', str(pid))
    f = (p / 'stat').read_text().rsplit(')', 1)[1].split()
    ids = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(f[1]), 'pgid': int(f[2]), 'session': int(f[3]),
            'startticks': int(f[19]), 'uid': int(ids['Uid'].split()[0]),
            'gid': int(ids['Gid'].split()[0]),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

def write(name, value):
    clock(cleanup=True)
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    assert len(raw) <= MAX_CHANNEL
    with (OUT / name).open('xb') as f:
        assert f.write(raw) == len(raw)
        f.flush()
        os.fsync(f.fileno())

def digest(fd, p, cleanup=False):
    clock(cleanup)
    s = os.fstat(fd)
    before = epoch(s)
    assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 1024 * 1024
    assert before == epoch(p.lstat()) and p.resolve(strict=True) == p
    h = hashlib.sha256()
    count = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while b := os.read(fd, 65536):
        clock(cleanup)
        count += len(b)
        assert count <= 1024 * 1024
        h.update(b)
    assert count == s.st_size and before == epoch(os.fstat(fd)) == epoch(p.lstat())
    return {'path': str(p), 'size_bytes': count, 'sha256': h.hexdigest(), 'epoch7': before}

def pin(p):
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        value = digest(fd, p)
        PINS[p] = (fd, value)
        return value
    except BaseException:
        os.close(fd)
        raise

def scan():
    found = []
    errors = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            f = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            if original and (int(p.name) == original['pid'] or int(f[2]) == original['pgid'] or int(f[3]) == original['session']):
                found.append(owner(int(p.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            errors.append({'pid': int(p.name), 'type': type(e).__name__, 'errno': getattr(e, 'errno', None)})
    return {'at_ns': time.time_ns(), 'members': found, 'errors': errors}

try:
    assert os.getuid() == os.getgid() == 1000 and sys.version_info[:3] == (3, 12, 3)
    assert ROOT.resolve(strict=True) == ROOT and ROOT.stat().st_uid == ROOT.stat().st_gid == 1000
    assert not os.path.lexists(OUT) and not os.path.lexists(RESULT)
    OUT.mkdir(mode=0o700)
    output_owned = True
    recipe_path = HERE / 'recipe.bound.v1.json'
    actual_recipe = pin(recipe_path)
    assert actual_recipe['size_bytes'] == RECIPE_SIZE and actual_recipe['sha256'] == RECIPE_SHA
    recipe_fd = PINS[recipe_path][0]
    os.lseek(recipe_fd, 0, os.SEEK_SET)
    recipe_raw = os.read(recipe_fd, RECIPE_SIZE + 1)
    assert len(recipe_raw) == RECIPE_SIZE and hashlib.sha256(recipe_raw).hexdigest() == RECIPE_SHA
    recipe = json.loads(recipe_raw)
    assert recipe['source_commit'] == COMMIT and recipe['checkout'] == str(ROOT) and recipe['output'] == str(RESULT)
    assert recipe['benchmark_root_commit_untouched'] == 'a00aa57f7d9534f8e7920f14f70d6a75a23570ed' and COMMIT != recipe['benchmark_root_commit_untouched']
    assert recipe['benchmark_source_impact_review']=={'path': '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-ci-clock-independent-source-review-v1/review.v1.json', 'size_bytes': 9951, 'sha256': '835bf6c7c991c78062adc39459b34f51eab7c598c71185a7b00fe777f62f9d6d'}
    assert recipe['benchmark_source_impact_inventory']=={'path': '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-ci-clock-independent-source-review-v1/source-impact.v1.json', 'size_bytes': 160709, 'sha256': 'dcdc63621620f579653574d0a1380baac2d683c117d83b8b194b46e67abb2a41'}
    assert recipe['reviewed_ci_path_pins']=={'scripts/ci_namespace_diagnostic_v1.py': {'size_bytes': 25359, 'sha256': 'bc69cdd5db314b7421d87fdaeb3a88d9411ae0f2e29713f75bc8909dfe8b0292'}, 'scripts/ci_userns_profile_v1.py': {'size_bytes': 28890, 'sha256': '5bd7622130c41d8bef03d2da87f87c987738478a5b77412857fd85f24c73cf43'}, 'tests/test_ci_namespace_diagnostic_v1.py': {'size_bytes': 33264, 'sha256': '5c8519ff1a1d600ba6ed72051498dd0da62f68d89e29b48079f546315bb7ac64'}, 'tests/test_ci_userns_profile_v1.py': {'size_bytes': 41955, 'sha256': 'dbcea702679255fd64bb223875385fc1800ed0946958e83ceefda59a0fdc2695'}}
    for relative, expected in recipe['source_pins'].items():
        actual = pin(ROOT / relative)
        assert actual['size_bytes'] == expected['size_bytes'] and actual['sha256'] == expected['sha256']
    pin(Path(__file__))
    assert recipe_path in PINS
    git = ['/usr/bin/git', '-c', 'core.longpaths=true', '-C', str(ROOT)]
    assert subprocess.check_output([*git, 'rev-parse', 'HEAD'], timeout=30) == (COMMIT + '\n').encode()
    assert subprocess.check_output([*git, 'status', '--porcelain=v1', '-z', '--untracked-files=no'], timeout=30) == b''
    python = str(Path(sys.executable).resolve(strict=True))
    argv = ['/usr/bin/timeout', '--verbose', '--signal=TERM', '--kill-after=10s', '5400s',
            python, '-I', '-B', str(ROOT / 'scripts/run_ci_checks.py'), '--expected-commit', COMMIT,
            '--output-dir', str(RESULT), '--job-started-monotonic-ns', str(START_NS)]
    for name in counts:
        streams[name] = (OUT / (name + '.raw')).open('xb')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', MPLBACKEND='Agg', OPENSPEC_TELEMETRY='0')
    child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, env=env)
    original = owner(child.pid)
    write('dispatch.v1.json', {'source_commit': COMMIT, 'argv': argv, 'controller': owner(os.getpid()),
          'original': original, 'job_started_monotonic_ns': START_NS, 'deadline_ns': END_NS,
          'cleanup_deadline_ns': HARD_NS, 'source_pins': [v for _, v in PINS.values()],
          'hardware_acceptance': False})
    print(json.dumps({'status': 'original_full_ci_started', 'source_commit': COMMIT, 'owner': original}), flush=True)
    for name, pipe in [('stdout', child.stdout), ('stderr', child.stderr)]:
        os.set_blocking(pipe.fileno(), False)
        selector.register(pipe, selectors.EVENT_READ, name)
    while selector.get_map() or child.poll() is None:
        clock()
        for key, _ in selector.select(.1):
            b = os.read(key.fd, 65536)
            if not b:
                selector.unregister(key.fileobj)
                eof.add(key.data)
                continue
            assert counts[key.data] + len(b) <= MAX_CHANNEL, 'original CI channel cap'
            assert streams[key.data].write(b) == len(b)
            counts[key.data] += len(b)
    child.wait(timeout=max(.001, (END_NS - time.monotonic_ns()) / 1e9))
    clock()
    assert child.returncode == 0, 'original full CI exit is failed; retain stock report'
    report = json.loads((RESULT / 'report.json').read_bytes())
    assert report['successful'] is True and report['commit'] == COMMIT and report['changed_tracked_paths'] == []
    assert report['raw_checkout_bytes_match_commit'] is True
except BaseException as e:
    primary = err(e)
finally:
    if child is not None:
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            pass
        else:
            if primary is None:
                primary = err(RuntimeError('original CI left a process group'))
            try:
                os.killpg(child.pid, signal.SIGKILL)
                signals.append('SIGKILL-original-group')
            except ProcessLookupError:
                pass
            except BaseException as e:
                closes.append(err(e))
        try:
            child.wait(timeout=max(.001, (HARD_NS - time.monotonic_ns()) / 1e9))
        except BaseException as e:
            closes.append(err(e))
    try:
        selector.close()
    except BaseException as e:
        closes.append(err(e))
    for pipe in (() if child is None else (child.stdout, child.stderr)):
        try:
            pipe.close()
        except BaseException as e:
            closes.append(err(e))
    for f in streams.values():
        try:
            f.flush()
            os.fsync(f.fileno())
        except BaseException as e:
            closes.append(err(e))
        finally:
            try:
                f.close()
            except BaseException as e:
                closes.append(err(e))
    after = []
    for p, (fd, before) in PINS.items():
        try:
            value = digest(fd, p, cleanup=True)
            assert value == before
            after.append(value)
        except BaseException as e:
            closes.append(err(e))
        finally:
            try:
                os.close(fd)
            except BaseException as e:
                closes.append(err(e))
    scans = [scan(), scan()]
    if any(s['members'] or s['errors'] for s in scans):
        closes.append(err(RuntimeError('original CI process quiescence scan failed')))
    if output_owned:
        write('terminal.v1.json', {'status': 'success' if primary is None and not closes else 'failed',
              'source_commit': COMMIT, 'original': original, 'returncode': None if child is None else child.returncode,
              'first_error': primary, 'close_errors': closes, 'signals': signals, 'eof': sorted(eof),
              'channel_bytes': counts, 'elapsed_s': (time.monotonic_ns() - START_NS) / 1e9,
              'source_before_after_equal': len(after) == len(PINS), 'held_descriptors_released': not closes,
              'process_scans': scans, 'full_stock_report': str(RESULT / 'report.json'), 'hardware_acceptance': False})
    if time.monotonic_ns() >= END_NS and primary is None:
        primary = err(TimeoutError('original CI receipt-last5400s bound'))
        if output_owned:
            write('late-failure.v1.json', {'first_error': primary, 'status': 'failed'})
    clock(cleanup=True)
    print(json.dumps({'status': 'success' if primary is None and not closes else 'failed', 'source_commit': COMMIT,
                      'returncode': None if child is None else child.returncode, 'first_error': primary,
                      'close_errors': closes, 'elapsed_s': (time.monotonic_ns() - START_NS) / 1e9}), flush=True)
    if time.monotonic_ns() >= END_NS and primary is None:
        primary = err(TimeoutError('original CI5400s bound after final stdout flush'))
        if output_owned:
            write('late-failure.v1.json', {'first_error': primary, 'status': 'failed'})
    clock(cleanup=True)
sys.exit(0 if primary is None and not closes else 1)
