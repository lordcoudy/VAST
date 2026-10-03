"""Literal GPU successor of actual closed CPU08 auditor; target not executed."""
import ast,hashlib,json
from pathlib import Path
OUT=Path(__file__).parent
BASE=OUT.parent/'decision28-cpu08-independent-audit-v1/audit_cpu08_v1.py'
raw=BASE.read_bytes();assert len(raw)==22413 and hashlib.sha256(raw).hexdigest()=='5f2d62e67ed2414d6b09826ade9362b1acbeabb4db4fd71a248b34e667351a06'
text=raw.decode();changes=[]
for before,after,count in (
 ('CPU08','GPU02',1),('cpu-pair-08','gpu-pair-02',2),
 ('run_original_cpu_component_pair_ext4_decision28_v4.py','run_original_gpu_component_pair_ext4_decision28_v4.py',1),
 ('445535a2ea9176effbe97e5de1db53aae614645e40db65bc1debf74489371f36','fa4bb696e20ac179557096525ad8eebfa0febae388f3e3033d8890eb7416f938',1),
 ("cli['resource']=='cpu'","cli['resource']=='gpu'",1),
 ("component-gstreamer_custom-cpu-h264-","component-gstreamer_custom-gpu-h264-",1),
 ("cold['resource']=='cpu'","cold['resource']=='gpu'",1),
 ('vast_cpu08_ext4','vast_gpu02_ext4',3),('task_18_8_complete','task_18_9_complete',3)):
    assert text.count(before)==count,(before,text.count(before))
    text=text.replace(before,after);changes.append({'before':before,'after':after,'count':count})
inverse=text
for row in reversed(changes):
    assert inverse.count(row['after'])==row['count'];inverse=inverse.replace(row['after'],row['before'])
assert inverse.encode()==raw
functions=lambda b:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(b).body if isinstance(n,ast.FunctionDef)}
assert functions(raw)==functions(text)
new=text.encode()
def pin(p,b):return {'path':p.as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def save(name,b):
    with (OUT/name).open('xb') as f:f.write(b)
save('cpu08-audit.original.raw',raw);save('audit_gpu02_v1.py',new)
source=pin(OUT/'audit_gpu02_v1.py',new)
author={'schema_version':1,'author':'/root/decision28_source_peer','scope':'Source-only auditor author; ROOT independent source review before one observation; not self-approved independent execution.','source':pin(BASE,raw),'successor':source,'exact_raw_inverse':True,'all10_module_function_ASTs_unchanged':True,'module_function_names':sorted(functions(raw)),'literal_replacements':changes,'all_core_custody_process_guardian_raw_cold_FD_close_late_logic_unchanged':True,'budgets':{'audit_s':120,'external_containment_s':135,'external_kill_after_s':5,'leaf_bytes':67108864,'decoded_document_bytes':1048576,'report_bytes':1048576,'late_companion_bytes':65536},'no_target_import_compile_execution_tests_Git_engine_model_device_or_cleanup':True,'future_owner':None,'future_result':None}
save('author.v1.json',(json.dumps(author,sort_keys=True,indent=2)+'\n').encode())
prep={'schema_version':1,'source':source,'reviewed_original_commit':'a00aa57f7d9534f8e7920f14f70d6a75a23570ed','original_terminal':{'path':'artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02-original-controller/original.terminal.v1.json','size_bytes':94879,'sha256':'7272120d78ae1d851a46cee48cf1f51267da504b4550a7a434d86c2db8cda062'},'original_owner':{'pid':78946,'pgid':78946,'startticks':49999029,'controller_pid':78944,'guardian_pid':79194,'guardian_startticks':50008295},'future_auditor_owner':None,'future_audit_outcome':None,'ROOT_independent_source_review_required_before_execution':True,'proposed_original_argv':['/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python','-I','-B',(OUT/'audit_gpu02_v1.py').as_posix().replace('E:','/mnt/e'),'7272120d78ae1d851a46cee48cf1f51267da504b4550a7a434d86c2db8cda062','94879','78946'],'acceptance_requires':['Original once-only tool returncode0/EOF/reaped and no late companion','All95 exact current source/input descriptors/fullSHA/sevenepochs under heldFD and recheck','Both original GPU arms/full cold/all-phase receipts and24 nonfixture phase rows','Authenticated guardian closure and actual reserve absence','Two error-free current original controller/CLI/guardian/native-child process/group/session absence scans','Independent allcloseattempts and actual reviewer FD baseline restoration before receipt'],'scope':'Read-only original exact GPU02 outputs/current95/proc metadata. No engine/model/device measurement, cleanup, retry, Git, source95 or production mutation.'}
save('preparation.v1.json',(json.dumps(prep,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'source':source,'functions_unchanged':len(functions(raw)),'literal_occurrences':sum(r['count'] for r in changes)}))
