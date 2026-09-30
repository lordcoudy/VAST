"""Prepare one independent cold reader; no production/source restoration here."""
import hashlib
import json
from pathlib import Path, PurePosixPath

root = Path.cwd()
base = Path(__file__).parent
linux_root = '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec'
pair = linux_root + '/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04'
index = json.loads((root / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04/runtime/component_runtime_index.v1.json').read_bytes())
terminal = json.loads((root / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04/component_cli_terminal.v1.json').read_bytes())
guardian = json.loads((root / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04/guardian/service_authority.v1.json').read_bytes())
assert terminal['status'] == 'failed' and terminal['component_pairs'] == 0
assert terminal['guardian_cleanup_verified'] and terminal['capacity_reservation']['released']
assert len(index['bundles']) == 2
arguments = dict(project_root=linux_root, component_authority_path=index['component_authority']['path'],
    capture_plan_path=pair + '/operations/capture-plan/capture_plan_index.v1.json',
    runtime_bundle_paths=[row['descriptor']['path'] for row in index['bundles']],
    arm_result_paths=[pair + '/operations/arms/' + row['operation_id'] + '/component_arm_result.v1.json'
                      for row in index['bundles']],
    guardian_authority_path=pair + '/guardian/service_authority.v1.json',
    guardian_lifecycle_path=pair + '/guardian/service_lifecycle.v1.json',
    preprocessing_contract_path=pair + '/preprocessing/guardian-preprocessing-contract.v1.json',
    preprocessing_receipt_path=pair + '/preprocessing/guardian-component-preprocessing-receipt.v1.json',
    analytics_socket_path=guardian['front_socket']['path'],
    scratch_root=str(PurePosixPath(terminal['capacity_reservation']['path']).parent),
    output_dir=pair + '-corrected-cold-01')
with (base / 'arguments.v1.json').open('xb') as stream:
    stream.write((json.dumps(arguments, sort_keys=True, indent=2) + '\n').encode())
reader_sha = hashlib.sha256((base / 'corrected_component_runtime_v1.py').read_bytes()).hexdigest()
driver = base / 'run_reader.py'
raw = driver.read_text()
old = '23202bc4cdbf8d5955273457a0560054bc985696d883a1dcd96485c54a34e0883'
assert raw.count(old) == 1
driver.write_bytes(raw.replace(old, reader_sha).encode())
original = root / 'artifacts/benchmark_recovery_20260930/component-cold-provider-seam-repair-v1/dispatch.py'
observer = original.read_text()
start, end = observer.index('PATHS = ('), observer.index('LIMIT = ')
new_paths = '''original_path = ROOT / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04-original-controller/original.terminal.v1.json'
assert hashlib.sha256(original_path.read_bytes()).hexdigest() == '88b9c117f75b45454b8facc781e1bb291750de388b85f03c31fe7135b1496b0e'
original = json.loads(original_path.read_bytes())
EXPECTED = {row['descriptor']['path']: row['descriptor'] for row in original['pins_before']}
assert len(EXPECTED) == 95
PATHS = tuple(EXPECTED) + tuple(str(Path(__file__).parent / name) for name in
    ('run_reader.py', 'corrected_component_runtime_v1.py', 'arguments.v1.json', 'observe.py')) + (str(original_path),)
held = {}
def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
'''
observer = observer[:start] + new_paths + observer[end:]
observer = observer.replace("return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}",
    "return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch': epoch(path.lstat())}")
start = observer.index('before = pins()')
end = observer.index('started_at_ns, started = ')
observer = observer[:start] + '''for path in PATHS:
    named = Path(path)
    fd = os.open(named, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    held[path] = (fd, epoch(os.fstat(fd)))
before = pins()
for path, expected in EXPECTED.items():
    assert {key: before[path][key] for key in expected} == expected, 'Original producer source bytes are not present: ' + path
for path, (fd, snapshot) in held.items():
    assert snapshot == before[path]['epoch'] == epoch(os.fstat(fd))
argv = [sys.executable, '-I', '-B', str(Path(__file__).parent / 'run_reader.py')]
''' + observer[end:]
observer = observer.replace('now - started > 30:', 'now - started > 600:')
observer = observer.replace('now - started > 35:', 'now - started > 615:')
observer = observer.replace("after = pins()", "after = pins()\nfor path, (fd, snapshot) in held.items():\n    assert snapshot == epoch(os.fstat(fd)) == after[path]['epoch']\n    os.close(fd)")
observer = observer.replace('vast_component_source_boundary_test_execution_v1', 'vast_cpu04_corrected_cold_consumer_execution_v1')
observer = observer.replace('Actual cold provider/cardinality entry and physical header reader regressions plus existing temporary-file/socket runtime fixtures; no Docker/model/guardian/hardware or CPU rerun.',
    'One separately pinned corrected cold consumer under original v5 producer source bytes; actual readonly image inspections and original model numeric validation are stock operations. No new native measurement/guardian/container/device probe/reserve. Original CPU04 CLI remains failed; current custody epochs are new observations, never rebound to original execution witnesses.')
observer = observer.replace("'sources_stable': before == after,", "'sources_stable': before == after, 'execution_budget_s': 600, 'teardown_budget_s': 15, 'original_producer_byte_pins': 95, 'separately_pinned_reader': True, 'original_cli_remains_failed': True,")
with (base / 'observe.py').open('xb') as stream:
    stream.write(observer.encode())
rows = []
for name in ('run_reader.py', 'corrected_component_runtime_v1.py', 'arguments.v1.json', 'observe.py'):
    path = base / name
    raw = path.read_bytes()
    rows.append({'path': str(path.relative_to(root)), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
with (base / 'preparation.v1.json').open('xb') as stream:
    stream.write((json.dumps({'files': rows, 'executed': False, 'original_cli_remains_failed': True,
        'source_restoration_not_performed': True, 'producer_sources_must_equal_original_v5_bytes': True,
        'stock_cold_predicates_unchanged_except_provider': True}, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps({'files': len(rows), 'reader_sha256': reader_sha, 'cold_output': arguments['output_dir'], 'executed': False}))
