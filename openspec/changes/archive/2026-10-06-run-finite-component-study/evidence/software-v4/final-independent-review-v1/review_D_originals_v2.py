"""Finite read-only review of retained originals; never import or execute CI targets."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
ROOT = Path('/mnt/e/STUDY/VAST/tmp/finite-component-study-20261005')
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

directory = HERE.parent / 'original-retention-v1'
run_id, cpu_id, host_id = 37279566144, 111664198463, 111664198751
commit = '42725b4fc7b2e5c0cc71d79ea57a1f1fa48fef9a'
source = read(HERE.parent / 'retain_originals_v1.py')
criteria = json.loads(read(ROOT / 'ci-D-acceptance-criteria.v1.json'))
retention_tools = json.loads(read(HERE.parent / 'retention.original-tools.json'))
assert retention_tools['init']['result']['chunk_id'] == '4bb138' and retention_tools['init']['result']['session_id'] == 54266
assert retention_tools['final']['result']['chunk_id'] == '68dc13' and retention_tools['final']['result']['exit_code'] == 0
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
assert provider_run['run_attempt'] == 1 and provider_run['run_number'] == 72 and provider_run['path'] == '.github/workflows/ci.yml'
jobs = {j['id']: j for j in metadata['jobs']['jobs']}
assert set(jobs) == {cpu_id, host_id}
assert all(j['run_id'] == run_id and j['head_sha'] == commit and j['conclusion'] == 'success' and j['status'] == 'completed' for j in jobs.values())
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
discovered_count = len(child['discovered_ids'])
success_count = len(child['successful_test_ids'])
assert discovered_count == len(set(child['discovered_ids']))
assert success_count == len(set(child['successful_test_ids']))
assert child['errors'] == child['failures'] == child['expected_failures'] == child['unexpected_successes'] == child['missing_required_successes'] == []
skip_count = len(child['skips'])
assert skip_count == len(child['portable_skip_audit'])
selection = child['selection']

def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

pins = criteria['baseline']['inventory_pins']
assert len(child['discovered_ids']) == 3110 and child['tests_run'] == 3101
assert success_count == 3013 and skip_count == 88 and child['successful'] is True
for key, expected in (
    ('discovered_ids', pins['discovered_ids_canonical_sha256']),
    ('portable_ids', pins['portable_ids_canonical_sha256']),
    ('allowed_portable_skips', pins['allowed_portable_skips_canonical_sha256']),
    ('integration_declarations', pins['integration_declarations_canonical_sha256'])):
    assert canonical_sha(selection[key]) == expected, key
assert selection['manifest_path'] == pins['manifest_path'] and selection['manifest_sha256'] == pins['manifest_sha256']
assert canonical_sha(child['portable_skip_audit']) == pins['actual_portable_skip_audit_canonical_sha256']
selected_count, integration_count = len(selection['portable_ids']), len(selection['integration_declarations'])
assert selection['counts'] == {'discovered':3110,'portable':3101,'integration':9}
assert selection['integration_executed'] is False and selection['hardware_acceptance'] is False
assert selection['discovered_ids'] == child['discovered_ids']
portable, successful = set(selection['portable_ids']), set(child['successful_test_ids'])
skipped = {r['test_id'] for r in child['skips']}
assert len(portable) == selected_count and len(skipped) == skip_count and successful.isdisjoint(skipped)
assert portable == successful | skipped
integrations = {row['test_id'] for row in selection['integration_declarations']}
assert len(integrations) == integration_count and portable.isdisjoint(integrations)
assert set(child['discovered_ids']) == portable | integrations
allowed = {r['test_id']:r for r in selection['allowed_portable_skips']}
audit = []
for row in child['skips']:
    assert row['test_id'] in allowed and row['reason'] == allowed[row['test_id']]['reason']
    audit.append(allowed[row['test_id']])
assert sorted(audit,key=lambda r:r['test_id']) == child['portable_skip_audit']
assert all(row['acceptance_claim'] is False for row in audit)
residual = criteria['required_transition_to_actual_success']
fixtures = criteria['all_eight_original_fixture_ids']
assert len(residual) == 6 and set(residual) <= successful and set(REQUIRED) <= successful
deferred_fixture_ids = sorted(set(fixtures)-set(residual))
assert len(deferred_fixture_ids) == 2 and set(deferred_fixture_ids) <= integrations
assert set(fixtures) <= set(child['discovered_ids']) and set(fixtures) & portable == set(residual)
assert report['built_targets'] == TARGETS and report['hardware_gaps']
assert report['canonical_python'].endswith('/Python/3.12.3/x64/bin/python3.12')
command_controls = {}
def command_ok(value):
    assert value['returncode'] == 0 and value['timed_out'] is False and value['cleanup_error'] is None
for command_name in ('model-assets.json','native-configure.json','native-build.json','gstreamer-packages.json'):
    value = member_json(cpu,command_name); command_ok(value); command_controls[command_name] = value
assert command_controls['native-build.json']['argv'][-6:] == TARGETS
assert report['gstreamer_packages'] == command_controls['gstreamer-packages.json']
assert len(report['python_syntax']) == len(set(report['python_syntax'])) and len(report['bash_syntax']) == len(set(report['bash_syntax']))
for factory in ('appsrc','queue','videoconvert'):
    value = report['gstreamer_factories'][factory]
    assert member_json(cpu,'factory-'+factory+'.json') == value['command']
    command_ok(value['command'])
    raw = cpu.get('factory-'+factory+'.stdout')
    # Actual factory stdout is independently hash-checked again below from the ZIP.
assert cpu['tracked-source.before.json'] == cpu['tracked-source.after.json']
tracking = member_json(cpu,'tracked-source.before.json')
assert all(set(r)=={'size_bytes','sha256'} for r in tracking.values())
assert report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == []
assert tracking[selection['manifest_path']]['sha256'] == selection['manifest_sha256']
host_report = member_json(host,'report.json')
assert host_report['commit'] == commit and host_report['changed_tracked_paths'] == []
assert host_report['diagnostic_passed'] is True and host_report['diagnostic_tests_only'] is True
assert host_report['full_ci_successful'] is False and host_report['hardware_acceptance'] is False
assert host['tracked-source.before.json'] == host['tracked-source.after.json'] == cpu['tracked-source.before.json']
command_ok(host_report['original_process'])
assert member_json(host,'host-prerequisites.json') == host_report['original_process']

GIT = ['/mnt/c/Program Files/Git/cmd/git.exe','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true',
       '-C','C:/Users/s-a-balashov/.codex/worktrees/finite-component-study/VAST']
git_commands = []
def git_small(args, cap=2*1048576):
    clock(); command = GIT+args
    result = subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=True)
    assert len(result.stdout)<=cap and result.stderr == b''
    git_commands.append(command)
    return result.stdout
assert git_small(['rev-parse','HEAD']).strip().decode() == commit
tree = git_small(['ls-tree','-rzl','--full-tree',commit])
rows = []
for record in tree.rstrip(b'\0').split(b'\0'):
    fields, path = record.split(b'\t',1)
    mode, kind, oid, size = fields.split()
    assert kind==b'blob' and len(oid)==40 and mode in (b'100644',b'100755')
    rows.append({'path':path.decode('utf-8'),'mode':mode.decode(),'git_blob_oid':oid.decode(),'size_bytes':int(size)})
assert len(rows)==len({r['path'] for r in rows}) <= 10000
assert sum(r['size_bytes'] for r in rows) <= 512*1048576
query = HERE/'git-batch-queries.v2.original.txt'
with query.open('xb') as stream:
    stream.write(b''.join(r['git_blob_oid'].encode()+b'\n' for r in rows))
batch_command=GIT+['cat-file','--batch']; git_commands.append(batch_command)
process=None; needed={}
try:
    with query.open('rb') as queries, (HERE/'git-batch.stderr.v2.original.raw').open('xb') as errors:
        process=subprocess.Popen(batch_command,stdin=queries,stdout=subprocess.PIPE,stderr=errors)
        for row in rows:
            clock()
            oid,kind,size=process.stdout.readline(256).rstrip(b'\n').split()
            assert oid.decode()==row['git_blob_oid'] and kind==b'blob' and int(size)==row['size_bytes']
            remaining=int(size); h=hashlib.sha256(); g=hashlib.sha1(b'blob '+size+b'\0'); parts=[]
            keep=row['path'] in ('.ci/model-assets.v1.json','.ci/integration-test-selection.v1.json','.github/workflows/ci.yml')
            while remaining:
                clock(); block=process.stdout.read(min(65536,remaining)); assert block
                remaining-=len(block);h.update(block);g.update(block)
                if keep:parts.append(block)
            assert process.stdout.read(1)==b'\n' and g.hexdigest()==row['git_blob_oid']
            row['sha256']=h.hexdigest()
            if keep:needed[row['path']]=b''.join(parts)
        assert process.stdout.read(1)==b''
        assert process.wait(timeout=min(10,max(.1,END-time.monotonic())))==0
    assert (HERE/'git-batch.stderr.v2.original.raw').stat().st_size==0
finally:
    if process is not None:
        if process.poll() is None:
            process.kill();process.wait(timeout=10)
        process.stdout.close()
expected_tracking={row['path']:{k:row[k] for k in ('size_bytes','sha256')} for row in rows}
assert expected_tracking == tracking, 'Every hosted raw tracked source equals exact D Git object bytes'
assert git_small(['rev-parse','HEAD']).strip().decode()==commit
git_diff=git_small(['diff','--no-renames','--raw','-z',commit,'--'])
dirty_paths=[]
for row in git_diff.rstrip(b'\0').split(b'\0')[1::2]:
    dirty_paths.append(row.decode('utf-8'))
allowed_dirty_docs={'PLAN.md','progress.md','openspec/changes/run-finite-component-study/conformance.md',
                    'openspec/changes/run-finite-component-study/implementation-validation.md'}
assert set(dirty_paths)<=allowed_dirty_docs, 'Any current production/test/CI/planning-spec change needs its own source gate'
failed_reader_source=read(HERE/'review_D_originals_v1.py')
assert len(failed_reader_source)==36921 and hashlib.sha256(failed_reader_source).hexdigest()=='bf67af9ba53ad546f523c15d4429f92426fde269265fd90748a51900c6e6adac'
source_table_sha=hashlib.sha256(cpu['tracked-source.before.json']).hexdigest()
source_git_summary={'rows':len(rows),'bytes':sum(r['size_bytes'] for r in rows),
 'original_table_sha256':source_table_sha,'canonical_table_sha256':canonical_sha(expected_tracking),
 'mode_path_object_size_sha_rows_canonical_sha256':canonical_sha(rows),
 'modes':{m:sum(r['mode']==m for r in rows) for m in sorted({r['mode'] for r in rows})},
 'all_raw_Git_blob_SHA1_and_SHA256_verified':True,'managed_HEAD_before_after':commit,
 'managed_production_test_CI_spec_source_diff_from_D_empty':True,
 'current_dirty_progress_docs_outside_exact_D_CI_scope':dirty_paths,'current_raw_diff_sha256':hashlib.sha256(git_diff).hexdigest(),'git_commands':git_commands,'Git_batch_EOF_returncode0_and_reader_closed':True}
assert hashlib.sha256(needed[selection['manifest_path']]).hexdigest()==selection['manifest_sha256']

asset_manifest=json.loads(needed['.ci/model-assets.v1.json'])
acquisition_reviews={}
with zipfile.ZipFile(io.BytesIO(read(ROOT/archive_rows['cpu']['path']))) as archive:
    for factory,value in report['gstreamer_factories'].items():
        raw=archive.read('factory-'+factory+'.stdout')
        assert len(raw)==value['stdout_size_bytes'] and hashlib.sha256(raw).hexdigest()==value['stdout_sha256']
    binaries=['build/bin/vast_native_gst_probe','build/bin/vast_checkpoint_source',
              'build/lib/libgstadaptivescheduler.so','build/lib/libgstvastanalyticsterminal.so',
              'build/lib/libgstvastanalyticsqueue.so','build/lib/libgstvastcheckpointprefixqueue.so']
    for name in binaries:
        assert archive.read(name)[:4]==b'\x7fELF'
for lane,members in archives.items():
    acquisition=member_json(members,'model-acquisition/report.json')
    assert acquisition['status']=='complete' and acquisition['requires_original_exit_zero'] is True
    assert acquisition['hardware_acceptance'] is False and len(acquisition['assets'])==8
    assert [r['index'] for r in acquisition['assets']]==list(range(8))
    command_ok(member_json(members,'model-assets.json'))
    for pin in acquisition['inputs']:
        assert tracking[pin['path']]=={k:pin[k] for k in ('size_bytes','sha256')}
    for actual,expected in zip(acquisition['assets'],asset_manifest['assets']):
        assert actual['status']=='downloaded'
        assert {k:actual[k] for k in ('path','size_bytes','sha256','sha384')} == {k:expected[k] for k in ('path','size_bytes','sha256','sha384')}
        index=actual['index'];base='model-acquisition/asset-'+format(index,'02d')
        dispatch=member_json(members,base+'.dispatch.json')
        terminal_asset=member_json(members,base+'.terminal.json')
        detail=member_json(members,base+'.json')
        assert terminal_asset['returncode']==0 and terminal_asset['timed_out'] is False
        assert dispatch['started_monotonic'] <= detail['started_monotonic'] and terminal_asset['elapsed_s']>=detail['elapsed_s']
        assert dispatch['started_monotonic']+terminal_asset['elapsed_s'] <= dispatch['deadline_monotonic']
        assert dispatch['inputs']==acquisition['inputs'] and detail['asset']==expected
        assert detail['index']==index and detail['status']=='downloaded' and detail['http_status']==200
        assert detail['publication_attempted'] is True and detail['publication_observed'] is True
        for key in ('completed_write_bytes','hashed_prefix_bytes','received_bytes','original_file_observed_bytes'):
            assert detail[key]==actual['size_bytes']
        assert detail['received_prefix_sha256']==actual['sha256'] and detail['received_prefix_sha384']==actual['sha384']
        assert terminal_asset['child_inherits_original_group'] is True and terminal_asset['child_pgid']==terminal_asset['outer_pgid']
    acquisition_reviews[lane]={'original':acquisition,'actual8dispatch_terminal_detail_joins':True,'all8downloaded':True}
host_test_log=None
with zipfile.ZipFile(io.BytesIO(read(ROOT/archive_rows['host']['path']))) as archive:
    host_test_log=archive.read('host-prerequisites.stderr')
assert b'Ran 2 tests' in host_test_log and b'OK' in host_test_log
for test_id in host_report['test_ids']:
    method=test_id.rsplit('.',1)[1]
    assert method.encode() in host_test_log
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
assert ('Ran ' + str(selected_count) + ' tests').encode() in test_raw
assert (('OK (skipped=' + str(skip_count) + ')').encode() in test_raw if skip_count else b'OK' in test_raw)

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
assert join['audit_clock_bracket_ns'] == bins and bins[0] <= audit_ns <= bins[1]
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
assert all(type(observer[k]) is int and observer[k] >= 0 for k in ('requests_sent', 'responses_started', 'responses_completed'))
assert observer['requests_sent'] >= observer['responses_started'] == observer['responses_completed']
assert observer['unmatched_or_coalesced_requests_possible'] == observer['requests_sent'] - observer['responses_started']
assert observer['response_matching'] == 'ordinary signals may coalesce; no one-to-one or timely claim'
assert observer['requests_stopped_before_disposition_restore'] is True


observer_events=[json.loads(line) for line in cpu['external-test-observer/events.original.jsonl'].splitlines()] if 'external-test-observer/events.original.jsonl' in cpu else None
with zipfile.ZipFile(io.BytesIO(read(cpu_zip_path))) as archive:
    observer_event_raw=archive.read('external-test-observer/events.original.jsonl')
    trace_raw=archive.read('external-test-observer/trace.original.log')
events=[json.loads(line) for line in observer_event_raw.splitlines()]
sent=[e for e in events if e['event']=='request_sent']
responses=[e for e in events if e['event']=='response_received']
ready_events=[e for e in responses if e['response']['event']=='ready']
response_starts=[e for e in responses if e['response']['event']=='response_started']
response_finishes=[e for e in responses if e['response']['event']=='response_finished']
assert len(ready_events)==1 and len(sent)==observer['requests_sent']==24
assert len(response_starts)==observer['responses_started']==24 and len(response_finishes)==observer['responses_completed']==24
assert [e['request_seq'] for e in sent]==list(range(1,25))
assert [e['response']['response_ordinal'] for e in response_starts]==[e['response']['response_ordinal'] for e in response_finishes]==list(range(1,25))
for beginning,ending in zip(response_starts,response_finishes):
    assert beginning['response']['child_monotonic_ns']<=ending['response']['child_monotonic_ns']
    assert ending['response']['dump_failed'] is False
assert len(trace_raw)==observer['trace_bytes'] and ready_events[0]['response']['pid']==observer['owner']['pid']
timing=[e for e in events if e['event']=='response_timing']
assert len(timing)==24 and all(e['timely_response_claim'] is False for e in timing)
# Exact Git modes are joined separately from source byte table; none is inferred from the table.
for lane,row in archive_rows.items():
    job_id=cpu_id if lane=='cpu' else host_id
    log_row=next(r for r in terminal['originals'] if r.get('job_id')==job_id) if any(r.get('job_id')==job_id for r in terminal['originals']) else next(r for r in terminal['originals'] if r['path'].endswith('job-'+str(job_id)+'.original.log'))
    log=read(ROOT/log_row['path'],32*1048576)
    assert commit.encode() in log and b'Complete job' in log
    assert ('sha256:'+row['sha256']).encode() in log or row['sha256'].encode() in log
assert all(v['monotonic_ns']>=starts[k]['monotonic_ns'] for k,v in finishes.items())
earliest_test_ns=min(v['monotonic_ns'] for v in starts.values())
assets_last=max(member_json(cpu,'model-acquisition/asset-'+format(i,'02d')+'.dispatch.json')['started_monotonic']+
                member_json(cpu,'model-acquisition/asset-'+format(i,'02d')+'.terminal.json')['elapsed_s'] for i in range(8))
assert assets_last*1000000000 < earliest_test_ns
assert report['elapsed_s'] == 1537.8427825239999
for path,pin in list(read_pins.items()):
    assert descriptor(path,read(path,32*1048576))==pin

def control_pin(lane,name):
    return {'original_zip':read_pins[ROOT/archive_rows[lane]['path']],
            'original_member':next(r for r in archive_rows[lane]['members'] if r['name']==name)}
result={'schema_version':1,'kind':'exact_D_original_source_CI_acceptance','reviewer':'/root/final_release_review',
 'change':'run-finite-component-study','pull_request':'https://github.com/lordcoudy/VAST/pull/5',
 'status':'PASS_SOURCE_CI_ONLY','reviewable':True,'blocking_findings':[],'reviewer_handles_released':True,
 'source_commit':commit,'run_id':run_id,'run_number':72,'run_attempt':1,
 'CPU_job_id':cpu_id,'host_job_id':host_id,'provider_status':'completed','provider_conclusion':'success',
 'jobs':[{k:jobs[i][k] for k in ('id','name','status','conclusion','started_at','completed_at')} for i in (cpu_id,host_id)],
 'original_retention_terminal':read_pins[directory/'original-retention-terminal.v1.json'],
 'original_provider_metadata':read_pins[metadata_path],
 'retainer_source':read_pins[HERE.parent/'retain_originals_v1.py'],
 'retainer_genuine_original_tool_records':read_pins[HERE.parent/'retention.original-tools.json'],
 'retainer_actual_tool_ids':['4bb138','68dc13'],'retainer_no_extra_invocation_by_reviewer':True,
 'originals':originals,'verified_archives':[{k:v for k,v in r.items() if k!='members'} for r in archive_reviews],
 'all253member_descriptor_canonical_sha256':canonical_sha([r for a in archive_reviews for r in a['members']]),
 'required_controls':[control_pin(lane,name) for lane,names in {
   'cpu':['report.json','unittest-child.report.json','tracked-source.before.json','tracked-source.after.json',
          'unittest.original.log','namespace-profile/profile-lifecycle.json','external-test-observer/terminal.v1.json',
          'external-test-observer/events.original.jsonl','namespace-profile/joined-denial.json','model-acquisition/report.json'],
   'host':['report.json','tracked-source.before.json','tracked-source.after.json','host-prerequisites.json','host-prerequisites.stderr','model-acquisition/report.json']
 }.items() for name in names],
 'tests':{'discovered':3110,'selected':3101,'success':3013,'skip':88,'deferred_integration':9,
   'failure':0,'error':0,'expected_failure':0,'unexpected_success':0,'missing_required':0,
   'all3101unique_starts_terminals_actual_outcomes_joined':True,'elapsed_s':report['elapsed_s'],
   'all6prior_errors_now_original_success':residual,'all8original_fixture_ids_discovered':fixtures,
   'two_unchanged_original_GST_fixture_integration_deferrals':deferred_fixture_ids,
   'required_native3_success':REQUIRED},
 'selection':{'baseline_C_exact_ordered_discovery_portable_allowlist_and9declarations_preserved':True,
   'manifest_path':selection['manifest_path'],'manifest_sha256':selection['manifest_sha256'],
   'all88exact_skip_ID_reason_scope_joins':True,'skip_audit_canonical_sha256':canonical_sha(child['portable_skip_audit']),
   'nine_original_declarations':selection['integration_declarations'],'integration_executed':False},
 'source':source_git_summary,'native_build':{'targets':TARGETS,'six_ELF_outputs_verified':binaries,
    'controls':command_controls,'python_syntax_files':len(report['python_syntax']),
    'bash_syntax_files':len(report['bash_syntax']),'packages':report['packages'],
    'factories_original_stdout_SHA_size_joined':['appsrc','queue','videoconvert']},
 'model_assets':{'CPU_and_host_original8_downloads_hash_size_dispatch_terminal_detail_verified':True,
    'total_asset_bytes_per_lane':sum(r['size_bytes'] for r in acquisition_reviews['cpu']['original']['assets']),
    'asset_manifest_sha256':tracking['.ci/model-assets.v1.json']['sha256'],
    'all_CPU_asset_terminals_precede_test_starts':True,'original_asset_rows':acquisition_reviews['cpu']['original']['assets']},
 'clock_profile_observer':{'coarseclock_kerneldenial_original_join_verified':True,
   'profile_name':profile['name'],'profile_load_unload_verified_and_held_FDs_released':True,
   'observer':observer,'all24request_response_start_finish_raw_events_joined':True,
   'no_forced_TERM_KILL':True,'both_control_trace_EOF':True,'profile_child_label_verified':True},
 'host':{'original_report':host_report,'actual2test_outcomes_in_original_stderr_and_exit0':True,
    'full_ci_successful_retained_false':True,'hardware_acceptance_retained_false':True},
 'CI_accepted':True,'source_CI_gate_closed':True,'physical_preparation_accepted':False,'hardware_accepted':False,
 'full_qualification_accepted':False,'scientific_acceptance':False,'release_approved':False,'merge_ready':False,
 'reader_process_history':{'actual_reader01':'75a0c4','exit_code':1,
    'source_pin':read_pins[HERE/'review_D_originals_v1.py'],
    'cause':'Overbroad extra current checkout empty predicate rejected four root-owned progress docs after exact-D original source/Git joins had passed; reader02 records progress docs outside exact-D CI scope, without weakening any original-D acceptance.',
    'target_or_CI_replayed':False},
 'historical_failures_preserved':['A09562f7 FAILED','B full hosted failures remain FAILED','C81492fb1 FAILED six errors',
    'local broader fragment GREEN01 FAILED','genuine REDs remain RED'],
 'criteria_disposition':'Prepared eight fixture ID criterion clarified from actual unchanged selection: six portable original successes plus two historical integration deferrals; no required selected method waived.',
 'scope_limits':['Only stdlib readers and bounded read-only Git object commands ran. No project import, tests, hosted command, model inference, engine/GI/physical prep/pilot/effect/research was executed by reviewer.',
   'CPU hardware_acceptance false and original hardware gaps remain explicit. Nine deferrals and88approved skips do not prove their behavior.',
   'Hosted assets are original producer hash/download facts; model bodies and interpreter/plugin backing binaries are not contained in the retained ZIP. Their byte claims cannot be independently rehashed locally.',
   'Observer original-child exit/EOF/owned profile retirement does not establish global or unknown descendant quiescence or a numeric FD inventory.',
   'Current source/CI gate permits subsequent separately controlled physical preparation. Physical build/reference/material/readiness, pilot/effects/reduction/closure, conformance/archive/latest CI/final release gates remain separate.',
   'Earlier broad schema locator output was truncated; acceptance-critical fields were subsequently evaluated from complete actual original bytes inside this finite reader.'],
 'elapsed_s':time.monotonic()-START}
raw=(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
assert len(raw)<256*1048576; clock()
path=HERE/'review.v1.json'
with path.open('xb') as stream:
    assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
print(json.dumps({'review':descriptor(path,raw),'status':result['status'],'reviewable':True,
                 'counts':result['tests'],'source':source_git_summary,'elapsed_s':result['elapsed_s']},sort_keys=True),flush=True)

