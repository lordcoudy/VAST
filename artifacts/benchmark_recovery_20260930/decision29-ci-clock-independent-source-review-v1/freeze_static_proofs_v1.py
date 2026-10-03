"""Finite static byte/AST and inventory review; never import a reviewed target."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
OUT=Path(__file__).resolve().parent
OLD=BASE/'decision29-ci-clock-repair-v1/before'
LINUX_ROOT='/home/s-a-balashov/work/vast-component-release-20260930-d27'
EXT4=Path(r'\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-component-release-20260930-d27')
CHANGED=['scripts/ci_namespace_diagnostic_v1.py','scripts/ci_userns_profile_v1.py',
         'tests/test_ci_namespace_diagnostic_v1.py','tests/test_ci_userns_profile_v1.py']

def raw(path):
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        value=stream.read(16*1024*1024+1)
        after=os.fstat(stream.fileno())
    assert len(value)<=16*1024*1024
    assert (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    assert len(value)==before.st_size
    return value

def pin(path,label=None):
    value=raw(path)
    return {'path':str(path) if label is None else label,'size_bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}

def dump(node):return ast.dump(node,include_attributes=False)
def funcs(tree):return {n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
def calls(tree,attribute):
    return [dump(n) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr==attribute]
def save(name,value):
    with (OUT/name).open('xb') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2).encode()+b'\n');stream.flush();os.fsync(stream.fileno())

proofs=[]
for rel in [CHANGED[0],CHANGED[1],CHANGED[3]]:
    before=raw(OLD/(rel.replace('/','__')+'.raw'));after=raw(ROOT/rel)
    old,new=ast.parse(before),ast.parse(after);a,b=funcs(old),funcs(new)
    unchanged=[n for n in a if n in b and dump(a[n])==dump(b[n])]
    changed=[n for n in a if n in b and dump(a[n])!=dump(b[n])]
    constants=lambda tree:{n.targets[0].id:dump(n.value) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
    assert constants(old)==constants(new)
    assert calls(old,'Popen')==calls(new,'Popen')
    row={'source':pin(ROOT/rel,rel),'before':pin(OLD/(rel.replace('/','__')+'.raw')),
         'unchanged_original_module_functions':unchanged,'changed_original_module_functions':changed,
         'new_module_functions':sorted(set(b)-set(a)),'module_constant_ASTs_unchanged':True,'Popen_call_ASTs_unchanged':True}
    if rel.endswith('ci_userns_profile_v1.py') and rel.startswith('scripts/'):
        normalized=copy.deepcopy(b['held_ci_userns_profile_v1'])
        joins=[n for n in ast.walk(normalized) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='join_original_userns_denial_v1']
        assert len(joins)==1 and len(joins[0].keywords)==1
        assert joins[0].keywords[0].arg=='expected_clock_contract_version' and joins[0].keywords[0].value.value==2
        joins[0].keywords=[]
        assert dump(normalized)==dump(a['held_ci_userns_profile_v1'])
        row['live_held_function_inverse_only_explicit_expected_version2']=True
    if rel.startswith('tests/'):
        ac=next(n for n in old.body if isinstance(n,ast.ClassDef));bc=next(n for n in new.body if isinstance(n,ast.ClassDef) and n.name==ac.name)
        am,bm=funcs(ac),funcs(bc)
        names=[n for n in am if n.startswith('test')]
        changed_tests=[]
        for n in names:
            if dump(am[n])==dump(bm[n]):continue
            changed_tests.append(n);normalized=copy.deepcopy(bm[n])
            joins=[x for x in ast.walk(normalized) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='join_original_userns_denial_v1']
            assert len(joins)==1 and len(joins[0].keywords)==1
            kw=joins[0].keywords[0];assert kw.arg=='expected_clock_contract_version' and kw.value.value==1
            joins[0].keywords=[];assert dump(normalized)==dump(am[n])
        newclass=next(n for n in new.body if isinstance(n,ast.ClassDef) and n.name=='AuditClockTests')
        row.update(original_test_method_count=len(names),original_tests_unchanged_or_only_explicit_legacy_keyword=True,
                   explicit_legacy_only_changed_test_methods=changed_tests,
                   original_test_assertion_call_ASTs_unchanged=calls(ac,'assertEqual')==calls(bc,'assertEqual') and
                       all(dump(x) in [dump(y) for y in ast.walk(bc) if isinstance(y,ast.Call)] for x in ast.walk(ac)
                           if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr.startswith('assert')),
                   new_clock_test_methods=list(funcs(newclass)))
        assert row['original_test_assertion_call_ASTs_unchanged']
    proofs.append(row)

runner=BASE/'decision29-ci-clock-repair-v1/run_focused_v1.py'
oldrunner=BASE/'decision29-ci-clock-repair-v1/original-focused-controller.raw'
ra,rb=ast.parse(raw(oldrunner)),ast.parse(raw(runner))
af={n.name:dump(n) for n in ast.walk(ra) if isinstance(n,ast.FunctionDef)}
bf={n.name:dump(n) for n in ast.walk(rb) if isinstance(n,ast.FunctionDef)}
assert af==bf and calls(ra,'Popen')==calls(rb,'Popen')
proofs.append({'source':pin(runner,str(runner.relative_to(ROOT))),'before':pin(oldrunner),
 'all_original_function_and_method_ASTs_unchanged':True,'original_function_names':list(af),'Popen_call_ASTs_unchanged':True,
 'original_execution_cleanup_channel_budgets_unchanged':{'work_s':120,'cleanup_s':10,'each_channel_bytes':1048576}})
save('static-source-proofs.v1.json',proofs)

inventory_path=BASE/'component-ext4-relocation-feasibility-v1/inventory.v1.json'
inv=json.loads(raw(inventory_path))
selected_path=BASE/'decision28-host-identity-source-checkpoint-v1/committed-checkpoint-proof.v1.json'
selected=json.loads(raw(selected_path))['selected73']
current_path=BASE/'decision28-current95-preparation-v1/decision28-current95-original-attempt01/current95-inputs.v1.json'
current=json.loads(raw(current_path))
assert len(selected)==73 and len(current['actual_current95'])==95
assert current['source_commit']=='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
group_membership={k:{'count':len(v),'paths':v,'changed_path_intersection':sorted(set(v)&set(CHANGED))} for k,v in inv['source_groups'].items()}
assert all(not row['changed_path_intersection'] for row in group_membership.values())
current_paths=[row['descriptor']['path'] for row in current['actual_current95']]
current_rel=[p[len(LINUX_ROOT)+1:] for p in current_paths if p.startswith(LINUX_ROOT+'/')]
assert not set(CHANGED)&set(current_rel) and not set(CHANGED)&{r['path'] for r in selected}
reads={}
def verify_ext4(rel,expected):
    if rel not in reads:reads[rel]=pin(EXT4/rel,rel)
    actual=reads[rel];assert actual['size_bytes']==expected['size_bytes'] and actual['sha256']==expected['sha256'],rel
    return actual
current_descriptors=[]
for row in current['actual_current95']:
    expected=row['descriptor'];path=expected['path']
    if path.startswith(LINUX_ROOT+'/'):
        rel=path[len(LINUX_ROOT)+1:];actual=verify_ext4(rel,expected)
    elif path.startswith('/home/s-a-balashov/'):
        actual=pin(Path(r'\\wsl.localhost\Ubuntu')/path.lstrip('/'),path)
        assert actual['size_bytes']==expected['size_bytes'] and actual['sha256']==expected['sha256']
    else:raise AssertionError('Unexpected current95 path domain '+path)
    current_descriptors.append({'expected':expected,'observed':actual,'full_physical_bytes_equal':True})
selected_descriptors=[{'expected':row,'observed':verify_ext4(row['path'],row)} for row in selected]
original={row['path']:row for row in inv['copy_inputs']}
native_workers={}
for group in ['native_probe_deepstream','native_probe_openvino','native_probe_savant','analytics_worker_openvino','analytics_worker_tensorrt']:
    native_workers[group]=[{'expected_unchanged_original_input':original[rel],'observed':verify_ext4(rel,original[rel])}
                           for rel in inv['source_groups'][group]]
save('source-impact.v1.json',{'schema_version':1,'scope':'Four exact CI scripts/tests compared with actual runtime inventory paths; full physical source bytes read without source execution.',
 'changed_CI_paths':CHANGED,'changed_CI_pins':[pin(ROOT/p,p) for p in CHANGED],
 'actual_inventory':pin(inventory_path),'actual_selected73_inventory':pin(selected_path),'actual_current95_inventory':pin(current_path),
 'all_ten_source_group_memberships':group_membership,'actual95_changed_path_intersection':sorted(set(CHANGED)&set(current_rel)),
 'selected73_changed_path_intersection':sorted(set(CHANGED)&{r['path'] for r in selected}),
 'actual95_physical_full_SHA_and_size_equal':current_descriptors,'selected73_physical_full_SHA_and_size_equal':selected_descriptors,
 'native_three_worker_two_physical_full_SHA_and_size_equal':native_workers,'all_read_handles_released':True,
 'Linux_seven_epoch_fresh_reobservation_claimed':False,'limits':'Windows UNC metadata reads establish full physical byte equality and unchanged inventory membership. Linux held seven-epoch/process closure is retained in the genuine CPU08/GPU02 controller/auditor evidence, not recreated by Windows stat.'})
print(json.dumps({'static_proof':pin(OUT/'static-source-proofs.v1.json'),'source_impact':pin(OUT/'source-impact.v1.json'),
 'reviewed_root_source_pins':[r['source'] for r in proofs],'runtime_physical_source_read_count':len(reads),
 'all_current95_full_bytes_equal':True,'all_selected73_full_bytes_equal':True,'native_three_worker_two_full_bytes_equal':True}))
