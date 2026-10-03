"""Later metadata-only two-scan closure; no engine or producer-data read."""
import ast
import hashlib
import json
import os
from pathlib import Path
import time

BASE = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/component-cpu07-worker-events-observation-preparation-v1')
start = time.monotonic()
fd_before = len(os.listdir('/proc/self/fd'))
source = (BASE / 'close_original_observation_v1.py').read_bytes()
report_raw = (BASE / 'original-observation-closure-review.v1.json').read_bytes()
report = json.loads(report_raw)
assert hashlib.sha256(report_raw).hexdigest() == 'a944ac4dc1be3307f2912fc1b3501eb29cdba11f2f388f2be8c67e16a86f596b'
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
tree = ast.parse(source)
functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('proc', 'scan')], type_ignores=[])
exec(compile(functions, 'closed-metadata-scan-functions', 'exec'), globals())
owners = [item['original'] for item in report['process_scans'][0]['owners']] + [report['scanner']]
owners.append({'pid': report['scanner']['ppid'], 'pgid': report['scanner']['pgid'], 'startticks': None, 'uid': 1000, 'gid': 1000, 'boot_id': BOOT, 'limitation': 'Metadata timeout startticks were not captured before dispatch; PID/path/group absence is separately observed.'})
scans = [scan(owners)]
time.sleep(0.05)
scans.append(scan(owners))
assert all(not item['scan_errors'] and not item['group_members'] and all(owner['original_pid_path_absent'] for owner in item['owners']) for item in scans)
fd_after = len(os.listdir('/proc/self/fd'))
assert fd_before == fd_after
value = {'schema_version': 1, 'scope': 'later metadata-only closure of original query and first finite closure scanner', 'engine_queries': 0, 'scanner': proc(os.getpid()), 'source': {'path': str(BASE / 'close_original_observation_v1.py'), 'size_bytes': len(source), 'sha256': hashlib.sha256(source).hexdigest()}, 'original_closure': {'path': str(BASE / 'original-observation-closure-review.v1.json'), 'size_bytes': len(report_raw), 'sha256': hashlib.sha256(report_raw).hexdigest()}, 'process_scans': scans, 'fd_before': fd_before, 'fd_after': fd_after, 'all_read_handles_released': True, 'elapsed_s': time.monotonic() - start}
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('ascii')
path = BASE / 'original-observation-later-process-closure.v1.json'
with path.open('xb') as output:
    output.write(raw)
    output.flush()
    os.fsync(output.fileno())
assert time.monotonic() - start < 30
print(json.dumps({'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'scanner_pid': os.getpid()}))
