"""Read the closed original ZIP and compare a finite set of committed CI sources."""
import collections
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = ROOT / 'artifacts/benchmark_recovery_20260930/ci-a3-original-retention-v1'
COMMIT = 'a3e976d02e19e714232bc78a4da3e72c99bb8cde'
PATHS = (
    '.github/workflows/ci.yml', 'scripts/run_ci_checks.py',
    'scripts/ci_external_test_observer_v1.py', 'scripts/run_ci_host_diagnostics.py',
    'scripts/prepare_ci_model_assets.py', '.ci/model-assets.v1.json',
    'tests/test_analytics_peer_identity.py',
    'scripts/backend_publication_process_supervisor_v3.py',
    'tests/test_backend_q4_two_phase_executor_v1.py',
    'scripts/publication_policy_qualification_execution_code_closure_v1.py',
    'tests/test_checkpoint_analytics_execution_client_cpp.py',
)


def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def seal(name, value):
    with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, separators=(',', ':'))
        stream.write('\n')
    return descriptor(OUT / name)


def exception_line(row):
    lines = row['traceback'].rstrip().splitlines()
    assertions = [line for line in lines if line.startswith('AssertionError')]
    return assertions[0] if assertions else lines[-1]


def error_bucket(row):
    line = exception_line(row)
    if line.startswith('FileNotFoundError:'):
        return 'absent_physical_fixture_or_output'
    if line.startswith('ModuleNotFoundError:'):
        return 'module_import'
    if 'Python interpreter is not one canonical physical file' in line:
        return 'interpreter_canonical_path_predicate'
    if 'missing reachable Python source:' in line:
        return 'runtime_source_dependency_inventory'
    if 'stage=namespace;' in line and 'errno=13' in line:
        return 'namespace_stage_errno13'
    if 'POSIX broker' in line:
        return 'broker_other_or_cascade'
    return 'other_original_exception'


jobs = json.loads((OUT / 'jobs.connector.json').read_bytes())['jobs']
artifacts = json.loads((OUT / 'artifacts.connector.json').read_bytes())['artifacts']
job = next(row for row in jobs if row['id'] == 109855554487)
artifact = next(row for row in artifacts if row['id'] == 11092536960)
assert job['run_id'] == 36705774549 and job['status'] == 'completed'
assert job['conclusion'] == 'failure' and artifact['workflow_run']['head_sha'] == COMMIT
zip_path = OUT / '36705774549-cpu/original-artifact.zip'
zip_descriptor = descriptor(zip_path)
assert zip_descriptor['size_bytes'] == artifact['size_in_bytes'] == 1431770
assert zip_descriptor['sha256'] == artifact['digest'].removeprefix('sha256:')
inventory = json.loads((zip_path.parent / 'zip-readonly-inventory.v1.json').read_bytes())
assert inventory['all_member_crc_verified'] and inventory['zip_members'] == 159
with zipfile.ZipFile(zip_path) as archive:
    names = set(archive.namelist())
    report = json.loads(archive.read('report.json'))
    child = json.loads(archive.read('unittest-child.report.json'))
    observer = json.loads(archive.read('external-test-observer/terminal.v1.json'))
    before = json.loads(archive.read('tracked-source.before.json'))
    after = json.loads(archive.read('tracked-source.after.json'))
    assert report['commit'] == COMMIT and report['unittest'] == child
    assert report['observer'] == observer and before == after
    assert report['changed_tracked_paths'] == [] and report['raw_checkout_bytes_match_commit']
    assert not report['successful'] and not child['successful'] and not report['hardware_acceptance']
    assert observer['returncode'] == 1 and observer['signal'] is None
    assert not observer['forced_sigterm'] and not observer['forced_sigkill']
    assert observer['pipe_eof'] == {'control': True, 'trace': True}
    critical = []
    for path in PATHS:
        raw = subprocess.run(
            ['/usr/bin/git', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
             '--work-tree=' + str(ROOT), 'show', COMMIT + ':' + path],
            capture_output=True, check=True, timeout=10).stdout
        actual = {'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        assert before[path] == actual
        critical.append({'path': path, **actual})
    members = []
    for path in ('report.json', 'unittest-child.report.json', 'tracked-source.before.json',
                 'tracked-source.after.json', 'external-test-observer/terminal.v1.json',
                 'external-test-observer/launch.v1.json', 'external-test-observer/events.original.jsonl',
                 'external-test-observer/responses.original.jsonl', 'external-test-observer/trace.original.log',
                 'unittest.original.log', 'model-acquisition/report.json', 'native-build.json'):
        raw = archive.read(path)
        members.append({'member': path, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    model = json.loads(archive.read('model-acquisition/report.json'))
    assert model['status'] == 'complete' and len(model['assets']) == 8
    assert all(row['status'] == 'downloaded' for row in model['assets'])
    build = json.loads(archive.read('native-build.json'))
    assert build['returncode'] == 0 and not build['timed_out']
    required_prefix = 'test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.'
    required = [required_prefix + suffix for suffix in (
        'test_native_client_regression', 'test_native_policy_topology_regression',
        'test_native_reset_queue_level_regression')]
    required_outcomes = [{'test_id': test_id, 'passed': test_id in child['successful_test_ids']}
                         for test_id in required]
    assert child['missing_required_successes'] == [required[-1]]
    failures = [{'kind': kind, 'test_id': row['test_id'], 'original_exception_line': exception_line(row),
                 'original_traceback_sha256': hashlib.sha256(row['traceback'].encode()).hexdigest()}
                for kind in ('errors', 'failures') for row in child[kind]]
    failure_index = seal('failure-index.v1.json', {'source_zip': zip_descriptor, 'rows': failures,
        'scope': 'Derived index of original report rows; full original tracebacks remain in the ZIP.'})
    counts = {key: len(child[key]) for key in ('errors', 'failures', 'skips', 'successful_test_ids',
                                              'expected_failures', 'unexpected_successes', 'missing_required_successes')}
    error_buckets = dict(collections.Counter(error_bucket(row) for row in child['errors']))
    modules = {kind: dict(collections.Counter(row['test_id'].split('.')[0] for row in child[kind]))
               for kind in ('errors', 'failures')}
    receipt = {
        'schema_version': 1, 'artifact_kind': 'vast_a3_original_ci_readonly_outcome_join_v1',
        'run_id': 36705774549, 'job_id': job['id'], 'job_conclusion': 'failure',
        'artifact_id': artifact['id'], 'source_commit': COMMIT, 'zip': zip_descriptor,
        'zip_members': 159, 'all_crc_and_provider_digest_verified': True,
        'original_members': members, 'decoded_job_log': descriptor(OUT / 'original-decoded-job.log'),
        'source_before_after_equal': True, 'tracked_paths': len(before),
        'report_raw_checkout_matches_commit': True, 'critical_committed_blobs_verified': critical,
        'full_report_elapsed_s': report['elapsed_s'], 'full_report_failure': report['failure'],
        'tests_run': child['tests_run'], 'original_result_row_counts': counts,
        'row_count_note': 'Result arrays include subtests/class setup failures and are not a disjoint partition of tests_run.',
        'error_message_buckets': error_buckets, 'original_result_module_counts': modules,
        'failure_index': failure_index, 'required_native_outcomes': required_outcomes,
        'six_native_build_targets': report['built_targets'], 'native_build_returncode': 0,
        'model_acquisition': {'downloaded': 8, 'elapsed_s': model['elapsed_s']},
        'observer': {key: observer[key] for key in (
            'returncode', 'signal', 'failure', 'ready', 'pidfd_acquisition_failed',
            'forced_sigterm', 'forced_sigkill', 'pipe_eof', 'requests_sent', 'responses_started',
            'responses_completed', 'requests_stopped_before_disposition_restore', 'trace_bytes',
            'response_channel_bytes', 'unmatched_or_coalesced_requests_possible', 'descendant_quiescence')},
        'limitations': [
            'Original normal child returncode1 is observed; it does not establish the cause of earlier139 terminations.',
            'Message buckets are triage, not proved root causes; namespace errno13 does not identify a denial policy or syscall.',
            'Connector API snapshots are normalized and job text decoded; no raw HTTP byte identity is claimed.',
            'No CI/workflow action, cancellation, restart, test execution, profile change, Docker or hardware workload.',
            'Mapped source membership/source before-after do not grant model parity or benchmark acceptance.'],
        'temporary_urls_saved': False, 'full_ci_successful': False, 'hardware_acceptance': False,
    }
    result = seal('outcome-join.v1.json', receipt)
    print(json.dumps({'receipt': result, 'failure_index': failure_index,
                      'counts': counts, 'error_message_buckets': error_buckets,
                      'required_native_outcomes': required_outcomes}, sort_keys=True))
