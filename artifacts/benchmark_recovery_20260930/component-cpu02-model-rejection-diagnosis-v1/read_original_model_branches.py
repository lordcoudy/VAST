"""Original preserved-file branch recomputation only; no engine or inference calls."""
import hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'scripts'))
import checkpoint_model_parity_v4 as v4
from checkpoint_model_parity_acceptance_v4 import _assessment_binding
START=time.monotonic()
PATHS=('scripts/checkpoint_model_parity.py','scripts/checkpoint_model_parity_v4.py',
 'scripts/checkpoint_model_parity_acceptance_v4.py','scripts/publication_policy_qualification_bootstrap_v2.py',
 'scripts/publication_gstreamer_component_inputs_v1.py',
 'configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.yaml',
 'configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json')
def descriptor(p):
 before=p.stat();h=hashlib.sha256();size=0
 with p.open('rb') as f:
  while b:=f.read(1048576):
   if time.monotonic()-START>300:raise TimeoutError('file-only branch diagnosis300s cap')
   size+=len(b);h.update(b)
 after=p.stat();assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
 return {'path':str(p),'size_bytes':size,'sha256':h.hexdigest()}
def save(name,value):
 raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode();assert len(raw)<=16*1024*1024
 with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 return descriptor(OUT/name)
before={p:descriptor(ROOT/p) for p in PATHS}
stat_text=Path('/proc/self/stat').read_text();row=stat_text[stat_text.rfind(')')+2:].split()
owner={'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgid(0),'startticks':int(row[19]),'uid':os.getuid(),'gid':os.getgid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
save('original.launch.v1.json',{'argv':sys.argv,'owner':owner,'started_at_ns':time.time_ns(),'source_before':before,'scope':'Pure preserved-file original4 slot assessments; no assess_model_parity_v4, command_runner, Docker/image query, model runtime/inference, probe, rebuild or CPU retry.'})
print(json.dumps({'phase':'file_branch_diagnosis_started','owner':owner}),flush=True)
results={};failure=None
try:
 manifest=v4.load_parity_manifest_v4(ROOT/PATHS[5],project_root=ROOT)
 for branch in v4.parity_v3.BRANCHES:
  result=v4.parity_v3._assess_slot_v2(branch,manifest,root=ROOT)
  reference=save('branch-'+branch+'.v1.json',result)
  results[branch]={'descriptor':reference,'ready':result['ready'],'blockers':result['blockers'],'recomputed_parity':result['recomputed_parity']}
  print(json.dumps({'phase':'original_file_branch_complete','branch':branch,'elapsed_s':time.monotonic()-START,'blockers':result['blockers'],'recomputed_parity':result['recomputed_parity']}),flush=True)
except BaseException as e:failure={'type':type(e).__name__,'message':str(e)}
after={p:descriptor(ROOT/p) for p in PATHS}
terminal=save('original.terminal.v1.json',{'schema_version':1,'artifact_kind':'vast_component_cpu02_preserved_model_slot_diagnosis_v1','owner':owner,'finished_at_ns':time.time_ns(),'elapsed_s':time.monotonic()-START,'source_before':before,'source_after':after,'source_stable':before==after,'original_failure':failure,'branches':results,'image_branch':'Original canonical assessment did live2base+2worker image inspect but did not retain raw responses/blockers. This file-only recomputation observes no current engine/image state and cannot identify original image blockers.','accepted':False,'publication_ready':False,'scope':'Current physical preserved raw/corpus/model/producer checks only. Not an acceptance-loader substitute or model rerun.'})
print(json.dumps({'phase':'file_branch_diagnosis_terminal','receipt':terminal,'failure':failure,'source_stable':before==after}),flush=True)
raise SystemExit(bool(failure) or before!=after)
