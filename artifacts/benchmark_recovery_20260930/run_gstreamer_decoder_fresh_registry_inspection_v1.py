"""Original read-only GPU registry refresh properties; no decode/model acceptance."""
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
assert len(sys.argv) == 4, 'expected reviewed commit, build directory, fresh output directory'
COMMIT, BUILD_DIRECTORY, OUTPUT_DIRECTORY = sys.argv[1:]
assert subprocess.check_output(['/usr/bin/git', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
    '--work-tree=' + str(ROOT), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
DEST = ROOT / OUTPUT_DIRECTORY
assert DEST.resolve().is_relative_to(ROOT / 'artifacts/benchmark_recovery_20260930')
DEST.mkdir(mode=0o700)
sys.path.insert(0, str(ROOT / 'scripts'))
from publication_operational_container_custody_v1 import _confirmed_absent, _state, PROJECTION, LABEL


def desc(path):
    path = Path(path)
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    return {'path': str(path), 'size_bytes': info.st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(name, value):
    path = DEST / name
    with path.open('xb') as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    return desc(path)


def owner(pid):
    raw = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    rows = Path(f'/proc/{pid}/status').read_text().splitlines()
    ids = {row.split(':', 1)[0]: row.split()[1:] for row in rows if ':' in row}
    return {'pid': pid, 'ppid': int(raw[1]), 'proc_stat_starttime_ticks': int(raw[19]),
        'uid': int(ids['Uid'][0]), 'gid': int(ids['Gid'][0]),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


build = ROOT / BUILD_DIRECTORY / 'original.stdout'
assert build.resolve().is_relative_to(ROOT / 'artifacts/benchmark_recovery_20260930')
image = dict(line.split('=', 1) for line in build.read_text().splitlines()
    if '=' in line and not line.startswith('{'))['image_id']
assert image.startswith('sha256:') and len(image) == 71
engine = Path('/usr/bin/docker').resolve(strict=True)
engine_before = desc(engine)
engine_fd = os.open(engine, os.O_RDONLY | os.O_NOFOLLOW)
sock = Path('/run/docker.sock').resolve(strict=True)
s = sock.stat()
socket_before = [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid]
env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'DOCKER_HOST': 'unix://' + str(sock)}
source_before = desc(Path(__file__))
auxseq = 0


def command(arguments):
    global auxseq
    auxseq += 1
    started = time.time_ns()
    result = subprocess.run([f'/proc/self/fd/{engine_fd}', *arguments], executable=f'/proc/self/fd/{engine_fd}',
        pass_fds=(engine_fd,), env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
    facts = {}
    for key in ('stdout', 'stderr'):
        raw = getattr(result, key)
        assert len(raw) <= 65536
        path = DEST / f'engine_{auxseq:02d}.{key}'
        with path.open('xb') as stream:
            stream.write(raw)
        facts[key] = desc(path)
    write(f'engine_{auxseq:02d}.v1.json', {'argv': [str(engine), *arguments], 'returncode': result.returncode,
        'started_at_ns': started, 'terminal_at_ns': time.time_ns(), **facts})
    return result


daemon_before = command(('info', '--format', '{{json .ID}}'))
assert daemon_before.returncode == 0 and daemon_before.stderr == b''
receipts = []
for phase, entrypoint, arguments in (
        ('version', '/bin/sh', ('-c', 'unset GST_REGISTRY_UPDATE; command -v gst-inspect-1.0; exec gst-inspect-1.0 --version')),
        ('nvh264dec', '/usr/bin/env', ('-u', 'GST_REGISTRY_UPDATE', 'gst-inspect-1.0', 'nvh264dec')),
        ('nvh265dec', '/usr/bin/env', ('-u', 'GST_REGISTRY_UPDATE', 'gst-inspect-1.0', 'nvh265dec'))):
    name = 'vast-gst-readonly-' + uuid.uuid4().hex
    label = hashlib.sha256((COMMIT + image + name + phase).encode()).hexdigest()
    empty = command(('container', 'inspect', '--format', PROJECTION, name))
    assert _confirmed_absent(empty.returncode, empty.stdout, empty.stderr, name)
    cidfile = DEST / (phase + '.cid')
    argv = ('run', '--rm', '--name', name, '--cidfile', str(cidfile), '--label', LABEL + '=' + label,
        '--gpus', 'all', '--network', 'none', '--read-only', '--pids-limit', '128', '--memory', '1g',
        '--cpus', '1', '--tmpfs', '/tmp:rw,nosuid,nodev,size=67108864,mode=1777',
        '--env', 'HOME=/tmp', '--env', 'XDG_CACHE_HOME=/tmp',
        '--env', 'GST_REGISTRY=/tmp/vast-gst-properties.registry.bin',
        '--env', 'NVIDIA_DRIVER_CAPABILITIES=compute,utility,video', '--entrypoint', entrypoint, image, *arguments)
    started = time.time_ns()
    write(phase + '.prelaunch.v1.json', {'commit': COMMIT, 'image_id': image, 'phase': phase,
        'argv': [str(engine), *argv], 'name': name, 'label': label, 'reserved_at_ns': started,
        'engine': engine_before, 'socket_identity': socket_before, 'observer': source_before,
        'classification': 'read-only plugin metadata using stock fresh GPU registry refresh; no source/decode/inference', 'accepted': False})
    timed_out = False
    with (DEST / (phase + '.stdout')).open('xb') as stdout, (DEST / (phase + '.stderr')).open('xb') as stderr:
        process = subprocess.Popen([f'/proc/self/fd/{engine_fd}', *argv], executable=f'/proc/self/fd/{engine_fd}',
            pass_fds=(engine_fd,), env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
        child = owner(process.pid)
        write(phase + '.process-start.v1.json', {'child': child, 'controller': owner(os.getpid()),
            'started_at_ns': started, 'argv': [str(engine), *argv]})
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        finally:
            stdout.flush(); stderr.flush(); os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
    cid = None
    if cidfile.exists():
        cidraw = cidfile.read_bytes()
        assert len(cidraw) in (64, 65) and (len(cidraw) == 64 or cidraw[-1:] == b'\n')
        cid = cidraw[:64].decode('ascii')
        assert len(cid) == 64 and all(c in '0123456789abcdef' for c in cid)
    identifier = cid or name
    observed = command(('container', 'inspect', '--format', PROJECTION, identifier))
    absent = _confirmed_absent(observed.returncode, observed.stdout, observed.stderr, identifier)
    state = None
    if not absent:
        assert observed.returncode == 0 and observed.stderr == b''
        state = _state(observed.stdout, {'name': name, 'label': label,
            'container_image': {'image_id': image}, 'reserved_at_ns': started}, identifier, time.time_ns())
        cid = state['Id']
        if state['Running']:
            stopped = command(('container', 'stop', '--time', '5', cid))
            assert stopped.returncode == 0 and stopped.stdout == (cid + '\n').encode() and stopped.stderr == b''
            final = command(('container', 'inspect', '--format', PROJECTION, cid))
            absent = _confirmed_absent(final.returncode, final.stdout, final.stderr, cid)
            assert absent
            timed_out = True
    facts = {key: desc(DEST / (phase + '.' + key)) for key in ('stdout', 'stderr')}
    assert all(row['size_bytes'] <= 1048576 for row in facts.values())
    receipt = write(phase + '.terminal.v1.json', {'phase': phase, 'commit': COMMIT, 'image_id': image,
        'argv': [str(engine), *argv], 'child': child, 'returncode': process.returncode, 'timed_out': timed_out,
        'started_at_ns': started, 'terminal_at_ns': time.time_ns(), 'container_id': cid,
        'container_not_found_after_rm': absent, 'observed_state': state,
        'oom_killed': None if state is None else state['OOMKilled'], 'accepted': False, 'publication_ready': False, **facts})
    receipts.append(receipt)
    print(json.dumps({'phase': phase, 'returncode': process.returncode, 'timed_out': timed_out,
        'container_not_found_after_rm': absent, 'receipt': receipt}), flush=True)
    assert not timed_out and absent
daemon_after = command(('info', '--format', '{{json .ID}}'))
s = sock.stat()
stable = daemon_after.returncode == 0 and daemon_before.stdout == daemon_after.stdout and daemon_after.stderr == b'' \
    and engine_before == desc(engine) and socket_before == [s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid] \
    and source_before == desc(Path(__file__))
receipt = write('decoder-inspection.v1.json', {'commit': COMMIT, 'image_id': image, 'observations': receipts,
    'daemon_engine_socket_source_stable': stable, 'accepted': False, 'publication_ready': False,
    'classification': 'actual read-only GStreamer fresh GPU registry plugin/version observations only'})
os.close(engine_fd)
print(json.dumps({'receipt': receipt, 'stable': stable}), flush=True)
assert stable
