"""Original packaged socket regression observer; no model acceptance."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
COMMIT = '7f3dfa42858c85d6e3db2cb1274dd13af35696c9'
DEST = ROOT / 'artifacts/benchmark_recovery_20260930/gstreamer-packaged-regression'
DEST.mkdir(mode=0o700)
sys.path.insert(0, str(ROOT / 'scripts'))
from publication_operational_container_custody_v1 import _confirmed_absent, _state, PROJECTION, LABEL


def desc(path):
    path = Path(path)
    info = path.lstat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == path.stat().st_size
    return {'path': str(path), 'size_bytes': info.st_size, 'sha256': digest}


def write(name, value):
    path = DEST / name
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    return desc(path)


def owner(pid):
    parts = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    rows = Path(f'/proc/{pid}/status').read_text().splitlines()
    ids = {row.split(':', 1)[0]: row.split()[1:] for row in rows if ':' in row}
    return {'pid': pid, 'ppid': int(parts[1]), 'proc_stat_starttime_ticks': int(parts[19]),
        'uid': int(ids['Uid'][0]), 'gid': int(ids['Gid'][0]),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


engine = Path('/usr/bin/docker').resolve(strict=True)
engine_before = desc(engine)
engine_fd = os.open(engine, os.O_RDONLY | os.O_NOFOLLOW)
socket = Path('/var/run/docker.sock').resolve(strict=True)
socket_info = socket.lstat()
socket_before = [socket_info.st_dev, socket_info.st_ino, socket_info.st_mode, socket_info.st_uid, socket_info.st_gid]
ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'DOCKER_HOST': 'unix://' + str(socket)}
command_count = 0


def command(arguments):
    global command_count
    command_count += 1
    started = time.time_ns()
    result = subprocess.run([f'/proc/self/fd/{engine_fd}', *arguments], executable=f'/proc/self/fd/{engine_fd}',
        pass_fds=(engine_fd,), env=ENV, capture_output=True, timeout=20)
    facts = {}
    for key in ('stdout', 'stderr'):
        raw = getattr(result, key)
        assert len(raw) <= 65536
        path = DEST / f'engine_{command_count:02d}.{key}'
        with path.open('xb') as stream:
            stream.write(raw)
        facts[key] = desc(path)
    write(f'engine_{command_count:02d}.v1.json', {'argv': [str(engine), *arguments], 'returncode': result.returncode,
        'started_at_ns': started, 'terminal_at_ns': time.time_ns(), **facts})
    return result


build = ROOT / 'artifacts/benchmark_recovery_20260930/gstreamer-first-build/original.stdout'
values = dict(line.split('=', 1) for line in build.read_text().splitlines() if '=' in line and not line.startswith('{'))
image = values['image_id']
assert image.startswith('sha256:') and len(image) == 71
modules = ('checkpoint_native_policy_runtime', 'checkpoint_gstreamer_analytics_sidecar',
    'checkpoint_gstreamer_analytics_bridge', 'analytics_execution_protocol', 'analytics_execution_endpoint',
    'publication_guardian_operational_recorder_v1', 'publication_operational_request_domain_v1',
    'publication_operational_request_reconciliation_v1', 'publication_policy_qualification_execution_closure_v1',
    'publication_policy_projection_v1', 'publication_policy_contract', 'checkpoint_admission',
    'checkpoint_deepstream_protocol_bridge', 'checkpoint_gstreamer_runtime')
expected = {name: desc(ROOT / 'scripts' / (name + '.py'))['sha256'] for name in modules}
write('packaged-source-expectations.v1.json', expected)
loader = DEST / 'packaged_test_loader.v1.py'
loader.write_text('''import sys,os,json,hashlib,importlib,tempfile,unittest
from pathlib import Path
sys.path[:0]=['/opt/vast/checkpoint','/opt/vast/python','/mnt/vast-tests']
expected=json.loads(Path('/mnt/vast-expectations.json').read_bytes())
fixture=Path(tempfile.mkdtemp(prefix='vast-packaged-fixtures-'))
(fixture/'scripts').symlink_to('/opt/vast/checkpoint',target_is_directory=True)
(fixture/'tests').symlink_to('/mnt/vast-tests',target_is_directory=True)
(fixture/'configs').symlink_to('/mnt/vast-configs',target_is_directory=True)
(fixture/'deploy').mkdir()
(fixture/'deploy/native_gst_probe').symlink_to('/mnt/vast-native-source',target_is_directory=True)
support=[importlib.import_module(name) for name in ['test_checkpoint_gstreamer_analytics_sidecar','test_checkpoint_native_policy_runtime']]
boundary=importlib.import_module('test_publication_operational_boundary_v1')
for module in [*support,boundary]:module.ROOT=fixture
observed={}
for name,sha in expected.items():
 module=importlib.import_module(name);path=Path(module.__file__).resolve(strict=True)
 assert path.parent==Path('/opt/vast/checkpoint'),(name,str(path))
 digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==sha,(name,digest,sha)
 observed[name]={'path':str(path),'sha256':digest}
for name in ['yaml','numpy']:
 path=Path(importlib.import_module(name).__file__).resolve(strict=True)
 assert Path('/opt/vast/python') in path.parents,(name,str(path))
print(json.dumps({'packaged_runtime_modules':observed,'no_host_runtime_imports':True,'inference':'local_fixture','publication_acceptance':False}),flush=True)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(boundary.PublicationOperationalBoundaryTests)
assert suite.countTestCases()==10,suite.countTestCases()
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert not result.skipped,result.skipped
sys.exit(0 if result.wasSuccessful() else 1)
''')
source_paths = [ROOT / 'tests' / (name + '.py') for name in ('test_publication_operational_boundary_v1',
    'test_checkpoint_gstreamer_analytics_sidecar', 'test_checkpoint_native_policy_runtime')]
source_paths += [ROOT / 'configs/analytics_execution_layer.yaml', ROOT / 'configs/checkpoint_analytics_models_openvino.yaml',
    ROOT / 'deploy/native_gst_probe/vast_native_gst_probe.cpp', loader, Path(__file__)]
before = [desc(path) for path in source_paths]
name = 'vast-recovery-gst-boundary-' + uuid.uuid4().hex[:20]
label = hashlib.sha256(json.dumps({'commit': COMMIT, 'image': image, 'name': name, 'sources': before}, sort_keys=True).encode()).hexdigest()
cidfile = DEST / 'original.cid'
daemon_before = command(('info', '--format', '{{json .ID}}'))
assert daemon_before.returncode == 0 and daemon_before.stderr == b''
empty = command(('container', 'inspect', '--format', PROJECTION, name))
assert _confirmed_absent(empty.returncode, empty.stdout, empty.stderr, name)
image_observation = command(('image', 'inspect', '--format', '{{json .Id}} {{json .Config.User}} {{json .Config.Entrypoint}} {{json .Config.Labels}}', image))
assert image_observation.returncode == 0 and image_observation.stderr == b''
arguments = ('run', '--rm', '--name', name, '--cidfile', str(cidfile), '--label', LABEL + '=' + label,
    '--network', 'none', '--read-only', '--pids-limit', '256', '--memory', '2g', '--cpus', '2',
    '--tmpfs', '/tmp:rw,nosuid,nodev,size=536870912,mode=1777', '--env', 'OPENBLAS_NUM_THREADS=1', '--env', 'OMP_NUM_THREADS=1',
    '--env', 'MKL_NUM_THREADS=1', '--env', 'NUMEXPR_NUM_THREADS=1',
    '--mount', f'type=bind,src={ROOT / "tests"},dst=/mnt/vast-tests,readonly',
    '--mount', f'type=bind,src={ROOT / "configs"},dst=/mnt/vast-configs,readonly',
    '--mount', f'type=bind,src={ROOT / "deploy/native_gst_probe"},dst=/mnt/vast-native-source,readonly',
    '--mount', f'type=bind,src={loader},dst=/mnt/vast-loader.py,readonly',
    '--mount', f'type=bind,src={DEST / "packaged-source-expectations.v1.json"},dst=/mnt/vast-expectations.json,readonly',
    '--entrypoint', '/usr/bin/python3', image, '-I', '-B', '/mnt/vast-loader.py')
write('prelaunch.v1.json', {'commit': COMMIT, 'image_id': image, 'engine': engine_before, 'socket_identity': socket_before,
    'argv': [str(engine), *arguments], 'sources': before, 'name': name, 'label': label, 'cidfile': str(cidfile),
    'classification': 'packaged real socket/memfd/recorder/reconciliation regression, local inference fixture only', 'accepted': False})
started = time.time_ns()
clock = time.monotonic()
stdout, stderr = DEST / 'original.stdout', DEST / 'original.stderr'
timeout = False
with stdout.open('xb') as output, stderr.open('xb') as errors:
    process = subprocess.Popen([f'/proc/self/fd/{engine_fd}', *arguments], executable=f'/proc/self/fd/{engine_fd}',
        pass_fds=(engine_fd,), env=ENV, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, start_new_session=True)
    child = owner(process.pid)
    write('original-process-start.v1.json', {'argv': [str(engine), *arguments], 'child': child,
        'controller': owner(os.getpid()), 'started_at_ns': started, 'commit': COMMIT})
    print(json.dumps({'phase': 'packaged_real_front_started', 'pid': process.pid, 'image_id': image, 'name': name}), flush=True)
    try:
        process.wait(timeout=300)
    except subprocess.TimeoutExpired:
        timeout = True
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    output.flush();errors.flush();os.fsync(output.fileno());os.fsync(errors.fileno())
cidraw = cidfile.read_bytes()
assert len(cidraw) in (64, 65) and (len(cidraw) == 64 or cidraw[-1:] == b'\n')
cid = cidraw[:64].decode('ascii')
assert len(cid) == 64 and all(char in '0123456789abcdef' for char in cid)
observed = command(('container', 'inspect', '--format', PROJECTION, cid))
absent = _confirmed_absent(observed.returncode, observed.stdout, observed.stderr, cid)
state = None
if not absent:
    assert observed.returncode == 0 and observed.stderr == b''
    state = _state(observed.stdout, {'name': name, 'label': label,
        'container_image': {'image_id': image}, 'reserved_at_ns': started}, cid, time.time_ns())
    if state['Running']:
        stopped = command(('container', 'stop', '--time', '5', cid))
        assert stopped.returncode == 0 and stopped.stdout == (cid + '\n').encode() and stopped.stderr == b''
        observed = command(('container', 'inspect', '--format', PROJECTION, cid))
        absent = _confirmed_absent(observed.returncode, observed.stdout, observed.stderr, cid)
        assert absent
        timeout = True
daemon_after = command(('info', '--format', '{{json .ID}}'))
assert daemon_after.returncode == 0 and daemon_after.stdout == daemon_before.stdout and daemon_after.stderr == b''
after = [desc(path) for path in source_paths]
info = socket.lstat()
stable = before == after and desc(engine) == engine_before and socket_before == [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]
terminal = write('original-terminal.v1.json', {'schema_version': 1, 'commit': COMMIT, 'image_id': image,
    'child': child, 'returncode': process.returncode, 'timed_out': timeout, 'started_at_ns': started,
    'finished_at_ns': time.time_ns(), 'elapsed_s': time.monotonic() - clock, 'stdout': desc(stdout), 'stderr': desc(stderr),
    'sources_before': before, 'sources_after': after, 'sources_engine_socket_stable': stable, 'cidfile': desc(cidfile),
    'container_id': cid, 'container_not_found_after_rm': absent, 'observed_state': state,
    'oom_killed': None if state is None else state['OOMKilled'], 'accepted': False, 'publication_ready': False,
    'classification': 'real packaged Python and front socket/memfd accounting tests with local inference fixture; no model or benchmark acceptance'})
print(json.dumps({'phase': 'packaged_real_front_terminal', 'returncode': process.returncode, 'timed_out': timeout,
    'sources_engine_socket_stable': stable, 'container_not_found_after_rm': absent, 'receipt': terminal,
    'stdout_tail': stdout.read_text(errors='replace')[-1200:], 'stderr_tail': stderr.read_text(errors='replace')[-2000:]}), flush=True)
os.close(engine_fd)
if process.returncode or timeout or not stable:
    sys.exit(78)
