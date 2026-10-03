"""One prepared, gated cleanup of original mount2708; no acceptance authority.

Requires a separately reviewed, concrete consumer-closure binding and source pin.
This file has not been executed. The sole subprocess argv is fixed umount.
"""
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930')
HERE = BASE / 'decision29-runtime-bind-owned-cleanup-preparation-v1'
OUT = HERE / 'original-owned-cleanup-attempt01'
BINDING = HERE / 'consumer-closure.bound.v1.json'
ROOT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
SOURCE = Path('/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1')
TARGET = ROOT / '.publication-runtime/full-publication-cp312-v1'
PYTHON = SOURCE / 'bin/python'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
NAMESPACE = 'mnt:[4026532217]'
CP_SHA = '1643dacd9feaedc58f3cc581e4d22577dfe25c09b10282936186ccf0f2e61118'
CP_EPOCH = [2096, 87545, 33261, 1, 8020928, 1787574148546271435, 1787574148546271435]
CREATOR = BASE / 'decision29-runtime-bind-prerequisite-capture-preparation-v1/original-bind-attempt01'
CREATOR_EXEC = (19078, '829110b9b75faf53fcce812d188fe318540422c1c7d12acd2019257b6aaa9dea')
CREATOR_CLOSURE = (5037, '3cf93ba8891604fdaddb2689ed3400ab5ce4ae50a8c6eac723466bff6815275b')
CI_BASE = BASE / 'decision29-successor-ci-D-prerequisite-capture-preparation-v1/original-full-ci-prerequisite-attempt01'
CI_REVIEW_BASE = BASE / 'decision29-local-ci-D-prerequisite-result-review-preparation-v1'
CONFORMANCE_BASE = BASE / 'decision29-current-conformance-preparation-v1'
ARGV = ['/usr/bin/umount', '--', str(TARGET)]
CHANNEL_CAP = 65536
MOUNT_CAP = 4194304
CONTROL_CAP = 4194304
CONTROL_TOTAL_CAP = 33554432
START = time.monotonic()
WORK_END = START + 30
HARD_END = START + 40
errors, close_errors, handles, leaves, directories = [], [], [], [], []
control_bytes = 0
output_owned = False
facts, controller, command_result = {}, None, None


def interrupted(signum, _frame):
    raise TimeoutError('owned cleanup received signal ' + str(signum))


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)


def fault(exc):
    row = {'type': type(exc).__name__, 'message': str(exc)[:2048], 'errno': getattr(exc, 'errno', None)}
    if len(errors) < 32:
        errors.append(row)
    return row


def gate(end=WORK_END):
    if time.monotonic() >= end:
        raise TimeoutError('original absolute owned cleanup deadline')


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def identity(s):
    return (s.st_dev, s.st_ino, s.st_mode)


def raw(name, data):
    with (OUT / name).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save(name, value):
    raw(name, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())


def digest(fd, limit, end=WORK_END):
    value, offset = hashlib.sha256(), 0
    while True:
        gate(end)
        block = os.pread(fd, min(1048576, limit + 1 - offset), offset)
        if not block:
            break
        offset += len(block)
        if offset > limit:
            raise ValueError('held leaf exceeds fixed bound')
        value.update(block)
    return offset, value.hexdigest()


def hold(path, limit, expected=None, expected_epoch=None, temporary=False):
    """Register every FD before assertions; temporary target holds close locally."""
    assert path.is_absolute() and '..' not in path.parts and path == Path(os.path.normpath(path))
    local, local_dirs, row, fd = [], [], None, None
    try:
        cursor = Path('/')
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        local.append((cursor, parent))
        local_dirs.append((cursor, parent, os.fstat(parent)))
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            cursor /= part
            local.append((cursor, child))
            observed = os.fstat(child)
            assert stat.S_ISDIR(observed.st_mode) and identity(observed) == identity(os.lstat(cursor))
            local_dirs.append((cursor, child, observed))
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        local.append((path, fd))
        observed = os.fstat(fd)
        assert stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1
        assert epoch(observed) == epoch(os.lstat(path))
        size, sha = digest(fd, limit)
        assert size == observed.st_size and epoch(observed) == epoch(os.fstat(fd)) == epoch(os.lstat(path))
        if expected is not None:
            assert (size, sha) == tuple(expected), 'held original size/SHA differs: ' + str(path)
        if expected_epoch is not None:
            assert epoch(observed) == expected_epoch, 'held original seven epochs differ: ' + str(path)
        for name, directory, prior in local_dirs:
            assert identity(prior) == identity(os.fstat(directory)) == identity(os.lstat(name))
        row = {'path': str(path), 'size_bytes': size, 'sha256': sha, 'epoch7': epoch(observed)}
        if not temporary:
            handles.extend(local)
            directories.extend(local_dirs)
            leaves.append((path, fd, row))
            local = []
        return row, None if temporary else fd
    finally:
        for name, held in reversed(local):
            try:
                os.close(held)
            except BaseException as exc:
                close_errors.append({'path': str(name), 'type': type(exc).__name__, 'message': str(exc)[:512]})


def read_control(path, expected):
    global control_bytes
    row, fd = hold(path, CONTROL_CAP, expected)
    control_bytes += row['size_bytes']
    assert control_bytes <= CONTROL_TOTAL_CAP
    data = os.pread(fd, row['size_bytes'] + 1, 0)
    assert len(data) == row['size_bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    assert epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
    return json.loads(data), row


def owner(pid):
    location = Path('/proc') / str(pid)
    values = (location / 'stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in (location / 'status').read_text().splitlines() if ':' in line)
    cmdline = (location / 'cmdline').read_bytes()
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19]), 'state': values[0], 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'argv': cmdline.rstrip(b'\0').decode('utf-8').split('\0') if cmdline else [], 'cmdline_empty_observed': not cmdline}


def scan(owners):
    pids = {r['pid'] for r in owners}
    groups = {r['pgid'] for r in owners}
    sessions = {r['session'] for r in owners}
    rows, failed = [], []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            values = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(entry.name) in pids or int(values[2]) in groups or int(values[3]) in sessions:
                rows.append(owner(int(entry.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError, UnicodeError) as exc:
            failed.append({'pid': int(entry.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_ns': time.time_ns(), 'members': rows, 'errors': failed, 'original_pid_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in sorted(pids)}}


def require_absent(scans):
    assert len(scans) == 2 and all(not s['members'] and not s['errors'] and all(s['original_pid_absent'].values()) for s in scans), 'original owned process/group absence not proved'


def mount_observation(label):
    gate(HARD_END)
    with open('/proc/self/mountinfo', 'rb') as stream:
        data = stream.read(MOUNT_CAP + 1)
    assert len(data) <= MOUNT_CAP
    raw(label + '.mountinfo.raw', data)
    rows = []
    for line in data.decode('utf-8').splitlines():
        fields, extra = line.split(' - ', 1)
        left, right = fields.split(), extra.split()
        decode = lambda text: text.replace('\\040', ' ').replace('\\011', '\t').replace('\\012', '\n').replace('\\134', '\\')
        if decode(left[4]) in (str(SOURCE), str(TARGET)):
            rows.append({'mount_id': int(left[0]), 'parent_mount_id': int(left[1]), 'device': left[2], 'root': decode(left[3]), 'target': decode(left[4]), 'options': left[5].split(','), 'optional': left[6:], 'filesystem': right[0], 'source': decode(right[1]), 'superblock_options': right[2].split(','), 'original_line': line})
    return {'namespace': os.readlink('/proc/self/ns/mnt'), 'namespace_stat': epoch(os.stat('/proc/self/ns/mnt')), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'mountinfo_size_bytes': len(data), 'mountinfo_sha256': hashlib.sha256(data).hexdigest(), 'rows': rows}


def authentic_owners(value):
    found = []
    if isinstance(value, dict):
        if all(k in value for k in ('pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id')):
            if all(type(value[k]) is int and value[k] > 0 for k in ('pid', 'pgid', 'session', 'startticks')) and value['boot_id'] == BOOT:
                found.append({k: value[k] for k in ('pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id')})
        for nested in value.values():
            found.extend(authentic_owners(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(authentic_owners(nested))
    return found


def evidence(ref, parent):
    assert set(ref) == {'path', 'size_bytes', 'sha256'}
    path = Path(ref['path'])
    assert path.is_relative_to(parent) and path.suffix == '.json'
    assert type(ref['size_bytes']) is int and 0 < ref['size_bytes'] <= CONTROL_CAP
    assert re.fullmatch('[0-9a-f]{64}', ref['sha256'])
    return read_control(path, (ref['size_bytes'], ref['sha256']))


def verify_holds(end):
    for path, fd, row in leaves:
        assert epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
        assert digest(fd, row['size_bytes'], end) == (row['size_bytes'], row['sha256'])
        assert epoch(os.fstat(fd)) == row['epoch7'] == epoch(os.lstat(path))
    for path, fd, before in directories:
        assert identity(before) == identity(os.fstat(fd)) == identity(os.lstat(path))


def command():
    global command_result
    row = {'argv': ARGV, 'started_at_ns': time.time_ns(), 'owner': None, 'returncode': None, 'EOF': {'stdout': False, 'stderr': False}, 'signals': [], 'failure': None, 'reaped': False, 'observed_descendants': []}
    command_result = row
    child, selector = None, None
    streams, hashes, totals = {}, {c: hashlib.sha256() for c in ('stdout', 'stderr')}, {c: 0 for c in ('stdout', 'stderr')}
    try:
        gate()
        for channel in ('stdout', 'stderr'):
            streams[channel] = (OUT / ('umount.' + channel + '.raw')).open('x+b')
        child = subprocess.Popen(ARGV, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        # Observe before wait/poll/reap. A quick zombie can have an empty cmdline;
        # actual stat/status ownership remains retained, argv is not invented.
        row['owner'] = owner(child.pid)
        assert row['owner']['pid'] == row['owner']['pgid'] == row['owner']['session'] and row['owner']['uid'] == row['owner']['gid'] == 0
        assert row['owner']['boot_id'] == BOOT
        save('umount.launch.v1.json', {'capture_owner': controller, 'command': row})
        selector = selectors.DefaultSelector()
        for channel, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, channel)
        seen = set()
        while selector.get_map() or child.poll() is None:
            gate()
            try:
                children = Path('/proc', str(child.pid), 'task', str(child.pid), 'children').read_text().split()
                for pid in children:
                    if int(pid) not in seen:
                        try:
                            row['observed_descendants'].append(owner(int(pid)))
                            seen.add(int(pid))
                        except FileNotFoundError:
                            pass
            except FileNotFoundError:
                pass
            for key, _ in selector.select(min(.01, max(0, WORK_END - time.monotonic()))):
                channel = key.data
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    row['EOF'][channel] = True
                    selector.unregister(key.fileobj)
                    continue
                permitted = min(len(block), CHANNEL_CAP - totals[channel])
                if permitted:
                    assert streams[channel].write(block[:permitted]) == permitted
                    hashes[channel].update(block[:permitted])
                    totals[channel] += permitted
                if permitted != len(block):
                    raise ValueError('owned cleanup raw channel exceeds64KiB')
        row['returncode'] = child.wait(timeout=max(.001, WORK_END - time.monotonic()))
        row['reaped'] = True
    except BaseException as exc:
        row['failure'] = fault(exc)
        if child is not None:
            try:
                if child.poll() is None:
                    row['signals'].append({'signal': 'SIGTERM', 'at_ns': time.time_ns()})
                    os.killpg(child.pid, signal.SIGTERM)
                try:
                    row['returncode'] = child.wait(timeout=min(1, max(.001, HARD_END - time.monotonic())))
                except subprocess.TimeoutExpired:
                    row['signals'].append({'signal': 'SIGKILL', 'at_ns': time.time_ns()})
                    os.killpg(child.pid, signal.SIGKILL)
                    row['returncode'] = child.wait(timeout=max(.001, HARD_END - time.monotonic()))
                row['reaped'] = True
            except BaseException as cleanup_exc:
                fault(cleanup_exc)
    finally:
        if child is not None:
            for pipe in (child.stdout, child.stderr):
                try:
                    pipe.close()
                except BaseException as exc:
                    close_errors.append({'resource': 'child_pipe', **fault(exc)})
        if selector is not None:
            try:
                selector.close()
            except BaseException as exc:
                close_errors.append({'resource': 'selector', **fault(exc)})
        for channel, stream in streams.items():
            try:
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException as exc:
                fault(exc)
            stored = None
            try:
                observed = os.fstat(stream.fileno())
                size, sha = digest(stream.fileno(), CHANNEL_CAP, HARD_END)
                assert size == observed.st_size and epoch(observed) == epoch(os.fstat(stream.fileno())) == epoch(os.lstat(OUT / ('umount.' + channel + '.raw')))
                assert (size, sha) == (totals[channel], hashes[channel].hexdigest())
                stored = {'path': str(OUT / ('umount.' + channel + '.raw')), 'size_bytes': size, 'sha256': sha, 'epoch7': epoch(observed)}
            except BaseException as exc:
                fault(exc)
            row.setdefault('raw_channels', {})[channel] = {'acknowledged_bytes': totals[channel], 'acknowledged_sha256': hashes[channel].hexdigest(), 'stored_original_descriptor': stored, 'stored_descriptor_verified': stored is not None, 'EOF_observed': row['EOF'][channel]}
            try:
                stream.close()
            except BaseException as exc:
                close_errors.append({'resource': channel, **fault(exc)})
        row['finished_at_ns'] = time.time_ns()
        if child is not None:
            original = row['owner'] or {'pid': child.pid, 'pgid': child.pid, 'session': child.pid}
            row['two_owned_process_scans'] = [scan([original] + row['observed_descendants']), scan([original] + row['observed_descendants'])]
            try:
                require_absent(row['two_owned_process_scans'])
            except BaseException as exc:
                fault(exc)
        if output_owned:
            save('umount.command.v1.json', row)
    return row


fd_before = len(list(Path('/proc/self/fd').iterdir()))
try:
    assert len(sys.argv) == 4, 'requires exact bound-closure size/SHA and reviewed source SHA'
    binding_size, binding_sha, self_sha = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    assert re.fullmatch('[0-9a-f]{64}', binding_sha) and re.fullmatch('[0-9a-f]{64}', self_sha)
    assert Path(__file__).absolute() == HERE / 'capture_owned_runtime_bind_cleanup_v1.py'
    assert os.getuid() == os.getgid() == 0 and Path(sys.executable) == PYTHON and sys.version_info[:3] == (3, 12, 3)
    controller = owner(os.getpid())
    controller['observed_parent'] = owner(controller['ppid'])
    assert controller['boot_id'] == BOOT and os.readlink('/proc/self/ns/mnt') == NAMESPACE
    # Exclusive output ownership is established before any original operation.
    OUT.mkdir(mode=0o700)
    output_owned = True
    hold(Path(__file__), CONTROL_CAP, (Path(__file__).stat().st_size, self_sha))
    binding, binding_pin = read_control(BINDING, (binding_size, binding_sha))
    assert binding['schema_version'] == 1 and binding['kind'] == 'original_owned_runtime_bind_cleanup_gate_v1'
    assert binding['source_commit_D'] == COMMIT and binding['reviewed_capture_sha256'] == self_sha
    assert binding['cleanup_authorized'] is True and binding['all_D_consumers_closed'] is True and binding['no_new_D_consumers_since_closure'] is True
    assert binding['underlying_target_directory_pre_mount_identity'] is None and binding['delete_directories'] is False
    creator, creator_pin = read_control(CREATOR / 'execution.v1.json', CREATOR_EXEC)
    closure, closure_pin = read_control(CREATOR / 'root-original-closure.v1.json', CREATOR_CLOSURE)
    assert creator['status'] == 'verified' and creator['source_commit'] == COMMIT and creator['all_held_FDs_closed'] is True and not creator['errors'] and not creator['close_errors']
    assert closure['original_true_exit_code'] == 0 and closure['all_raw_command_hashes_and_closures_joined'] is True and closure['late_companion_absent'] is True
    require_absent(closure['two_current_process_scans'] if 'original_pid_absent' in closure['two_current_process_scans'][0] else [{**s, 'original_pid_absent': s['actual_owner_pid_paths_absent']} for s in closure['two_current_process_scans']])
    assert creator['mount_after']['namespace'] == closure['current_mount_namespace'] == NAMESPACE and creator['mount_after']['boot_id'] == BOOT
    assert creator['mount_after']['rows'] == closure['actual_source_and_target_rows']
    cp_pin, _ = hold(PYTHON, CP_EPOCH[4], (CP_EPOCH[4], CP_SHA), CP_EPOCH)
    executable = binding['umount_executable']
    assert set(executable) == {'path', 'size_bytes', 'sha256', 'epoch7'} and executable['path'] == '/usr/bin/umount'
    assert type(executable['size_bytes']) is int and 0 < executable['size_bytes'] <= CONTROL_CAP and re.fullmatch('[0-9a-f]{64}', executable['sha256'])
    umount_pin, umount_fd = hold(Path('/usr/bin/umount'), CONTROL_CAP, (executable['size_bytes'], executable['sha256']), executable['epoch7'])
    tool_stat = os.fstat(umount_fd)
    assert tool_stat.st_uid == tool_stat.st_gid == 0 and tool_stat.st_mode & 0o111 and not tool_stat.st_mode & 0o022
    head_pin, head_fd = hold(ROOT / '.git/HEAD', 41, (41, '33b3c32b7cd1f722f6eeaf2bff0e7ee83a9e2f01bcaa902a4d72f96558b507af'))
    assert os.pread(head_fd, 42, 0) == (COMMIT + '\n').encode()
    documents, proof_pins = [], []
    ci = binding['full_ci']
    for label in ('dispatch', 'terminal'):
        expected_path = CI_BASE / (label + '.v1.json')
        assert Path(ci[label]['path']) == expected_path
        value, pin = evidence(ci[label], CI_BASE)
        documents.append(value)
        proof_pins.append(pin)
    ci_review, pin = evidence(ci['result_review'], CI_REVIEW_BASE)
    proof_pins.append(pin)
    documents.append(ci_review)
    assert ci_review['status'] == 'verified' and ci_review['source_commit'] == COMMIT and ci_review['facts']['stock_evidence_complete'] is True
    assert ci_review['all_reader_handles_released'] is True and not ci_review['close_errors'] and ci_review['fd_before'] == ci_review['fd_after']
    # Closed failed and successful CI are both cleanup-eligible; neither is
    # rewritten or promoted by this resource operation.
    assert ci_review['original_full_CI_disposition'] in ('SUCCESS', 'FAILED')
    ci_process, pin = evidence(ci['process_closure'], CI_REVIEW_BASE)
    documents.append(ci_process)
    proof_pins.append(pin)
    conformance = binding['conformance']
    conf_terminal, pin = evidence(conformance['terminal'], CONFORMANCE_BASE)
    documents.append(conf_terminal)
    proof_pins.append(pin)
    assert conf_terminal['FD_holds_released'] is True and not conf_terminal['close_errors']
    for label in ('independent_review', 'process_closure'):
        value, pin = evidence(conformance[label], BASE)
        documents.append(value)
        proof_pins.append(pin)
    assert len(binding['additional_D_consumer_closures']) <= 32
    for ref in binding['additional_D_consumer_closures']:
        value, pin = evidence(ref, BASE)
        documents.append(value)
        proof_pins.append(pin)
    authentic = authentic_owners(documents)
    declared = binding['all_closed_consumer_owners']
    assert 3 <= len(declared) <= 512 and len({(r['pid'], r['startticks']) for r in declared}) == len(declared)
    assert all(set(r) == {'pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id'} and r in authentic for r in declared), 'closed consumers require original dispatch/terminal-derived owners'
    required_ci = authentic_owners([documents[0]['controller'], documents[1]['original'], ci_review['facts']['actual_observer']['owner']])
    assert required_ci and all(r in declared for r in required_ci)
    consumer_scans = [scan(declared), scan(declared)]
    require_absent(consumer_scans)
    assert not close_errors
    before = mount_observation('before')
    assert before['namespace'] == NAMESPACE and before['boot_id'] == BOOT and before['rows'] == creator['mount_after']['rows']
    assert before['namespace_stat'] == creator['mount_after']['namespace_stat']
    expected_target = [row for row in before['rows'] if row['target'] == str(TARGET)]
    assert len(expected_target) == 1 and expected_target[0]['mount_id'] == 2708 and expected_target[0]['parent_mount_id'] == 80
    assert epoch(os.lstat(TARGET)) == creator['mount_after']['target_directory_epoch7']
    assert epoch(os.lstat(SOURCE)) == creator['mount_after']['target_directory_epoch7']
    temporary_target, _ = hold(TARGET / 'bin/python', CP_EPOCH[4], (CP_EPOCH[4], CP_SHA), CP_EPOCH, temporary=True)
    assert not close_errors, 'target-side descriptors must all close before umount'
    assert all(not path.is_relative_to(TARGET) for path, _ in handles), 'self-created target-mount busy FD'
    verify_holds(WORK_END)
    require_absent([scan(declared), scan(declared)])
    precommand = mount_observation('immediate-pre-command')
    assert precommand['rows'] == before['rows'] and precommand['namespace'] == NAMESPACE and precommand['boot_id'] == BOOT
    assert precommand['namespace_stat'] == before['namespace_stat']
    facts = {'creator': creator_pin, 'creator_closure': closure_pin, 'binding': binding_pin, 'consumer_proof_pins': proof_pins, 'consumer_owner_scans': consumer_scans, 'canonical_python': cp_pin, 'umount_executable': umount_pin, 'source_HEAD': head_pin, 'target_python_before_only_all_FDs_closed': temporary_target, 'mount_before': before, 'mount_immediate_pre_command': precommand, 'original_underlying_target_directory_identity': None}
    gate()
    command_result = command()
    after = mount_observation('after')
    facts['mount_after'] = after
    assert command_result['returncode'] == 0 and command_result['reaped'] is True and all(command_result['EOF'].values()) and not command_result['failure'] and not command_result['signals'] and not errors and not close_errors
    expected_source = [row for row in before['rows'] if row['target'] == str(SOURCE)]
    assert len(expected_source) == 1 and expected_source[0]['mount_id'] == 331
    assert after['namespace'] == NAMESPACE and after['boot_id'] == BOOT and after['rows'] == expected_source
    assert after['namespace_stat'] == before['namespace_stat'] and epoch(os.lstat(SOURCE)) == creator['mount_after']['target_directory_epoch7']
    observed_target = os.lstat(TARGET)
    assert stat.S_ISDIR(observed_target.st_mode)
    with os.scandir(TARGET) as entries:
        assert next(entries, None) is None, 'underlying retained target is unexpectedly nonempty'
    facts['retained_target_directory_post_unmount_observation_only'] = {'path': str(TARGET), 'epoch7': epoch(observed_target), 'empty_observed': True, 'pre_mount_identity_unknown': True, 'deleted': False}
    facts['global_source_mount331_unchanged'] = True
    facts['owned_target_mount2708_absent'] = True
    gate(HARD_END)
except BaseException as exc:
    fault(exc)
finally:
    try:
        verify_holds(HARD_END)
        facts['held_original_leaves_after_full_SHA_and_epoch_recheck'] = [row for _, _, row in leaves]
        facts['held_ancestor_identities_after_rechecked'] = True
    except BaseException as exc:
        fault(exc)
        facts['final_held_leaf_and_ancestor_recheck_failed'] = True
    # Attempt all independent retirements even after verification/save failure.
    for path, fd in reversed(handles):
        try:
            os.close(fd)
        except BaseException as exc:
            close_errors.append({'path': str(path), 'type': type(exc).__name__, 'message': str(exc)[:512]})

fd_after = len(list(Path('/proc/self/fd').iterdir()))
result = {'schema_version': 1, 'kind': 'original_owned_runtime_bind_cleanup_capture_v1', 'source_commit_D': COMMIT, 'status': 'verified_owned_unmount_not_acceptance' if not errors and not close_errors and fd_before == fd_after else 'failed', 'controller': controller, 'command': command_result, 'facts': facts, 'first_error': errors[0] if errors else None, 'errors': errors, 'close_errors': close_errors, 'all_held_FDs_closed': not close_errors, 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START, 'acceptance_claim': False, 'full_CI_acceptance': False, 'conformance_acceptance': False, 'benchmark_acceptance': False, 'directory_deletion_performed': False, 'underlying_target_directory_pre_mount_identity': None, 'limits': ['Only recorded original consumer and command PIDs/groups/sessions are scanned; no global descendant absence claim.', 'Original underlying target-directory inode was never recorded. Its post-unmount observation cannot prove pre-mount identity; empty directories remain.', 'No mount-source331 mutation, force/lazy/recursive umount, source/model/engine operation, test/CI replay or authority rebinding.', 'Capture controller/outer timeout absence requires an independent parent postterminal closure before cleanup is considered fully closed.']}
if output_owned:
    terminal_attempted = False
    terminal_saved = False
    try:
        gate(HARD_END)
        terminal_attempted = True
        save('execution.v1.json', result)
        terminal_saved = True
        print(json.dumps({'status': result['status'], 'capture_pid': os.getpid(), 'fd_before': fd_before, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START, 'acceptance_claim': False}), flush=True)
        gate(HARD_END)
    except BaseException as exc:
        fault(exc)
        result['status'] = 'failed'
        try:
            save('late-or-persistence-failure.v1.json', {'status': 'failed', 'first_error': result['first_error'] or errors[0], 'terminal_attempted': terminal_attempted, 'terminal_saved': terminal_saved, 'known_terminal_path': str(OUT / 'execution.v1.json'), 'complete_descriptor_verified': False, 'elapsed_s': time.monotonic() - START, 'acceptance_claim': False})
        except BaseException as companion_exc:
            print(json.dumps({'status': 'failed', 'first_error': errors[0], 'companion_failure': {'type': type(companion_exc).__name__, 'message': str(companion_exc)[:512]}, 'acceptance_claim': False}), flush=True)
else:
    print(json.dumps({'status': 'failed', 'output_owned': False, 'errors': errors, 'close_errors': close_errors, 'acceptance_claim': False}), flush=True)
raise SystemExit(0 if result['status'] == 'verified_owned_unmount_not_acceptance' else 1)
