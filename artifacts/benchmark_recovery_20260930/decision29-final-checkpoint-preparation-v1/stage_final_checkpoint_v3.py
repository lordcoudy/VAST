"""Prepared finite final staging only. Requires a separately reviewed sealed inventory.

No discovery, archive, commit, push, reset or normalization is performed here.
Original CI/conformance/archive outcomes must already be closed and pinned.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
BASE = 'artifacts/benchmark_recovery_20260930/'
CHANGE = 'openspec/changes/fix-benchmark-preparations-spec/'
MAIN = 'openspec/specs/benchmark-launch-preparation/spec.md'
D = '3c025b29b3c1d5275c2ec693410e4b83700583de'
B = 'a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
GIT = ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', '-c', 'core.longpaths=true']
START = time.monotonic()
END = START + 300
MAX_FILE = 8 * 1048576
MAX_TOTAL = 64 * 1048576
MAX_PATHS = 512
MAX_DOC = 1048576
DOCS = {'README.md', 'docs/gstreamer-component-benchmark-runbook.md', 'progress.md', 'BENCHMARK_RECOVERY_PLAN.md', '.gitattributes', MAIN}
CHANGE_FILES = (
    '.openspec.yaml', 'conformance-progress.md', 'design.md', 'image-invalidation.md',
    'implementation-approval.md', 'implementation-baseline.json', 'implementation-evidence.md',
    'implementation-validation.md', 'preparation-plan.md', 'proposal-validation.json',
    'proposal.md', 'review-context.json', 'reviewed-runtime-reconciliation.json',
    'reviewed-runtime-reconciliation.lf-check.json', 'specs/benchmark-launch-preparation/spec.md',
    'tasks.md', 'verification-plan.md',
)
NAMESPACES = (
    'decision28-four-arm-science-preparation-v1', 'decision28-four-arm-science-independent-actual-review-v1',
    'decision29-ci-P-C-original-independent-review-v1', 'decision29-local-ci-C-original-failure-review-v1',
    'decision29-ci-D-original-retention-v1', 'decision29-ci-D-original-independent-review-v1',
    'decision29-ci-P-original-retention-v1', 'decision29-ci-C-original-retention-v1',
    'decision29-local-ci-D-prerequisite-result-review-preparation-v1',
    'decision29-release-fresh-critique-v1',
    'decision29-current-ci-preparation-v1', 'decision29-current-ci-root-source-review-v1',
    'decision29-successor-ci-D-preparation-v1', 'decision29-successor-ci-D-prerequisite-capture-preparation-v1',
    'decision29-current95-post-setup-audit-preparation-v1', 'decision29-current95-post-D-setup-audit-preparation-v1',
    'decision29-current95-post-runtime-bind-audit-preparation-v1',
    'decision29-ext4-asset-cache-diagnosis-v1', 'decision29-ext4-asset-cache-copy-actual-review-v1',
    'decision29-ext4-asset-cache-stock-reuse-review-v1',
    'decision29-runtime-bind-prerequisite-plan-v1', 'decision29-runtime-bind-prerequisite-capture-preparation-v1',
    'decision29-runtime-bind-owned-cleanup-preparation-v1',
    'decision29-runtime-bind-gates-independent-review-v1', 'decision29-local-ci-D-original-review-preparation-v1',
    'decision29-r13-s6-manual-source-review-v1', 'decision29-current-conformance-preparation-v1',
    'decision29-current-conformance-independent-preparation-v1', 'decision29-current-conformance-independent-review-v1',
    'decision29-current-docs-v1', 'decision29-fresh-architecture-critique-v1',
    'decision29-final-checkpoint-preparation-v1', 'decision29-final-checkpoint-independent-review-v1',
    'decision29-sync-archive-original-review-v1',
)
physical = {}
epochs = {}
fds = set()
close_errors = []
objects_written = False
index_mutation_started = False


def clock():
    if time.monotonic() >= END:
        raise TimeoutError('final checkpoint original300s bound')


def run(args, payload=None):
    clock()
    completed = subprocess.run(GIT + args, cwd=ROOT, input=payload, capture_output=True,
                               timeout=min(15, max(.001, END - time.monotonic())))
    assert completed.returncode == 0, (args, completed.returncode, completed.stderr[:2048])
    assert len(completed.stdout) <= 16 * 1048576 and len(completed.stderr) <= 65536
    clock()
    return completed.stdout


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def canonical(name):
    assert type(name) is str and name and '\\' not in name and '\0' not in name and '\n' not in name and '\r' not in name
    path = Path(name)
    assert not path.is_absolute() and path.as_posix() == name and all(p not in {'', '.', '..'} for p in path.parts)
    assert not name.startswith('.git/') and name != '.git'
    return ROOT / path


def read(name):
    clock()
    path = canonical(name)
    assert path.resolve(strict=True) == path
    for parent in path.parents:
        if parent == ROOT.parent:
            break
        info = parent.lstat()
        assert stat.S_ISDIR(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 1024)
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= MAX_FILE
    assert not (getattr(before, 'st_file_attributes', 0) & 1024)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    fds.add(fd)
    primary = None
    try:
        observed_fd = os.fstat(fd)
        assert stat.S_ISREG(observed_fd.st_mode) and observed_fd.st_nlink == 1
        assert (observed_fd.st_dev, observed_fd.st_ino, observed_fd.st_size) == (before.st_dev, before.st_ino, before.st_size)
        blocks = []
        remaining = before.st_size
        while remaining:
            clock()
            block = os.read(fd, min(65536, remaining))
            assert block
            blocks.append(block)
            remaining -= len(block)
        assert os.read(fd, 1) == b''
        assert epoch(os.fstat(fd)) == epoch(observed_fd) and epoch(path.lstat()) == epoch(before)
        assert path.resolve(strict=True) == path
        return b''.join(blocks), epoch(before)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            os.close(fd)
            fds.remove(fd)
        except BaseException as exc:
            close_errors.append({'path': name, 'type': type(exc).__name__, 'message': str(exc)[:1024]})
            if primary is None:
                raise


def load_ref(ref):
    assert type(ref) is dict and set(ref) == {'path', 'size_bytes', 'sha256'}
    assert type(ref['size_bytes']) is int and 0 < ref['size_bytes'] <= MAX_DOC
    assert type(ref['sha256']) is str and re.fullmatch('[0-9a-f]{64}', ref['sha256'])
    raw, observed = read(ref['path'])
    assert len(raw) == ref['size_bytes'] and hashlib.sha256(raw).hexdigest() == ref['sha256']
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    return value, raw, observed


def raw_oid(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def allowed(name, archive_root):
    if name in DOCS:
        return True
    if name.startswith(archive_root):
        suffix = name[len(archive_root):]
        return suffix in CHANGE_FILES or suffix == 'implementation-closure.md'
    return any(name.startswith(BASE + namespace + '/') for namespace in NAMESPACES)


def normative(raw):
    lines = raw.decode('utf-8-sig').splitlines()
    requirements = []
    scenarios = []
    for index, line in enumerate(lines):
        if line.startswith('### Requirement: '):
            end = index + 1
            while end < len(lines) and not lines[end].startswith(('#### Scenario: ', '### Requirement: ')):
                end += 1
            requirements.append('\n'.join(lines[index:end]).strip())
        elif line.startswith('#### Scenario: '):
            end = index + 1
            while end < len(lines) and not lines[end].startswith(('#### Scenario: ', '### Requirement: ')):
                end += 1
            scenarios.append('\n'.join(lines[index:end]).strip())
    assert len(requirements) == 20 and len(scenarios) == 118
    return requirements, scenarios


def prospective(name, raw):
    expected = raw_oid(raw)
    differences = []
    for setting in ('false', 'true'):
        observed = run(['-c', 'core.autocrlf=' + setting, 'hash-object', '--path=' + name, '--stdin'], raw).decode().strip()
        if observed != expected:
            differences.append({'path': name, 'core_autocrlf': setting, 'raw_oid': expected, 'clean_oid': observed})
    return differences


def stage():
    global objects_written, index_mutation_started
    assert len(sys.argv) == 4, 'usage: helper SEALED_INVENTORY_RELATIVE_PATH SIZE SHA256'
    inventory_ref = {'path': sys.argv[1], 'size_bytes': int(sys.argv[2]), 'sha256': sys.argv[3]}
    assert inventory_ref['path'].startswith(BASE + 'decision29-final-checkpoint-preparation-v1/')
    inventory, inventory_raw, inventory_epoch = load_ref(inventory_ref)
    assert inventory['artifact_kind'] == 'sealed_final_checkpoint_inventory_v1' and inventory['status'] == 'sealed_reviewed_ready_for_staging'
    assert inventory['index_staging_authorized'] is True
    previous = inventory['base_commit']
    assert type(previous) is str and re.fullmatch('[0-9a-f]{40}', previous)
    assert inventory['CI_source_commit'] == D and inventory['benchmark_commit_untouched'] == B
    assert run(['rev-parse', '--show-object-format']).strip() == b'sha1'
    assert run(['rev-parse', 'HEAD']).decode().strip() == previous
    assert run(['diff', '--cached', '--name-only', '-z']) == b''
    archive_root = inventory['archive_root']
    assert re.fullmatch(r'openspec/changes/archive/\d{4}-\d{2}-\d{2}-fix-benchmark-preparations-spec/', archive_root)
    assert inventory['closed_prerequisite_facts'] == {
        'hosted_D_CI_accepted': True, 'latest_local_D_CI_accepted': True,
        'current_conformance_accepted': True, 'supported_sync_archive_closed': True,
        'current_docs_independently_reviewed': True, 'unexecuted_campaign_limits_preserved': True,
    }
    assert set(inventory['closed_review_refs']) == {'hosted_CI', 'local_CI', 'conformance', 'sync_archive', 'current_docs', 'staging_source'}
    staging_review = None
    for label, ref in inventory['closed_review_refs'].items():
        review, _, _ = load_ref(ref)
        assert review['reviewable'] is True and review['blocking_findings'] == [] and review['reviewer_handles_released'] is True, label
        if label == 'staging_source':
            staging_review = review
    archive, _, _ = load_ref(inventory['prearchive_move_manifest'])
    assert archive['artifact_kind'] == 'sealed_prearchive_physical_move_inventory_v1'
    assert archive['change_name'] == 'fix-benchmark-preparations-spec' and archive['archive_root'] == archive_root
    assert archive['observed_before_supported_archive'] is True
    suffixes = list(CHANGE_FILES)
    if archive['new_implementation_closure_snapshot'] is True:
        suffixes.append('implementation-closure.md')
    else:
        assert archive['new_implementation_closure_snapshot'] is False
    moves = archive['files']
    assert len(moves) == len(suffixes) and {row['old_path'] for row in moves} == {CHANGE + suffix for suffix in suffixes}
    assert len({row['old_path'] for row in moves}) == len(moves)
    files = inventory['files']
    assert type(files) is list and 0 < len(files) < MAX_PATHS
    assert len({row['path'] for row in files}) == len(files)
    assert all(allowed(row['path'], archive_root) for row in files)
    expected_names = {row['path'] for row in files}
    assert {'README.md', 'docs/gstreamer-component-benchmark-runbook.md', 'progress.md', 'BENCHMARK_RECOVERY_PLAN.md', '.gitattributes', MAIN} <= expected_names
    assert inventory_ref['path'] not in expected_names, 'sealed inventory must not contain an impossible self-hash'
    assert str(Path(__file__).resolve().relative_to(ROOT)).replace('\\', '/') in expected_names
    required_refs = {ref['path'] for ref in inventory['closed_review_refs'].values()}
    required_refs |= {inventory['prearchive_move_manifest']['path'], inventory['progress_preservation_ref']['path']}
    assert required_refs <= expected_names
    expected_names.add(inventory_ref['path'])
    physical[inventory_ref['path']] = inventory_raw
    epochs[inventory_ref['path']] = inventory_epoch
    total = len(inventory_raw)
    for row in files:
        assert set(row) == {'path', 'size_bytes', 'sha256', 'git_mode'}
        assert row['git_mode'] in {'100644', '100755'} and type(row['size_bytes']) is int
        raw, observed = read(row['path'])
        assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        total += len(raw)
        assert total <= MAX_TOTAL
        physical[row['path']] = raw
        epochs[row['path']] = observed
    assert physical[inventory_ref['path']] == inventory_raw and epochs[inventory_ref['path']] == inventory_epoch
    helper_name = Path(__file__).resolve().relative_to(ROOT).as_posix()
    helper_pin = {'path': helper_name, 'size_bytes': len(physical[helper_name]), 'sha256': hashlib.sha256(physical[helper_name]).hexdigest()}
    assert helper_pin in staging_review['owned_source_pins'], 'independent source review must pin this exact helper'
    for row in moves:
        old = row['old_path']
        new = archive_root + old[len(CHANGE):]
        assert row['new_path'] == new and new in expected_names and not os.path.lexists(canonical(old))
        assert len(physical[new]) == row['size_bytes'] and hashlib.sha256(physical[new]).hexdigest() == row['sha256']
        assert next(item['git_mode'] for item in files if item['path'] == new) == row['git_mode']
    assert normative(physical[MAIN]) == normative(physical[archive_root + 'specs/benchmark-launch-preparation/spec.md'])
    progress_before, _, _ = load_ref(inventory['progress_preservation_ref'])
    assert progress_before['artifact_kind'] == 'sealed_progress_original_suffix_preservation_v1'
    offset = progress_before['original_suffix_offset_bytes']
    assert type(offset) is int and 0 <= offset <= len(physical['progress.md'])
    suffix = physical['progress.md'][offset:]
    assert type(progress_before['original_suffix_size_bytes']) is int and progress_before['original_suffix_size_bytes'] > 0
    assert len(suffix) == progress_before['original_suffix_size_bytes'] and hashlib.sha256(suffix).hexdigest() == progress_before['original_suffix_sha256']
    original = {}
    for record in run(['ls-tree', '-rz', 'HEAD']).split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, kind, oid = meta.split()
        if kind == b'blob':
            original[os.fsdecode(name)] = (mode.decode(), oid.decode())
    tracked_old = {name for name in original if name.startswith(CHANGE)}
    assert tracked_old == {CHANGE + suffix for suffix in CHANGE_FILES}
    for row in moves:
        assert row['git_mode'] == (original[row['old_path']][0] if row['old_path'] in original else '100644')
    deletions = inventory['deletions']
    assert type(deletions) is list and len(deletions) == len(set(deletions)) and set(deletions) == tracked_old
    for name in deletions:
        assert not os.path.lexists(canonical(name))
    for row in files:
        if row['path'] in original:
            assert row['git_mode'] == original[row['path']][0], 'unrequested existing Git mode change'
    assert inventory_ref['path'] not in original or original[inventory_ref['path']][0] == '100644'
    attributes = run(['check-attr', '-z', '--stdin', 'filter'], ''.join(name + '\n' for name in sorted(expected_names)).encode()).split(b'\0')
    assert attributes[-1] == b'' and len(attributes[:-1]) == 3 * len(expected_names)
    assert all(attributes[index + 2] in {b'unspecified', b'unset'} for index in range(0, len(attributes) - 1, 3)), 'external clean filters are not allowed'
    filter_errors = []
    for name, raw in physical.items():
        filter_errors.extend(prospective(name, raw))
    if filter_errors:
        failure_raw = (json.dumps({'objects_written': False, 'index_mutation_started': False, 'prospective_filter_differences': filter_errors}, sort_keys=True, indent=2) + '\n').encode()
        assert len(failure_raw) <= MAX_DOC
        with (HERE / 'prospective-filter-failure.v1.json').open('xb') as stream:
            assert stream.write(failure_raw) == len(failure_raw)
            stream.flush()
            os.fsync(stream.fileno())
        raise AssertionError('prospective clean filters would change exact bytes; no Git mutation occurred')
    freeze_name = HERE.relative_to(ROOT).as_posix() + '/checkpoint-freeze.v1.json'
    assert freeze_name not in expected_names and not os.path.lexists(canonical(freeze_name))
    freeze = {'schema_version': 1, 'artifact_kind': 'final_checkpoint_exact_byte_preindex_freeze_v1',
              'previous_commit': previous, 'CI_source_commit': D, 'benchmark_commit_untouched': B,
              'inventory_ref': inventory_ref, 'owned_files': {name: {'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch7': epochs[name]} for name, raw in physical.items()},
              'owned_total_bytes': total, 'tracked_old_path_deletions': sorted(deletions),
              'archive_physical_moves': len(moves), 'archive_raw_byte_counterparts_equal': True,
              'main_and_archive_all20_requirement_and118_scenario_text_equal': True,
              'progress_original_suffix_preserved': True, 'prospective_raw_clean_false_true_equal': True,
              'final_archived_commit_CI_and_final_PR_review_merge_remain_pending': True}
    freeze_raw = (json.dumps(freeze, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    assert len(freeze_raw) <= MAX_DOC and total + len(freeze_raw) <= MAX_TOTAL
    assert prospective(freeze_name, freeze_raw) == []
    for name, raw in physical.items():
        actual, observed = read(name)
        assert actual == raw and observed == epochs[name]
    assert run(['rev-parse', 'HEAD']).decode().strip() == previous and run(['diff', '--cached', '--name-only', '-z']) == b''
    with canonical(freeze_name).open('xb') as stream:
        assert stream.write(freeze_raw) == len(freeze_raw)
        stream.flush()
        os.fsync(stream.fileno())
    physical[freeze_name] = freeze_raw
    _, epochs[freeze_name] = read(freeze_name)
    modes = {row['path']: row['git_mode'] for row in files}
    modes[inventory_ref['path']] = '100644'
    modes[freeze_name] = '100644'
    changed = {name for name, raw in physical.items() if original.get(name) != (modes[name], raw_oid(raw))}
    for name in sorted(changed):
        objects_written = True
        oid = run(['hash-object', '-w', '--stdin'], physical[name]).decode().strip()
        assert oid == raw_oid(physical[name])
        index_mutation_started = True
        run(['update-index', '--add', '--cacheinfo', modes[name] + ',' + oid + ',' + name])
    for name in sorted(deletions):
        index_mutation_started = True
        run(['update-index', '--force-remove', '--', name])
    expected_staged = changed | set(deletions)
    actual_staged = set(filter(None, os.fsdecode(run(['diff', '--cached', '--name-only', '-z'])).split('\0')))
    assert actual_staged == expected_staged
    for name, raw in physical.items():
        actual, observed = read(name)
        assert run(['show', ':' + name]) == raw == actual and observed == epochs[name]
    for name in deletions:
        assert not os.path.lexists(canonical(name))
    assert run(['rev-parse', 'HEAD']).decode().strip() == previous
    # Only exact newly authored paths are whitespace checked; original raw snapshots are never normalized.
    authored = inventory['authored_whitespace_check_paths']
    assert type(authored) is list and len(authored) == len(set(authored)) and set(authored) <= changed
    if authored:
        run(['-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol', 'diff', '--cached', '--check', '--', *authored])
    assert not fds and not close_errors
    clock()
    print(json.dumps({'owned_files': len(physical), 'changed_staged_files': len(expected_staged),
                      'tracked_deletions': len(deletions), 'archive_raw_moves': len(moves),
                      'owned_total_bytes': total + len(freeze_raw), 'physical_index_equal': True,
                      'exact_index_path_set': True, 'freeze_sha256': hashlib.sha256(freeze_raw).hexdigest(),
                      'final_archived_commit_checks_and_final_review_merge_pending': True}), flush=True)
    clock()


try:
    stage()
except BaseException as exc:
    # Do not reset or modify a partly staged index. Preserve the original failure for the root capture.
    for fd in tuple(fds):
        try:
            os.close(fd)
            fds.remove(fd)
        except BaseException as close_error:
            close_errors.append({'phase': 'independent-final-close', 'type': type(close_error).__name__, 'message': str(close_error)[:1024]})
    print(json.dumps({'status': 'failed_final_checkpoint_staging', 'type': type(exc).__name__,
                      'message': str(exc)[:4096], 'objects_written': objects_written,
                      'index_mutation_started': index_mutation_started, 'commit_or_push_performed': False,
                      'open_read_FDs': len(fds), 'close_errors': close_errors,
                      'elapsed_s': time.monotonic() - START}), flush=True)
    raise
