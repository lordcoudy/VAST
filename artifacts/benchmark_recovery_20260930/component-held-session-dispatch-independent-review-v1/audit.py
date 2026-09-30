"""Finite read-only v6 predispatch join: original stock file/epoch validator only."""
from pathlib import Path
import hashlib, json, os, stat, subprocess, sys, time
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
COMMIT='8fefa4ba0c5b135c66f85a6eb7f4fd1aaebfdc21'
V6='artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.v6.json'
V6SHA='fedf5d8c85c5e435d4bfab21b4c8851db1e07fd9a982f428f91621314b3a8805'
BEGIN=time.monotonic(); END=BEGIN+120
GIT=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
def clock():
    if time.monotonic()>=END: raise TimeoutError('pure audit120s')
def git(*args):
    clock(); return subprocess.check_output(GIT+list(args),cwd=ROOT,timeout=min(20,END-time.monotonic()))
def epoch(s):
    return {k:int(getattr(s,k,0)) for k in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns','st_file_attributes')}
def pin(path):
    clock(); before=path.lstat(); assert path.resolve(strict=True)==path and stat.S_ISREG(before.st_mode) and before.st_nlink==1
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        assert epoch(os.fstat(fd))==epoch(before)
        digest=hashlib.sha256(); total=0
        while block:=os.read(fd,1048576): clock(); digest.update(block);total+=len(block)
        assert epoch(os.fstat(fd))==epoch(before)==epoch(path.lstat()) and total==before.st_size
    finally: os.close(fd)
    return {'path':str(path),'size_bytes':total,'sha256':digest.hexdigest(),'snapshot':epoch(before)}
def relative_pin(relative):
    row=pin(ROOT/relative);row['path']=relative;return row
head=git('rev-parse','HEAD').decode().strip();assert head==COMMIT
index=git('diff','--cached','--name-only','-z');assert not index
receipt_pin=relative_pin(V6); assert receipt_pin['sha256']==V6SHA and receipt_pin['size_bytes']==30986
receipt=json.loads((ROOT/V6).read_bytes());assert receipt['status']=='frozen' and len(receipt['project_sources'])==87
before=[relative_pin(row['path']) for row in receipt['project_sources']]
assert before==receipt['project_sources'],'original WSL source epoch/byte mismatch'
assert pin(Path(sys.executable))==receipt['interpreter'],'original actual CPython epoch/byte mismatch'
assert all(git('show',COMMIT+':'+row['path'])== (ROOT/row['path']).read_bytes() for row in before)
sys.path.insert(0,str(ROOT/'scripts'))
from publication_policy_qualification_execution_code_closure_v1 import load_execution_code_closure_v1
loaded=load_execution_code_closure_v1(project_root=ROOT,receipt_path=ROOT/V6)
assert loaded['receipt']==receipt,'unchanged stock full physical closure comparison failed'
execution_rel='artifacts/benchmark_recovery_20260930/component-selected-host-closure-v6-original/execution.v1.json'
dispatch_rel='artifacts/benchmark_recovery_20260930/component-selected-host-closure-v6-original/dispatch.v1.json'
execution=json.loads((ROOT/execution_rel).read_bytes());dispatch=json.loads((ROOT/dispatch_rel).read_bytes())
assert execution['returncode']==0 and execution['timed_out'] is False and execution['source_before_after_equal'] is True
assert execution['before']==execution['after']=={r['path']:{'sha256':r['sha256'],'size_bytes':r['size_bytes']} for r in before}
assert execution['receipt']=={'sha256':V6SHA,'size_bytes':30986}
assert dispatch['argv'][0]==sys.executable and dispatch['argv'][-1]==str(ROOT/V6)
assert dispatch['helper']=={k:relative_pin('artifacts/benchmark_recovery_20260930/capture_selected_host_closure_v6.py')[k] for k in ('size_bytes','sha256')}
for name,row in execution['outputs'].items():
    actual=relative_pin('artifacts/benchmark_recovery_20260930/component-selected-host-closure-v6-original/'+name)
    assert {k:actual[k] for k in ('size_bytes','sha256')}==row
owner=dispatch['owner'];assert not Path('/proc',str(owner['pid'])).exists()
members=[]
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():continue
    try: parts=(entry/'stat').read_text().rsplit(')',1)[1].split()
    except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    if int(parts[2])==owner['pgid']:members.append(int(entry.name))
assert not members
pure_rel='artifacts/benchmark_recovery_20260930/component-held-session-host-image-scope-v1/review.v1.json'
pure=json.loads((ROOT/pure_rel).read_bytes());assert pure['selected_source_count']==73 and pure['host_sources_absent_from_selected_and_native_worker_images'] is True
runtime_rel=pure['selected_runtime_receipt']['path']; runtime=json.loads((ROOT/runtime_rel).read_bytes())
assert pure['selected_source_identity']==runtime['physical_identity']['source_identity']
assert runtime['physical_identity']['image_id']=='sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6'
assert relative_pin(runtime_rel)['sha256']==pure['selected_runtime_receipt']['sha256']
controllers=[]
for name,old,new,replacements in (
 ('cpu05','selected-gstreamer-cpu04-controller-preparation-v1/run_original_cpu_component_pair_v1.py','selected-gstreamer-cpu05-controller-preparation-v1/run_original_cpu_component_pair_v1.py',[('V5','V6'),('v5','v6'),('cpu-pair-04','cpu-pair-05')]),
 ('gpu01v2','selected-gstreamer-gpu01-controller-preparation-v1/run_original_gpu_component_pair_v1.py','selected-gstreamer-gpu01-controller-preparation-v2/run_original_gpu_component_pair_v1.py',[('V5','V6'),('v5','v6')])):
    prefix='artifacts/benchmark_recovery_20260930/';text=(ROOT/(prefix+old)).read_bytes()
    for a,b in replacements:text=text.replace(a.encode(),b.encode())
    assert text==(ROOT/(prefix+new)).read_bytes()
    controllers.append({'name':name,'prepared':relative_pin(prefix+new),'raw_literal_inverse':True,'required_actual_arguments':[COMMIT,V6SHA]})
for fresh in ('cpu-pair-05','cpu-pair-05-original-controller','gpu-pair-01','gpu-pair-01-original-controller'):
    assert not os.path.lexists(ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'/fresh)
after=[relative_pin(row['path']) for row in receipt['project_sources']];assert before==after
assert receipt_pin==relative_pin(V6)
assert git('rev-parse','HEAD').decode().strip()==COMMIT and not git('diff','--cached','--name-only','-z')
clock()
report={'schema_version':1,'artifact_kind':'vast_component_held_session_actual_dispatch_independent_review_v1','disposition':'approved_original_dispatch_gate','source_commit':COMMIT,'index_empty':True,'actual_v6':receipt_pin,'source_rows87_original_WSL_full_snapshots_equal':True,'source_rows87_current_commit_bytes_equal':True,'stock_full_physical_loader_passed':True,'interpreter_original_full_snapshot_equal':True,'sources_before_after':before,'capture_execution':relative_pin(execution_rel),'capture_dispatch':relative_pin(dispatch_rel),'capture_original_returncode':0,'capture_elapsed_s':execution['elapsed_s'],'capture_original_pid_and_group_absent':True,'prepared_controllers':controllers,'pure_stock_image_scope':relative_pin(pure_rel),'selected_original_runtime_receipt':relative_pin(runtime_rel),'fresh_output_names_absent':True,'elapsed_s':time.monotonic()-BEGIN,'no_engine_model_native_namespace_test_operations':True,'benchmark_accepted':False,'all_temporary_fds_released':True,'limits':['The existing selected image identity is joined from retained stock metadata; no new engine query was made.','This audit does not validate paired output, guardian or container cleanup. Actual original CLI/cold/terminal evidence remains required.','No source epochs are refreshed or rebound. Each current WSL snapshot equals the new original v6 receipt; v5 is not used as authority.']}
raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'review.v1.json').open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
print(json.dumps({'disposition':report['disposition'],'source_commit':COMMIT,'v6_sha256':V6SHA,'sources':87,'temporary_fds_released':True,'report_sha256':hashlib.sha256(raw).hexdigest(),'elapsed_s':report['elapsed_s']}))