"""Finite postterminal original prerequisite-D review; retain success or failure without replay."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
CI = BASE / 'decision29-successor-ci-D-prerequisite-capture-preparation-v1'
CHECKOUT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
OUTPUT = CHECKOUT.with_name(CHECKOUT.name + '-prerequisite-original-output')
WRAPPER = CI / 'original-full-ci-prerequisite-attempt01'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
assert len(sys.argv) == 5, 'usage: reader ACTUAL_WRAPPER_TERMINAL_SIZE SHA256 ORIGINAL_TOOL_FINAL_RC TERMINAL_CELL'
TERMINAL_SIZE, TERMINAL_SHA, TOOL_RC, TOOL_CELL = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
assert 0 < TERMINAL_SIZE <= 4*1048576 and len(TERMINAL_SHA) == 64 and all(c in '0123456789abcdef' for c in TERMINAL_SHA)
assert TOOL_RC in (0, 1, 78, 124, 137) and 0 < len(TOOL_CELL) <= 128
START = time.monotonic()
END = START + 120
CAP = 4*1048576
TOTAL_CAP = 64*1048576
held, ancestors, pins, copies = {}, {}, [], []
total = 0
fd_before = len(list(Path('/proc/self/fd').iterdir()))
OUT = HERE / 'original-prerequisite-review-attempt01'
output_owned = False
error = None
close_errors = []
facts = {}
original_disposition = 'UNKNOWN'
original_pass = False
wrapper_late = None
REQUIRED = ['test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.' + n
            for n in ('test_native_client_regression', 'test_native_policy_topology_regression', 'test_native_reset_queue_level_regression')]
TARGETS = ['vast_native_gst_probe', 'vast_checkpoint_source', 'gstadaptivescheduler',
           'gstvastanalyticsterminal', 'gstvastanalyticsqueue', 'gstvastcheckpointprefixqueue']

def clock():
    if time.monotonic() >= END:
        raise TimeoutError('finite postterminal metadata review120s')

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def descriptor(path, raw):
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def read(path):
    global total
    clock()
    if path not in held:
        for parent in reversed(path.parents):
            if parent not in ancestors:
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                ancestors[parent] = (fd, None)
                s = os.fstat(fd)
                ancestors[parent] = (fd, [s.st_dev, s.st_ino, s.st_mode])
                assert stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(parent.lstat().st_mode)
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        held[path] = (fd, None, None)
        before = epoch(os.fstat(fd))
        held[path] = (fd, before, None)
        assert stat.S_ISREG(before[2]) and before[3] == 1 and before[4] <= CAP
        assert epoch(path.lstat()) == before
    fd, before, known = held[path]
    os.lseek(fd, 0, os.SEEK_SET)
    blocks, count = [], 0
    while block := os.read(fd, 65536):
        clock(); count += len(block); total += len(block)
        assert count <= CAP and total <= TOTAL_CAP
        blocks.append(block)
    raw = b''.join(blocks)
    assert len(raw) == before[4] and epoch(os.fstat(fd)) == epoch(path.lstat()) == before
    actual = {**descriptor(path, raw), 'epoch7': before}
    if known is not None:
        assert actual == known
    held[path] = (fd, before, actual)
    return raw

def preserve(path, relative):
    name = PurePosixPath(relative)
    assert not name.is_absolute() and '..' not in name.parts and '\\' not in relative
    raw = read(path)
    destination = OUT / 'original-copies' / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        assert stream.write(raw) == len(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(destination) == raw
    copies.append({'original': held[path][2], 'qualified_raw_copy': held[destination][2], 'raw_bytes_unchanged': True})
    return raw

def scan(owners):
    clock()
    found, errors = [], []
    pids = {r['pid'] for r in owners}
    groups = {r['pgid'] for r in owners if r.get('pgid') is not None}
    sessions = {r['session'] for r in owners if r.get('session') is not None}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(p.name) in pids or int(fields[2]) in groups or int(fields[3]) in sessions:
                ids = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
                found.append({'pid': int(p.name), 'pgid': int(fields[2]), 'session': int(fields[3]),
                              'startticks': int(fields[19]), 'uid': int(ids['Uid'].split()[0]), 'gid': int(ids['Gid'].split()[0])})
        except FileNotFoundError:
            pass
        except (OSError, ValueError, IndexError, KeyError) as exc:
            errors.append({'pid': int(p.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_monotonic_ns': time.monotonic_ns(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'original_PID_paths_absent': {str(pid): not os.path.lexists('/proc/' + str(pid)) for pid in sorted(pids)},
            'matched_owned_PID_PGID_session_members': found, 'errors': errors}

try:
    assert sys.version_info[:3] == (3, 12, 3) and os.getuid() == os.getgid() == 1000
    # The first input is the immutable final wrapper terminal supplied after root's genuine tool completion.
    raw_terminal = read(WRAPPER / 'terminal.v1.json')
    assert len(raw_terminal) == TERMINAL_SIZE and hashlib.sha256(raw_terminal).hexdigest() == TERMINAL_SHA
    terminal = json.loads(raw_terminal)
    assert terminal['source_commit'] == COMMIT
    assert not os.path.lexists(OUT)
    OUT.mkdir(mode=0o700); output_owned = True
    terminal = json.loads(preserve(WRAPPER / 'terminal.v1.json', 'wrapper/terminal.v1.json'))
    dispatch = json.loads(preserve(WRAPPER / 'dispatch.v1.json', 'wrapper/dispatch.v1.json'))
    stdout = preserve(WRAPPER / 'stdout.raw', 'wrapper/stdout.raw')
    stderr = preserve(WRAPPER / 'stderr.raw', 'wrapper/stderr.raw')
    if os.path.lexists(WRAPPER / 'late-failure.v1.json'):
        wrapper_late = json.loads(preserve(WRAPPER / 'late-failure.v1.json', 'wrapper/late-failure.v1.json'))
    assert terminal['status'] in ('success', 'failed')
    original_disposition = 'SUCCESS' if terminal['status'] == 'success' and TOOL_RC == 0 and wrapper_late is None else 'FAILED'
    facts = {'actual_wrapper_terminal': terminal, 'actual_wrapper_dispatch': dispatch,
             'wrapper_late_companion': wrapper_late, 'stock_evidence_complete': False,
             'all_qualified_original_copies': copies}
    assert dispatch['source_commit'] == COMMIT and dispatch['original'] == terminal['original']
    assert terminal['original']['pid'] == terminal['original']['pgid'] > 0
    assert terminal['original']['startticks'] > 0 and dispatch['controller']['pid'] > 0
    assert terminal['original']['uid'] == terminal['original']['gid'] == 1000
    assert dispatch['controller']['uid'] == dispatch['controller']['gid'] == 1000
    assert terminal['original']['boot_id'] == dispatch['controller']['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert terminal['close_errors'] == [] and terminal['held_descriptors_released'] is True
    assert terminal['source_before_after_equal'] is True and terminal['signals'] == [] and terminal['eof'] == ['stderr', 'stdout']
    assert len(stdout) == terminal['channel_bytes']['stdout'] and len(stderr) == terminal['channel_bytes']['stderr']
    assert len(terminal['process_scans']) == 2 and all(not s['members'] and not s['errors'] for s in terminal['process_scans'])
    assert terminal['elapsed_s'] < 5410 and dispatch['deadline_ns'] - dispatch['job_started_monotonic_ns'] == 5400*10**9
    assert dispatch['cleanup_deadline_ns'] - dispatch['deadline_ns'] == 10*10**9
    report = json.loads(preserve(OUTPUT / 'report.json', 'stock/report.json'))
    before_raw = preserve(OUTPUT / 'tracked-source.before.json', 'stock/tracked-source.before.json')
    after_raw = preserve(OUTPUT / 'tracked-source.after.json', 'stock/tracked-source.after.json')
    tracking = json.loads(before_raw)
    after_tracking = json.loads(after_raw)
    actual_changed = sorted(k for k in set(tracking) | set(after_tracking) if tracking.get(k) != after_tracking.get(k))
    prior_table_path = BASE / 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/original-copies/stock/tracked-source.before.json'
    prior_table_raw = read(prior_table_path)
    assert len(prior_table_raw) == 1270968 and hashlib.sha256(prior_table_raw).hexdigest() == '105568f276b37f57aad59b81efaa6524c816b4e595679da56807a1087daba0ea'
    assert json.loads(prior_table_raw) == tracking
    source_equal = before_raw == after_raw
    assert len(tracking) == 5577 and isinstance(tracking, dict)
    assert all(set(row) == {'size_bytes', 'sha256'} for row in tracking.values())
    assert report['commit'] == COMMIT and report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == actual_changed
    assert report['job_started_monotonic_ns'] == dispatch['job_started_monotonic_ns']
    assert report['absolute_deadline_ns'] == dispatch['deadline_ns']
    source_joins = []
    for original_pin in dispatch['source_pins']:
        p = Path(original_pin['path'])
        raw = read(p)
        assert len(raw) == original_pin['size_bytes'] and hashlib.sha256(raw).hexdigest() == original_pin['sha256']
        assert held[p][2]['epoch7'] == original_pin['epoch7']
        if p.is_relative_to(CHECKOUT):
            assert tracking[p.relative_to(CHECKOUT).as_posix()] == {k: original_pin[k] for k in ('size_bytes', 'sha256')}
        source_joins.append({'original_capture_pin': original_pin, 'current_held_pin': held[p][2]})
    child = json.loads(preserve(OUTPUT / 'unittest-child.report.json', 'stock/unittest-child.report.json'))
    assert report['unittest'] == child
    log_raw = preserve(OUTPUT / 'unittest.original.log', 'stock/unittest.original.log')
    starts, finishes = {}, {}
    for line in log_raw.splitlines():
        if not line.startswith(b'{'): continue
        event = json.loads(line)
        if event.get('event') == 'test_started':
            assert event['test_id'] not in starts; starts[event['test_id']] = event
        elif event.get('event') == 'test_terminal':
            assert event['test_id'] not in finishes; finishes[event['test_id']] = event
    selection = child['selection']; portable = set(selection['portable_ids'])
    success = set(child['successful_test_ids']); skipped = {r['test_id'] for r in child['skips']}
    prior_child_path = BASE / 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/original-copies/stock/unittest-child.report.json'
    prior_child_raw = read(prior_child_path)
    assert len(prior_child_raw) == 1734578 and hashlib.sha256(prior_child_raw).hexdigest() == '93c23027abbca094608fb480c5f230cc99ba3d6a832aefa8abf3a8d3e2fe48c9'
    prior_child = json.loads(prior_child_raw)
    # Historical D is an exact discovery/declaration inventory, never current execution authority.
    assert child['discovered_ids'] == prior_child['discovered_ids']
    assert len(child['discovered_ids']) == len(set(child['discovered_ids']))
    for key in ('portable_ids', 'integration_declarations', 'allowed_portable_skips', 'manifest_path', 'manifest_sha256'):
        assert selection[key] == prior_child['selection'][key]
    assert selection['counts'] == {'discovered': len(child['discovered_ids']), 'portable': len(portable),
                                   'integration': len(selection['integration_declarations'])}
    assert selection['discovered_ids'] == child['discovered_ids'] and selection['integration_executed'] is False
    assert child['tests_run'] == len(portable) == len(starts) == len(finishes)
    assert set(starts) == set(finishes) == portable
    assert len(success) == len(child['successful_test_ids']) and len(skipped) == len(child['skips'])
    outcome_sets = {name: {k for k, v in finishes.items() if v['outcome'] == name}
                    for name in ('success', 'skip', 'failure', 'error', 'expected_failure', 'unexpected_success')}
    assert set().union(*outcome_sets.values()) == portable
    assert outcome_sets['success'] == success and outcome_sets['skip'] == skipped
    assert outcome_sets['expected_failure'] == set(child['expected_failures'])
    assert outcome_sets['unexpected_success'] == set(child['unexpected_successes'])
    failure_parents, error_parents = set(), set()
    original_trace_id_joins = []
    for category, target in (('failures', failure_parents), ('errors', error_parents)):
        for row in child[category]:
            exact = [k for k in portable if row['test_id'] == k or row['test_id'].startswith(k + ' (')]
            assert len(exact) == 1, 'Original failure/subtest ID cannot uniquely join its discovered parent'
            target.add(exact[0])
            original_trace_id_joins.append({'category': category, 'original_test_id': row['test_id'], 'parent_test_id': exact[0]})
    assert failure_parents <= outcome_sets['failure'] | outcome_sets['error']
    assert outcome_sets['failure'] <= failure_parents
    assert error_parents == outcome_sets['error']
    assert all(starts[k]['monotonic_ns'] <= finishes[k]['monotonic_ns'] for k in starts)
    allowed = {r['test_id']: r for r in selection['allowed_portable_skips']}
    assert len(allowed) == len(selection['allowed_portable_skips'])
    skip_audit, skip_mismatches = [], []
    for row in child['skips']:
        if row['test_id'] not in allowed or row['reason'] != allowed[row['test_id']]['reason']:
            skip_mismatches.append({'original': row, 'allowed_declaration': allowed.get(row['test_id'])})
        else:
            skip_audit.append(allowed[row['test_id']])
    if 'portable_skip_audit' in child:
        assert child['portable_skip_audit'] == skip_audit and not skip_mismatches
    else:
        assert child['successful'] is False and child.get('child_failure')
    assert all(row['acceptance_claim'] is False for row in allowed.values())
    assert tracking[selection['manifest_path']]['sha256'] == selection['manifest_sha256']
    assert len(selection['integration_declarations']) == 9
    assert set(REQUIRED) - success <= set(child['missing_required_successes'])
    assert report['built_targets'] == TARGETS
    actual_native_successes = sorted(set(REQUIRED) & success)
    commands = {}
    for name in ('model-assets', 'native-configure', 'native-build'):
        commands[name] = json.loads(preserve(OUTPUT / (name + '.json'), 'stock/' + name + '.json'))
        assert commands[name]['returncode'] == 0 and commands[name]['timed_out'] is False and commands[name]['cleanup_error'] is None
        for channel in ('stdout', 'stderr'):
            preserve(OUTPUT / (name + '.' + channel), 'stock/' + name + '.' + channel)
    factories = report['gstreamer_factories']
    assert set(factories) == {'appsrc', 'queue', 'videoconvert'}
    for factory, row in factories.items():
        observed = json.loads(preserve(OUTPUT / ('factory-' + factory + '.json'), 'stock/factory-' + factory + '.json'))
        assert observed == row['command'] and observed['returncode'] == 0 and observed['timed_out'] is False and observed['cleanup_error'] is None
        factory_raw = preserve(OUTPUT / ('factory-' + factory + '.stdout'), 'stock/factory-' + factory + '.stdout')
        preserve(OUTPUT / ('factory-' + factory + '.stderr'), 'stock/factory-' + factory + '.stderr')
        assert len(factory_raw) == row['stdout_size_bytes'] and hashlib.sha256(factory_raw).hexdigest() == row['stdout_sha256']
        assert len(factory_raw) <= 65536 and b'Factory Details:' in factory_raw and b'Plugin Details:' in factory_raw
    packages = json.loads(preserve(OUTPUT / 'gstreamer-packages.json', 'stock/gstreamer-packages.json'))
    assert packages == report['gstreamer_packages'] and packages['returncode'] == 0
    for channel in ('stdout', 'stderr'):
        preserve(OUTPUT / ('gstreamer-packages.' + channel), 'stock/gstreamer-packages.' + channel)
    acquisition = json.loads(preserve(OUTPUT / 'model-acquisition/report.json', 'stock/model-acquisition/report.json'))
    assert acquisition['status'] == 'complete' and len(acquisition['assets']) == 8 and all(r['status'] == 'reused' for r in acquisition['assets'])
    assert sum(r['size_bytes'] for r in acquisition['assets']) == 15514597
    reuse_raw = read(BASE / 'decision29-ext4-asset-cache-stock-reuse-review-v1/review.v1.json')
    assert len(reuse_raw) == 24571 and hashlib.sha256(reuse_raw).hexdigest() == '890f5a0e0df96d846ba6a39f699c339c7dbce49e9662c37bb4c681a5c7327b78'
    reuse = json.loads(reuse_raw); assert reuse['facts']['closed_stock_report']['assets'] == acquisition['assets'] and reuse['error'] is None
    observer = json.loads(preserve(OUTPUT / 'external-test-observer/terminal.v1.json', 'stock/observer-terminal.v1.json'))
    assert report['observer'] == observer
    observer_launch = json.loads(preserve(OUTPUT / 'external-test-observer/launch.v1.json', 'stock/observer-launch.v1.json'))
    assert observer_launch['owner'] == observer['owner'] and observer_launch['argv'] == observer['argv']
    observer_trace = preserve(OUTPUT / 'external-test-observer/trace.original.log', 'stock/observer-trace.original.log')
    observer_responses = preserve(OUTPUT / 'external-test-observer/responses.original.jsonl', 'stock/observer-responses.original.jsonl')
    preserve(OUTPUT / 'external-test-observer/events.original.jsonl', 'stock/observer-events.original.jsonl')
    assert len(observer_trace) == observer['trace_bytes'] and len(observer_responses) == observer['response_channel_bytes']
    observer_late = None
    if os.path.lexists(OUTPUT / 'external-test-observer/late-finalization.failure.json'):
        observer_late = json.loads(preserve(OUTPUT / 'external-test-observer/late-finalization.failure.json', 'stock/observer-late-finalization.failure.json'))
    assert observer['successful'] == (observer['returncode'] == 0 and observer['failure'] is None)
    assert observer['owner']['pid'] > 0 and observer['owner']['startticks'] > 0
    assert observer['owner']['boot_id'] == terminal['original']['boot_id']
    assert all(observer['pipe_eof'].values()) and observer['forced_sigterm'] is False and observer['forced_sigkill'] is False
    assert observer['pidfd_failure'] is None and observer['requests_stopped_before_disposition_restore'] is True
    assert observer['owner']['uid'] == observer['owner']['gid'] == 1000
    profile = report['namespace_profile']; diagnostic = report['namespace_diagnostic']
    assert diagnostic['capture_completed'] is True
    if profile['attempted'] is False:
        assert profile['status'] == 'not_required' and diagnostic['namespace_succeeded'] is True
        assert child['profile_observation']['expected_profile'] is None
    else:
        assert profile['status'] == 'completed' and profile['held_fds_released'] is True
        assert profile['load_verified'] is True and profile['unload_verified'] is True
        assert child['profile_observation']['actual_label']['value'] == profile['name'] + ' (unconfined)'
    assert report['hardware_acceptance'] is False
    original_pass = (terminal['status'] == 'success' and terminal['returncode'] == TOOL_RC == 0
                     and terminal['first_error'] is None and wrapper_late is None
                     and report['successful'] is True and child['successful'] is True
                     and observer['successful'] is True and source_equal and observer_late is None
                     and terminal['elapsed_s'] < 5400)
    if original_pass:
        assert not child['failures'] and not child['errors'] and not child['unexpected_successes']
        assert not child['missing_required_successes'] and not skip_mismatches
        assert not child.get('child_failure') and not child.get('observer_failure')
        assert set(REQUIRED) <= success and report.get('failure') is None
        assert report.get('deadline_failure') is None and report.get('source_integrity_failure') is None
    else:
        assert TOOL_RC != 0 or terminal['status'] == 'failed' or wrapper_late is not None or report['successful'] is False
    original_disposition = 'SUCCESS' if original_pass else 'FAILED'
    owners = [dispatch['controller'], terminal['original'], observer['owner']]
    scans = [scan(owners), scan(owners)]
    assert all(not r['errors'] and not r['matched_owned_PID_PGID_session_members'] and all(r['original_PID_paths_absent'].values()) for r in scans)
    for path in list(held): read(path)
    for path, (fd, before) in ancestors.items():
        s, named = os.fstat(fd), path.lstat()
        assert [s.st_dev, s.st_ino, s.st_mode] == [named.st_dev, named.st_ino, named.st_mode] == before
    facts = {'actual_wrapper_terminal': terminal, 'actual_wrapper_dispatch': dispatch,
             'source_tables_equal': source_equal, 'source_table_rows': len(tracking), 'source_capture_current_joins': source_joins,
             'actual_changed_source_paths': actual_changed,
             'actual_counts': {'discovered': len(child['discovered_ids']), 'selected': len(portable), 'success': len(success),
                               'skip': len(child['skips']), 'failure': len(child['failures']), 'error': len(child['errors']),
                               'expected_failure': len(child['expected_failures']), 'unexpected_success': len(child['unexpected_successes']),
                               'deferred_integration': len(selection['integration_declarations'])},
             'all_selected_unique_original_start_terminal_joins': True, 'approved_skips': skip_audit,
             'unapproved_original_skip': skip_mismatches, 'child_failure': child.get('child_failure'),
             'original_trace_id_joins': original_trace_id_joins, 'terminal_outcome_counts': {k: len(v) for k, v in outcome_sets.items()},
             'stock_evidence_complete': True, 'actual_native_success_ids': actual_native_successes,
             'loaded_factory_originals': factories, 'wrapper_late_companion': wrapper_late,
             'observer_launch': observer_launch, 'observer_late_companion': observer_late,
             'nine_deferred_integrations': selection['integration_declarations'], 'required_native_success_ids': REQUIRED,
             'six_built_targets': TARGETS, 'original_commands': commands, 'actual_observer': observer,
             'actual_namespace_diagnostic': diagnostic, 'actual_namespace_profile': profile,
             'model_copy_and_reuse_review': held[BASE / 'decision29-ext4-asset-cache-stock-reuse-review-v1/review.v1.json'][2],
             'fresh_owned_process_scans': scans, 'all_qualified_original_copies': copies}
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
finally:
    for fd, _, _ in reversed(list(held.values())):
        try: os.close(fd)
        except BaseException as exc: close_errors.append({'type': type(exc).__name__, 'message': str(exc)[:512]})
    for fd, _ in reversed(list(ancestors.values())):
        try: os.close(fd)
        except BaseException as exc: close_errors.append({'type': type(exc).__name__, 'message': str(exc)[:512]})
fd_after = len(list(Path('/proc/self/fd').iterdir()))
result = {'schema_version': 1, 'reviewer': '/root/adversarial_review', 'source_commit': COMMIT,
          'status': 'verified' if error is None and not close_errors and fd_before == fd_after else 'failed',
          'facts': facts, 'error': error, 'close_errors': close_errors, 'fd_before': fd_before, 'fd_after': fd_after,
          'all_reader_handles_released': not close_errors, 'reader_pid': os.getpid(), 'original_tool_session': 'not observed by reader; terminal cell supplied by parent',
          'root_reported_original_tool_closure': {'returncode': TOOL_RC, 'terminal_cell': TOOL_CELL, 'basis': 'Parent explicit genuine terminal notification'},
          'metadata_streamed_bytes': total, 'elapsed_s': time.monotonic()-START,
          'no_target_imports_queries_tests_model_body_reads_or_dispatch': True, 'hardware_acceptance': False,
          'original_full_CI_disposition': original_disposition, 'mandatory_local_CI_pass': original_pass and error is None and not close_errors and fd_before == fd_after,
          'metadata_review_status_is_not_CI_acceptance': True,
          'limits': ['Only after authentic parent completion are final originals read and copied with full hashes and held seven-epoch/name checks.',
                     'Original wrapper reports release and two scans, but no numeric FD count; only this reader has an observed FD before/after count.',
                     'Fresh scans cover the recorded owned PIDs/groups/sessions. They do not assert global process quiescence or prove unrelated descendants.',
                     'Portable skips and deferred integrations do not certify those scenarios or scientific/hardware acceptance.',
                     'Failure of this finite review remains failure and never changes or reruns the original CI.']}
if output_owned:
    raw = json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode()+b'\n'
    assert len(raw) <= CAP
    with (OUT / 'review.v1.json').open('xb') as stream:
        assert stream.write(raw) == len(raw); stream.flush(); os.fsync(stream.fileno())
    if time.monotonic() >= END:
        result['status'] = 'failed'
        with (OUT / 'late-failure.v1.json').open('xb') as stream:
            value = json.dumps({'status': 'failed', 'first_error': error or {'type': 'TimeoutError', 'message': 'post-report/FD-close120s bound'}}).encode()+b'\n'
            assert stream.write(value) == len(value); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({'status': result['status'], 'original_CI_disposition': original_disposition, 'reader_pid': os.getpid(), 'fd_before': fd_before, 'fd_after': fd_after,
                      'review': descriptor(OUT / 'review.v1.json', raw), 'error': error}, sort_keys=True))
    if time.monotonic() >= END and result['status'] == 'verified':
        result['status'] = 'failed'
        with (OUT / 'late-failure.v1.json').open('xb') as stream:
            value = json.dumps({'status': 'failed', 'first_error': {'type': 'TimeoutError', 'message': 'after stdout120s bound'}}).encode()+b'\n'
            assert stream.write(value) == len(value); stream.flush(); os.fsync(stream.fileno())
else:
    print(json.dumps({'status': 'failed', 'output_owned': False, 'error': error, 'close_errors': close_errors}))
raise SystemExit(0 if result['status'] == 'verified' else 1)
