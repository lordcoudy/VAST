"""Close finite selector safeguard source/test evidence; no discovery or workload."""
from pathlib import Path
import ast
import difflib
import hashlib
import json
import os

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).parent
CAPTURE=HERE.with_name('decision25-ci-selection-v1')
def pin(path):
    raw=path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
green_path=CAPTURE/'safeguards-green-02/terminal.v1.json'
green=json.loads(green_path.read_bytes())
assert green['original_child_returncode']==0 and green['sources_stable']
assert green['source_before']==green['source_after']
for name,value in green['source_after'].items():
    current=pin(ROOT/name)
    assert current['sha256']==value['sha256'] and current['size_bytes']==value['size_bytes']
assert b'Ran 20 tests' in (CAPTURE/'safeguards-green-02/stderr.raw').read_bytes()
for name,value in green['outputs'].items():
    current=pin(CAPTURE/'safeguards-green-02'/(name+'.raw'))
    assert current['sha256']==value['sha256'] and current['size_bytes']==value['size_bytes']
manifest=ROOT/'.ci/integration-test-selection.v1.json'
assert pin(manifest)['sha256']=='a27ff9488d658637e16e81d0a6b6614ce9ac43716b7dd5b152060a2cb093c987'
document=json.loads(manifest.read_bytes())
source=ROOT/'scripts/ci_test_selection_v1.py'
tree=ast.parse(source.read_text())
# Evaluate only the constant declarations using a restricted namespace.
declarations=[n for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)
              and n.targets[0].id in {'RUNTIME_SAFETY_MODULES','RETIRED_MIGRATION_IDS'}]
constants={}
exec(compile(ast.Module(body=declarations,type_ignores=[]),'<reviewed constants>','exec'),
     {'frozenset':frozenset,'__builtins__':{}},constants)
safety=constants['RUNTIME_SAFETY_MODULES'];retired=constants['RETIRED_MIGRATION_IDS']
assert len(safety)==35 and all((ROOT/'tests'/(name+'.py')).is_file() for name in safety)
assert len(retired)==10 and retired=={r['test_id'] for r in document['allowed_portable_skips']
                                    if r['classification']=='existing_retired_schema_migration'}
assert not safety & {r['test_id'].split('.',1)[0] for r in document['integration_declarations']}
assert not safety & {r['test_id'].split('.',1)[0] for r in document['allowed_portable_skips']}
test=ROOT/'tests/test_ci_test_selection_v1.py'
oldtree=ast.parse((HERE/'before/test_ci_test_selection_v1.py').read_text())
newtree=ast.parse(test.read_text())
def methods(tree):
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SelectionContracts')
    return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,ast.FunctionDef)}
old_methods,new_methods=methods(oldtree),methods(newtree)
assert all(name in new_methods for name in old_methods)
assert all(old_methods[name]==new_methods[name] for name in old_methods
           if name!='test_existing_retired_source_decorator_is_inventory_nonexecution_only')
for path in (source,test):
    before=(HERE/'before'/path.name).read_text()
    diff=''.join(difflib.unified_diff(before.splitlines(True),path.read_text().splitlines(True),
                                     fromfile='before/'+path.name,tofile=path.relative_to(ROOT).as_posix()))
    with (HERE/(path.name+'.diff')).open('x') as stream:stream.write(diff)
value={'schema_version':1,'artifact_kind':'vast_decision25_ci_selector_safeguards_author_review_v1',
 'reviewable':True,'independent_review':False,
 'approved_planning_commit':'bec47b794ef9183fe9e3ce4cb1ec15541070f96f',
 'owned_final':[pin(source),pin(test)],'manifest_unchanged':pin(manifest),
 'before_inventory':pin(HERE/'before/inventory.json'),
 'original_green':{**pin(green_path),'tests':20,'original_returncode':0,
    'source3_before_after_equal':True,'original_group_members':green['original_group_members'],
    'capture_elapsed_s':green['elapsed_s'],'raw_stderr':pin(CAPTURE/'safeguards-green-02/stderr.raw')},
 'original_red':[pin(CAPTURE/name/'terminal.v1.json') for name in ('safeguards-red-01','safeguards-red-02','safeguards-red-03')],
 'behavior':{'finite_safety_modules':sorted(safety),'finite_module_count':35,
     'integration_deferral_forbidden':True,'new_skip_declarations_forbidden':True,
     'original_retired_ids':sorted(retired),'retired_source_decorator_required':True,
     'original_integration_declarations':9,'original_skip_declarations':80,
     'existing_skip_ids_and_reasons_unchanged':True,'case_objects_and_order_retained':True,
     'all_other_original_method_AST_identical':True,'new_unit_methods':4,
     'old_positive_fixture_change':'Replace synthetic legacy ID with one exact original tombstone ID; decorator and nonexecution assertions retained.'},
 'self_review':['The finite module inventory can require reviewed maintenance when a new safety module is added; every undeclared test remains mandatory by default.',
    'Tests use original method identity strings with explicit TestCase metadata fixtures. No broker/raw/component/native method body or namespace work is run by these selection tests.',
    'Initial RED01 included one synthetic raw method coordinate; source-only inspection corrected the raw/skip coordinates to actual existing methods before RED02. All original failures remain retained.',
    'The original80 skip audit proves unchanged metadata/nonexecution, not80 passing tests. Full-host conformance and retired10 disposition remain separate.',
    'Reviewer now authors these2files after identifying gaps; a parent-independent source review is required. Earlier partialreview2ea522 is not final approval of these new bytes.'],
 'tests_run_by_author':20,'default_discovery_invoked':False,'engine_queries':0,
 'namespace_calls':0,'model_calls':0,'hardware_acceptance':False}
with (HERE/'author-review.v1.json').open('xb') as stream:
    stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
print(json.dumps(pin(HERE/'author-review.v1.json')))
