"""Original read-only research prerequisite metadata; no compiler/decoder execution."""
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
METADATA_PROGRAM = 'import os,sys,json,subprocess,hashlib,stat,shutil\nfrom pathlib import Path\ndef desc(path):\n p=Path(path).resolve(strict=True);before=p.stat();assert stat.S_ISREG(before.st_mode) and before.st_size<=268435456\n sha=hashlib.sha256()\n with p.open(\'rb\') as f:\n  while block:=f.read(1048576):sha.update(block)\n after=p.stat();assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)\n return {\'path\':str(p),\'size_bytes\':before.st_size,\'sha256\':sha.hexdigest()}\ndef command(argv):\n try:\n  p=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,timeout=10)\n  assert len(p.stdout)<=65536 and len(p.stderr)<=65536\n  return {\'argv\':argv,\'returncode\':p.returncode,\'stdout_hex\':p.stdout.hex(),\'stderr_hex\':p.stderr.hex(),\'stdout_text\':p.stdout.decode(\'utf8\',\'replace\'),\'stderr_text\':p.stderr.decode(\'utf8\',\'replace\')}\n except FileNotFoundError as e:return {\'argv\':argv,\'unavailable\':type(e).__name__}\nrows=[command([\'pkg-config\',\'--modversion\',m]) for m in [\'gstreamer-1.0\',\'gstreamer-app-1.0\',\'gstreamer-video-1.0\',\'glib-2.0\']]\nrows.append(command([\'pkg-config\',\'--cflags\',\'--libs\',\'gstreamer-1.0\',\'gstreamer-app-1.0\',\'gstreamer-video-1.0\']))\ninc=command([\'pkg-config\',\'--variable=includedir\',\'gstreamer-1.0\']);rows.append(inc)\nrows.append(command([\'dpkg-query\',\'-W\',\'-f=${binary:Package} ${Version}\\n\',\'g++\',\'gcc\',\'libglib2.0-dev\',\'python3-gi\']))\nlinked=command([\'ldd\',\'/usr/local/bin/vast_checkpoint_source\']);rows.append(linked)\nfiles={}\nfor key,value in [(\'source_binary\',\'/usr/local/bin/vast_checkpoint_source\'),(\'nvcodec_plugin\',\'/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0/libgstnvcodec.so\'),(\'compiler\',shutil.which(\'c++\')),(\'pkg_config\',shutil.which(\'pkg-config\'))]:\n if value:files[key]=desc(value)\nheaders={}\nif inc.get(\'returncode\')==0:\n prefix=Path(inc[\'stdout_text\'].strip())/\'gstreamer-1.0\'\n for relative in [\'gst/gst.h\',\'gst/gstversion.h\',\'gst/gstbuffer.h\',\'gst/gstpad.h\',\'gst/app/gstappsrc.h\',\'gst/app/gstappsink.h\',\'gst/video/video-frame.h\',\'gst/video/video-info.h\']:\n  p=prefix/relative\n  headers[relative]=desc(p) if p.is_file() else {\'missing_path\':str(p)}\nlibraries=[]\nfor line in linked.get(\'stdout_text\',\'\').splitlines():\n if \'=> /\' in line:\n  path=line.split(\'=> \',1)[1].split(\' \',1)[0]\n  if Path(path).is_file():libraries.append(desc(path))\ngi_program=r"""import sys,os,json,hashlib,stat\nfrom pathlib import Path\nif sys.argv[1]==\'stock_path\':\n for p in reversed(os.environ.get(\'VAST_NATIVE_PYTHONPATH\',\'\').split(\':\')):\n  if p:sys.path.insert(0,p)\nresult={\'route\':sys.argv[1],\'sys_path\':sys.path,\'available\':False}\ntry:\n import gi\n gi.require_version(\'Gst\',\'1.0\');gi.require_version(\'GstApp\',\'1.0\');gi.require_version(\'GstVideo\',\'1.0\')\n from gi.repository import Gst,GstApp,GstVideo\n result.update(available=True,gi_version=gi.__version__,gi_path=gi.__file__,gst_version=list(Gst.version()),gst_app_module=repr(GstApp),gst_video_module=repr(GstVideo),api={\'appsrc_push_buffer\':hasattr(GstApp.AppSrc,\'push_buffer\'),\'appsink_try_pull_sample\':hasattr(GstApp.AppSink,\'try_pull_sample\'),\'video_frame_map\':hasattr(GstVideo.VideoFrame,\'map\')})\n paths=set()\n for line in Path(\'/proc/self/maps\').read_text().splitlines():\n  fields=line.split()\n  if len(fields)>=6 and fields[-1].startswith(\'/\') and any(x in fields[-1] for x in (\'libgstreamer\',\'libgstapp\',\'libgstvideo\',\'libgobject\',\'libglib\')):paths.add(fields[-1])\n result[\'loaded_libraries\']=[{\'path\':str(Path(p).resolve()),\'size_bytes\':Path(p).stat().st_size,\'sha256\':hashlib.sha256(Path(p).read_bytes()).hexdigest()} for p in sorted(paths)]\nexcept Exception as e:result.update(error_type=type(e).__name__,error=str(e))\nprint(json.dumps(result,sort_keys=True))\n"""\ngi=[command([\'/usr/bin/python3\',\'-I\',\'-B\',\'-c\',gi_program,route]) for route in [\'isolated\',\'stock_path\']]\nprint(json.dumps({\'classification\':\'read-only installed package/header/ABI metadata; no compiler or decoder pipeline execution\',\'commands\':rows,\'files\':files,\'headers\':headers,\'source_linked_libraries\':libraries,\'gi_probes\':gi,\'environment\':{key:os.environ.get(key) for key in (\'PATH\',\'LD_LIBRARY_PATH\',\'PKG_CONFIG_PATH\',\'GI_TYPELIB_PATH\',\'VAST_NATIVE_PYTHONPATH\')},\'accepted\':False,\'publication_ready\':False},sort_keys=True))\n'
for phase, entrypoint, arguments in (('package_metadata', '/usr/bin/python3', ('-I', '-B', '-c', METADATA_PROGRAM)),):
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
        'classification': 'read-only installed header/library/GI metadata; no source/compiler/decode/inference', 'accepted': False})
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
    'classification': 'actual read-only research package prerequisite metadata only'})
os.close(engine_fd)
print(json.dumps({'receipt': receipt, 'stable': stable}), flush=True)
assert stable
