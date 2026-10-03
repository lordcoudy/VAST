"""Finite read-only ZIP/status/source join; neither hosted failure is diagnosed here."""
import collections, hashlib, json, pathlib, re, subprocess, zipfile
ROOT = pathlib.Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = ROOT / 'artifacts/benchmark_recovery_20260930/ci-followup-original-retention-v1'
COMMITS = {36692564717: '9ad1a52b38cd5028de6b04bcc08192309ef192cf', 36699519675: 'ded811a8043575e7a93cf0bbc28696ac53667d3c'}
PATHS = ('.github/workflows/ci.yml', 'scripts/run_ci_checks.py', 'scripts/run_ci_host_diagnostics.py',
    'scripts/prepare_ci_model_assets.py', '.ci/model-assets.v1.json', 'tests/test_analytics_peer_identity.py',
    'scripts/backend_publication_process_supervisor_v3.py', 'tests/test_backend_q4_two_phase_executor_v1.py')
def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
rows = []
for run, commit in COMMITS.items():
    jobs = json.loads((OUT / f'{run}.jobs.connector.json').read_bytes())['jobs']
    artifacts = json.loads((OUT / f'{run}.artifacts.connector.json').read_bytes())['artifacts']
    for kind in ('cpu', 'host'):
        job = next(j for j in jobs if (j['name'] == 'cpu-checks') == (kind == 'cpu'))
        artifact = next(a for a in artifacts if a['name'].startswith('vast-cpu-checks-' if kind == 'cpu' else 'vast-host-diagnostics-'))
        assert artifact['workflow_run']['head_sha'] == commit and job['run_id'] == run and job['status'] == 'completed'
        directory = OUT / f'{run}-{kind}'
        path = directory / 'original-artifact.zip'
        logpath = OUT / f'{run}.{kind}.original-decoded-job.log'
        inventory = json.loads((directory / 'zip-readonly-inventory.v1.json').read_bytes())
        assert descriptor(path)['sha256'] == artifact['digest'].removeprefix('sha256:') and inventory['all_member_crc_verified']
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            before = json.loads(archive.read('tracked-source.before.json'))
            for relative in PATHS:
                raw = subprocess.run(['/usr/bin/git', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
                    '--work-tree=' + str(ROOT), 'show', commit + ':' + relative], capture_output=True, check=True, timeout=10).stdout
                assert before[relative] == {'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            row = {'run_id': run, 'source_commit': commit, 'kind': kind, 'job_id': job['id'], 'job_status': job['status'],
                'job_conclusion': job['conclusion'], 'artifact_id': artifact['id'], 'zip': descriptor(path),
                'zip_members': inventory['zip_members'], 'all_crc_and_provider_digest_verified': True,
                'decoded_job_log': descriptor(logpath), 'source_before_count': len(before),
                'critical_original_source_blobs_verified': list(PATHS), 'source_after_present': 'tracked-source.after.json' in names,
                'full_ci_successful': False, 'crash_cause': 'unknown', 'exact_denied_syscall_cause': 'unknown'}
            model = json.loads(archive.read('model-acquisition/report.json'))
            assert model['status'] == 'complete' and len(model['assets']) == 8 and all(a['status'] == 'downloaded' for a in model['assets'])
            row['original_model_acquisition'] = {'assets_downloaded': 8, 'elapsed_s': model['elapsed_s']}
            if kind == 'host':
                report = json.loads(archive.read('report.json'))
                assert report['commit'] == commit and report['diagnostic_passed'] and not report['full_ci_successful']
                assert report['original_process']['returncode'] == 0 and len(report['test_ids']) == 2
                row.update(diagnostic_tests_passed=report['test_ids'], original_child_returncode=0,
                    source_before_after_equal=before == json.loads(archive.read('tracked-source.after.json')))
                assert row['source_before_after_equal'] and job['conclusion'] == 'success'
            else:
                text = archive.read('unittest.original.log').decode('utf-8')
                events = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
                log = logpath.read_text(encoding='utf-8')
                assert 'Process completed with exit code 139.' in log and job['conclusion'] == 'failure'
                build = json.loads(archive.read('native-build.json'))
                assert build['returncode'] == 0 and not build['timed_out']
                row.update(original_logged_exit_code=139, native_build_returncode=0,
                    event_counts=dict(collections.Counter(e.get('event') for e in events)), last_original_event=events[-1],
                    namespace_errno13_line_count=sum('stage=namespace;' in line and 'errno=13' in line for line in text.splitlines()),
                    original_stack_log_bytes=len(archive.read('unittest-stacks.original.log')))
            rows.append(row)
receipt = {'schema_version': 1, 'artifact_kind': 'vast_original_ci_followup_readonly_retention_v1', 'rows': rows,
    'capture_scope': 'Four original immutable ZIPs, connector-normalized API snapshots, decoded original job text and finite historical blob joins.',
    'limitations': ['No raw HTTP API/log-byte identity claim: connector returns normalized metadata and decoded text.',
        'Full jobs terminated139 without final report/source-after; last started test and namespace errno13 do not establish a crash or syscall cause.',
        'No workflow action, restart, cancellation, full-suite execution, namespace/profile change, Docker or hardware workload.'],
    'temporary_urls_saved': False, 'full_ci_successful': False, 'hardware_acceptance': False}
with (OUT / 'outcome-join.v1.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(receipt, stream, sort_keys=True, separators=(',', ':')); stream.write('\n')
print(json.dumps({'original_runs_retained': 2, 'original_zips_verified': 4, 'critical_blobs_per_original': len(PATHS)}))
