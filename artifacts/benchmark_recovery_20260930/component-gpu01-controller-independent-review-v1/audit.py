"""Read-only binding review of an unexecuted controller; no project imports."""
import ast, hashlib, json, os, stat, time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
held=[]
def pin(relative):
    path=ROOT/relative; fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW); info=os.fstat(fd)
    assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<1024*1024
    raw=os.read(fd,info.st_size+1); assert len(raw)==info.st_size
    e=lambda s:[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
    assert e(info)==e(path.lstat()); held.append((fd,path,e(info),e,raw))
    return raw,{'path':relative,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
cpu,cp=pin('artifacts/benchmark_recovery_20260930/selected-gstreamer-cpu04-controller-preparation-v1/run_original_cpu_component_pair_v1.py')
gpu,gp=pin('artifacts/benchmark_recovery_20260930/selected-gstreamer-gpu01-controller-preparation-v1/run_original_gpu_component_pair_v1.py')
assert cp['sha256']=='f5c60a937c87353621d614060f1471646a4349969a87af4c157d32a0fde080ea'
assert gp['sha256']=='807f28e2cb6acb5584d318a0064a9eaa11095a3982a5327e50bf7293fbff3027'
assert cpu.replace(b'CPU',b'GPU').replace(b'cpu',b'gpu').replace(b'gpu-pair-04',b'gpu-pair-01')==gpu
assert gpu.replace(b'gpu-pair-01',b'gpu-pair-04').replace(b'gpu',b'cpu').replace(b'GPU',b'CPU')==cpu
ast.parse(gpu)
previous,pv=pin('artifacts/benchmark_recovery_20260930/component-host-renewal-v3-independent-review-v1/review.v1.json')
assert pv['sha256']=='3649f754e9645559c4169bd98313eb0993190e6191103e2dd7acde37f1f7b14e'
closure,cl=pin('artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.v5.json')
value=json.loads(closure); assert value['status']=='frozen' and len(value['project_sources'])==87
assert cl['sha256'].startswith('3b9cc84e')
for name in ('gpu-pair-01','gpu-pair-01-original-controller'):
    assert not os.path.lexists(ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7'/name)
for fd,path,epoch,e,raw in held:
    assert e(os.fstat(fd))==epoch==e(path.lstat()); os.lseek(fd,0,os.SEEK_SET); assert os.read(fd,len(raw)+1)==raw
report={'schema_version':1,'artifact_kind':'vast_independent_gpu01_prepared_controller_review_v1',
 'disposition':'approved_unexecuted_literal_only_controller_preparation','independent_review':True,'reviewed_at_ns':time.time_ns(),
 'source_pins':[cp,gp],'basis_review':pv,'current_closed_host_closure':cl,
 'checks':['Forward and inverse raw byte proof exact for CPU→GPU, cpu→gpu, gpu-pair-04→gpu-pair-01 only.',
 'CPU04-reviewed ownership,95-input custody,1MiB channels,2100s stock pair/2250s observer/15s teardown and existing20GiB CLI reserve behavior unchanged.',
 'Original dynamic source commit and host-closure argument gates unchanged; image e474 and runtime receipt61874 unchanged.',
 'New GPU01 output and observer namespaces absent at review; no CPU04 active output read.'],
 'limits':['This is source preparation approval, not execution or hardware/scientific acceptance.',
 'Actual GPU dispatch requires root authorization after CPU04 terminal, independent custody audit and cold review close.',
 'No reviewer tests, engine query, model or worker operation.']}
raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
destination=Path(__file__).parent/'review.v1.json'
with destination.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
for fd,*_ in held: os.close(fd)
print(json.dumps({'path':str(destination),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}))
