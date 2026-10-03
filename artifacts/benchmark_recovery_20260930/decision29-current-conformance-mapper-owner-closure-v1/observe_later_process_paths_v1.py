"""Two later actual scans of the already closed metadata observer and parent."""
import json
import os
import time
from pathlib import Path

HERE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-current-conformance-mapper-owner-closure-v1')
OUT = HERE / 'original-observation-attempt01'
IDS = {11079, 11080}
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
START = time.monotonic()


def scan():
    rows, errors = [], []
    for path in Path('/proc').iterdir():
        assert time.monotonic() - START < 10
        if not path.name.isdigit():
            continue
        try:
            values = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(path.name) in IDS or int(values[2]) == 11079 or int(values[3]) == 11079:
                rows.append({'pid': int(path.name), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19])})
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError) as exc:
            errors.append({'pid': int(path.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_monotonic_ns': time.monotonic_ns(), 'original_PID_paths_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in sorted(IDS)}, 'owned_group_session_members': rows, 'errors': errors}


fd_before = len(list(Path('/proc/self/fd').iterdir()))
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
scans = [scan(), scan()]
assert all(not s['errors'] and not s['owned_group_session_members'] and all(s['original_PID_paths_absent'].values()) for s in scans)
assert not os.path.lexists(OUT / 'late-failure.v1.json')
fd_after = len(list(Path('/proc/self/fd').iterdir()))
assert fd_before == fd_after
result = {'schema_version': 1, 'status': 'verified', 'boot_id': BOOT, 'original_observer_PID': 11080, 'original_timeout_PID_PGID_session': 11079, 'original_both_startticks': 51688361, 'two_later_actual_scans': scans, 'late_companion_absent': True, 'scanner_PID': os.getpid(), 'scanner_fd_before': fd_before, 'scanner_fd_after': fd_after, 'elapsed_s': time.monotonic() - START, 'no_global_descendant_absence_claim': True, 'no_CI_test_reader_model_engine_replay': True}
with (OUT / 'later-observer-process-closure.v1.json').open('xb') as stream:
    stream.write((json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
    stream.flush()
    os.fsync(stream.fileno())
assert time.monotonic() - START < 10
print(json.dumps(result), flush=True)
raise SystemExit(0)
