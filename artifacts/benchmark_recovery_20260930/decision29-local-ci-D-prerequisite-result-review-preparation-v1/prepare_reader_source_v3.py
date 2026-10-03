"""Author only a future metadata reader; do not import or execute it or any target."""
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
START = time.monotonic()
author_inputs = []

def pin(path):
    assert time.monotonic() - START < 120
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    try:
        s = os.fstat(fd)
        named = path.lstat()
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        before = [getattr(s, k) for k in fields]
        named_before = [getattr(named, k) for k in fields]
        assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 4 * 1048576
        assert before[:6] == named_before[:6]
        raw = bytearray()
        while block := os.read(fd, 65536):
            assert time.monotonic() - START < 120 and len(raw) + len(block) <= s.st_size
            raw.extend(block)
        assert len(raw) == s.st_size
        assert [getattr(os.fstat(fd), k) for k in fields] == before
        assert [getattr(path.lstat(), k) for k in fields] == named_before
        value = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                 'author_fd_epoch7': before, 'author_named_epoch7': named_before}
        author_inputs.append(value)
        return bytes(raw), value
    finally:
        os.close(fd)

def save(name, raw):
    assert time.monotonic() - START < 120
    if name == 'accepted-failed-D-reader.before.raw' and (HERE / name).exists():
        existing, value = pin(HERE / name)
        assert existing == raw
        return value
    with (HERE / name).open('xb') as stream:
        assert stream.write(raw) == len(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {'path': str(HERE / name), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

old_path = BASE / 'decision29-local-ci-D-original-review-preparation-v1/review_actual_local_D_v2.py'
raw, old_pin = pin(old_path)
assert old_pin['size_bytes'] == 19769 and old_pin['sha256'] == 'c73b28f1c56c1b04f1ca49ecc8eaef7e9894582c36bcb350c67896e9d309767b'
text = raw.decode()
changes = []

def replace(before, after, purpose):
    global text
    assert text.count(before) == 1, (purpose, text.count(before))
    text = text.replace(before, after)
    changes.append({'before': before, 'after': after, 'purpose': purpose})

replace('"""Finite postterminal FAILED local D review. Never turn reviewed failure into CI acceptance."""',
        '"""Finite postterminal original prerequisite-D review; retain success or failure without replay."""', 'Scope label')
replace("CI = BASE / 'decision29-successor-ci-D-preparation-v1'", "CI = BASE / 'decision29-successor-ci-D-prerequisite-capture-preparation-v1'", 'Fresh capture preparation')
replace("OUTPUT = CHECKOUT.with_name(CHECKOUT.name + '-original-output')", "OUTPUT = CHECKOUT.with_name(CHECKOUT.name + '-prerequisite-original-output')", 'Fresh stock output')
replace("WRAPPER = CI / 'original-full-ci-attempt01'", "WRAPPER = CI / 'original-full-ci-prerequisite-attempt01'", 'Fresh closed wrapper')
replace("OUT = HERE / 'original-review-attempt01'", "OUT = HERE / 'original-prerequisite-review-attempt01'", 'Fresh exclusive reader output')
replace('facts = {}', "facts = {}\noriginal_disposition = 'UNKNOWN'\noriginal_pass = False\nwrapper_late = None", 'Unknown future outcome until observed')
replace("    assert not os.path.lexists(WRAPPER / 'late-failure.v1.json')", """    if os.path.lexists(WRAPPER / 'late-failure.v1.json'):
        wrapper_late = json.loads(preserve(WRAPPER / 'late-failure.v1.json', 'wrapper/late-failure.v1.json'))
    assert terminal['status'] in ('success', 'failed')
    original_disposition = 'SUCCESS' if terminal['status'] == 'success' and TOOL_RC == 0 and wrapper_late is None else 'FAILED'
    facts = {'actual_wrapper_terminal': terminal, 'actual_wrapper_dispatch': dispatch,
             'wrapper_late_companion': wrapper_late, 'stock_evidence_complete': False,
             'all_qualified_original_copies': copies}""", 'Preserve late-failed original and partial wrapper evidence')
replace("    assert terminal['original']['pid'] == terminal['original']['pgid'] == 95805 and terminal['original']['startticks'] == 50718283\n    assert dispatch['controller']['pid'] == 95791", """    assert terminal['original']['pid'] == terminal['original']['pgid'] > 0
    assert terminal['original']['startticks'] > 0 and dispatch['controller']['pid'] > 0
    assert terminal['original']['uid'] == terminal['original']['gid'] == 1000
    assert dispatch['controller']['uid'] == dispatch['controller']['gid'] == 1000
    assert terminal['original']['boot_id'] == dispatch['controller']['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()""", 'Derive genuine current owner identities, never reuse old PIDs')
replace("    assert terminal['elapsed_s'] < 5400 and dispatch['deadline_ns'] - dispatch['job_started_monotonic_ns'] == 5400*10**9", "    assert terminal['elapsed_s'] < 5410 and dispatch['deadline_ns'] - dispatch['job_started_monotonic_ns'] == 5400*10**9", 'Metadata may retain an original deadline failure; original success still requires5400')
replace("    assert before_raw == after_raw\n    tracking = json.loads(before_raw)", """    tracking = json.loads(before_raw)
    after_tracking = json.loads(after_raw)
    actual_changed = sorted(k for k in set(tracking) | set(after_tracking) if tracking.get(k) != after_tracking.get(k))
    prior_table_path = BASE / 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/original-copies/stock/tracked-source.before.json'
    prior_table_raw = read(prior_table_path)
    assert json.loads(prior_table_raw) == tracking
    source_equal = before_raw == after_raw""", 'Retain actual source drift on failure and join original committed D table')
replace("    assert report['commit'] == COMMIT and report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == []", "    assert report['commit'] == COMMIT and report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == actual_changed", 'Verify actual source-change report rather than force failure or success')
start_block = "    assert len(child['discovered_ids']) == len(set(child['discovered_ids'])) == 3001"
end_block = "    assert tracking[selection['manifest_path']]['sha256'] == selection['manifest_sha256'] and len(selection['integration_declarations']) == 9"
begin, end = text.index(start_block), text.index(end_block) + len(end_block)
replace(text[begin:end], """    prior_child_path = BASE / 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/original-copies/stock/unittest-child.report.json'
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
    assert set(REQUIRED) - success <= set(child['missing_required_successes'])""", 'Actual dynamic outcomes and exact unchanged inventory; no forced88 skips or old failure')
replace("    assert set(REQUIRED) <= success and report['built_targets'] == TARGETS", "    assert report['built_targets'] == TARGETS\n    actual_native_successes = sorted(set(REQUIRED) & success)", 'Observe actual native results; require all only for original success')
replace("        assert commands[name]['returncode'] == 0 and commands[name]['timed_out'] is False and commands[name]['cleanup_error'] is None", """        assert commands[name]['returncode'] == 0 and commands[name]['timed_out'] is False and commands[name]['cleanup_error'] is None
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
        preserve(OUTPUT / ('gstreamer-packages.' + channel), 'stock/gstreamer-packages.' + channel)""", 'Join original build/tool raw channels and loaded native prerequisite facts')
replace("    reuse = json.loads(reuse_raw); assert reuse['facts']['closed_stock_report'] == acquisition and reuse['error'] is None", "    reuse = json.loads(reuse_raw); assert reuse['facts']['closed_stock_report']['assets'] == acquisition['assets'] and reuse['error'] is None", 'Join exact8 static asset descriptors without rebinding old acquisition owner/timing')
replace("    assert report['observer'] == observer and observer['returncode'] == 1 and observer['successful'] is False\n    assert observer['failure'] == 'original suite child did not exit zero'", """    assert report['observer'] == observer
    assert observer['successful'] == (observer['returncode'] == 0 and observer['failure'] is None)
    assert observer['owner']['pid'] > 0 and observer['owner']['startticks'] > 0
    assert observer['owner']['boot_id'] == terminal['original']['boot_id']""", 'Observe genuine current suite-child outcome and owner')
start_block = "    assert terminal['status'] == 'failed' and terminal['returncode'] == TOOL_RC == 1"
end_block = "    assert report['failure'] == 'RuntimeError: original full-suite child/observer failed; see original lifecycle/trace'"
begin, end = text.index(start_block), text.index(end_block) + len(end_block)
replace(text[begin:end], """    assert report['hardware_acceptance'] is False
    original_pass = (terminal['status'] == 'success' and terminal['returncode'] == TOOL_RC == 0
                     and terminal['first_error'] is None and wrapper_late is None
                     and report['successful'] is True and child['successful'] is True
                     and observer['successful'] is True and source_equal
                     and terminal['elapsed_s'] < 5400)
    if original_pass:
        assert not child['failures'] and not child['errors'] and not child['unexpected_successes']
        assert not child['missing_required_successes'] and not skip_mismatches
        assert not child.get('child_failure') and not child.get('observer_failure')
        assert set(REQUIRED) <= success and report.get('failure') is None
        assert report.get('deadline_failure') is None and report.get('source_integrity_failure') is None
    else:
        assert TOOL_RC != 0 or terminal['status'] == 'failed' or wrapper_late is not None or report['successful'] is False
    original_disposition = 'SUCCESS' if original_pass else 'FAILED'""", 'Strict success branch and separate authentic failure disposition')
replace("             'source_tables_equal': True, 'source_table_rows': 5577, 'source_capture_current_joins': source_joins,\n             'actual_counts': {'discovered': 3001, 'selected': 2992, 'success': 2904, 'skip': 88, 'failure': 0, 'error': 0, 'deferred_integration': 9},\n             'all_2992_unique_original_start_terminal_joins': True, 'approved_skips': skip_audit, 'unapproved_original_skip': skip_mismatches, 'child_failure': child['child_failure'],", """             'source_tables_equal': source_equal, 'source_table_rows': len(tracking), 'source_capture_current_joins': source_joins,
             'actual_changed_source_paths': actual_changed,
             'actual_counts': {'discovered': len(child['discovered_ids']), 'selected': len(portable), 'success': len(success),
                               'skip': len(child['skips']), 'failure': len(child['failures']), 'error': len(child['errors']),
                               'expected_failure': len(child['expected_failures']), 'unexpected_success': len(child['unexpected_successes']),
                               'deferred_integration': len(selection['integration_declarations'])},
             'all_selected_unique_original_start_terminal_joins': True, 'approved_skips': skip_audit,
             'unapproved_original_skip': skip_mismatches, 'child_failure': child.get('child_failure'),
             'original_trace_id_joins': original_trace_id_joins, 'terminal_outcome_counts': {k: len(v) for k, v in outcome_sets.items()},
             'stock_evidence_complete': True, 'actual_native_success_ids': actual_native_successes,
             'loaded_factory_originals': factories, 'wrapper_late_companion': wrapper_late,""", 'Export actual counts, failures, native and raw facts')
replace("'reviewer': '/root/architecture_review'", "'reviewer': '/root/adversarial_review'", 'Current reader author attribution')
replace("'all_reader_handles_released': not close_errors, 'reader_pid': os.getpid(), 'original_tool_session': 68257,", "'all_reader_handles_released': not close_errors, 'reader_pid': os.getpid(), 'original_tool_session': 'not observed by reader; terminal cell supplied by parent',", 'No stale original session')
replace("'original_full_CI_disposition': 'FAILED', 'mandatory_local_CI_pass': False,", "'original_full_CI_disposition': original_disposition, 'mandatory_local_CI_pass': original_pass and error is None and not close_errors and fd_before == fd_after,", 'Actual CI result remains distinct from metadata-reader status')
replace("'original_CI_disposition': 'FAILED'", "'original_CI_disposition': original_disposition", 'Dynamic printed disposition')

replace("    assert json.loads(prior_table_raw) == tracking", "    assert len(prior_table_raw) == 1270968 and hashlib.sha256(prior_table_raw).hexdigest() == '105568f276b37f57aad59b81efaa6524c816b4e595679da56807a1087daba0ea'\n    assert json.loads(prior_table_raw) == tracking", 'Hard-pin the historical raw-D inventory without execution-authority rebinding')
replace("    assert report['observer'] == observer", """    assert report['observer'] == observer
    observer_launch = json.loads(preserve(OUTPUT / 'external-test-observer/launch.v1.json', 'stock/observer-launch.v1.json'))
    assert observer_launch['owner'] == observer['owner'] and observer_launch['argv'] == observer['argv']
    observer_trace = preserve(OUTPUT / 'external-test-observer/trace.original.log', 'stock/observer-trace.original.log')
    observer_responses = preserve(OUTPUT / 'external-test-observer/responses.original.jsonl', 'stock/observer-responses.original.jsonl')
    preserve(OUTPUT / 'external-test-observer/events.original.jsonl', 'stock/observer-events.original.jsonl')
    assert len(observer_trace) == observer['trace_bytes'] and len(observer_responses) == observer['response_channel_bytes']
    observer_late = None
    if os.path.lexists(OUTPUT / 'external-test-observer/late-finalization.failure.json'):
        observer_late = json.loads(preserve(OUTPUT / 'external-test-observer/late-finalization.failure.json', 'stock/observer-late-finalization.failure.json'))""", 'Retain original observer raw trace/response/event channels and authenticated launch, with no one-to-one or descendant claims')
replace("                     and observer['successful'] is True and source_equal", "                     and observer['successful'] is True and source_equal and observer_late is None", 'Observer late failure cannot grant original CI pass')
replace("             'loaded_factory_originals': factories, 'wrapper_late_companion': wrapper_late,", "             'loaded_factory_originals': factories, 'wrapper_late_companion': wrapper_late,\n             'observer_launch': observer_launch, 'observer_late_companion': observer_late,", 'Retain observer launch and late facts in report')

replace("    if 'portable_skip_audit' in child:", "    skip_audit.sort(key=lambda row: row['test_id'])\n    if 'portable_skip_audit' in child:", 'Match actual unchanged selector sorted audit contract; never assume unittest traversal order')

new_raw = text.encode()
assert len(new_raw) < 64 * 1024
old_functions = [ast.dump(n, include_attributes=False) for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
new_functions = [ast.dump(n, include_attributes=False) for n in ast.parse(new_raw).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
assert len(old_functions) == 6 and old_functions == new_functions
inverse = text
for change in reversed(changes):
    assert inverse.count(change['after']) == 1, change['purpose']
    inverse = inverse.replace(change['after'], change['before'])
assert inverse.encode() == raw
before = save('accepted-failed-D-reader.before.raw', raw)
reader = save('review_actual_prerequisite_local_D_v3.py', new_raw)
delta = save('complete-source.delta.v3.patch', ''.join(difflib.unified_diff(raw.decode().splitlines(True), text.splitlines(True),
             fromfile='accepted-failed-D/review_actual_local_D_v2.py', tofile='prepared-prerequisite-D/review_actual_prerequisite_local_D_v3.py')).encode())
references = {}
for key, rel in {
    'original_failed_D_metadata_review': 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/review.v1.json',
    'original_failed_D_child_discovery_inventory': 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/original-copies/stock/unittest-child.report.json',
    'original_failed_D_tracked_raw_table': 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/original-copies/stock/tracked-source.before.json',
    'reviewed_fresh_capture_preparation': 'decision29-successor-ci-D-prerequisite-capture-preparation-v1/preparation.v2.json',
    'actual_prerequisite_and_dispatch_grant': 'decision29-successor-ci-D-prerequisite-capture-preparation-v1/root-actual-prerequisite-and-dispatch-grant.v1.json',
    'actual_bind_execution': 'decision29-runtime-bind-prerequisite-capture-preparation-v1/original-bind-attempt01/execution.v1.json',
    'actual_bind_physical_and_owner_closure': 'decision29-runtime-bind-prerequisite-capture-preparation-v1/original-bind-attempt01/root-original-closure.v1.json',
    'actual_focused_runtime_test': 'decision29-runtime-bind-prerequisite-capture-preparation-v1/original-focused-test-attempt01/unit-result.v1.json',
    'actual_fresh95_audit': 'decision29-current95-post-runtime-bind-audit-preparation-v1/original-post-runtime-bind-audit-attempt01/review.v1.json',
    'actual_runtime_bind_gates_independent_review': 'decision29-runtime-bind-gates-independent-review-v1/review.v3.json',
}.items():
    _, references[key] = pin(BASE / rel)
preparation = {
    'schema_version': 1, 'status': 'prepared_unexecuted_while_original_CI_is_active', 'author': '/root/adversarial_review',
    'source_commit': '3c025b29b3c1d5275c2ec693410e4b83700583de',
    'reader': reader, 'accepted_failed_D_reader': old_pin, 'preserved_original': before, 'complete_source_diff': delta,
    'source_change_scope': 'Declared path retarget plus explicit top-level outcome/owner/report generalization; not a literal-only entire-source adaptation.',
    'ordered_reversible_changes': changes, 'all_six_primitive_function_ASTs_unchanged': True,
    'function_names': ['clock', 'epoch', 'descriptor', 'read', 'preserve', 'scan'],
    'complete_declared_inverse_reconstructs_accepted_bytes': True,
    'references': references, 'future_wrapper_terminal': None, 'future_original_tool_returncode': None,
    'future_original_terminal_cell': None, 'future_actual_reader_outcome': None,
    'runtime_args': ['ACTUAL_WRAPPER_TERMINAL_SIZE', 'ACTUAL_WRAPPER_TERMINAL_SHA256', 'ACTUAL_ORIGINAL_TOOL_FINAL_RC', 'ACTUAL_TERMINAL_CELL'],
    'outer_envelope_required': 'Pinned CPython3.12.3 -I -B; /usr/bin/timeout --signal=TERM --kill-after=10s 120s; actual outer original status/EOF/reap/FD/process closure independently retained.',
    'limits': {'reader_work_s': 120, 'outer_cleanup_s': 10, 'each_leaf_bytes': 4194304, 'aggregate_streamed_metadata_bytes': 67108864},
    'fresh_stock_root': '/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D-prerequisite-original-output',
    'closed_capture_namespace': 'decision29-successor-ci-D-prerequisite-capture-preparation-v1/original-full-ci-prerequisite-attempt01',
    'fresh_reader_output': 'original-prerequisite-review-attempt01',
    'current_CI_started_parent_notification_only': {'root_tool_cell': 'e7322f', 'session': 90022},
    'source_only_inspection': 'No active CI output was read. Only the frozen accepted reader, clean-D runner source and closed prerequisite/original controls were inspected.',
    'source_schema_basis': {'path': '/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D/scripts/run_ci_checks.py',
                            'size_bytes': 29477, 'sha256': 'ce375eca51164a76ab6a88cf02b92804077f08c6b8401d68b48e293020c27a2c',
                            'reviewed_lines': [[95, 128], [225, 281], [340, 391], [394, 420], [465, 577]]},
    'count_and_history_rules': [
        'Original failed D stays failed. Its exact full discovery/declaration and raw source tables are historical static inventories only.',
        'Future successes, failures, errors, expected failures, unexpected successes and skips are derived from original starts/terminals/report. No fixed old88 observed skip count.',
        '88 allowed skip declarations remain unchanged and all source-attested reasons audited. An existing mounted case may execute successfully instead of skipping.',
        'Current owners derive only from the actual future wrapper dispatch/terminal and original observer. No old PID, starttick or session is rebound.',
        'Exact8 asset descriptors may join the closed supported-reuse metadata; old command owner/timing/report is never relabeled as the new acquisition.',
        'A metadata review can verify a failed original. Full CI pass requires the strict coherent original report/child/observer/wrapper0, required native successes, source equality, skip audit and original deadline.'
    ],
    'explicit_limits': [
        'Reader requires complete final stock reports/log/source tables and clean retained capture closure to seal all-scope evidence. Missing or inconsistent failure-stage evidence stays a failed/incomplete reader review, with available raw copies retained.',
        'Command JSON and raw build/factory channels do not expose original command numeric PID/FD identities; none are invented. Fresh scans cover only authenticated recorded controller/stock/suite owners and their PGIDs/sessions.',
        'Factory plugin descriptors are original stock observations; this reader never reopens plugin/model bodies or performs a new query.',
        'Primitive scanner/custody/caps and final report/flush/close/late logic remain inherited. Actual clean one-shot writes/FD restoration and independent reader-owner postterminal closure remain required.',
        'No local/hosted job, target, test, mount, Git, stock loader, engine, model or policy operation is performed by source preparation.'
    ],
    'all_author_input_handles_released': True,
    'author_epoch_view_limitation': 'Windows author FD and named views recorded separately and independently stable; no original Linux source95 epoch or future target output is asserted.',
    'reader_imported_compiled_or_executed': False, 'release_acceptance': False, 'conformance_acceptance': False, 'hardware_acceptance': False,
    'author_elapsed_s_before_receipt': time.monotonic() - START
}
ref = save('preparation.v3.json', (json.dumps(preparation, sort_keys=True, indent=2) + '\n').encode())
assert time.monotonic() - START < 120
print(json.dumps({'reader': reader, 'preparation': ref, 'diff': delta, 'status': 'prepared_unexecuted', 'all_author_input_handles_released': True}))
