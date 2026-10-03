"""Finite read-only peer audit; no project imports, tests or engine calls."""
import ast, hashlib, json, os, stat, time
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
OUT = Path(__file__).parent
held = {}
def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
def read(path):
    p = Path(path)
    if not p.is_absolute(): p = ROOT / p
    if p not in held:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        s = os.fstat(fd)
        assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 2*1024*1024
        raw = os.read(fd, s.st_size + 1)
        assert len(raw) == s.st_size and epoch(s) == epoch(p.lstat()) == epoch(os.fstat(fd))
        held[p] = (fd, epoch(s), raw)
    return held[p][2]
def desc(p):
    raw = read(p)
    p = Path(p)
    return {'path': str(p.relative_to(ROOT) if p.is_absolute() else p), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
def doc(p): return json.loads(read(p))
def physical(d):
    actual = desc(d['path'])
    assert actual['size_bytes'] == d['size_bytes'] and actual['sha256'] == d['sha256']
    return actual
def assignments(raw, names):
    return {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(raw).body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names}
renewal = doc(BASE/'component-host-image-binding-renewal-v3/renewal.v1.json')
before = read(BASE/'component-host-image-binding-renewal-v3/original-host-wrapper.raw')
current = read('scripts/checkpoint_gstreamer_publication_runtime_v3.py')
names = set(renewal['renewed_constants'])
assert len(names) == 6
old_values = assignments(before, names); new_values = assignments(current, names)
assert new_values == renewal['renewed_constants']
def without_bindings(raw):
    tree = ast.parse(raw)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in names)]
    return ast.dump(tree, include_attributes=False)
assert without_bindings(before) == without_bindings(current)
pairs = [(old_values[k], new_values[k]) for k in ('EXPECTED_IMAGE_REFERENCE','EXPECTED_IMAGE_ID','EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256')]
pairs.append((old_values['EXPECTED_IMAGE_LABELS']['org.vast.runtime-source-sha256'],new_values['EXPECTED_IMAGE_LABELS']['org.vast.runtime-source-sha256']))
inverse = current
for old, new in pairs: inverse = inverse.replace(new.encode(), old.encode())
assert inverse == before
old_test = read(BASE/'component-host-image-binding-renewal-v3/original-runtime-test.raw')
new_test = read('tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py')
inverse_test = new_test
for old, new in pairs[:3]: inverse_test = inverse_test.replace(new.encode(), old.encode())
assert inverse_test == old_test
receipt = doc(renewal['receipt']['path']); physical(renewal['receipt'])
physical_identity = receipt['physical_identity']
assert receipt['candidate_binding_eligible'] is True and receipt['blockers'] == []
assert new_values['EXPECTED_IMAGE_ID'] == physical_identity['image_id']
assert new_values['EXPECTED_REPOSITORY_DIGEST'] == physical_identity['canonical_repository_digest']
assert new_values['EXPECTED_IMAGE_REFERENCE'] == physical_identity['final_reference']
assert new_values['EXPECTED_IMAGE_LABELS'] == physical_identity['labels']
assert new_values['EXPECTED_EMBEDDED_ARTIFACTS'] == physical_identity['embedded_files']
assert len(physical_identity['labels']) == 9 and len(physical_identity['embedded_files']) == 11
build = BASE/'selected-gstreamer-build-a4e145b7-v1'; packaged = BASE/'selected-gstreamer-packaged-a4e145b7-v1'
build_op = doc(build/'operation.terminal.v1.json'); packaged_op = doc(packaged/'operation.terminal.v1.json')
for directory, operation in ((build,build_op),(packaged,packaged_op)):
    assert operation['failure'] is None and operation['accepted'] is False and operation['publication_ready'] is False
    for d in operation['commands']:
        physical(d); command = doc(d['path'])
        physical(command['stdout']); physical(command['stderr'])
assert packaged_op['exact_owned_remove_completed'] and packaged_op['exact_cid_and_name_absence_after_remove']
state = packaged_op['original_observed_state']
assert state['ExitCode']==0 and state['Running'] is False and state['Pid']==0 and state['OOMKilled'] is False
assert state['Image']==physical_identity['image_id']
images = doc(build/'image-after.stdout.raw'); assert len(images)==3
def projection(image):
    c=image['Config']
    return {'Id':image['Id'],'RepoDigests':sorted(image['RepoDigests']),'Architecture':image['Architecture'],
            'Os':image['Os'],'Created':image['Created'],'Config':{'Entrypoint':c['Entrypoint'],'User':c['User'],'Labels':{k:c['Labels'][k] for k in sorted(new_values['EXPECTED_IMAGE_LABELS'])}}}
for image in images:
    assert image['Id']==physical_identity['image_id'] and image['RepoDigests']==[new_values['EXPECTED_REPOSITORY_DIGEST']]
    digest=hashlib.sha256(json.dumps(projection(image),sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()
    assert digest == new_values['EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256']
focused_path=BASE/'component-host-image-binding-renewal-focused-v1/attempt03-new-schema-image/execution.json'
focused=doc(focused_path)
assert focused['returncode']==0 and not focused['timed_out'] and focused['source_before_after_equal']
assert focused['quiescence']=={'original_group_absent':True,'original_pid_absent':True}
assert focused['dispatch']['before']==focused['after'] and len(focused['after'])==20
for path,d in focused['after'].items(): assert desc(path)['sha256']==d['sha256'] and desc(path)['size_bytes']==d['size_bytes']
for leaf,d in focused['outputs'].items():
    actual=desc(focused_path.parent/leaf); assert actual['sha256']==d['sha256'] and actual['size_bytes']==d['size_bytes']
assert b'Ran 23 tests' in read(focused_path.parent/'stderr.bin') and read(focused_path.parent/'stderr.bin').rstrip().endswith(b'OK')
assert b'Ran 19 tests' in read(packaged/'packaged-component-front.stderr.raw')
cpu03=BASE/'selected-gstreamer-cpu03-controller-preparation-v1/run_original_cpu_component_pair_v1.py'
cpu04=BASE/'selected-gstreamer-cpu04-controller-preparation-v1/run_original_cpu_component_pair_v1.py'
old=read(cpu03); new=read(cpu04); restored=new
for a,b in [('V4','V5'),('v4','v5'),('cpu-pair-03','cpu-pair-04'),('a3e976d0','a4e145b7'),
            (old_values['EXPECTED_IMAGE_ID'],new_values['EXPECTED_IMAGE_ID']),
            ('7807fc43cf4f706d2756baefcbdd4887798b04168db06f7acbdbea4a8541cc8c',renewal['receipt']['sha256'])]:
    restored=restored.replace(b.encode(),a.encode())
assert restored == old
assert not os.path.lexists(ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04')
assert not os.path.lexists(ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04-original-controller')
capture=BASE/'capture_selected_host_closure_v5.py'; read(capture)
assert 'scripts/checkpoint_gstreamer_publication_runtime_v3.py' not in read('deploy/gstreamer_custom/publication/runtime-source-allowlist.txt').decode().splitlines()
for p,(fd,e,raw) in held.items():
    assert epoch(os.fstat(fd))==e==epoch(p.lstat())
    os.lseek(fd,0,os.SEEK_SET); assert os.read(fd,len(raw)+1)==raw
report={'schema_version':1,'artifact_kind':'vast_independent_selected_host_renewal_review_v1',
 'disposition':'approved_scoped_source_renewal_and_unexecuted_cpu04_preparation','reviewable':True,'independent_review':True,
 'reviewed_at_ns':time.time_ns(),'source_pins':[desc(p) for p in ('scripts/checkpoint_gstreamer_publication_runtime_v3.py','tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py')],
 'evidence_pins':[desc(p) for p in (build/'operation.terminal.v1.json',packaged/'operation.terminal.v1.json',ROOT/renewal['receipt']['path'],focused_path,cpu03,cpu04,capture)],
 'checks':['six static assignments match original rebuilt image receipt; all other AST and inverse raw bytes unchanged',
 'three test literals only; inverse raw bytes preserve CRLF and every assertion',
 'retained final/A/B inspect exact image ID, single RepoDigest, stock projection digest, nine labels and eleven embedded bindings',
 'original23 local tests exit0, twenty source witnesses stable and original process/group quiescence retained',
 'original19 packaged fixture gate exit0; stopped0/Pid0/OOMfalse, exact owned removal then CID/name absence',
 'CPU04 inverse raw equals CPU03 after exact binding literals only; original2250/2100/15 deadlines and1MiB channels unchanged; output namespaces absent'],
 'held_input_count':len(held),'limits':['No reviewer test, engine query or workload executed.',
 'The first read-only audit exited1 at projection equality because it used the generic builder projection rather than the runtime/refreeze projection; original audit bytes preserved, original tool traceback not saved as a physical log.',
 'New actual stock host closure v5 must be captured and joined before the one CPU04 dispatch; historical v4 supplies path inventory only.',
 'The host wrapper is excluded from selected runtime allowlist; renewal alone does not invalidate the rebuilt image.',
 'This review grants no aggregate model parity rebinding, benchmark or scientific acceptance.'],
 'audit_source':desc(Path(__file__))}
raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'review.v1.json').open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
for fd,_,_ in held.values(): os.close(fd)
print(json.dumps({'path':str(OUT/'review.v1.json'),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'disposition':report['disposition']}))
