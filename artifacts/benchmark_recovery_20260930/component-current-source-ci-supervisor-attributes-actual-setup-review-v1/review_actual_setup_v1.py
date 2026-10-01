"""Read only closed original setup metadata; never run setup, tests or models."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).parent
PREP = HERE.parent / 'component-current-source-ci-supervisor-attributes-preparation-v1'
START = time.monotonic()
held = []
pins = {}


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def read(path, expected=None):
    path = Path(path)
    assert path.resolve(strict=True) == path
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    held.append((fd, path, epoch(os.fstat(fd))))
    s = os.fstat(fd)
    assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 8388608
    raw = b''
    while chunk := os.read(fd, 65536):
        raw += chunk
    assert len(raw) == s.st_size and epoch(s) == epoch(os.fstat(fd)) == epoch(path.lstat())
    pin = {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch7': epoch(s)}
    if expected is not None:
        for key in ('path', 'size_bytes', 'sha256'):
            assert expected[key] == pin[key], (path, key)
        if 'epoch7' in expected:
            assert expected['epoch7'] == pin['epoch7']
    pins[str(path)] = pin
    return raw


def owner(pid):
    p = Path('/proc', str(pid))
    values = (p / 'stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in (p / 'status').read_text().splitlines() if ':' in line)
    return {'pid': pid, 'ppid': int(values[1]), 'pgid': int(values[2]), 'session': int(values[3]), 'startticks': int(values[19]), 'uid': int(status['Uid'].split()[0]), 'gid': int(status['Gid'].split()[0]), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def scan(ids, groups, sessions):
    matches = []
    errors = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(p.name) in ids or int(fields[2]) in groups or int(fields[3]) in sessions:
                matches.append(owner(int(p.name)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            errors.append({'pid': int(p.name), 'type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)})
    return {'at_ns': time.time_ns(), 'members': matches, 'errors': errors, 'pids_absent': {str(pid): not Path('/proc', str(pid)).exists() for pid in sorted(ids)}}


report = None
error = None
try:
    assert os.getuid() == os.getgid() == 1000 and sys.version_info[:3] == (3, 12, 3)
    preparation = json.loads(read(PREP / 'preparation.v1.json'))
    assert pins[str(PREP / 'preparation.v1.json')]['sha256'] == '61fbb55ef7acf48a020786fc8995b88f714d288d3e155a566f3756dfc4675470'
    recipe = json.loads(read(PREP / 'recipe.v1.json', preparation['files']['recipe.v1.json']))
    for name in ('setup_original_current_ci_v1.py', 'capture_original_setup_v1.py', 'capture_original_full_ci_v1.py'):
        read(PREP / name, preparation['files'][name])
    terminal_raw = read(PREP / 'original-setup.capture-terminal.v1.json')
    assert len(terminal_raw) == 4544 and hashlib.sha256(terminal_raw).hexdigest() == '15e8c02cf46313e0e62281e8394982a71529c415c6e2216c0377bb2b1bf742df'
    terminal = json.loads(terminal_raw)
    launch = json.loads(read(PREP / 'original-setup.capture-launch.v1.json'))
    child = json.loads(read(PREP / 'original-setup.child-owner.v1.json'))
    read(PREP / 'root-grant.v1.json')
    result = json.loads(read(PREP / 'original-setup-attempt01/execution.v1.json'))
    assert terminal['returncode'] == 0 and terminal['failure'] is None and terminal['signals'] == []
    assert terminal['elapsed_s'] < 310 and terminal['capture_fds_closed'] and terminal['original_child_reaped']
    assert terminal['source_before'] == terminal['source_after'] == preparation['files']['setup_original_current_ci_v1.py']
    assert terminal['argv'] == launch['argv'] and terminal['timeout_owner'] == launch['timeout_owner']
    assert child == terminal['setup_owner'] and launch['capture_owner']['pid'] == terminal['capture_owner']['pid']
    assert launch['work_s'] == 300 and launch['cleanup_s'] == 10
    for key in ('stdout', 'stderr'):
        read(terminal[key]['path'], terminal[key])
    assert terminal['late_failure_absent'] and not os.path.lexists(PREP / 'original-setup-attempt01/late-failure.v1.json')
    assert result['status'] == 'prepared_exact_source_and_prerequisites' and result['source_commit'] == preparation['source_commit']
    assert result['root'] == recipe['checkout'] and result['output_future'] == recipe['output']
    assert result['raw_committed_bytes_equal'] and result['eight_reviewed_source_pins_equal']
    assert result['held95_fds_released'] and result['close_errors'] == []
    assert result['benchmark_root_head_unchanged'] == recipe['benchmark_root_commit_untouched']
    assert result['benchmark_root_identity_unchanged'] and result['benchmark95_input_epochs_unchanged']
    root = Path(result['root'])
    assert root.resolve(strict=True) == root
    root_stat = root.lstat()
    assert [root_stat.st_dev, root_stat.st_ino, root_stat.st_mode, root_stat.st_uid, root_stat.st_gid] == result['root_identity']
    assert root_stat.st_uid == root_stat.st_gid == 1000 and result['parent_filesystem'][2] == 'ext4'
    assert result['available_bytes_before'] >= 20 * 1024 ** 3
    assert result['shared_object_alternate'] == '/mnt/e/STUDY/VAST/.git/objects'
    assert read(root / '.git/HEAD').strip().decode() == recipe['source_commit']
    assert read(Path(recipe['benchmark_root_untouched']) / '.git/HEAD').strip().decode() == recipe['benchmark_root_commit_untouched']
    assert read(root / '.git/objects/info/alternates').strip().decode() == result['shared_object_alternate']
    assert not os.path.lexists(result['output_future']) and not os.path.lexists(PREP / 'original-full-ci-attempt01')
    commands = result['commands']
    assert len(commands) == 14 and [c['argv'] for c in commands[2:8]] == recipe['setup_commands']
    for command in commands:
        assert command['returncode'] == 0 and command['child_reaped']
        for key in ('stdout', 'stderr'):
            if key in command:
                read(command[key]['path'], command[key])
    assert read(PREP / 'original-setup-attempt01/06-setup.stdout.raw').strip().decode() == recipe['source_commit']
    assert read(PREP / 'original-setup-attempt01/07-setup.stdout.raw') == b''
    assert read(PREP / 'original-setup-attempt01/08-autocrlf.stdout.raw').strip() == b'false'
    inventory = json.loads(read(result['tracked_source_inventory']['path'], result['tracked_source_inventory']))
    assert len(inventory) == result['tracked_count'] == 4721
    assert sum(row['size_bytes'] for row in inventory) == result['tracked_bytes'] == 213031024
    indexed = {row['path']: row for row in inventory}
    assert len(indexed) == len(inventory)
    tree = read(PREP / 'original-setup-attempt01/09-tree.stdout.raw')
    tree_rows = {}
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, oid = metadata.split()
        assert kind == b'blob' and mode in (b'100644', b'100755')
        tree_rows[os.fsdecode(name)] = oid.decode()
    assert len(tree_rows) == len(indexed) and all(tree_rows[path] == row['git_oid'] for path, row in indexed.items())
    for relative, row in indexed.items():
        p = root / relative
        assert p.resolve(strict=True) == p and epoch(p.lstat()) == row['epoch7']
    catfile = commands[10]
    assert catfile['streamed_raw_blob_count'] == len(inventory) and catfile['streamed_raw_blob_bytes'] == result['tracked_bytes']
    for relative, expected in recipe['source_pins'].items():
        row = indexed[relative]
        assert row['size_bytes'] == expected['size_bytes'] and row['sha256'] == expected['sha256']
        read(root / relative, {'path': str(root / relative), **expected, 'epoch7': row['epoch7']})
    requirements = read(root / '.ci/requirements.txt').decode().splitlines()
    expected_packages = dict(line.split('==') for line in requirements if line and not line.startswith('#'))
    assert {p['name']: p['actual'] for p in result['packages']} == expected_packages
    assert all(p['actual'] == p['expected'] for p in result['packages'])
    assert read(PREP / 'original-setup-attempt01/11-pip-check.stdout.raw').strip() == b'No broken requirements found.'
    assert len(result['native_packages'].splitlines()) == 8 and all(row.endswith('install ok installed') for row in result['native_packages'].splitlines())
    for p in result['tools'].values():
        assert Path(p).resolve(strict=True) == Path(p) and stat.S_ISREG(Path(p).lstat().st_mode)
    assert epoch(Path(result['canonical_python']['path']).lstat()) == result['canonical_python']['epoch7']
    witness = json.loads(read(PREP.parent / 'component-gpu01-ext4-postterminal-audit-preparation-v1/held-inputs-and-processes.v1.json'))
    assert len(witness['actual_current95']) == 95
    for row in witness['actual_current95']:
        p = Path(row['descriptor']['path'])
        assert p.resolve(strict=True) == p and epoch(p.lstat()) == row['epoch']
    gpu_closure = read(PREP.parent / 'component-gpu01-ext4-actual-audit-closure-v1/review.v1.json')
    assert hashlib.sha256(gpu_closure).hexdigest() == '6c25127270763cf47a03291be9b2115671ea7d6df3d4d8c19fb7f59932b79768'
    all_owners = [terminal[key] for key in ('capture_owner', 'timeout_owner', 'setup_owner')] + [c['owner'] for c in commands]
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert all(o['uid'] == o['gid'] == 1000 and o['boot_id'] == boot and o['startticks'] > 0 for o in all_owners)
    for original_scan in terminal['process_scans'] + result['command_process_scans']:
        assert not original_scan['members'] and not original_scan['errors'] and all(original_scan['pids_absent'].values())
    ids = {o['pid'] for o in all_owners}
    groups = {o['pgid'] for o in all_owners}
    sessions = {o['session'] for o in all_owners if 'session' in o}
    scans = [scan(ids, groups, sessions), scan(ids, groups, sessions)]
    assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
    for fd, path, before in held:
        assert epoch(os.fstat(fd)) == before == epoch(path.lstat())
    report = {
        'schema_version': 1, 'artifact_kind': 'vast_attributes_checkout_actual_setup_metadata_review_v1',
        'status': 'passed_setup_only_no_full_ci_or_benchmark_acceptance', 'source_commit': recipe['source_commit'],
        'checkout': result['root'], 'actual_original_elapsed_s': terminal['elapsed_s'],
        'actual_original_capture_timeout_setup_owners': {k: terminal[k] for k in ('capture_owner', 'timeout_owner', 'setup_owner')},
        'actual_original_command_owners': [c['owner'] for c in commands],
        'tracked_count': len(inventory), 'tracked_bytes': result['tracked_bytes'],
        'original_streamed_raw_git_equality_current_epochs_and_tree_oids_join': True,
        'eight_current_source_pins_join': True, 'original_prerequisites_passed': True,
        'original95_epochs_unchanged_and_setup_fds_released': True,
        'original_benchmark_head_still_0ad': True, 'late_failure_absent': True,
        'fresh_process_scans': scans, 'physical_metadata_inputs': list(pins.values()),
        'reader_owner': owner(os.getpid()),
        'limitations': ['Metadata review relies on the genuine setup producer byte-for-byte streamed Git comparison; reader did not repeat its 213MB hash pass or read model data.', 'The timeout birth observation retained argv=[empty string] in state D; this is preserved as a pre-exec observation, not asserted executable custody. Its real setup child argv, owner and terminal are joined.', 'Setup and prerequisites permit separately authorized stock CI; no full CI or renewed benchmark acceptance is granted.'],
    }
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)[:4096]}
    report = {'status': 'failed_no_dependent_grant', 'first_error': error, 'physical_metadata_inputs': list(pins.values())}
finally:
    close_errors = []
    for fd, _, _ in held:
        try:
            os.close(fd)
        except OSError as exc:
            close_errors.append({'type': type(exc).__name__, 'errno': exc.errno})
    report['reader_fd_count'] = len(held)
    report['reader_fds_released'] = not close_errors
    report['reader_close_errors'] = close_errors
    report['elapsed_s'] = time.monotonic() - START
    raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
    with (HERE / 'review.v1.json').open('xb') as stream:
        assert stream.write(raw) == len(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({'status': report['status'], 'review': {'path': str(HERE / 'review.v1.json'), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, 'reader_fds_released': report['reader_fds_released'], 'elapsed_s': report['elapsed_s'], 'first_error': error}), flush=True)
sys.exit(0 if error is None and not close_errors else 1)
