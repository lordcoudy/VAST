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

directory = BASE / 'decision29-ci-D-original-retention-v1'
run_id, cpu_id, host_id = 37116707816, 111184814376, 111184814522
commit = '3c025b29b3c1d5275c2ec693410e4b83700583de'
source = read(directory / 'retain_originals_v1.py')
assert len(source) == 5915 and hashlib.sha256(source).hexdigest() == 'fd64baad9301accae368f8316c22bf87ea7420d94d7b37562ba2a3b584b2c276'
source_review = json.loads(read(directory / 'root-independent-source-review.v1.json'))
terminal = json.loads(read(directory / 'original-retention-terminal.v1.json'))
assert terminal['status'] == 'originals_retained' and terminal['run_id'] == run_id and terminal['source_commit'] == commit
assert terminal['provider_run_success'] is True and terminal['elapsed_s'] < 180
assert terminal['temporary_signed_URL_or_token_saved'] is False and terminal['workflow_action'] is None
metadata_path = ROOT / terminal['metadata']['path']
metadata_raw = read(metadata_path)
assert descriptor(Path(terminal['metadata']['path']), metadata_raw) == terminal['metadata']
metadata = json.loads(metadata_raw)
provider_run = metadata['run']
assert provider_run['id'] == run_id and provider_run['head_sha'] == commit
assert provider_run['status'] == 'completed' and provider_run['conclusion'] == 'success'
jobs = {j['id']: j for j in metadata['jobs']['jobs']}
assert set(jobs) == {cpu_id, host_id}
assert all(j['run_id'] == run_id and j['head_sha'] == commit and j['conclusion'] == 'success' for j in jobs.values())
assert not any(s['conclusion'] == 'failure' for j in jobs.values() for s in j['steps'])
providers = {a['id']: a for a in metadata['artifacts']['artifacts']}
assert len(providers) == metadata['artifacts']['total_count'] == 2 and len(terminal['originals']) == 4
originals, archive_reviews, archives, archive_rows = [], [], {}, {}
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
        lane = 'cpu' if row['artifact_name'].startswith('vast-cpu-checks-') else 'host'
        archives[lane], archive_rows[lane] = members, row
assert set(archives) == {'cpu', 'host'}
cpu, host = archives['cpu'], archives['host']
report, child = member_json(cpu, 'report.json'), member_json(cpu, 'unittest-child.report.json')
assert report['commit'] == commit and report['successful'] is True and report['hardware_acceptance'] is False
assert report['unittest'] == child and report['elapsed_s'] < 5400
assert report['absolute_deadline_ns'] - report['job_started_monotonic_ns'] == 5400*1000000000
assert len(child['discovered_ids']) == len(set(child['discovered_ids'])) == 3001
assert child['tests_run'] == 2992 and len(child['successful_test_ids']) == len(set(child['successful_test_ids'])) == 2904
assert child['errors'] == child['failures'] == child['expected_failures'] == child['unexpected_successes'] == child['missing_required_successes'] == []
assert len(child['skips']) == len(child['portable_skip_audit']) == 88
selection = child['selection']
assert selection['counts'] == {'discovered': 3001, 'portable': 2992, 'integration': 9}
assert selection['integration_executed'] is False and selection['hardware_acceptance'] is False
assert selection['discovered_ids'] == child['discovered_ids']
portable, successful = set(selection['portable_ids']), set(child['successful_test_ids'])
skipped = {r['test_id'] for r in child['skips']}
assert len(portable) == 2992 and len(skipped) == 88 and successful.isdisjoint(skipped) and portable == successful | skipped
allowed = {r['test_id']: r for r in selection['allowed_portable_skips']}
audit = []
for row in child['skips']:
    assert row['test_id'] in allowed and row['reason'] == allowed[row['test_id']]['reason']
    audit.append(allowed[row['test_id']])
assert sorted(audit, key=lambda r: r['test_id']) == child['portable_skip_audit']
assert all(row['acceptance_claim'] is False for row in audit)
assert len(selection['integration_declarations']) == 9
assert set(REQUIRED) <= successful and report['built_targets'] == TARGETS
for command_name in ('model-assets.json', 'native-configure.json', 'native-build.json'):
    command = member_json(cpu, command_name)
    assert command['returncode'] == 0 and command['timed_out'] is False and command['cleanup_error'] is None
acquisition = member_json(cpu, 'model-acquisition/report.json')
assert acquisition['status'] == 'complete' and len(acquisition['assets']) == 8
assert [r['index'] for r in acquisition['assets']] == list(range(8))
assert all(row['status'] == 'downloaded' for row in acquisition['assets'])
assert sum(row['size_bytes'] for row in acquisition['assets']) == 15514597
assert cpu['tracked-source.before.json'] == cpu['tracked-source.after.json']
tracking = member_json(cpu, 'tracked-source.before.json')
assert isinstance(tracking, dict) and len(tracking) == 5577
assert all(set(r) == {'size_bytes', 'sha256'} for r in tracking.values())
assert report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == []
assert hashlib.sha256(cpu['tracked-source.before.json']).hexdigest() == '105568f276b37f57aad59b81efaa6524c816b4e595679da56807a1087daba0ea'
assert tracking[selection['manifest_path']]['sha256'] == selection['manifest_sha256']
host_report = member_json(host, 'report.json')
assert host_report['commit'] == commit and host_report['changed_tracked_paths'] == []
assert host_report['diagnostic_passed'] is True and host_report['diagnostic_tests_only'] is True and host_report['full_ci_successful'] is False
assert host['tracked-source.before.json'] == host['tracked-source.after.json'] == cpu['tracked-source.before.json']

# Join every streamed test start/terminal to the report instead of inferring from its final count.
cpu_zip_path = ROOT / archive_rows['cpu']['path']
with zipfile.ZipFile(io.BytesIO(read(cpu_zip_path))) as archive:
    test_raw = archive.read('unittest.original.log')
    original_profile = archive.read('namespace-profile/owned.profile')
    profile_lists = {phase: archive.read('namespace-profile/' + phase + '/stdout.raw')
                     for phase in ('load-before', 'load-after', 'unload-after')}
assert len(test_raw) <= 8*1048576
original_test_pin = next(r for r in archive_rows['cpu']['members'] if r['name'] == 'unittest.original.log')
assert len(test_raw) == original_test_pin['size_bytes'] and hashlib.sha256(test_raw).hexdigest() == original_test_pin['sha256']
starts, finishes = {}, {}
for line in test_raw.splitlines():
    if not line.startswith(b'{'): continue
    item = json.loads(line)
    if item.get('event') == 'test_started':
        assert item['test_id'] not in starts
        starts[item['test_id']] = item
    elif item.get('event') == 'test_terminal':
        assert item['test_id'] not in finishes
        finishes[item['test_id']] = item
assert set(starts) == set(finishes) == portable
assert {k for k, v in finishes.items() if v['outcome'] == 'success'} == successful
assert {k for k, v in finishes.items() if v['outcome'] == 'skip'} == skipped
assert all(starts[k]['monotonic_ns'] <= finishes[k]['monotonic_ns'] and finishes[k]['elapsed_s'] >= 0 for k in starts)
assert b'Ran 2992 tests' in test_raw and b'OK (skipped=88)' in test_raw

diagnostic = report['namespace_diagnostic']; original = diagnostic['original_setup_observations']
ready = next(row for row in original if row['event'] == 'original_ready')
unshare = next(row for row in original if row['event'] == 'syscall_started' and row.get('syscall') == 'unshare')
unshare_done = next(row for row in original if row['event'] == 'syscall_completed' and row.get('syscall') == 'unshare')
failed_open = next(row for row in original if row['event'] == 'syscall_failed')
assert failed_open == diagnostic['first_failed_syscall'] and failed_open['syscall'] == 'open'
assert failed_open['path'] == '/proc/self/setgroups' and failed_open['errno'] == 13
assert unshare['flags'] == 268435456 and ready['label']['value'] == 'unconfined'
assert unshare['monotonic_ns'] <= unshare_done['terminal_monotonic_ns'] <= failed_open['monotonic_ns'] <= failed_open['terminal_monotonic_ns']
joined = member_json(cpu, 'namespace-profile/joined-denial.json')
join, owner = joined['join'], diagnostic['owner']
denial = diagnostic['policy_denial']['records'][0]['original_journal_record']
assert join['pid'] == owner['pid'] == ready['original_pid'] == unshare['original_pid'] == failed_open['original_pid']
assert join['boot_id'] == owner['boot_id'] and denial['_BOOT_ID'].replace('-', '') == owner['boot_id'].replace('-', '')
assert join['python'] == owner['executable_realpath'] == ready['executable'] and join['failed_operation'] == 'open:/proc/self/setgroups'
assert join['denied_profile'] == 'unprivileged_userns' and join['denied_capability'] == 'sys_admin' and join['initial_label'] == 'unconfined'
match = re.search(r'audit\((\d+)\.(\d{3}):', denial['MESSAGE']); assert match
audit_ns = int(match[1])*1000000000 + int(match[2])*1000000
assert audit_ns == join['audit_wall_time_ns'] and 'pid=' + str(owner['pid']) in denial['MESSAGE'] and 'operation="capable"' in denial['MESSAGE']
assert diagnostic['started_wall_time_ns']-2000000 <= int(denial['__REALTIME_TIMESTAMP'])*1000 <= diagnostic['terminal_wall_time_ns']+2000000
assert unshare['monotonic_ns']-2000000 <= int(denial['__MONOTONIC_TIMESTAMP'])*1000 <= failed_open['terminal_monotonic_ns']+2000000
for pin in joined['inputs'][1:]:
    relative = pin['path'].split('/vast-cpu-checks/', 1)[1]
    value = cpu[relative]
    assert len(value) == pin['size_bytes'] and hashlib.sha256(value).hexdigest() == pin['sha256']
before, after = unshare['audit_coarse_before'], failed_open['audit_coarse_after']
assert before == unshare_done['audit_coarse_before']
for sample, phase in ((before, 'before_unshare'), (after, 'after_failed_setgroups_open')):
    assert sample['available'] is True and sample['clock_id'] == 5 and sample['clock_name'] == 'CLOCK_REALTIME_COARSE'
    assert type(sample['value_ns']) is int and sample['phase'] == phase and sample['original_pid'] == owner['pid'] and sample['boot_id'] == owner['boot_id']
    assert sample['started_monotonic_ns'] <= sample['terminal_monotonic_ns']
assert ready['namespace_clock_contract_version'] == join['namespace_clock_contract_version'] == 2
assert ready['monotonic_ns'] <= before['started_monotonic_ns'] <= before['terminal_monotonic_ns'] <= unshare['monotonic_ns']
assert failed_open['terminal_monotonic_ns'] <= after['started_monotonic_ns'] <= after['terminal_monotonic_ns'] <= diagnostic['terminal_monotonic_ns']
bins = [before['value_ns']//1000000*1000000, after['value_ns']//1000000*1000000]
assert before['value_ns'] <= after['value_ns'] and join['audit_clock_basis'] == 'CLOCK_REALTIME_COARSE'
assert join['audit_clock_bracket_ns'] == bins == [1791023604417000000, 1791023604417000000] and audit_ns == bins[0]
profile = report['namespace_profile']
assert profile == member_json(cpu, 'namespace-profile/profile-lifecycle.json')
assert profile['status'] == 'completed' and profile['attempted'] is True and profile['held_fds_released'] is True
assert profile['load_verified'] is True and profile['unload_verified'] is True
for phase in ('load_terminal', 'unload_terminal'):
    assert profile[phase]['returncode'] == 0 and profile[phase]['capture_completed'] is True and profile[phase]['failure'] is None and profile[phase]['timed_out'] is False
assert hashlib.sha256(original_profile).hexdigest() == profile['profile']['sha256'] and len(original_profile) == profile['profile']['size_bytes']
assert original_profile.decode() == 'abi <abi/4.0>,\nprofile ' + profile['name'] + ' ' + join['python'] + ' flags=(unconfined) {\n  userns,\n}\n'
assert profile['name'].encode() not in profile_lists['load-before'] and profile['name'].encode() in profile_lists['load-after'] and profile['name'].encode() not in profile_lists['unload-after']
observation = child['profile_observation']
assert observation['actual_label']['path'] == '/proc/self/attr/current'
assert observation['expected_profile'] == observation['actual_label']['value'] == profile['name'] + ' (unconfined)'
observer = report['observer']
assert observer == member_json(cpu, 'external-test-observer/terminal.v1.json')
assert observer['returncode'] == 0 and observer['successful'] is True and observer['failure'] is None
assert all(observer['pipe_eof'].values()) and observer['forced_sigterm'] is False and observer['forced_sigkill'] is False
assert observer['owner']['pid'] == observation['pid'] and observer['owner']['boot_id'] == owner['boot_id']
assert observer['requests_sent'] == observer['responses_started'] == observer['responses_completed'] == 19
assert observer['requests_stopped_before_disposition_restore'] is True

# Retain exact original control member bytes; these are decoded copies, never a new provider terminal.
decoded = []
control_plan = {'cpu': {'report.json': 'cpu.report.original.json',
                       'tracked-source.before.json': 'cpu.source-before.original.json',
                       'tracked-source.after.json': 'cpu.source-after.original.json',
                       'unittest-child.report.json': 'cpu.unittest-child.report.original.json',
                       'external-test-observer/terminal.v1.json': 'cpu.observer-terminal.original.json',
                       'namespace-profile/joined-denial.json': 'cpu.joined-denial.original.json',
                       'namespace-profile/profile-lifecycle.json': 'cpu.profile-lifecycle.original.json',
                       'model-acquisition/report.json': 'cpu.model-acquisition.original.json'},
                'host': {'report.json': 'host.report.original.json'}}
for lane, plan in control_plan.items():
    original_zip = read_pins[ROOT / archive_rows[lane]['path']]
    expected = {r['name']: r for r in archive_rows[lane]['members']}
    for member_name, destination_name in plan.items():
        value = archives[lane][member_name]; destination = HERE / destination_name
        assert len(value) == expected[member_name]['size_bytes'] and hashlib.sha256(value).hexdigest() == expected[member_name]['sha256']
        with destination.open('xb') as stream:
            assert stream.write(value) == len(value); stream.flush(); os.fsync(stream.fileno())
        assert read(destination) == value
        decoded.append({'descriptor': read_pins[destination], 'original_zip': original_zip, 'original_member': expected[member_name], 'raw_member_bytes_unchanged': True})
for path, pin in list(read_pins.items()):
    assert descriptor(path, read(path, 32*1048576)) == pin
result = {'schema_version': 1, 'reviewer': '/root/architecture_review', 'reviewable': True, 'blocking_findings': [],
          'source_commit': commit, 'run_id': run_id, 'CPU_job_id': cpu_id, 'host_job_id': host_id,
          'provider_status': 'completed', 'provider_conclusion': 'success', 'both_job_conclusions': 'success',
          'original_retention_terminal': read_pins[directory / 'original-retention-terminal.v1.json'],
          'original_provider_metadata': read_pins[metadata_path], 'owned_retainer_source': read_pins[directory / 'retain_originals_v1.py'],
          'all_four_original_leaves': originals, 'verified_archives': archive_reviews, 'decoded_original_controls': decoded,
          'original_test_counts': {'discovered': 3001, 'selected': 2992, 'success': 2904, 'skip': 88, 'failure': 0, 'error': 0, 'missing_required_success': 0, 'deferred_integration': 9},
          'raw_test_start_terminal_log': original_test_pin, 'all_2992_unique_start_terminal_and_outcome_joins': True,
          'required_native_test_ids_successful': REQUIRED, 'six_built_targets': TARGETS,
          'selection_manifest_path': selection['manifest_path'], 'selection_manifest_sha256': selection['manifest_sha256'],
          'all_portable_skips_exactly_allowlisted': True, 'skip_audit': child['portable_skip_audit'],
          'nine_deferred_integration_declarations': selection['integration_declarations'],
          'raw_checkout_bytes_match_commit': True, 'tracked_file_count': 5577, 'source_before_after_bytes_identical': True,
          'source_table_shape': 'dict keyed repository-relative path; each value exact size_bytes/sha256',
          'clock_policy_join': {'version': 2, 'before_original': before, 'after_original': after, 'observed_millisecond_bins': bins, 'audit_ns': audit_ns},
          'joined_denial_original': joined, 'original_kernel_record': denial, 'profile_original': profile,
          'profile_child_observation': observation, 'observer_original': observer, 'original_host_report': host_report,
          'all_eight_hosted_model_assets_downloaded_and_verified': True, 'mandatory_hosted_CPU_CI_pass_for_exact_commit': True,
          'hardware_acceptance': False, 'local_ext4_full_CI_acceptance': None,
          'root_reported_original_retention_tool': {'tool_id': 'afeea9', 'returncode': 0, 'elapsed_s': terminal['elapsed_s']},
          'reviewer_handles_released': True, 'no_provider_or_target_action': True,
          'limits': ['No hosted command, tests, builds, profile or query was replayed; every archive member was streamed and SHA/CRC/path checked.',
                     'Original source inventory equality and commit match are provider facts; the hosted checkout itself is not locally accessible.',
                     'Hosted interpreter bytes are not in the ZIP; the first joined executable descriptor was not freshly rehashed.',
                     'The observer explicitly does not establish descendant quiescence from original child status; no numeric FD count or global process absence is invented.',
                     '88 allowlisted portable skips and 9 deferred integrations do not prove their behavior or hardware/scientific acceptance.',
                     'Local D full CI and scientific release evidence are independent; historical P/C failures remain unchanged.'],
          'elapsed_s': time.monotonic()-START}
raw = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
assert len(raw) <= 8*1048576; clock()
path = HERE / 'review.v1.json'
with path.open('xb') as stream:
    assert stream.write(raw) == len(raw); stream.flush(); os.fsync(stream.fileno())
clock()
print(json.dumps({'review': descriptor(path, raw), 'provider_conclusion': 'success', 'reviewable': True}, sort_keys=True))
