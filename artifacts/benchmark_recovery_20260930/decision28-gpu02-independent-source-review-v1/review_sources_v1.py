"""Independent static peer review only; target driver never imported or executed."""
import ast, hashlib, json, os
from pathlib import Path
OUT=Path(__file__).parent
BASE=OUT.parent/'decision28-host-cpu08-final-binding-v1/run_original_cpu_component_pair_ext4_decision28_v4.py'
TARGET=OUT.parent/'decision28-gpu02-preparation-v1/run_original_gpu_component_pair_ext4_decision28_v4.py'
PREP=TARGET.parent/'preparation.v1.json'
raw=BASE.read_bytes();new=TARGET.read_bytes();prep_raw=PREP.read_bytes();prep=json.loads(prep_raw)
def pin(p,b):return {'path':p.as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
assert len(raw)==len(new)==23631
assert hashlib.sha256(raw).hexdigest()=='445535a2ea9176effbe97e5de1db53aae614645e40db65bc1debf74489371f36'
assert hashlib.sha256(new).hexdigest()=='fa4bb696e20ac179557096525ad8eebfa0febae388f3e3033d8890eb7416f938'
steps=[('CPU08','GPU02',1),('cpu-pair-08','gpu-pair-02',2),('CPU','GPU',4),('original_cpu_component_','original_gpu_component_',3),("'--resource','cpu'","'--resource','gpu'",1)]
expected=raw.decode();ordered=[]
for old,after,count in steps:
    assert expected.count(old)==count,(old,expected.count(old));expected=expected.replace(old,after)
    ordered.append({'before':old,'after':after,'count':count})
assert expected.encode()==new
inverse=new.decode()
# Inverse in this order removes GPU02 before the overlapping GPU label.
for old,after,count in steps:
    assert inverse.count(after)==count,(after,inverse.count(after));inverse=inverse.replace(after,old)
assert inverse.encode()==raw
assert prep['literal_replacements']==ordered
assert all(prep[k] is None for k in ('future_dispatch_grant','future_original_owner_and_outcome','future_root_copy_descriptor'))
assert prep['source']['sha256']==hashlib.sha256(raw).hexdigest() and prep['successor']['sha256']==hashlib.sha256(new).hexdigest()
old_tree=ast.parse(raw);new_tree=ast.parse(new)
funcs=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
old_functions,new_functions=funcs(old_tree),funcs(new_tree)
assert old_functions==new_functions
popen=lambda tree:[ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='Popen']
assert popen(old_tree)==popen(new_tree) and len(popen(new_tree))==1
unchanged_TOP=lambda tree:[ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
assert unchanged_TOP(old_tree)==unchanged_TOP(new_tree)
root=Path(r'\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-component-release-20260930-d27')
observed=[]
for relative in ('artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02','artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02-original-controller','artifacts/benchmark_recovery_20260930/decision28-gpu02-preparation-v1/run_original_gpu_component_pair_ext4_decision28_v4.py'):
    p=root/relative
    # This is a current Windows-accessible name observation, not Linux FD custody.
    try:p.lstat();absent=False
    except FileNotFoundError:absent=True
    assert absent,relative
    observed.append({'relative':relative,'observed_absent':True,'basis':'read-only exact UNC name lstat; future live driver must recheck exclusive absence'})
review={'schema_version':1,'artifact_kind':'decision28_gpu02_prepared_source_independent_review_v1','reviewer':'/root/decision28_source_peer','reviewed_commit':'a00aa57f7d9534f8e7920f14f70d6a75a23570ed','disposition':'approved_source_only','reviewable':True,'blocking_findings':[],'reviewer_handles_released':True,'owned_source_pins':[pin(TARGET,new),pin(PREP,prep_raw)],'considered_CPU_baseline':pin(BASE,raw),'literal_replacement_occurrences':11,'ordered_literal_replacements':ordered,'exact_raw_forward_and_reverse_join':True,'all_module_function_ASTs_identical':True,'module_function_names':sorted(old_functions),'Popen_call_AST_identical':True,'Popen_count':1,'Popen_runtime_argv_delta':'Only the argv assignment resource literal cpu becomes gpu; output/controller path literals change to their separately owned GPU02 names. All remaining argv elements and Popen keyword arguments are identical.','namespace_absence_observations':observed,'findings':['Actual image222a0003 and genuine runtime receipt0b8a34e6 are unchanged. Host closure remains a required typed future64hex runtime argument; source commit remains a required40hex runtime argument.','Six exact source/input roles,87 full source descriptors, canonical interpreter and driver self pin form95 fresh held inputs. The driver does not require its self pin to equal the historical CPU controller; no extra current95 collector is needed for this separately owned GPU dispatch under the present stock CLI contract.','Stock CLI still performs live loader/source contract checks. The driver pins genuine source/role bytes and full seven-field current epochs before launch, keeps them held through the original child, hashes and compares afterward, independently attempts every close, and checks FD baseline restoration before and after terminal persistence.','2250s whole observation,2100s stock CLI,15s teardown,1MiB channels/normal metadata and64KiB failure/late companions are unchanged. All source/input/image validators and original scientific intake/deadline/settings remain identical.','First-cause latch, bounded additional errors, partial acquisition ownership, original owner/executable join, EOF/reap, two error-aware process scans, exclusive destination, terminal after FD release and nonauthorizing companions retain their reviewed CPUv4 code.','Original future GPU owner/copy/grant/result stay null. The three specific target names were observed absent; the original future driver independently rechecks exclusive output absence at execution.','Two fallback error-report phase strings retain original_cpu_failed_* from the CPU source. They carry no resource, authority or acceptance decision and do not affect argv or custody; preserved unchanged by the declared minimal resource substitution.'],'limits':['Static peer review only; no target import/compile/execution, tests, engine/model/native/device operation, Git operation or cleanup.','No actual GPU source copy, dispatch grant, original owner, terminal, closure, result, benchmark acceptance or full CI success is invented.','Exact UNC name observations are not Linux FD custody or future absence proof; ROOT must recheck and bind actual source copy/commit/host before its one original dispatch.','GPU dispatch still depends on the separately closed CPU08 independent actual audit and ROOT grant.']}
with (OUT/'review.v1.json').open('xb') as f:f.write((json.dumps(review,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'review':pin(OUT/'review.v1.json',(OUT/'review.v1.json').read_bytes()),'owned_source_pins':review['owned_source_pins'],'functions_unchanged':len(old_functions)}))
