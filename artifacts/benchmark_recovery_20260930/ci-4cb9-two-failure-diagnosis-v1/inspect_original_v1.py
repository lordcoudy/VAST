"""Finite read-only inspection of the original 4cb hosted failure artifact."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
OUT = BASE / 'ci-4cb9-two-failure-diagnosis-v1'
ZIP = BASE / 'ci-4cb9-original-host-retention-v1/36783010512-cpu/original-artifact.zip'
EXPECTED = 'ad640c85c3641140fb26ce5f473bc37ff4424c731f0cebf6bb36068643f55bfb'
IDS = (
    'test_backend_publication_output_transaction_v3.BackendPublicationOutputTransactionV3Tests.test_two_coordinators_spawn_at_most_once',
    'test_publication_operational_process_custody_v1.ProcessCustodyTests.test_caught_invalid_phase_remains_sticky_and_call_capacity_is_bounded',
)
FILES = (
    'scripts/backend_publication_process_supervisor_v3.py',
    'scripts/backend_publication_output_transaction_v3.py',
    'scripts/publication_operational_process_custody_v1.py',
    'tests/test_backend_publication_output_transaction_v3.py',
    'tests/test_publication_operational_process_custody_v1.py',
)

def descriptor(path):
    raw = path.read_bytes()
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'epoch': [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]}

def write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())

def contains(value, target):
    if isinstance(value, dict):
        return any(contains(item, target) for item in value.values())
    if isinstance(value, list):
        return any(contains(item, target) for item in value)
    return isinstance(value, str) and (value == target or value.endswith('/' + target))

assert ZIP.stat().st_size == 1973434
assert hashlib.sha256(ZIP.read_bytes()).hexdigest() == EXPECTED
copy_dir = OUT / 'observer-original-member-copies-v1'
copy_dir.mkdir()
copied = []
selected = ('external-test-observer/events.original.jsonl', 'external-test-observer/launch.v1.json',
            'external-test-observer/responses.original.jsonl', 'external-test-observer/terminal.v1.json',
            'external-test-observer/trace.original.log')
with zipfile.ZipFile(ZIP) as archive:
    infos = archive.infolist()
    assert len({row.filename for row in infos}) == len(infos)
    assert sum(row.file_size for row in infos) <= 64 * 1024 * 1024
    for row in infos:
        name = PurePosixPath(row.filename)
        assert not name.is_absolute() and '..' not in name.parts and chr(92) not in row.filename
        assert not stat.S_ISLNK(row.external_attr >> 16) and row.file_size <= 8 * 1024 * 1024
    for name in selected:
        info = archive.getinfo(name)
        raw = archive.read(name)
        target = copy_dir / name.split('/')[-1]
        write(target, raw)
        copied.append({'original_member': name, 'crc32': info.CRC, 'copy': descriptor(target)})
    report = json.loads(archive.read('report.json'))
    unittest_report = json.loads(archive.read('unittest-child.report.json'))
    native = json.loads(archive.read('native-build.json'))
    event_rows = [json.loads(line) for line in archive.read(selected[0]).splitlines() if line]

inv = json.loads((BASE / 'component-ext4-relocation-feasibility-v1/inventory.v1.json').read_bytes())
closure_path = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4.v1.json')
closure = json.loads(closure_path.read_bytes())
allowlists = sorted(ROOT.glob('deploy/**/runtime-source-allowlist.txt')) + sorted(ROOT.glob('deploy/**/source-allowlist.txt')) + sorted(ROOT.glob('deploy/**/dependency-allowlist.txt'))
memberships = []
for name in FILES:
    memberships.append({'relative_path': name, 'current': descriptor(ROOT / name),
                        'host87': contains(closure['project_sources'], name),
                        'finite2693': contains(inv['copy_inputs'], name),
                        'allowlists': [str(p.relative_to(ROOT)) for p in allowlists if name in p.read_text().splitlines()]})

unit = report.get('unittest', unittest_report)
fact = {
    'schema_version': 1, 'artifact_kind': 'vast_original_ci_two_failure_inspection_v1',
    'accepted': False, 'original_zip': descriptor(ZIP), 'original_member_count': len(infos),
    'original_copies': copied, 'original_unittest_keys': sorted(unittest_report),
    'original_report_commit': report.get('commit'), 'original_full_elapsed_s': report.get('elapsed_s'),
    'original_tests_run': unit.get('tests_run'),
    'original_success_count': len(unit.get('successful_test_ids', [])),
    'original_failures': unit.get('failures'), 'original_error_count': len(unit.get('errors', [])),
    'original_skip_count': len(unit.get('skips', [])),
    'required_native_missing': unit.get('missing_required_successes'),
    'original_native_build': native, 'original_profile': report.get('namespace_profile'),
    'original_portable_skip_audit': unit.get('portable_skip_audit'),
    'original_source_changed_count': report.get('changed_tracked_paths'),
    'original_observer_terminal': json.loads((copy_dir / 'terminal.v1.json').read_bytes()),
    'matching_observer_events': [row for row in event_rows if any(contains(row, name) for name in IDS)],
    'source_memberships': memberships,
    'limitations': ['The original capacity traceback does not expose the ValueError swallowed by assertRaises.',
                    'A source-demonstrated owner-commit failure response hazard is not a timing reconstruction of the original run.',
                    'No test, namespace, policy, model or engine workload was run by this inspector.'],
}
raw = json.dumps(fact, sort_keys=True, indent=2).encode() + b'\n'
write(OUT / 'original-facts.v1.json', raw)
print(json.dumps({'report': descriptor(OUT / 'original-facts.v1.json'),
                  'memberships': [{k: v for k, v in row.items() if k != 'current'} for row in memberships],
                  'events': fact['matching_observer_events'], 'unittest_keys': fact['original_unittest_keys'],
                  'tests_run': fact['original_tests_run'], 'skip_count': fact['original_skip_count'],
                  'error_count': fact['original_error_count']}, sort_keys=True))
