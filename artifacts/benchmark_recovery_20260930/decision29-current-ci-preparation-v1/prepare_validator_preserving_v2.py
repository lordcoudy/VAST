"""Preserve author v1 and fix only its overlapping-map predicate merge; no target execution."""
import ast
import hashlib
import json
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent
LINUX='/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-current-ci-preparation-v1'
def pin(path):
    raw=path.read_bytes();return {'path':LINUX+'/'+path.name,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def write(name,raw):
    with (HERE/name).open('xb') as stream:assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
    return pin(HERE/name)
def functions(raw):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}
old_setup=(HERE/'setup_original_current_ci_v1.py').read_bytes()
before="    for relative,pin in {**recipe['source_pins'],**recipe['reviewed_ci_path_pins']}.items():"
after="    for relative,pin in [*recipe['source_pins'].items(),*recipe['reviewed_ci_path_pins'].items()]:"
text=old_setup.decode('ascii');assert text.count(before)==1;text=text.replace(before,after)
assert text.replace(after,before).encode('ascii')==old_setup and functions(text)==functions(old_setup)
setup=write('setup_original_current_ci_v2.py',text.encode('ascii'))
old_capture=(HERE/'capture_original_setup_v1.py').read_bytes();capture=old_capture.decode('ascii')
rows=[("source=here/'setup_original_current_ci_v1.py'","source=here/'setup_original_current_ci_v2.py'"),
 ("before['size_bytes']==16780 and before['sha256']=='aee8876b15a54fbeb222ac6999536ef49be1eaa115e01ccd1a72f860021b547c'",
  "before['size_bytes']=="+str(setup['size_bytes'])+" and before['sha256']=='"+setup['sha256']+"'")]
for before2,after2 in rows:assert capture.count(before2)==1;capture=capture.replace(before2,after2)
inverse=capture
for before2,after2 in reversed(rows):assert inverse.count(after2)==1;inverse=inverse.replace(after2,before2)
assert inverse.encode('ascii')==old_capture and functions(capture)==functions(old_capture)
capture_pin=write('capture_original_setup_v2.py',capture.encode('ascii'))
preparation=json.loads((HERE/'preparation.v1.json').read_bytes())
preparation['status']='authored_validator_preserving_v2_source_only_unexecuted_C_unbound_B_preserved'
preparation['source_correction_from_preparation_v1']=pin(HERE/'preparation.v1.json')
preparation['source_pins']=[setup,capture_pin,pin(HERE/'capture_original_full_ci_v1.py')]
preparation['setup_dispatch_filename']='capture_original_setup_v2.py'
preparation['source_correction']='Author v1 used a merged dict for8 recipe source predicates and4 reviewed CI predicates; duplicate script keys overrode2 original predicates. V2 iterates both item lists independently, preserving all12 validations. Source v1 and preparation v1 remain immutable and are ineligible for setup dispatch.'
preparation['v2_forward_inverse_to_v1_equal']=True
preparation['v2_original_function_ASTs_equal']=True
preparation['new_target_module_functions']=[]
preparation['v2_exact_changes']={'setup':{'before':before,'after':after},'capture':[{'before':a,'after':b} for a,b in rows]}
prepared=write('preparation.v2.json',(json.dumps(preparation,sort_keys=True,indent=2)+'\n').encode())
author={'schema_version':1,'author':'/root/decision28_source_peer','independent_review':False,
 'status':'source_only_corrected_before_any_dispatch','source_v1_preserved_and_superseded':True,
 'v1_concrete_author_finding':preparation['source_correction'],'prepared_v2':prepared,
 'final_source_pins':preparation['source_pins'],'recipe_template':pin(HERE/'recipe.template.v1.json'),
 '8_setup_4_capture_original_function_ASTs_equal':True,'all12_original_and_added_pin_predicates_preserved':True,
 'execution_or_binding_performed':False,'actual_C_binding':None,'actual_setup_result':None,'actual_full_CI_result':None,
 'author_handles_released':True}
receipt=write('author.v2.json',(json.dumps(author,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'author':receipt,'preparation':prepared,'setup':setup,'capture':capture_pin,'full_capture_unchanged':pin(HERE/'capture_original_full_ci_v1.py')}))
