"""Finite metadata/source join; no target imports, tests, mount or weight reads."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
BIND = BASE / 'decision29-runtime-bind-prerequisite-capture-preparation-v1'
FOCUSED = BIND / 'original-focused-test-attempt01'
AUDIT = BASE / 'decision29-current95-post-runtime-bind-audit-preparation-v1'
EXPECTED = 'test_backend_publication_output_transaction_production_v3.BackendPublicationOutputTransactionProductionV3Tests.test_canonical_wsl_venv_requires_plain_copied_python'
START = time.monotonic()
FD_BEFORE = len(os.listdir('/proc/self/fd'))
held = []
pins = []
failures = []
closes = []
facts = {}


def epoch(value):
    return [value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def read(path, expected=None):
    assert time.monotonic() - START < 30
    path = Path(path)
    assert path.resolve(strict=True) == path
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    held.append((path, fd))
    before = os.fstat(fd)
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 1048576
    assert epoch(before) == epoch(path.lstat())
    blocks = []
    position = 0
    while position <= before.st_size:
        assert time.monotonic() - START < 30
        block = os.pread(fd, min(65536, before.st_size + 1 - position), position)
        if not block:
            break
        blocks.append(block)
        position += len(block)
    raw = b''.join(blocks)
    assert len(raw) == before.st_size and epoch(os.fstat(fd)) == epoch(before) == epoch(path.lstat())
    row = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch7': epoch(before)}
    if expected is not None:
        assert all(row[key] == expected[key] for key in ('path', 'size_bytes', 'sha256'))
        assert row['epoch7'] == expected.get('epoch', expected.get('epoch7', row['epoch7']))
    pins.append(row)
    return raw


def doc(path):
    return json.loads(read(path))


def scan(owners):
    ids = {row['pid'] for row in owners}
    groups = {row['pgid'] for row in owners}
    answer = {'at_monotonic_ns': time.monotonic_ns(), 'members': [], 'errors': [], 'original_pid_absent': {}}
    for item in Path('/proc').iterdir():
        if not item.name.isdigit():
            continue
        try:
            fields = (item / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(item.name) in ids or int(fields[2]) in groups:
                answer['members'].append({'pid': int(item.name), 'pgid': int(fields[2]), 'startticks': int(fields[19]), 'state': fields[0]})
        except (FileNotFoundError, ProcessLookupError):
            pass
        except BaseException as error:
            answer['errors'].append({'pid': int(item.name), 'type': type(error).__name__})
    for pid in sorted(ids):
        try:
            os.stat('/proc/' + str(pid))
            answer['original_pid_absent'][str(pid)] = False
        except (FileNotFoundError, ProcessLookupError):
            answer['original_pid_absent'][str(pid)] = True
        except BaseException as error:
            answer['original_pid_absent'][str(pid)] = None
            answer['errors'].append({'pid': pid, 'type': type(error).__name__})
    assert not answer['members'] and not answer['errors'] and all(answer['original_pid_absent'].values())
    return answer


try:
    assert sys.version_info[:3] == (3, 12, 3) and os.getuid() == os.getgid() == 1000
    read(Path(__file__).resolve())
    bind = doc(BIND / 'original-bind-attempt01/execution.v1.json')
    execution = doc(FOCUSED / 'execution.v1.json')
    dispatch = doc(FOCUSED / 'dispatch.v1.json')
    launch = doc(FOCUSED / 'launch.v1.json')
    result = doc(FOCUSED / 'unit-result.v1.json')
    grant = doc(BIND / 'focused-test-preparation-and-root-grant.v1.json')
    fresh = doc(AUDIT / 'original-post-runtime-bind-audit-attempt01/review.v1.json')
    assert pins[-1]['size_bytes'] == 127794 and pins[-1]['sha256'] == '56de11220a59b9138488210713d9ee58a3ba60fd9b9f1dd06bafda6ffd871e37'
    manifest = doc(BASE / 'decision28-current95-preparation-v1/decision28-current95-original-attempt01/current95-inputs.v1.json')
    assert bind['status'] == 'verified' and bind['first_error'] is None and not bind['errors'] and not bind['close_errors']
    assert bind['fd_before'] == bind['fd_after'] == 6 and bind['all_held_FDs_closed']
    assert execution['returncode'] == 0 and execution['failure'] is None and execution['source_stable']
    assert execution['flags'] == {'overflow': False, 'reader_errors': [], 'timed_out': False}
    assert execution['eof'] == {'stderr': True, 'stdout': True} and execution['readers_alive'] is False
    assert execution['fd_before'] == execution['fd_after'] == 6 and execution['elapsed_s'] < 120
    assert launch['owner'] == execution['owner'] and launch['argv'] == dispatch['argv']
    assert execution['source_before'] == execution['source_after'] == dispatch['source_before']
    for channel in ('stdout', 'stderr'):
        body = read(execution['channels'][channel]['path'], execution['channels'][channel])
        if channel == 'stderr':
            assert EXPECTED.rsplit('.', 1)[1].encode() in body and b'Ran 1 test' in body and body.endswith(b'OK\n')
            facts['actual_stderr_utf8'] = body.decode('utf-8')
        else:
            assert body == b''
    assert result['ids'] == [EXPECTED] and result['tests_run'] == 1
    assert result['failures'] == result['errors'] == result['skips'] == []
    assert result['source_stable'] and result['source_before'] == result['source_after']
    assert len(result['fd_timing_facts']) == 1 and result['fd_timing_facts'][0]['id'] == EXPECTED
    assert result['fd_timing_facts'][0]['fd_before'] == result['fd_timing_facts'][0]['fd_after'] == 4
    for observation in execution['process_scans']:
        assert observation['original_pid_absent'] and not observation['owned_group_members'] and not observation['read_errors']
    for row in execution['source_before'] + result['source_before']:
        if row['path'] not in {item['path'] for item in pins}:
            read(row['path'], row)
    assert next(row for row in result['source_before'] if row['path'].endswith('/tests/test_backend_publication_output_transaction_production_v3.py'))['sha256'] == 'f78c2fa070e672f3777aca28f5d5043a19fca63987afa5fd8300d1582334812d'
    assert grant['prepared_source']['sha256'] == '0565533e5ae299e0f0a154e1cb52f9b4f8758a06e50fe1bba67c616361ecac7e'
    assert fresh['reviewable'] and fresh['actual95_count'] == 95 and fresh['actual95_full_SHA_and_original_Linux_seven_epochs_current_equal']
    assert fresh['first_error'] is None and fresh['errors'] == fresh['blocking_findings'] == fresh['close_errors'] == [] and fresh['error_overflow'] == 0
    assert fresh['all_read_handles_released'] and fresh['all_source_and_metadata_before_after_equal']
    assert fresh['fd_before'] == fresh['fd_after'] == 6 and fresh['elapsed_s'] < 120
    assert fresh['before'] == fresh['after'] and len(fresh['before']) == 105
    assert all(row['released'] for row in fresh['independent_close_attempts'])
    for observed in fresh['fresh_process_scans']:
        assert not observed['members'] and not observed['errors'] and not observed['error_overflow'] and not observed['member_overflow'] and all(observed['pids_absent'].values())
    before_map = {row['descriptor']['path']: row for row in fresh['before']}
    original95 = manifest['actual_current95']
    assert len(original95) == len({row['descriptor']['path'] for row in original95}) == 95
    assert manifest['composition'] == {'role_documents': 6, 'fresh_project_sources': 87, 'canonical_interpreter': 1, 'exact_current_controller': 1, 'unique_total': 95}
    for row in original95:
        assert before_map[row['descriptor']['path']] == row
        assert epoch(Path(row['descriptor']['path']).lstat()) == row['epoch']
    read(AUDIT / 'audit_actual95_post_runtime_bind_v1.py', {'path': str(AUDIT / 'audit_actual95_post_runtime_bind_v1.py'), **{key: before_map[str(AUDIT / 'audit_actual95_post_runtime_bind_v1.py')]['descriptor'][key] for key in ('size_bytes', 'sha256')}, 'epoch': before_map[str(AUDIT / 'audit_actual95_post_runtime_bind_v1.py')]['epoch']})
    for path in (FOCUSED / 'late-failure.v1.json', AUDIT / 'original-post-runtime-bind-audit-attempt01/failure-companion.v1.json', BIND / 'original-bind-attempt01/late-failure.v1.json'):
        assert not os.path.lexists(path)
    owners = [dispatch['owner'], launch['owner'], fresh['reviewer'], {'pid': fresh['reviewer']['ppid'], 'pgid': fresh['reviewer']['pgid']}, bind['controller'], bind['controller']['observed_parent']]
    for item in bind['commands']:
        owners += [item['owner']] + item['observed_descendants']
    scans = [scan(owners), scan(owners)]
    facts.update(canonical_test_id=EXPECTED, original_test_count=1, successes=1, failures=0, errors=0, skips=0, actual_test_FD_baseline=[4, 4], actual_capture_FD_baseline=[6, 6], source_test_full_bytes_and_epochs_rechecked=True, focused_original_elapsed_s=execution['elapsed_s'], source_D=fresh['CI_checkpoint_D'], benchmark_B=fresh['benchmark_checkpoint_B'], fresh95_manifest_composition=manifest['composition'], fresh95_retained_full_sha_and_epoch_proof_joined=True, fresh95_current_named_epochs_metadata_only_rechecked=True, fresh95_leaf_and_ancestor_closes=len(fresh['independent_close_attempts']), actual_fresh95_FD_baseline=[6, 6], fresh95_original_elapsed_s=fresh['elapsed_s'], two_additional_original_owner_scans=scans, original_owners=owners, original_root_tool_references={'focused': '509856 CLOSED0 (ROOT original terminal notification)', 'post_bind95': 'ae608c CLOSED0 (ROOT original terminal notification)', 'bind_closure': '0a7ac2 CLOSED0 (ROOT original terminal notification)'})
except BaseException as error:
    failures.append({'type': type(error).__name__, 'message': str(error)[:2048]})
finally:
    for path, fd in held:
        try:
            expected = next(row for row in pins if row['path'] == str(path))
            assert epoch(os.fstat(fd)) == expected['epoch7'] == epoch(path.lstat())
        except BaseException as error:
            failures.append({'type': type(error).__name__, 'message': str(error)[:2048], 'path': str(path)})
        finally:
            try:
                os.close(fd)
                closes.append({'path': str(path), 'released': True})
            except BaseException as error:
                failures.append({'type': type(error).__name__, 'message': str(error)[:2048]})
                closes.append({'path': str(path), 'released': False})
    fd_after = len(os.listdir('/proc/self/fd'))
    if fd_after != FD_BEFORE:
        failures.append({'type': 'FD_baseline', 'message': 'reader FD baseline changed'})
    report = {'schema_version': 1, 'artifact_kind': 'actual_D_canonical_runtime_and_fresh95_independent_metadata_review_v1', 'reviewable': not failures, 'blocking_findings': failures, 'facts': facts, 'physical_inputs': pins, 'reader_pid': os.getpid(), 'reader_fd_before': FD_BEFORE, 'reader_fd_after': fd_after, 'independent_close_attempts': closes, 'all_reader_handles_released': all(row['released'] for row in closes), 'elapsed_s': time.monotonic() - START, 'full_CI_acceptance': False, 'benchmark_or_hardware_acceptance': False, 'limits': ['No test, mount, CI, target import, Git, engine or inference executed by this reviewer.', 'Original95 full byte verification is joined from the exact closed original audit; this reader only rechecks all95 named Linux epochs, without repeating their full bytes.', 'Original reaping/EOF and numeric FD counts come from the retained producer; additional process scans verify exact recorded owners/groups only, not global host quiescence.', 'ROOT original-tool returncode references are notifications rather than invented duplicate raw tool-terminal files.', 'Reader own future PID absence requires its actual tool completion and a later scan; no self-absence is claimed.']}
    with (HERE / 'review.v3.json').open('xb') as stream:
        payload = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if time.monotonic() - START >= 30 or len(os.listdir('/proc/self/fd')) != FD_BEFORE:
        with (HERE / 'late-failure.v3.json').open('xb') as stream:
            stream.write((json.dumps({'acceptance': False, 'elapsed_s': time.monotonic() - START}) + '\n').encode())
        failures.append({'type': 'late', 'message': 'final receipt/FD gate failed'})
    print(json.dumps({'review': str(HERE / 'review.v3.json'), 'size_bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest(), 'reviewable': not failures, 'reader_pid': os.getpid(), 'fd_before': FD_BEFORE, 'fd_after': fd_after, 'elapsed_s': time.monotonic() - START}), flush=True)
raise SystemExit(1 if failures else 0)
