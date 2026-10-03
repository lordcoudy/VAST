"""Finite metadata author only: no target import, process probe, or umount."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time

START = time.monotonic()
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
LINUX_BASE = '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
BOOT = 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
SOURCE_SHA = 'e4321413fb7a9613a362bd544347de8d552c1ebd50615beb78d3b82dbce98921'
CI_BASE = 'decision29-successor-ci-D-prerequisite-capture-preparation-v1/original-full-ci-prerequisite-attempt01/'
CI_REVIEW = 'decision29-local-ci-D-prerequisite-result-review-preparation-v1/'
MAPPER = 'decision29-current-conformance-preparation-v1/attempt01/'
MAPPER_CLOSE = 'decision29-current-conformance-mapper-owner-closure-v1/'
CF = 'decision29-current-conformance-independent-review-v1/'
BIND = 'decision29-runtime-bind-gates-independent-review-v1/'
CONFIG = {
    'ci_dispatch': (CI_BASE + 'dispatch.v1.json', 5426, '68f7184244fd4343317a75e0390ee5851110033628acf77022cdf0c819fc2bdc'),
    'ci_terminal': (CI_BASE + 'terminal.v1.json', 964, '3edd982ef6967a065fc52f1bf266fc0614fe4e69b64b6d875ccfc47ec98d658b'),
    'ci_review': (CI_REVIEW + 'original-prerequisite-review-attempt01/review.v1.json', 119285, '5a58508acf35f71d3c2934a022de1bff2e60eb44a39b6f85bd48cc3715ab7c60'),
    'ci_closure': (CI_REVIEW + 'independent-owner-late-closure-v1/actual-tool-and-owner-closure-supplement.v1.json', 5410, '45957c4900ec9edd6d0712bfbb8cf94c07401a01457bea09106938e95f1ccd45'),
    'mapper_terminal': (MAPPER + 'terminal.v1.json', 1419, 'ffa350ef8061a69a12bd019a5a5c5e41b15b74ba8a4f8000bc5d665da1ec3d52'),
    'cf_review': (CF + 'review.v1.json', 434057, 'af861006d56d00e466648cf2479f1536925f7b33f5a246916e924c067abec202'),
    'cf_closure': (CF + 'reviewer-owner-late-closure.v1.json', 4648, 'e3fea3ab9dcb4e2e633b9744eb4bb4aff692d4a049c40d4b8aef219bee6a162e'),
    'cf_later': (CF + 'final-tool-closure.v1.json', 677, '11514e3417af92c6a3ea75752c33b22f3bbcf2558ebf0e77bd01519c11b1db97'),
    'mapper_closure': (MAPPER_CLOSE + 'actual-tool-and-owner-closure-supplement.v1.json', 4763, 'c708bff2864de2b1ead9ff2f06d894d311f7174ef998034bac3e61d042e86e4e'),
    'mapper_observation': (MAPPER_CLOSE + 'original-observation-attempt01/closure.v1.json', 5327, '2756f040256f1c42cbb699b28c323e98cd6705131c706ab61a41572029fb8f07'),
    'bind_review': (BIND + 'review.v3.json', 26021, '524f12a1b3aabbabc39b580e8ed4b7ee3e56dd82bf9f3f8381dc8a9fc147203d'),
    'bind_closure': (BIND + 'closed-reviewer-supplement.v1.json', 3843, 'b07d7fc88c4362389bc2aa492f8bfd5c1b0f961a44f7ff855d0ddf0f5881e2d7'),
}
held = []
observations = []
closed = []
close_errors = []

def check_time():
    assert time.monotonic() - START < 20, 'metadata author deadline'

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def hold_file(path, size, digest):
    check_time()
    assert 0 < size <= 4 * 1024 * 1024
    assert not path.is_symlink()
    named = os.lstat(path)
    assert stat.S_ISREG(named.st_mode) and named.st_nlink == 1
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    held.append((path, fd, epoch(os.fstat(fd)), epoch(named)))
    initial = os.fstat(fd)
    assert initial.st_dev == named.st_dev and initial.st_ino == named.st_ino
    assert initial.st_size == size and stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1
    chunks = []
    remaining = size
    while remaining:
        check_time()
        part = os.read(fd, min(65536, remaining))
        assert part, 'short control read'
        chunks.append(part)
        remaining -= len(part)
    assert os.read(fd, 1) == b''
    data = b''.join(chunks)
    assert hashlib.sha256(data).hexdigest() == digest
    observations.append({'path': str(path), 'size_bytes': size, 'sha256': digest,
                         'fd_epoch7_before': epoch(initial), 'named_epoch7_before': epoch(named)})
    return data

def descriptor(key):
    rel, size, digest = CONFIG[key]
    return {'path': LINUX_BASE + '/' + rel, 'size_bytes': size, 'sha256': digest}

def normalize(value):
    assert type(value.get('pid')) is int and value['pid'] > 0
    row = {key: value.get(key) for key in ('pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id')}
    for key in ('pgid', 'session', 'startticks'):
        assert row[key] is None or type(row[key]) is int and row[key] > 0
    for key in ('uid', 'gid'):
        assert row[key] is None or type(row[key]) is int and row[key] >= 0
    assert row['boot_id'] in (None, BOOT)
    return row

def candidates_from_docs(value):
    result = []
    if isinstance(value, dict):
        if type(value.get('pid')) is int and value['pid'] > 0:
            result.append(normalize(value))
        if type(value.get('reader_pid')) is int and value['reader_pid'] > 0:
            result.append(normalize({'pid': value['reader_pid']}))
        if type(value.get('original_pid')) is int and value['original_pid'] > 0:
            result.append(normalize({'pid': value['original_pid'], 'pgid': value.get('original_pgid')}))
        for nested in value.values():
            result.extend(candidates_from_docs(nested))
    elif isinstance(value, list):
        for nested in value:
            result.extend(candidates_from_docs(nested))
    return result

def write_new(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    with path.open('xb') as stream:
        assert stream.write(data) == len(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {'path': str(path), 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def main():
    docs = {key: json.loads(hold_file(BASE / rel, size, sha)) for key, (rel, size, sha) in CONFIG.items()}
    hold_file(HERE / 'capture_owned_runtime_bind_cleanup_v2.py', 31423, SOURCE_SHA)
    hold_file(HERE / 'preparation.v2.json', 15424, '7c49e12ad65864d74d3d700b3af4f87238fd0fc1e17218d08c7e33234f673f3c')
    ci, cf, terminal = docs['ci_review'], docs['cf_review'], docs['mapper_terminal']
    assert ci['status'] == 'verified' and ci['source_commit'] == COMMIT
    assert ci['original_full_CI_disposition'] == 'SUCCESS' and ci['facts']['stock_evidence_complete'] is True
    assert ci['all_reader_handles_released'] is True and not ci['close_errors'] and ci['fd_before'] == ci['fd_after']
    assert cf['source_commit'] == COMMIT and cf['reviewable'] is True and cf['reviewer_handles_released'] is True
    assert cf['first_failure'] is None and not cf['close_errors'] and cf['fd_before'] == cf['fd_after']
    assert not cf['blocking_findings'] and len(cf['requirements']) == 20 and len(cf['scenario_adjudications']) == 118
    assert terminal['source_commit'] == COMMIT and terminal['FD_holds_released'] is True and not terminal['close_errors']
    assert docs['ci_closure']['status'] == docs['mapper_closure']['status'] == 'verified'
    assert docs['cf_closure']['late_failure_absent'] is True and docs['cf_later']['late_failure_absent'] is True
    assert docs['cf_closure']['reviewer_handles_released'] is True and docs['cf_later']['all_prior_review_handles_released'] is True
    for scan in docs['cf_closure']['two_actual_scans']:
        assert not scan['group_members'] and not scan['scan_errors'] and all(a['original_pid_path_absent'] for a in scan['actors'])
    assert all(s['original_metadata_scanner_11263_absent'] for s in docs['cf_later']['actual_later_scans'])
    assert ci['facts']['actual_wrapper_dispatch'] == docs['ci_dispatch']
    assert ci['facts']['actual_wrapper_terminal'] == docs['ci_terminal']
    owners, provenance = [], []
    def add(key, pointer, value):
        row = normalize(value)
        identity = (row['pid'], row['startticks'])
        existing = next((r for r in owners if (r['pid'], r['startticks']) == identity), None)
        assert existing is None or existing == row
        if existing is None:
            owners.append(row)
            provenance.append({'owner': row, 'control': descriptor(key), 'named_JSON_pointer': pointer})
    add('ci_dispatch', '/controller', docs['ci_dispatch']['controller'])
    add('ci_terminal', '/original', docs['ci_terminal']['original'])
    add('ci_review', '/facts/actual_observer/owner', ci['facts']['actual_observer']['owner'])
    add('ci_review', '/reader_pid', {'pid': ci['reader_pid']})
    add('ci_review', '/facts/actual_namespace_diagnostic/owner', ci['facts']['actual_namespace_diagnostic']['owner'])
    add('mapper_terminal', '/original_pid + /original_pgid', {'pid': terminal['original_pid'], 'pgid': terminal.get('original_pgid')})
    add('cf_review', '/reader_original', cf['reader_original'])
    add('cf_review', '/reader_original/observed_parent', cf['reader_original']['observed_parent'])
    for i, owner in enumerate(docs['bind_review']['facts']['original_owners']):
        add('bind_review', '/facts/original_owners/' + str(i), owner)
    add('bind_review', '/reader_pid', {'pid': docs['bind_review']['reader_pid']})
    for key, owner, pointer in (
        ('ci_closure', docs['ci_closure']['metadata_observer_original']['observed_owner'], '/metadata_observer_original/observed_owner'),
        ('mapper_observation', docs['mapper_observation']['observer'], '/observer')):
        add(key, pointer, owner)
        add(key, pointer + '/observed_parent', owner['observed_parent'])
    authentic = candidates_from_docs(list(docs.values()))
    assert all(row in authentic for row in owners)
    assert 4 <= len(owners) <= 512 and all(row['pid'] != 1 for row in owners)
    owners.sort(key=lambda r: (r['pid'], r['startticks'] or -1))
    tool = docs['mapper_closure']['umount_executable_actual']
    assert tool['path'] == '/usr/bin/umount' and tool['size_bytes'] == 39296
    assert tool['sha256'] == '186774a008ad69cf60bce6af35a850608d1c6ba410d3eca4113ea55b3a8b54d6'
    assert tool['epoch7'] == [2096, 46737, 35309, 1, 39296, 1787158071000000000, 1788318592831788374]
    binding = {
        'schema_version': 1, 'kind': 'original_owned_runtime_bind_cleanup_gate_v1',
        'source_commit_D': COMMIT, 'reviewed_capture_sha256': SOURCE_SHA,
        'cleanup_authorized': False,
        'all_D_consumers_closed': True,
        'no_new_D_consumers_since_closure': True,
        'underlying_target_directory_pre_mount_identity': None,
        'delete_directories': False,
        'umount_executable': {k: tool[k] for k in ('path', 'size_bytes', 'sha256', 'epoch7')},
        'full_ci': {k: descriptor(v) for k, v in {'dispatch':'ci_dispatch', 'terminal':'ci_terminal', 'result_review':'ci_review', 'process_closure':'ci_closure'}.items()},
        'conformance': {k: descriptor(v) for k, v in {'terminal':'mapper_terminal', 'independent_review':'cf_review', 'process_closure':'cf_closure'}.items()},
        'additional_D_consumer_closures': [descriptor(k) for k in ('cf_later', 'mapper_closure', 'mapper_observation', 'bind_review', 'bind_closure')],
        'all_closed_consumer_owners': owners,
    }
    before = json.loads((HERE / 'consumer-closure.pending.v2.json').read_bytes())
    assert set(before) == set(binding)
    changed = [k for k in before if before[k] != binding[k]]
    for i, (path, fd, initial, named_initial) in enumerate(held):
        assert epoch(os.fstat(fd)) == initial and epoch(os.lstat(path)) == named_initial
        observations[i]['fd_epoch7_after'] = epoch(os.fstat(fd))
        observations[i]['named_epoch7_after'] = epoch(os.lstat(path))
    return binding, provenance, changed, ci['facts']['actual_counts']

first_error = None
payload = None
try:
    payload = main()
except BaseException as exc:
    first_error = {'type': type(exc).__name__, 'message': str(exc)}
finally:
    for path, fd, *_ in reversed(held):
        try:
            os.close(fd)
            closed.append(str(path))
        except BaseException as exc:
            close_errors.append({'path': str(path), 'type': type(exc).__name__, 'message': str(exc)})
if first_error or close_errors:
    failure = {'schema_version': 1, 'first_error': first_error, 'close_errors': close_errors,
               'closed_inputs': closed, 'cleanup_executed': False, 'elapsed_s': time.monotonic() - START}
    write_new(HERE / 'consumer-candidate-metadata-author-failure.v1.json', failure)
    raise SystemExit(1)
check_time()
binding, provenance, changed, counts = payload
candidate = write_new(HERE / 'consumer-closure.candidate.v1.json', binding)
report = {
    'schema_version': 1, 'kind': 'closed_consumer_cleanup_binding_candidate_metadata_v1',
    'status': 'prepared_not_authorized_not_executed', 'candidate': candidate,
    'reviewed_cleanup_source_sha256': SOURCE_SHA, 'named_owner_count': len(binding['all_closed_consumer_owners']),
    'owner_field_provenance': provenance, 'control_input_witnesses': observations,
    'changed_keys_from_preserved_pending_v2': changed,
    'all_author_input_FDs_closed': len(closed) == len(held) and not close_errors,
    'independent_close_attempt_count': len(held), 'close_errors': close_errors,
    'actual_CI_counts_unmodified': counts, 'actual_conformance_20_118_reviewable': True,
    'current_boot_known_owner_filter': BOOT, 'foreign_boot_owner_objects_embedded': False,
    'cleanup_dispatch_performed': False, 'umount_invoked': False,
    'source_v2_modified': False, 'acceptance_claim': False,
    'parent_dispatch_attestation': 'Root reported no new D consumer after final semantic reader closure; only Windows metadata and read-only Git activity. Exact cleanup execution grant remains pending.',
    'remaining_exact_root_dispatch_conditions': [
        'Root must supply the exact cleanup execution grant and attest no new D consumers.',
        'Create the exclusive consumer-closure.bound.v1.json from this candidate only after that grant, changing cleanup_authorized to true; pin its actual size/SHA and reconfirm no intervening D consumer.',
        'Execute only the reviewed v2 fixed sole-umount capture under its unchanged 30+10 envelope. Every held proof and all declared current-process absences are verified afresh by that source before Popen.',
        'Close its own original capture/outer-timeout identity independently after the genuine terminal.'
    ],
    'limits': [
        'This is Windows stdlib metadata authorship; its descriptor epochs are not substituted for original Linux execution or source epochs.',
        'Known current-D actor records only: namespace observation PID 1, anonymous nested test PIDs and historical hosted actors are not declared as consumers.',
        'Original mapper birth/session and CI reader birth/group/session are null. No missing owner field, descendant absence, signal or approval is invented.',
        'Only named original actors and their recorded groups/sessions are scanned by the future capture. There is no global host-quiescence claim.',
        'Current namespace diagnostic owner6996 is authentic and included conservatively; original source reaping is retained, and future immediate pre-umount process scans remain mandatory.',
        'Metadata-only last scanners are not runtime-bind target consumers; their actual closure limitations remain in the held source reports.',
        'Underlying target-directory inode was never observed before mounting. Leave the directories intact; global source mount331 and its interpreter remain unchanged.',
        'Conformance, archive, final CI/review and release acceptance are separate; no failed original CI or benchmark outcome is rewritten.'
    ],
    'elapsed_s': time.monotonic() - START,
}
check_time()
ref = write_new(HERE / 'consumer-candidate-preparation.v1.json', report)
check_time()
print(json.dumps({'candidate': candidate, 'preparation': ref, 'owners': len(binding['all_closed_consumer_owners']), 'cleanup_executed': False}), flush=True)
check_time()
