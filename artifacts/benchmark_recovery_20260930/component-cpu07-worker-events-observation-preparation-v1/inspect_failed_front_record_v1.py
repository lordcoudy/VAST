"""Read one bounded closed route journal; no inference or payload replay."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time

HERE = Path(__file__).resolve().parent
PAIR = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-07')
START = time.monotonic()
FD_BEFORE = len(os.listdir('/proc/self/fd'))
PATH = PAIR / 'guardian-operational/vehicle_type-cpu.jsonl'
REQUEST = 'edf739962630fd9cc16e41d5291746d57060c2af31bb5d4f90de4ec8db97328f'

def epoch(v):
    return [v.st_dev, v.st_ino, v.st_mode, v.st_nlink, v.st_size, v.st_mtime_ns, v.st_ctime_ns]

def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')

group_path = PAIR / 'guardian-operational/operational_group.v1.json'
group_raw = group_path.read_bytes()
assert len(group_raw) == 4665
group = json.loads(group_raw)
group_body = dict(group)
group_sha = group_body.pop('sha256')
assert hashlib.sha256(canonical(group_body)).hexdigest() == group_sha
declared = next(row for row in group['journals'] if row['route'] == 'vehicle_type:cpu')
assert declared['path'] == str(PATH) and declared['size_bytes'] == 970514 and declared['sha256'] == 'f24d0fe6e5710b5564be30849dd5599801ef7894de76062221c252c60549ee91'
before = PATH.lstat()
assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 2 * 1024 * 1024
fd = os.open(PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
assert epoch(os.fstat(fd)) == epoch(before)
digest = hashlib.sha256()
starts = []
terminals = []
failed = []
event_count = 0
previous = None
try:
    with os.fdopen(os.dup(fd), 'rb') as source:
        header_raw = source.readline(65537)
        digest.update(header_raw)
        assert len(header_raw) <= 65536
        header = json.loads(header_raw)
        body = dict(header)
        previous = body.pop('sha256')
        assert canonical(header) + b'\n' == header_raw and hashlib.sha256(canonical(body)).hexdigest() == previous
        for line in iter(lambda: source.readline(769), b''):
            assert time.monotonic() - START < 30 and len(line) <= 768 and line.endswith(b'\n')
            digest.update(line)
            record = json.loads(line)
            body = dict(record)
            observed = body.pop('sha256')
            assert canonical(record) + b'\n' == line and hashlib.sha256(bytes.fromhex(previous) + canonical(body)).hexdigest() == observed
            previous = observed
            event_count += 1
            if record.get('request_id') == REQUEST:
                starts.append(record)
            if 'begin_seq' in record:
                if record['outcome'] == 'failed':
                    failed.append(record)
                terminals.append(record)
    assert digest.hexdigest() == declared['sha256'] and event_count == declared['event_count'] == 2104 and previous == declared['final_event_sha256']
    assert len(starts) == 1
    joined = [record for record in terminals if record['begin_seq'] == starts[0]['seq']]
    assert len(joined) == 1
    terminal = joined[0]
    assert terminal['outcome'] == 'failed' and terminal['send'] == 'failed'
    assert type(terminal['response']) is str and len(terminal['response']) == 64
    assert epoch(os.fstat(fd)) == epoch(PATH.lstat()) == epoch(before)
finally:
    os.close(fd)
fd_after = len(os.listdir('/proc/self/fd'))
assert fd_after == FD_BEFORE
value = {'schema_version': 1, 'scope': 'one physically bounded closed vehicle_type/cpu operational journal; chain and exact failed request join only', 'benchmark_accepted': False, 'journal': declared, 'journal_epoch': epoch(before), 'group': {'path': str(group_path), 'size_bytes': len(group_raw), 'sha256': hashlib.sha256(group_raw).hexdigest()}, 'event_chain_valid': True, 'matching_begin': starts[0], 'matching_terminal': terminal, 'all_failed_route_terminals': failed, 'fd_before': FD_BEFORE, 'fd_after': fd_after, 'held_fd_released': True, 'interpretation': 'The per-request response was reset to None at sidecar5339 and assigned only after bridge.execute returns at5494. A nonnull response digest plus send=failed proves that this retained failure occurred during delivery of a constructed response to the native front; stage=inference currently includes that response-send block. It does not by itself identify why the native front closed.', 'limits': ['No response payload is retained or reconstructed by this reader.', 'No model/inference/native/engine work and no full cold acceptance are performed.', 'The failed original CLI remains failed; this record is diagnostic only.'], 'elapsed_s': time.monotonic() - START}
raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
output = HERE / 'failed-front-record-review.v1.json'
with output.open('xb') as destination:
    destination.write(raw)
    destination.flush()
    os.fsync(destination.fileno())
assert time.monotonic() - START < 30
print(json.dumps({'path': str(output), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'begin': starts[0], 'terminal': terminal}))
