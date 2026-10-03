"""Finite postterminal FAILED local D review. Never turn reviewed failure into CI acceptance."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
CI = BASE / 'decision29-successor-ci-D-preparation-v1'
CHECKOUT = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
OUTPUT = CHECKOUT.with_name(CHECKOUT.name + '-original-output')
WRAPPER = CI / 'original-full-ci-attempt01'
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
OUT = HERE / 'original-review-attempt01'
output_owned = False
error = None
close_errors = []
facts = {}
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
    assert not os.path.lexists(WRAPPER / 'late-failure.v1.json')
    assert dispatch['source_commit'] == COMMIT and dispatch['original'] == terminal['original']
    assert terminal['original']['pid'] == terminal['original']['pgid'] == 95805 and terminal['original']['startticks'] == 50718283
    assert dispatch['controller']['pid'] == 95791
    assert terminal['close_errors'] == [] and terminal['held_descriptors_released'] is True
    assert terminal['source_before_after_equal'] is True and terminal['signals'] == [] and terminal['eof'] == ['stderr', 'stdout']
    assert len(stdout) == terminal['channel_bytes']['stdout'] and len(stderr) == terminal['channel_bytes']['stderr']
    assert len(terminal['process_scans']) == 2 and all(not s['members'] and not s['errors'] for s in terminal['process_scans'])
    assert terminal['elapsed_s'] < 5400 and dispatch['deadline_ns'] - dispatch['job_started_monotonic_ns'] == 5400*10**9
    assert dispatch['cleanup_deadline_ns'] - dispatch['deadline_ns'] == 10*10**9
    report = json.loads(preserve(OUTPUT / 'report.json', 'stock/report.json'))
    before_raw = preserve(OUTPUT / 'tracked-source.before.json', 'stock/tracked-source.before.json')
    after_raw = preserve(OUTPUT / 'tracked-source.after.json', 'stock/tracked-source.after.json')
    assert before_raw == after_raw
    tracking = json.loads(before_raw)
    assert len(tracking) == 5577 and isinstance(tracking, dict)
    assert all(set(row) == {'size_bytes', 'sha256'} for row in tracking.values())
    assert report['commit'] == COMMIT and report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == []
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
    assert len(child['discovered_ids']) == len(set(child['discovered_ids'])) == 3001
    assert selection['counts'] == {'discovered': 3001, 'portable': 2992, 'integration': 9}
    assert selection['discovered_ids'] == child['discovered_ids'] and selection['integration_executed'] is False
    assert child['tests_run'] == len(portable) == len(starts) == len(finishes) == 2992
    assert set(starts) == set(finishes) == portable
    assert len(success) == 2904 and len(skipped) == len(child['skips']) == 88
    assert child['failures'] == child['errors'] == child['expected_failures'] == child['unexpected_successes'] == child['missing_required_successes'] == []
    assert {k for k, v in finishes.items() if v['outcome'] == 'success'} == success
    assert {k for k, v in finishes.items() if v['outcome'] == 'skip'} == skipped
    assert success.isdisjoint(skipped) and success | skipped == portable
    assert all(starts[k]['monotonic_ns'] <= finishes[k]['monotonic_ns'] for k in starts)
    allowed = {r['test_id']: r for r in selection['allowed_portable_skips']}
    skip_audit, skip_mismatches = [], []
    for row in child['skips']:
        assert row['test_id'] in allowed
        if row['reason'] != allowed[row['test_id']]['reason']:
            skip_mismatches.append({'original': row, 'allowed_declaration': allowed[row['test_id']]})
        else:
            skip_audit.append(allowed[row['test_id']])
    expected_unapproved = 'test_backend_publication_output_transaction_production_v3.BackendPublicationOutputTransactionProductionV3Tests.test_canonical_wsl_venv_requires_plain_copied_python'
    assert len(skip_mismatches) == 1 and skip_mismatches[0]['original'] == {'test_id': expected_unapproved, 'reason': 'canonical WSL publication venv bind is not mounted'}
    assert child['child_failure'] == 'ValueError: unapproved portable skip identity/reason: ' + expected_unapproved
    assert 'portable_skip_audit' not in child and all(row['acceptance_claim'] is False for row in allowed.values())
    assert tracking[selection['manifest_path']]['sha256'] == selection['manifest_sha256'] and len(selection['integration_declarations']) == 9
    assert set(REQUIRED) <= success and report['built_targets'] == TARGETS
    commands = {}
    for name in ('model-assets', 'native-configure', 'native-build'):
        commands[name] = json.loads(preserve(OUTPUT / (name + '.json'), 'stock/' + name + '.json'))
        assert commands[name]['returncode'] == 0 and commands[name]['timed_out'] is False and commands[name]['cleanup_error'] is None
    acquisition = json.loads(preserve(OUTPUT / 'model-acquisition/report.json', 'stock/model-acquisition/report.json'))
    assert acquisition['status'] == 'complete' and len(acquisition['assets']) == 8 and all(r['status'] == 'reused' for r in acquisition['assets'])
    assert sum(r['size_bytes'] for r in acquisition['assets']) == 15514597
    reuse_raw = read(BASE / 'decision29-ext4-asset-cache-stock-reuse-review-v1/review.v1.json')
    assert len(reuse_raw) == 24571 and hashlib.sha256(reuse_raw).hexdigest() == '890f5a0e0df96d846ba6a39f699c339c7dbce49e9662c37bb4c681a5c7327b78'
    reuse = json.loads(reuse_raw); assert reuse['facts']['closed_stock_report'] == acquisition and reuse['error'] is None
    observer = json.loads(preserve(OUTPUT / 'external-test-observer/terminal.v1.json', 'stock/observer-terminal.v1.json'))
    assert report['observer'] == observer and observer['returncode'] == 1 and observer['successful'] is False
    assert observer['failure'] == 'original suite child did not exit zero'
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
    assert terminal['status'] == 'failed' and terminal['returncode'] == TOOL_RC == 1
    assert terminal['first_error'] == {'type': 'AssertionError', 'message': 'original full CI exit is failed; retain stock report'}
    assert report['successful'] is False and child['successful'] is False and report['hardware_acceptance'] is False
    assert report['failure'] == 'RuntimeError: original full-suite child/observer failed; see original lifecycle/trace'
    owners = [dispatch['controller'], terminal['original'], observer['owner']]
    scans = [scan(owners), scan(owners)]
    assert all(not r['errors'] and not r['matched_owned_PID_PGID_session_members'] and all(r['original_PID_paths_absent'].values()) for r in scans)
    for path in list(held): read(path)
    for path, (fd, before) in ancestors.items():
        s, named = os.fstat(fd), path.lstat()
        assert [s.st_dev, s.st_ino, s.st_mode] == [named.st_dev, named.st_ino, named.st_mode] == before
    facts = {'actual_wrapper_terminal': terminal, 'actual_wrapper_dispatch': dispatch,
             'source_tables_equal': True, 'source_table_rows': 5577, 'source_capture_current_joins': source_joins,
             'actual_counts': {'discovered': 3001, 'selected': 2992, 'success': 2904, 'skip': 88, 'failure': 0, 'error': 0, 'deferred_integration': 9},
             'all_2992_unique_original_start_terminal_joins': True, 'approved_skips': skip_audit, 'unapproved_original_skip': skip_mismatches, 'child_failure': child['child_failure'],
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
result = {'schema_version': 1, 'reviewer': '/root/architecture_review', 'source_commit': COMMIT,
          'status': 'verified' if error is None and not close_errors and fd_before == fd_after else 'failed',
          'facts': facts, 'error': error, 'close_errors': close_errors, 'fd_before': fd_before, 'fd_after': fd_after,
          'all_reader_handles_released': not close_errors, 'reader_pid': os.getpid(), 'original_tool_session': 68257,
          'root_reported_original_tool_closure': {'returncode': TOOL_RC, 'terminal_cell': TOOL_CELL, 'basis': 'Parent explicit genuine terminal notification'},
          'metadata_streamed_bytes': total, 'elapsed_s': time.monotonic()-START,
          'no_target_imports_queries_tests_model_body_reads_or_dispatch': True, 'hardware_acceptance': False,
          'original_full_CI_disposition': 'FAILED', 'mandatory_local_CI_pass': False,
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
    print(json.dumps({'status': result['status'], 'original_CI_disposition': 'FAILED', 'reader_pid': os.getpid(), 'fd_before': fd_before, 'fd_after': fd_after,
                      'review': descriptor(OUT / 'review.v1.json', raw), 'error': error}, sort_keys=True))
    if time.monotonic() >= END and result['status'] == 'verified':
        result['status'] = 'failed'
        with (OUT / 'late-failure.v1.json').open('xb') as stream:
            value = json.dumps({'status': 'failed', 'first_error': {'type': 'TimeoutError', 'message': 'after stdout120s bound'}}).encode()+b'\n'
            assert stream.write(value) == len(value); stream.flush(); os.fsync(stream.fileno())
else:
    print(json.dumps({'status': 'failed', 'output_owned': False, 'error': error, 'close_errors': close_errors}))
raise SystemExit(0 if result['status'] == 'verified' else 1)
