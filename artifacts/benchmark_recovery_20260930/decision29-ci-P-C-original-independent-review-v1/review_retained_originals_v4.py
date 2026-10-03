"""Finite read-only review of retained originals; never import or execute CI targets."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
START = time.monotonic()
END = START + 180
read_pins = {}
REQUIRED = ['test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.' + name
            for name in ('test_native_client_regression', 'test_native_policy_topology_regression', 'test_native_reset_queue_level_regression')]
TARGETS = ['vast_native_gst_probe', 'vast_checkpoint_source', 'gstadaptivescheduler',
           'gstvastanalyticsterminal', 'gstvastanalyticsqueue', 'gstvastcheckpointprefixqueue']
FAILED_ID = 'test_publication_runtime_frozen_identity_constants_v1.PublicationRuntimeFrozenIdentityConstantsV1Tests.test_gstreamer_current_runtime_is_exactly_refrozen'

def clock():
    assert time.monotonic() < END

def descriptor(path, raw):
    return {'path': path.as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def read(path, cap=8*1048576):
    clock()
    named_before = epoch(path.stat())
    with path.open('rb') as stream:
        before = epoch(os.fstat(stream.fileno()))
        raw = stream.read(cap + 1)
        assert len(raw) <= cap and before == epoch(os.fstat(stream.fileno()))
    assert named_before == epoch(path.stat()) and before[:6] == named_before[:6]
    pin = descriptor(path, raw)
    if path in read_pins:
        assert read_pins[path] == pin
    read_pins[path] = pin
    return raw

def member_json(members, name):
    return json.loads(members[name])

def verify_archive(row, provider):
    path = ROOT / row['path']
    raw = read(path)
    assert len(raw) == row['size_bytes'] == provider['size_in_bytes'] <= 8*1048576
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
    assert provider['digest'] == 'sha256:' + row['sha256'] and not provider['expired']
    expected = {r['name']: r for r in row['members']}
    assert len(expected) == row['member_count'] <= 4096
    observed = []
    retained = {}
    decoded = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert len(archive.infolist()) == len(expected)
        names = set()
        for item in archive.infolist():
            clock()
            name = PurePosixPath(item.filename)
            assert item.filename not in names and not name.is_absolute() and '..' not in name.parts and '\\' not in item.filename and ':' not in item.filename
            mode = item.external_attr >> 16
            assert not stat.S_ISLNK(mode) and (not mode or stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR))
            names.add(item.filename)
            decoded += item.file_size
            assert decoded <= 64*1048576
            h = hashlib.sha256()
            crc = count = 0
            parts = []
            keep = item.filename.endswith('.json') or item.filename in ('namespace-diagnostic/stdout.raw', 'namespace-diagnostic/kernel-query/stdout.raw')
            with archive.open(item) as stream:
                while block := stream.read(65536):
                    clock(); count += len(block); h.update(block); crc = zlib.crc32(block, crc)
                    if keep: parts.append(block)
            actual = {'name': item.filename, 'size_bytes': count, 'sha256': h.hexdigest(), 'crc32': crc}
            assert count == item.file_size and crc == item.CRC and actual == expected[item.filename]
            observed.append(actual)
            if keep: retained[item.filename] = b''.join(parts)
    assert decoded == row['decoded_size_bytes']
    return {'original_zip': read_pins[path], 'provider_digest_matched': True, 'member_count': len(observed),
            'decoded_size_bytes': decoded, 'all_CRC_full_SHA_and_safe_paths_verified': True, 'members': observed}, retained

plans = [('P', 37111719589, 111170763707, 111170763520, '56dd56bcc80519b99357546a49dbd65377e0db22',
          '94201084415e76c286aad629e47127ae4e721081cbf9b1857bbc075af2077e60', 2987, 2978, 2889, 'd083df', 5393),
         ('C', 37114105253, 111177442716, 111177442486, '04a5d1c7b90274af71f4ff2456ec3013107c2bb3',
          '38ea1f36337684aeff0bb46edb5da12956785913532712a07a9d94766ffcec76', 3001, 2992, 2903, '8d3cc5', 5561)]
reviews = []
for label, run_id, cpu_id, host_id, commit, source_sha, discovered, selected, successes, executor_tool, tracked_count in plans:
    directory = BASE / ('decision29-ci-' + label + '-original-retention-v1')
    source = read(directory / 'retain_originals_v1.py')
    assert len(source) == 6058 and hashlib.sha256(source).hexdigest() == source_sha
    raw_b = read(directory / 'original-source.raw')
    assert len(raw_b) == 6058 and hashlib.sha256(raw_b).hexdigest() == '3895c7e42bdfd10780da256e960559659389e475d4e7a8484b5813e9945733c5'
    source_review = json.loads(read(directory / 'root-independent-source-review.v1.json'))
    terminal = json.loads(read(directory / 'original-retention-terminal.v1.json'))
    assert terminal['status'] == 'originals_retained' and terminal['run_id'] == run_id and terminal['source_commit'] == commit
    assert terminal['provider_run_success'] is False and terminal['provider_expected_conclusion'] == 'failure'
    assert terminal['expected_job_conclusions'] == {str(cpu_id): 'failure', str(host_id): 'success'}
    assert terminal['elapsed_s'] < 180 and terminal['temporary_signed_URL_or_token_saved'] is False and terminal['workflow_action'] is None
    metadata_path = ROOT / terminal['metadata']['path']
    metadata_raw = read(metadata_path)
    assert descriptor(Path(terminal['metadata']['path']), metadata_raw) == terminal['metadata']
    metadata = json.loads(metadata_raw)
    provider_run = metadata['run']
    assert provider_run['id'] == run_id and provider_run['head_sha'] == commit and provider_run['status'] == 'completed' and provider_run['conclusion'] == 'failure'
    jobs = {j['id']: j for j in metadata['jobs']['jobs']}
    assert set(jobs) == {cpu_id, host_id}
    assert jobs[cpu_id]['conclusion'] == 'failure' and jobs[host_id]['conclusion'] == 'success'
    assert all(j['run_id'] == run_id and j['head_sha'] == commit for j in jobs.values())
    failed_steps = [s for s in jobs[cpu_id]['steps'] if s['conclusion'] == 'failure']
    assert len(failed_steps) == 1 and failed_steps[0]['number'] == 12
    providers = {a['id']: a for a in metadata['artifacts']['artifacts']}
    assert len(providers) == metadata['artifacts']['total_count'] == 2
    assert len(terminal['originals']) == 4
    originals = []
    archive_reviews = []
    archives = {}
    for row in terminal['originals']:
        path = ROOT / row['path']
        data = read(path, 32*1048576 if row['kind'] == 'original_job_log' else 8*1048576)
        assert descriptor(Path(row['path']), data) == {k: row[k] for k in ('path', 'size_bytes', 'sha256')}
        originals.append(read_pins[path])
        if row['kind'] == 'original_artifact':
            provider = providers[row['artifact_id']]
            assert provider['workflow_run']['id'] == run_id and provider['workflow_run']['head_sha'] == commit
            verified, members = verify_archive(row, provider)
            archive_reviews.append(verified)
            archives['cpu' if row['artifact_name'].startswith('vast-cpu-checks-') else 'host'] = members
    assert set(archives) == {'cpu', 'host'}
    cpu = archives['cpu']; host = archives['host']
    report = member_json(cpu, 'report.json')
    child = member_json(cpu, 'unittest-child.report.json')
    assert report['commit'] == commit and report['successful'] is False and report['hardware_acceptance'] is False
    assert report['failure'] == 'RuntimeError: original full-suite child/observer failed; see original lifecycle/trace'
    assert report['unittest'] == child
    assert len(child['discovered_ids']) == discovered and child['tests_run'] == selected and len(child['successful_test_ids']) == successes
    assert len(set(child['discovered_ids'])) == discovered and len(set(child['successful_test_ids'])) == successes
    assert child['errors'] == child['expected_failures'] == child['unexpected_successes'] == child['missing_required_successes'] == []
    assert len(child['failures']) == 1 and child['failures'][0]['test_id'] == FAILED_ID
    traceback = child['failures'][0]['traceback']
    assert 'line 346' in traceback and 'decision28-2a6a42c9' in traceback and 'component-release-20260930-a4e145b7' in traceback
    assert len(child['skips']) == len(child['portable_skip_audit']) == 88
    selection = child['selection']
    assert selection['counts'] == {'discovered': discovered, 'portable': selected, 'integration': 9}
    assert selection['integration_executed'] is False and selection['hardware_acceptance'] is False
    assert selection['discovered_ids'] == child['discovered_ids'] and len(selection['portable_ids']) == selected
    portable = set(selection['portable_ids']); successful = set(child['successful_test_ids'])
    failed = {r['test_id'] for r in child['failures']}; skipped = {r['test_id'] for r in child['skips']}
    assert successful.isdisjoint(failed | skipped) and failed.isdisjoint(skipped) and portable == successful | failed | skipped
    allowed = {r['test_id']: r for r in selection['allowed_portable_skips']}
    audit = []
    for row in child['skips']:
        assert row['test_id'] in allowed and row['reason'] == allowed[row['test_id']]['reason']
        audit.append(allowed[row['test_id']])
    assert sorted(audit, key=lambda r: r['test_id']) == child['portable_skip_audit']
    assert all(row['acceptance_claim'] is False for row in audit)
    assert set(REQUIRED) <= successful and report['built_targets'] == TARGETS
    for command_name in ('model-assets.json', 'native-configure.json', 'native-build.json'):
        command = member_json(cpu, command_name)
        assert command['returncode'] == 0 and command['timed_out'] is False and command['cleanup_error'] is None
    acquisition = member_json(cpu, 'model-acquisition/report.json')
    assert acquisition['status'] == 'complete' and len(acquisition['assets']) == 8
    assert all(row['status'] == 'downloaded' for row in acquisition['assets'])
    assert cpu['tracked-source.before.json'] == cpu['tracked-source.after.json']
    tracking = member_json(cpu, 'tracked-source.before.json')
    assert len(tracking) == tracked_count and report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == []
    host_report = member_json(host, 'report.json')
    assert host_report['commit'] == commit and host_report['changed_tracked_paths'] == [] and host_report['diagnostic_passed'] is True and host_report['diagnostic_tests_only'] is True and host_report['full_ci_successful'] is False
    assert host['tracked-source.before.json'] == host['tracked-source.after.json'] == cpu['tracked-source.before.json']
    diagnostic = report['namespace_diagnostic']; original = diagnostic['original_setup_observations']
    ready = next(row for row in original if row['event'] == 'original_ready')
    unshare = next(row for row in original if row['event'] == 'syscall_started' and row.get('syscall') == 'unshare')
    unshare_done = next(row for row in original if row['event'] == 'syscall_completed' and row.get('syscall') == 'unshare')
    failed_open = next(row for row in original if row['event'] == 'syscall_failed')
    assert failed_open == diagnostic['first_failed_syscall'] and failed_open['syscall'] == 'open' and failed_open['path'] == '/proc/self/setgroups' and failed_open['errno'] == 13
    assert unshare['flags'] == 268435456 and ready['label']['value'] == 'unconfined'
    assert unshare['monotonic_ns'] <= unshare_done['terminal_monotonic_ns'] <= failed_open['monotonic_ns'] <= failed_open['terminal_monotonic_ns']
    joined = member_json(cpu, 'namespace-profile/joined-denial.json')
    join = joined['join']; owner = diagnostic['owner']; denial = diagnostic['policy_denial']['records'][0]['original_journal_record']
    assert join['pid'] == owner['pid'] == ready['original_pid'] == unshare['original_pid'] == failed_open['original_pid']
    assert join['boot_id'] == owner['boot_id'] and denial['_BOOT_ID'].replace('-', '') == owner['boot_id'].replace('-', '')
    assert join['python'] == owner['executable_realpath'] == ready['executable'] and join['failed_operation'] == 'open:/proc/self/setgroups'
    assert join['denied_profile'] == 'unprivileged_userns' and join['denied_capability'] == 'sys_admin' and join['initial_label'] == 'unconfined'
    match = re.search(r'audit\((\d+)\.(\d{3}):', denial['MESSAGE'])
    assert match is not None
    audit_ns = int(match[1])*1000000000 + int(match[2])*1000000
    assert audit_ns == join['audit_wall_time_ns'] and 'pid=' + str(owner['pid']) in denial['MESSAGE'] and 'operation="capable"' in denial['MESSAGE']
    journal_wall = int(denial['__REALTIME_TIMESTAMP'])*1000
    journal_mono = int(denial['__MONOTONIC_TIMESTAMP'])*1000
    assert diagnostic['started_wall_time_ns']-2000000 <= journal_wall <= diagnostic['terminal_wall_time_ns']+2000000
    assert unshare['monotonic_ns']-2000000 <= journal_mono <= failed_open['terminal_monotonic_ns']+2000000
    for pin in joined['inputs'][1:]:
        relative = pin['path'].split('/vast-cpu-checks/', 1)[1]
        value = cpu[relative]
        assert len(value) == pin['size_bytes'] and hashlib.sha256(value).hexdigest() == pin['sha256']
    clock_review = {'version': 1, 'legacy_strict_allowance_ns': 2000000}
    if label == 'P':
        assert 'namespace_clock_contract_version' not in ready and 'audit_clock_bracket_ns' not in join
        assert unshare['wall_time_ns']-2000000 <= audit_ns <= failed_open['terminal_wall_time_ns']+2000000
    else:
        before = unshare['audit_coarse_before']; after = failed_open['audit_coarse_after']
        assert before == unshare_done['audit_coarse_before']
        for sample, phase in ((before, 'before_unshare'), (after, 'after_failed_setgroups_open')):
            assert sample['available'] is True and sample['clock_id'] == 5 and sample['clock_name'] == 'CLOCK_REALTIME_COARSE'
            assert type(sample['value_ns']) is int and sample['phase'] == phase and sample['original_pid'] == owner['pid'] and sample['boot_id'] == owner['boot_id']
            assert type(sample['started_monotonic_ns']) is int and type(sample['terminal_monotonic_ns']) is int and sample['started_monotonic_ns'] <= sample['terminal_monotonic_ns']
        assert ready['namespace_clock_contract_version'] == join['namespace_clock_contract_version'] == 2
        assert ready['monotonic_ns'] <= before['started_monotonic_ns'] <= before['terminal_monotonic_ns'] <= unshare['monotonic_ns']
        assert failed_open['terminal_monotonic_ns'] <= after['started_monotonic_ns'] <= after['terminal_monotonic_ns'] <= diagnostic['terminal_monotonic_ns']
        bins = [before['value_ns']//1000000*1000000, after['value_ns']//1000000*1000000]
        assert before['value_ns'] <= after['value_ns'] and join['audit_clock_basis'] == 'CLOCK_REALTIME_COARSE' and join['audit_clock_bracket_ns'] == bins
        assert bins[0] <= audit_ns <= bins[1] and bins == [1791020811412000000,1791020811412000000]
        clock_review = {'version': 2, 'CLOCK_REALTIME_COARSE_id': 5, 'before_original': before, 'after_original': after,
                        'observed_millisecond_bins': bins, 'audit_ns': audit_ns, 'inclusive_equal': audit_ns == bins[0] == bins[1]}
    profile = report['namespace_profile']
    assert profile['status'] == 'completed' and profile['attempted'] is True and profile['held_fds_released'] is True
    assert profile['load_verified'] is True and profile['unload_verified'] is True
    for phase in ('load_terminal', 'unload_terminal'):
        assert profile[phase]['returncode'] == 0 and profile[phase]['capture_completed'] is True and profile[phase]['failure'] is None and profile[phase]['timed_out'] is False
    observation = child['profile_observation']
    assert observation['expected_profile'] == observation['actual_label'] == profile['name'] + ' (unconfined)'
    observer = report['observer']
    assert observer['returncode'] == 1 and observer['successful'] is False and all(observer['pipe_eof'].values()) and observer['forced_sigterm'] is False and observer['forced_sigkill'] is False
    relevant = ['scripts/run_ci_checks.py', 'scripts/ci_namespace_diagnostic_v1.py', 'scripts/ci_userns_profile_v1.py',
                'tests/test_ci_namespace_diagnostic_v1.py', 'tests/test_ci_userns_profile_v1.py', 'tests/test_publication_runtime_frozen_identity_constants_v1.py',
                'scripts/checkpoint_gstreamer_publication_runtime_v3.py', 'artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json']
    reviews.append({'label': label, 'run_id': run_id, 'source_commit': commit,
                    'owned_source_pin': read_pins[directory / 'retain_originals_v1.py'],
                    'original_retention_terminal': read_pins[directory / 'original-retention-terminal.v1.json'],
                    'original_provider_metadata': read_pins[metadata_path], 'all_four_original_leaves': originals,
                    'root_reported_original_executor_closure': {'tool_id': executor_tool, 'returncode': 0, 'retention_elapsed_s': terminal['elapsed_s'], 'source': 'Parent original tool closure; original PID/FD/process scans not recorded by this retainer.'},
                    'provider_status': 'completed', 'provider_conclusion': 'failure',
                    'CPU_job_id': cpu_id, 'CPU_conclusion': 'failure', 'CPU_failed_step': failed_steps[0], 'host_job_id': host_id, 'host_conclusion': 'success',
                    'verified_archives': archive_reviews,
                    'original_test_counts': {'discovered': discovered, 'selected': selected, 'success': successes, 'skip': 88, 'failure': 1, 'error': 0, 'deferred_integration': 9},
                    'original_failure': child['failures'][0], 'required_native_test_ids_successful': REQUIRED,
                    'six_built_targets': TARGETS, 'all_eight_model_acquisitions_complete': True,
                    'selection_manifest_path': selection['manifest_path'], 'selection_manifest_sha256': selection['manifest_sha256'],
                    'all_portable_skips_exactly_allowlisted': True, 'skip_audit': child['portable_skip_audit'],
                    'nine_deferred_integration_declarations': selection['integration_declarations'],
                    'raw_checkout_bytes_match_commit': True, 'tracked_file_count': tracked_count,
                    'original_source_before_after_bytes_identical': True, 'relevant_original_source_descriptors': {k: tracking[k] for k in relevant},
                    'clock_policy_join': clock_review, 'joined_denial_original': joined, 'original_kernel_record': denial,
                    'profile_original': profile, 'profile_child_observation': observation, 'observer_original': observer,
                    'original_host_report': host_report,
                    'original_failed_remains_failed': True, 'mandatory_CI_pass': False,
                    'limits': ['All ZIP members and all four retained original leaves are hashed/CRC/path/size checked locally without requests or extraction.',
                               'Source-before/after equality is the retained provider original inventory; no Git/source/model/native/test/profile command was replayed.',
                               'The first joined input is a retained executable descriptor; the provider interpreter bytes are not present in the ZIP and are not freshly rehashed here.',
                               'Original observer explicitly does not establish descendant quiescence from original child status. No new process absence or numeric FD count is invented.',
                               'Skipped/deferred tests and hosted CPU tests do not grant physical GPU/full scientific acceptance.']})
for path, pin in list(read_pins.items()):
    assert descriptor(path, read(path, 32*1048576)) == pin
result = {'schema_version': 1, 'reviewer': '/root/decision28_source_peer', 'reviewable': True, 'blocking_findings': [],
          'reviewer_handles_released': True, 'owned_source_pins': [r['owned_source_pin'] for r in reviews],
          'original_runs': reviews, 'mandatory_CI_failure_blocks_merge': True,
          'merge_blocking_failures': [{'run_id': r['run_id'], 'test_id': FAILED_ID} for r in reviews],
          'no_provider_or_target_action': True, 'elapsed_s': time.monotonic()-START}
raw = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
assert len(raw) <= 8*1048576
path = HERE / 'review.v1.json'
with path.open('xb') as stream:
    assert stream.write(raw) == len(raw)
print(json.dumps({'review': descriptor(path, raw), 'original_provider_conclusions': ['failure', 'failure'], 'reviewable': True}, sort_keys=True))
