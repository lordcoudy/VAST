"""Author separate C-CI/B-benchmark helpers; never import or execute a target."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
HERE=Path(__file__).resolve().parent
OLD=BASE/'component-current95-ci-successor-preparation-v1'
LINUX_BASE='/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930'
BENCHMARK_COMMIT='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
CHECKOUT='/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29'
RESULT=CHECKOUT+'-original-output'
OLD_CHECKOUT='/home/s-a-balashov/work/vast-current-source-ci-20261001-current95'
MANIFEST_REL='decision28-current95-preparation-v1/decision28-current95-original-attempt01/current95-inputs.v1.json'
REVIEW_REL='decision29-ci-clock-independent-source-review-v1/review.v1.json'
IMPACT_REL='decision29-ci-clock-independent-source-review-v1/source-impact.v1.json'

def pin(path,label=None):
    with path.open('rb') as stream:raw=stream.read(4*1024*1024+1)
    assert len(raw)<=4*1024*1024
    return {'path':str(path) if label is None else label,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def write(name,raw):
    path=HERE/name
    with path.open('xb') as stream:
        assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
    return pin(path,LINUX_BASE+'/decision29-current-ci-preparation-v1/'+name)

def functions(raw):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}

expected={
 'setup_original_current_ci_v1.py':(15174,'8bddfb1ceccd736ebf1ab260b0f83637e950995666ced6db63167eff98234571'),
 'capture_original_setup_v1.py':(4942,'49beedf798ccd1288550b9173b6a2337b04a60231a8c2f8d121142ff2f14b37e'),
 'capture_original_full_ci_v1.py':(10983,'3040540f4a12efdb259ce5143748572671ddb9fcf2e8606c2171d771896eff77'),
 'recipe.template.v1.json':(7360,'ee1878fe41a5a8e85856994af820dade6c5ef4a0d9f91eba1f7e441230c11a1c')}
original={}
snapshots=[]
for name,(size,sha) in expected.items():
    raw=(OLD/name).read_bytes();assert len(raw)==size and hashlib.sha256(raw).hexdigest()==sha
    original[name]=raw;snapshots.append(write(name+'.original.raw',raw))
manifest_path=BASE/MANIFEST_REL
manifest=json.loads(manifest_path.read_bytes())
assert manifest['source_commit']==BENCHMARK_COMMIT and len(manifest['actual_current95'])==95
manifest_pin=pin(manifest_path,LINUX_BASE+'/'+MANIFEST_REL)
assert (manifest_pin['size_bytes'],manifest_pin['sha256'])==(44579,'3c9b7eca9c9b33e01624764b7ccfccb9d748c3ac9623389f7e12447f0085b150')
review_pin=pin(BASE/REVIEW_REL,LINUX_BASE+'/'+REVIEW_REL)
impact_pin=pin(BASE/IMPACT_REL,LINUX_BASE+'/'+IMPACT_REL)
assert (review_pin['size_bytes'],review_pin['sha256'])==(9951,'835bf6c7c991c78062adc39459b34f51eab7c598c71185a7b00fe777f62f9d6d')
assert (impact_pin['size_bytes'],impact_pin['sha256'])==(160709,'dcdc63621620f579653574d0a1380baac2d683c117d83b8b194b46e67abb2a41')
review=json.loads((BASE/REVIEW_REL).read_bytes());impact=json.loads((BASE/IMPACT_REL).read_bytes())
assert review['reviewable'] is True and review['blocking_findings']==[] and review['reviewer_handles_released'] is True
assert review['baseline_benchmark_commit']==BENCHMARK_COMMIT
ci_paths=['scripts/ci_namespace_diagnostic_v1.py','scripts/ci_userns_profile_v1.py','tests/test_ci_namespace_diagnostic_v1.py','tests/test_ci_userns_profile_v1.py']
assert impact['changed_CI_paths']==ci_paths and not impact['actual95_changed_path_intersection'] and not impact['selected73_changed_path_intersection']
assert all(not row['changed_path_intersection'] for row in impact['all_ten_source_group_memberships'].values())
ci_pins={row['path']:{k:row[k] for k in ('size_bytes','sha256')} for row in impact['changed_CI_pins']}
for relative,expected_pin in ci_pins.items():
    actual=pin(ROOT/relative);assert all(actual[k]==expected_pin[k] for k in ('size_bytes','sha256'))
changes={};prepared={}

def transform(name,pairs):
    text=original[name].decode('ascii');record=[]
    for before,after in pairs:
        count=text.count(before);assert count==1,(name,before,count)
        text=text.replace(before,after);record.append({'before':before,'after':after,'count':1})
    inverse=text
    for row in reversed(record):
        assert inverse.count(row['after'])==1
        inverse=inverse.replace(row['after'],row['before'])
    assert inverse.encode('ascii')==original[name]
    assert functions(text)==functions(original[name])
    changes[name]=record;prepared[name]=write(name,text.encode('ascii'))
    return text

source_impact_assertions=(
    "    assert recipe['benchmark_source_impact_review']=="+repr(review_pin)+"\n"
    "    assert recipe['benchmark_source_impact_inventory']=="+repr(impact_pin)+"\n"
    "    assert recipe['reviewed_ci_path_pins']=="+repr(ci_pins)+"\n")
setup=transform('setup_original_current_ci_v1.py',[
 ("RECIPE=HERE/'recipe.bound.v1.json';COMMIT=None", "RECIPE=HERE/'recipe.bound.v1.json';COMMIT=None;BENCHMARK_COMMIT='"+BENCHMARK_COMMIT+"'"),
 ("    assert recipe['benchmark_root_commit_untouched']==COMMIT",
  "    assert recipe['benchmark_root_commit_untouched']==BENCHMARK_COMMIT and COMMIT!=BENCHMARK_COMMIT\n"+source_impact_assertions.rstrip('\n')),
 ("    manifest_path=HERE/'current95-original-attempt01/current95-inputs.v1.json'",
  "    manifest_path=HERE.parent/'"+MANIFEST_REL+"'"),
 ("    assert current95['source_commit']==COMMIT and current95['project_root']==str(BENCH) and current95['all_collection_fds_released'] is True",
  "    assert current95['source_commit']==BENCHMARK_COMMIT and current95['project_root']==str(BENCH) and current95['all_collection_fds_released'] is True"),
 ("assert bench_head==COMMIT", "assert bench_head==BENCHMARK_COMMIT"),
 ("    for relative,pin in recipe['source_pins'].items():\n        found=next(row for row in raw_rows if row['path']==relative);assert found['size_bytes']==pin['size_bytes'] and found['sha256']==pin['sha256']",
  "    for relative,pin in {**recipe['source_pins'],**recipe['reviewed_ci_path_pins']}.items():\n        found=next(row for row in raw_rows if row['path']==relative);assert found['size_bytes']==pin['size_bytes'] and found['sha256']==pin['sha256']"),
 ("'benchmark_root_head_unchanged':bench_head,'benchmark95_input_epochs_unchanged':True",
  "'benchmark_root_head_unchanged':bench_head,'benchmark_root_commit':BENCHMARK_COMMIT,'ci_checkpoint_distinct_from_benchmark':COMMIT!=BENCHMARK_COMMIT,'benchmark95_input_epochs_unchanged':True")
])
transform('capture_original_setup_v1.py',[
 ('component-current95-ci-successor-preparation-v1','decision29-current-ci-preparation-v1'),
 ("before['size_bytes']==15174 and before['sha256']=='8bddfb1ceccd736ebf1ab260b0f83637e950995666ced6db63167eff98234571'",
  "before['size_bytes']=="+str(prepared['setup_original_current_ci_v1.py']['size_bytes'])+" and before['sha256']=='"+prepared['setup_original_current_ci_v1.py']['sha256']+"'")
])
transform('capture_original_full_ci_v1.py',[
 ("ROOT = Path('"+OLD_CHECKOUT+"')", "ROOT = Path('"+CHECKOUT+"')"),
 ("RESULT = Path('"+OLD_CHECKOUT+"-original-output')", "RESULT = Path('"+RESULT+"')"),
 ("    assert recipe['source_commit'] == COMMIT and recipe['checkout'] == str(ROOT) and recipe['output'] == str(RESULT)",
  "    assert recipe['source_commit'] == COMMIT and recipe['checkout'] == str(ROOT) and recipe['output'] == str(RESULT)\n"
  "    assert recipe['benchmark_root_commit_untouched'] == '"+BENCHMARK_COMMIT+"' and COMMIT != recipe['benchmark_root_commit_untouched']\n"
  +source_impact_assertions.rstrip('\n'))
])

recipe=json.loads(original['recipe.template.v1.json'])
recipe=json.loads(json.dumps(recipe).replace(OLD_CHECKOUT,CHECKOUT))
recipe['benchmark_root_commit_untouched']=BENCHMARK_COMMIT
recipe['current95_manifest']=manifest_pin
recipe['fresh_stock_closure_descriptor']=manifest['fresh_stock_closure_descriptor']
recipe['current_controller_descriptor']=manifest['current_controller_descriptor']
recipe['benchmark_source_impact_review']=review_pin
recipe['benchmark_source_impact_inventory']=impact_pin
recipe['reviewed_ci_path_pins']=ci_pins
for relative in recipe['source_pins']:
    actual=pin(ROOT/relative);recipe['source_pins'][relative]={k:actual[k] for k in ('size_bytes','sha256')}
recipe['preconditions'][0]='Actual CPU08/GPU02 at benchmark B are closed and independently audited. Genuine Decision28 B95 manifest/stock87 closure remain physically unchanged; the exact closed CI source-impact review joins95/73/native3/worker2 preservation and excludes the four reviewed CI paths. Distinct future CI checkpoint C must be committed/pushed and exactly bound before dispatch.'
recipe['preconditions'].append('The original setup verifies all95 held seven epochs, manifest full SHA and new CI checkout full raw Git bytes. Before any full-CI grant, ROOT must perform and independently join the original fresh full95 SHA/size plus seven-epoch author/peer witness, original setup tool rc/process/FD/final/late closure. Do not relabel the setup epoch-only loop as a full95 hash.')
recipe['stock_checks'][-1]='This local current-C-source CPU lane is distinct from hosted CI and the genuinely closed benchmark B CPU08/GPU02. It grants neither a benchmark replay/root renewal nor GPU/model parity or full publication/Q4/campaign acceptance.'
recipe['limitations']='Source-only template. Benchmark B and genuine closed B95/host/source-impact descriptors are actual retained inputs. CI checkpoint C, recipe.bound descriptor, clone/setup/full-CI owners, clocks and outcomes remain unbound/null. Preserve every historical checkout/output; no force/reset/clean/prune/resume/retry. ROOT must independently review source and bind actual C before one setup and one stock full-CI grant.'
assert recipe['source_commit'] is None and recipe['setup_commands'][3][-1] is None and recipe['stock_cli_argv'][5] is None
assert recipe['actual_ci_success'] is None and recipe['actual_ci_terminal'] is None and recipe['actual_clone'] is None
recipe_pin=write('recipe.template.v1.json',(json.dumps(recipe,sort_keys=True,indent=2)+'\n').encode())

oldrecipe=json.loads(original['recipe.template.v1.json']);normalized=copy.deepcopy(recipe)
normalized=json.loads(json.dumps(normalized).replace(CHECKOUT,OLD_CHECKOUT))
for field in ('benchmark_source_impact_review','benchmark_source_impact_inventory','reviewed_ci_path_pins'):normalized.pop(field)
for field in ('benchmark_root_commit_untouched','current95_manifest','fresh_stock_closure_descriptor','current_controller_descriptor','source_pins','preconditions','stock_checks','limitations'):
    normalized[field]=oldrecipe[field]
assert normalized==oldrecipe
transform_pin=write('literal-replacements.v1.json',(json.dumps(changes,sort_keys=True,indent=2)+'\n').encode())
diffs={}
import difflib
for name in prepared:
    diffs[name]=write(name+'.diff',''.join(difflib.unified_diff(original[name].decode().splitlines(True),
        (HERE/name).read_text().splitlines(True),fromfile=name+' original',tofile=name+' Decision29')).encode())
proof={'schema_version':1,'author':'/root/decision28_source_peer','independent_source_review_required':True,
 'status':'authored_source_only_unexecuted_C_unbound_B_preserved','future_ci_checkpoint_C':None,
 'benchmark_checkpoint_B':BENCHMARK_COMMIT,'future_setup_owner':None,'future_setup_outcome':None,
 'future_full_ci_owner':None,'future_full_ci_outcome':None,'future_recipe_bound_descriptor':None,
 'new_checkout':CHECKOUT,'new_stock_output':RESULT,'new_capture_namespace':LINUX_BASE+'/decision29-current-ci-preparation-v1',
 'source_pins':list(prepared.values()),'recipe_template':recipe_pin,'original_raw_snapshots':snapshots,
 'original_helpers':[{**pin(OLD/name),'module_function_names':list(functions(original[name]))} for name in prepared],
 'literal_replacements':transform_pin,'diffs':diffs,'all_original_module_function_ASTs_equal':True,
 'exact_helper_raw_forward_and_inverse_equal':True,'new_target_module_functions':[],
 'recipe_inverse_equal_except_declared_bindings_preconditions_and_pins':True,
 'bounds':{'setup_work_s':300,'setup_cleanup_s':10,'full_ci_work_s':5400,'full_ci_cleanup_s':10,
           'setup_each_channel_bytes':1048576,'setup_document_bytes':4194304,'full_ci_each_channel_document_bytes':4194304},
 'source_impact_review':review_pin,'source_impact_inventory':impact_pin,'genuine_B95_manifest':manifest_pin,
 'source_impact_does_not_waive_any_actual95_epoch_or_new_checkout_raw_Git_guard':True,
 'source_only_semantic_corrections':['B is an explicit unchanged benchmark commit, distinct from future C.',
   'The current95 source_commit and both benchmark HEAD checks remain B; the new checkout/source checks remain C.',
   'The manifest is the exact genuine Decision28 B95 original, never the old9d47/current95 namespace or a newly fabricated collector.',
   'Exact root-reviewed source-impact descriptors and four CI pins are required in the immutable recipe; all four new checkout paths join full raw Git rows.',
   'Only diagnostic/profile source pin bytes change in the original eight CI pins; stock commands, native builds/test selection/skips/policies and all helper functions remain unchanged.'],
 'mandatory_before_full_ci_grant':'Successful original setup plus fresh original full95 SHA/size and seven-epoch author/peer custody join, true tool rc/process/FD/final/late closure, actual immutable C recipe review and explicit ROOT dispatch grant.',
 'limitations':['Author statically reads metadata and source bytes only; no target helper import/compile/execution, tests, Git, model, native build, engine, device or CI operation.',
 'Original setup holds95 seven epochs; its separate fresh author/peer full-byte audit is retained as a required gate. No setup full95 hash claim is made.',
 'Fresh checkout/output/capture names are declared but their actual absence/filesystem/space/owner must be observed by the original guarded setup at dispatch. No future result is inferred.'],
 'author_handles_released':True,'Git_or_production_or_test_mutation':False,'targets_imported_compiled_or_executed':False}
preparation=write('preparation.v1.json',(json.dumps(proof,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'preparation':preparation,'sources':list(prepared.values()),'recipe':recipe_pin,'C':None,'B':BENCHMARK_COMMIT}))
