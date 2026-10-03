"""Original stock build observer; this file grants no benchmark acceptance."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
COMMIT = '7f3dfa42858c85d6e3db2cb1274dd13af35696c9'
observed = subprocess.check_output(['/usr/bin/git', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
    '--work-tree=' + str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
assert observed == COMMIT
DEST = ROOT / 'artifacts/benchmark_recovery_20260930/gstreamer-first-build'
DEST.mkdir(mode=0o700)
sys.path.insert(0, str(ROOT / 'scripts'))
from build_publication_runtime_images_after_refreeze_v1 import runtime_image_handoff_plan

native = ROOT / 'artifacts/fix_benchmark_preparations_20260928g/native-a/native_probe.freeze.json'
plan = runtime_image_handoff_plan(project_root=ROOT, native_receipt=native, artifact_dir=DEST)
row = next(r for r in plan['runtime_builds'] if r['system'] == 'gstreamer_custom')


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def desc(path):
    path = Path(path)
    before, digest = path.lstat(), hashlib.sha256()
    with path.open('rb') as stream:
        while part := stream.read(1048576):
            digest.update(part)
    assert epoch(before) == epoch(path.lstat()) and stat.S_ISREG(before.st_mode) and before.st_nlink == 1
    return {'path': str(path), 'size_bytes': before.st_size, 'sha256': digest.hexdigest()}


def owner(pid):
    values = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    rows = Path(f'/proc/{pid}/status').read_text().splitlines()
    ids = {line.split(':', 1)[0]: line.split()[1:] for line in rows if ':' in line}
    return {'pid': pid, 'proc_stat_starttime_ticks': int(values[19]), 'ppid': int(values[1]),
        'uid': int(ids['Uid'][0]), 'gid': int(ids['Gid'][0]),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def write(name, value):
    path = DEST / name
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    return desc(path)


paths = {native, Path(row['command'][1]), Path(__file__)}
for manifest in ('deploy/gstreamer_custom/publication/runtime-source-allowlist.txt',
        'deploy/gstreamer_custom/publication/runtime-dependency-allowlist.txt',
        'deploy/gstreamer_custom/publication/runtime-build-context-allowlist.txt'):
    path = ROOT / manifest
    paths.add(path)
    for line in path.read_text().splitlines():
        if line and not line.startswith('#'):
            paths.add(ROOT / line)
paths.update(ROOT / name for name in ('configs/publication_image_build_v1.json',
    'configs/publication_qualification_image_refreeze_v1.json', 'scripts/build_publication_runtime_images_after_refreeze_v1.py'))
paths = sorted(paths, key=str)
before = [desc(path) for path in paths]
engine = Path('/usr/bin/docker').resolve(strict=True)
socket = Path('/var/run/docker.sock').resolve(strict=True)
engine_before = desc(engine)
info = socket.lstat()
socket_before = {'path': str(socket), 'epoch': epoch(info), 'uid': info.st_uid, 'gid': info.st_gid}
environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'DOCKER_HOST': 'unix://' + str(socket), **row['environment']}
write('prelaunch.v1.json', {'schema_version': 1, 'artifact_kind': 'vast_original_stock_runtime_image_build_prelaunch_v1',
    'commit': COMMIT, 'sources': before, 'engine': engine_before, 'engine_socket': socket_before,
    'argv': row['command'], 'environment': environment, 'native_handoff_plan': plan,
    'accepted': False, 'publication_ready': False})
stdout, stderr = DEST / 'original.stdout', DEST / 'original.stderr'
started, clock = time.time_ns(), time.monotonic()
with stdout.open('xb') as output, stderr.open('xb') as errors:
    process = subprocess.Popen(row['command'], cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
        stdout=output, stderr=errors, start_new_session=True)
    child = owner(process.pid)
    print(json.dumps({'phase': 'stock_gstreamer_two_build_started', 'pid': process.pid,
        'source_commit': COMMIT, 'output_dir': str(DEST)}), flush=True)
    write('original-process-start.v1.json', {'schema_version': 1, 'argv': row['command'], 'controller': owner(os.getpid()),
        'child': child, 'started_at_ns': started, 'commit': COMMIT, 'accepted': False, 'publication_ready': False})
    next_report = time.monotonic() + 20
    while process.poll() is None:
        time.sleep(.5)
        if time.monotonic() >= next_report:
            print(json.dumps({'phase': 'stock_gstreamer_two_build_running', 'pid': process.pid,
                'elapsed_s': round(time.monotonic() - clock, 1), 'stdout_bytes': stdout.stat().st_size,
                'stderr_bytes': stderr.stat().st_size}), flush=True)
            next_report = time.monotonic() + 20
    returncode = process.wait()
    output.flush()
    errors.flush()
    os.fsync(output.fileno())
    os.fsync(errors.fileno())
after = [desc(path) for path in paths]
stable = before == after
engine_stable = desc(engine) == engine_before
socket_stable = epoch(socket.lstat()) == socket_before['epoch']
terminal = write('original-terminal.v1.json', {'schema_version': 1,
    'artifact_kind': 'vast_original_stock_runtime_image_build_terminal_v1', 'commit': COMMIT, 'child': child,
    'argv': row['command'], 'returncode': returncode, 'started_at_ns': started, 'finished_at_ns': time.time_ns(),
    'elapsed_s': time.monotonic() - clock, 'stdout': desc(stdout), 'stderr': desc(stderr),
    'sources_before': before, 'sources_after': after, 'sources_stable': stable,
    'engine_stable': engine_stable, 'socket_stable': socket_stable, 'accepted': False,
    'publication_ready': False, 'classification': 'original stock two-build image result; no model/hardware/benchmark acceptance'})
print(json.dumps({'phase': 'stock_gstreamer_two_build_terminal', 'returncode': returncode, 'sources_stable': stable,
    'engine_stable': engine_stable, 'socket_stable': socket_stable, 'receipt': terminal,
    'stdout_tail': stdout.read_text(errors='replace')[-2400:], 'stderr_tail': stderr.read_text(errors='replace')[-1200:]}), flush=True)
if returncode or not stable or not engine_stable or not socket_stable:
    sys.exit(78)
