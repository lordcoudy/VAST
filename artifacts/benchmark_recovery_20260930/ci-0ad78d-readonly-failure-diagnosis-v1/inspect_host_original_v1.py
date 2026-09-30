"""Bounded original hosted prerequisite archive inspection; no tests or workload."""
from pathlib import Path, PurePosixPath
import hashlib, json, os, stat, subprocess, zipfile
ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
RETAIN = ROOT / 'artifacts/benchmark_recovery_20260930/ci-0ad78d-original-host-retention-v1'
OUT = Path(__file__).parent / 'host-original-inspection-v1'
COMMIT = '0ad78d6abdb3c526544a17185af7fe8094716735'
OUT.mkdir(mode=0o700)
def ref(path):
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
def save(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    assert len(raw) <= 1024 * 1024
    with (OUT / name).open('xb') as out:
        out.write(raw); out.flush(); os.fsync(out.fileno())
    return ref(OUT / name)
archive = RETAIN / '36773798497-host/original-artifact.zip'
archive_ref = ref(archive)
assert archive_ref['size_bytes'] == 336328 and archive_ref['sha256'] == '2fdca7dac0c37065e9e8edc1cf8019015d05ca84930ee192203b3f310e99eaab'
jobs = json.loads((RETAIN / 'provider-jobs.final.original.json').read_bytes())['structuredContent']['jobs']
assert next(row for row in jobs if row['id'] == 110086521396)['conclusion'] == 'success'
with zipfile.ZipFile(archive) as z:
    names = set()
    for entry in z.infolist():
        path = PurePosixPath(entry.filename)
        assert not path.is_absolute() and '..' not in path.parts and '\\' not in entry.filename and '\0' not in entry.filename
        assert path.as_posix() == entry.filename and path.parts and ':' not in path.parts[0]
        assert not stat.S_ISLNK(entry.external_attr >> 16) and entry.file_size <= 1024 * 1024 and entry.filename not in names
        names.add(entry.filename)
    assert sum(entry.file_size for entry in z.infolist()) <= 4 * 1024 * 1024 and z.testzip() is None
    load = lambda name: json.loads(z.read(name))
    report = load('report.json'); before = load('tracked-source.before.json'); after = load('tracked-source.after.json')
    acquisition = load('model-acquisition/report.json'); original = load('host-prerequisites.json'); command = load('model-assets.json')
    facts = load('host-facts.original.json')
    ids = ['test_analytics_model_contract.AnalyticsModelContractTests.test_repository_manifest_is_complete_and_hash_bound', 'test_analytics_peer_identity.AnalyticsPeerIdentityAuthorityTests.test_observer_reads_exact_proc_file_and_small_docker_projection']
    assert report['commit'] == COMMIT and report['diagnostic_passed'] and report['diagnostic_tests_only'] and not report['full_ci_successful'] and not report['hardware_acceptance']
    assert report['test_ids'] == ids and report['original_process'] == original and report['changed_tracked_paths'] == [] and before == after
    assert original['returncode'] == command['returncode'] == 0 and not original['timed_out'] and not command['timed_out'] and original['cleanup_error'] is command['cleanup_error'] is None
    events = [json.loads(line) for line in z.read('host-prerequisites.stderr').splitlines() if line.startswith(b'{')]
    starts = [event for event in events if event['event'] == 'test_started']; terminals = [event for event in events if event['event'] == 'test_terminal']
    assert [event['test_id'] for event in starts] == [event['test_id'] for event in terminals] == ids
    assert all(event['outcome'] == 'success' for event in terminals)
    assert acquisition['status'] == 'complete' and acquisition['requires_original_exit_zero'] and acquisition['hardware_acceptance'] is False and len(acquisition['assets']) == 8
    asset_facts = []
    for index, asset in enumerate(acquisition['assets']):
        physical = load(f'model-acquisition/asset-{index:02}.json'); terminal = load(f'model-acquisition/asset-{index:02}.terminal.json')
        assert asset['index'] == index and asset['status'] == physical['status'] == 'downloaded'
        assert asset['size_bytes'] == physical['received_bytes'] == physical['hashed_prefix_bytes'] == physical['completed_write_bytes'] == physical['original_file_observed_bytes']
        assert asset['sha256'] == physical['received_prefix_sha256'] and asset['sha384'] == physical['received_prefix_sha384']
        assert physical['partial_path_matches_original_fd'] and physical['publication_observed'] and terminal['returncode'] == 0 and not terminal['timed_out']
        asset_facts.append(dict(asset, original_exit_code=terminal['returncode'], actual_child_pid=terminal['pid'], acquisition_elapsed_s=physical['elapsed_s']))
    source_paths = ['scripts/run_ci_host_diagnostics.py', 'scripts/prepare_ci_model_assets.py', '.ci/model-assets.v1.json', 'configs/checkpoint_analytics_models_openvino.yaml', 'tests/test_analytics_peer_identity.py', 'tests/test_analytics_model_contract.py', 'scripts/run_ci_checks.py']
    git = ['/usr/bin/git', '-c', 'core.longpaths=true', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec', 'cat-file', '--batch']
    blobs = subprocess.run(git, input=''.join(COMMIT + ':' + path + '\n' for path in source_paths).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
    assert len(blobs.stdout) <= 1024 * 1024 and not blobs.stderr
    cursor = 0; source_joins = []
    for path in source_paths:
        newline = blobs.stdout.index(b'\n', cursor); header = blobs.stdout[cursor:newline].split()
        assert len(header) == 3 and header[1] == b'blob'
        size = int(header[2]); raw = blobs.stdout[newline + 1:newline + size + 1]; cursor = newline + size + 2
        assert blobs.stdout[cursor - 1:cursor] == b'\n'
        row = {'path': path, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': header[0].decode()}
        assert before[path] == {key: row[key] for key in ['size_bytes', 'sha256']}
        source_joins.append(row)
    assert cursor == len(blobs.stdout)
    for source in acquisition['inputs']:
        assert before[source['path']] == {key: source[key] for key in ['size_bytes', 'sha256']}
    copy = OUT / 'host-prerequisites.stderr.original.raw'
    with copy.open('xb') as out:
        out.write(z.read('host-prerequisites.stderr')); out.flush(); os.fsync(out.fileno())
    result = {'schema_version': 1, 'artifact_kind': 'vast_0ad78d_original_host_prerequisites_readonly_review_v1', 'run_id': 36773798497, 'job_id': 110086521396, 'source_commit': COMMIT, 'provider_conclusion': 'success', 'archive': archive_ref, 'all_member_crc_verified': True, 'zip_member_count': len(names), 'decoded_bytes': sum(entry.file_size for entry in z.infolist()), 'actual_tracked_source_count': len(before), 'original_source_before_after_equal': True, 'seven_exact_source_blob_joins': source_joins, 'source_blob_read_argv': git, 'two_original_test_ids': ids, 'two_actual_success_terminals': terminals, 'original_host_prerequisites_command': original, 'raw_original_test_log': {'zip_member': 'host-prerequisites.stderr', 'member_crc32': z.getinfo('host-prerequisites.stderr').CRC, 'copy': ref(copy), 'byte_equality_verified': True}, 'original_asset_acquisition_command': command, 'original_asset_acquisition_elapsed_s': acquisition['elapsed_s'], 'eight_original_asset_facts': asset_facts, 'asset_total_bytes': sum(asset['size_bytes'] for asset in acquisition['assets']), 'original_host_facts': facts, 'original_decoded_job_log': ref(RETAIN / 'host-job-110086521396.decoded.exact.original.log'), 'scope': 'Two genuine original host prerequisites passed after eight exact canonical asset acquisitions. This does not grant full CI, CUDA/model numerical acceptance, namespace permission or benchmark acceptance.', 'full_ci_successful': False, 'hardware_acceptance': False, 'reviewer_tests_engine_models_namespace_or_source_changes': False}
print(json.dumps(save('host-review.v1.json', result), sort_keys=True))
