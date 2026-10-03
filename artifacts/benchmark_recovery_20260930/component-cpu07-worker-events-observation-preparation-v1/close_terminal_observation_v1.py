"""Finite metadata-only closure of the original exact-CID terminal query."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import time

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/component-cpu07-worker-events-observation-preparation-v1')
START = time.monotonic()
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
FD_BEFORE = len(os.listdir('/proc/self/fd'))
held = []
witnesses = []

def epoch(value):
    return [value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns]

def read(path):
    path = Path(path)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 100000
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    held.append((path, fd, epoch(before)))
    assert epoch(os.fstat(fd)) == epoch(before)
    raw = os.read(fd, 100001)
    assert len(raw) == before.st_size and epoch(os.fstat(fd)) == epoch(path.lstat()) == epoch(before)
    descriptor = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    witnesses.append({'descriptor': descriptor, 'epoch': epoch(before)})
    return raw

def load(relative):
    return json.loads(read(BASE / relative))

scan_source = read(BASE / 'close_original_observation_v1.py')
tree = ast.parse(scan_source)
functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('proc', 'scan')], type_ignores=[])
exec(compile(functions, 'original-metadata-scan-functions', 'exec'), globals())
outer = load('original-terminal-events-observation-outer-attempt01/capture.v1.json')
outer_launch = load('original-terminal-events-observation-outer-attempt01/launch.v1.json')
inner = load('original-terminal-events-observation-attempt01/execution.v1.json')
launch = load('original-terminal-events-observation-attempt01/launch.v1.json')
dispatch = load('original-terminal-events-observation-attempt01/dispatch.v1.json')
raw = read(BASE / 'original-terminal-events-observation-attempt01/stdout.raw')
stderr = read(BASE / 'original-terminal-events-observation-attempt01/stderr.raw')
outer_stdout = read(BASE / 'original-terminal-events-observation-outer-attempt01/stdout.raw')
outer_stderr = read(BASE / 'original-terminal-events-observation-outer-attempt01/stderr.raw')
source = read(BASE / 'observe_original_primary_worker_terminal_events_v5.py')
outer_source = read(BASE / 'capture_terminal_events_v1.py')
grant = load('root-one-terminal-events-grant.v1.json')
preparation = load('preparation.v4.json')
peer_raw = read(BASE.parent / 'component-cpu07-worker-events-independent-source-review-v1/review.v3.json')
assert hashlib.sha256(source).hexdigest() == '312d3ea99ff396b2e9074cbc1c1f9958ef3d8ceb6dd29ec01cc57dc71a4fed1d'
assert hashlib.sha256(outer_source).hexdigest() == '1ae5a35f2cf279ad8df157ca7db783deb9b72ea1218c10baa77e9c4a60115bf6'
assert hashlib.sha256(peer_raw).hexdigest() == '3d119d99cc00ac1e4337865d22a1ead83e28f0864d5ee4923e4d1c9c5e97d459'
assert outer['returncode'] == inner['returncode'] == 0 and outer['failure'] is inner['failure'] is None
assert inner['status'] == 'observed' and not inner['overflow'] and not inner['timed_out'] and not inner['signals'] and not inner['validation_errors']
assert all(inner['eof'].values()) and all(outer['eof'].values()) and not stderr and not outer_stderr
assert inner['fd_before'] == inner['fd_after'] == 4 and outer['fd_before'] == outer['fd_after'] == 6
assert outer['source_before'] == outer['source_after'] and len(raw) == 623
assert hashlib.sha256(raw).hexdigest() == inner['channels']['stdout']['sha256'] == '7e99e4a394ca5268001dceee6e055e40d6d67bb362e6644bf3cb3f415afc1057'
assert hashlib.sha256(outer_stdout).hexdigest() == outer['channels']['stdout']['sha256']
late_paths = [BASE / 'original-terminal-events-observation-attempt01/late-failure.v1.json', BASE / 'original-terminal-events-observation-outer-attempt01/late-failure.v1.json']
assert not any(path.exists() for path in late_paths)
events = [json.loads(line) for line in raw.splitlines()]
assert raw.endswith(b'\n') and events == inner['events'] and len(events) == 2
assert [event['action'] for event in events] == ['die', 'destroy'] and events[0]['exit_code'] == '0'
assert all(event['id'] == dispatch['observed_cid'] == '893b2b02a18906c5d7f840e2515e8f2fb8253c396cf4c2a3756efd1513f166aa' and event['name'] == 'vast-gst-analytics-f5a8e4aa391f4df1-vehicle-type-cpu' and event['image'] == 'sha256:ce138982695ea6d8218a9137bb858090a782e83e687be8fc252a32dc0bd9d5f9' and event['type'] == 'container' for event in events)
assert dispatch['terminal_action_filters'] == ['die', 'oom', 'kill', 'destroy']
expected_filters = ['type=container', 'container=' + dispatch['observed_cid'], 'event=die', 'event=oom', 'event=kill', 'event=destroy']
argv = dispatch['argv']
assert [argv[index + 1] for index, token in enumerate(argv[:-1]) if token == '--filter'] == expected_filters
assert dispatch['start_ns'] == 1790823221323071118 and dispatch['end_ns'] == 1790823586186876374
assert dispatch['command_seconds'] == 2 and dispatch['channel_caps'] == {'stdout': 8192, 'stderr': 1024}
owners = [outer['controller'], outer['owner'], dispatch['controller'], inner['owner']]
assert all(owner['boot_id'] == BOOT and owner['uid'] == owner['gid'] == 1000 for owner in owners)
assert outer_launch['controller'] == outer['controller'] and outer_launch['timeout_owner'] == outer['owner'] and launch['owner'] == inner['owner']
scans = [scan(owners)]
time.sleep(0.05)
scans.append(scan(owners))
assert all(not item['group_members'] and not item['scan_errors'] and all(owner['original_pid_path_absent'] for owner in item['owners']) for item in scans)
pair = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-07')
diagnostic_raw = read(pair / 'guardian/protocol_failure_diagnostic.v1.json')
native_raw = read(pair / 'operations/process-captures/component-gstreamer_custom-cpu-h264-independent-processes/engine_05.terminal.v1.json')
assert hashlib.sha256(diagnostic_raw).hexdigest() == '41c930a0f93d828dcb90116bd8fb31eca7cf83c5efb54f824c2c3b05b3c71e2c'
assert hashlib.sha256(native_raw).hexdigest() == '48db893068e2d9e606ab94bcaaa171af0f49d4106d622eb6e8f2a98da053bdc4'
diagnostic = json.loads(diagnostic_raw)
native = json.loads(native_raw)
assert diagnostic['observed_at_utc'] == '2026-10-01T02:59:42.125144+00:00'
epipe_at_ns = 1790823582125144000
assert native['returncode'] == 1 and native['terminal_at_ns'] == 1790823582977433219
assert events[0]['time_ns'] > native['terminal_at_ns'] > epipe_at_ns
for path, fd, initial in held:
    assert epoch(os.fstat(fd)) == epoch(path.lstat()) == initial
    os.lseek(fd, 0, os.SEEK_SET)
    reread = os.read(fd, 100001)
    witness = next(item for item in witnesses if item['descriptor']['path'] == str(path))
    assert hashlib.sha256(reread).hexdigest() == witness['descriptor']['sha256']
close_errors = []
for path, fd, initial in reversed(held):
    try:
        os.close(fd)
    except Exception as error:
        close_errors.append({'path': str(path), 'type': type(error).__name__, 'message': str(error)})
assert not close_errors
fd_after = len(os.listdir('/proc/self/fd'))
assert fd_after == FD_BEFORE
value = {'schema_version': 1, 'scope': 'finite metadata-only physical closure of separately granted original exact-CID terminal event observation', 'observation_valid': True, 'benchmark_accepted': False, 'worker_socket_close_cause': None, 'scanner': proc(os.getpid()), 'fd_before': FD_BEFORE, 'fd_after': fd_after, 'all_held_fds_released': True, 'close_errors': close_errors, 'input_witnesses': witnesses, 'process_scans': scans, 'late_failure_absent': [str(path) for path in late_paths], 'events': events, 'original_query_seconds': inner['elapsed_s'], 'original_outer_seconds': outer['elapsed_s'], 'source_before_after_equal': True, 'timeline': {'earliest_retained_protocol_failure_at_ns': epipe_at_ns, 'native_cli_terminal_at_ns': native['terminal_at_ns'], 'worker_die_at_ns': events[0]['time_ns'], 'worker_destroy_at_ns': events[1]['time_ns'], 'die_after_protocol_failure_ns': events[0]['time_ns'] - epipe_at_ns, 'die_after_native_cli_terminal_ns': events[0]['time_ns'] - native['terminal_at_ns']}, 'limits': ['Later daemon query is subject to last256-event retention.', 'No returned oom/kill event is not proof of absence.', 'Container die0 after the protocol failure does not identify the earlier socket-close mechanism.', 'Original first all-events query remains failed and immutable.', 'Original native stderr raw body was not retained; its digest is not substituted with this observation.'], 'elapsed_s': time.monotonic() - START}
assert value['elapsed_s'] < 30
target = BASE / 'original-terminal-events-closure-review.v1.json'
encoded = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
with target.open('xb') as output:
    output.write(encoded)
    output.flush()
    os.fsync(output.fileno())
assert time.monotonic() - START < 30
print(json.dumps({'path': str(target), 'size_bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest(), 'scanner_pid': os.getpid(), 'observation_valid': True, 'benchmark_accepted': False}))
