"""Original bounded execution of tiny collector fixtures only."""
from pathlib import Path
import hashlib,json,os,selectors,signal,subprocess,sys,time

ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930/component-ext4-relocation-preparation-v1'
OUT=BASE/'focused-attempt-02'
OUT.mkdir(mode=0o700)
START=time.monotonic()
DEADLINE=START+30
HARD=DEADLINE+10
MAX=1024*1024
NAMES=['setup_finite_ext4_root_v1.py','capture_selected_host_closure_ext4_v1.py','run_original_cpu_component_pair_ext4_v1.py','run_original_gpu_component_pair_ext4_v3.py','test_setup_finite_transfer_v1.py']
def epoch(i):return [i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns]
def pin(p):
 raw=p.read_bytes()
 return {'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch':epoch(p.lstat())}
def write(name,value):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
 with (OUT/name).open('xb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
def owner(pid):
 values=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
 ids=dict(line.split(':',1) for line in Path('/proc',str(pid),'status').read_text().splitlines() if ':' in line)
 return {'pid':pid,'ppid':int(values[1]),'pgid':int(values[2]),'startticks':int(values[19]),'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
before={name:pin(BASE/name) for name in NAMES}
argv=[sys.executable,'-I','-B',str(BASE/'test_setup_finite_transfer_v1.py'),'-v']
child=None
sel=selectors.DefaultSelector()
streams={name:(OUT/(name+'.raw')).open('xb') for name in ('stdout','stderr')}
counts={'stdout':0,'stderr':0}
errors=[]
record={'argv':argv,'timeout_s':30,'cleanup_s':10,'source_before':before,'controller':owner(os.getpid()),'owner':None,'timed_out':False,'capture_exceeded':False}
try:
 child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 record['owner']=owner(child.pid)
 write('dispatch.v1.json',record)
 for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
  os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,name)
 while sel.get_map() or child.poll() is None:
  if time.monotonic()>=DEADLINE:record['timed_out']=True;raise TimeoutError('original30s unit deadline')
  for key,_ in sel.select(.05):
   block=os.read(key.fd,65536)
   if not block:sel.unregister(key.fileobj);continue
   if len(block)>MAX-counts[key.data]:record['capture_exceeded']=True;raise RuntimeError('channel cap')
   streams[key.data].write(block);counts[key.data]+=len(block)
 child.wait(timeout=max(.001,DEADLINE-time.monotonic()))
except BaseException as exc:errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
finally:
 if child is not None:
  try:os.killpg(child.pid,0)
  except ProcessLookupError:pass
  else:
   os.killpg(child.pid,signal.SIGKILL)
   if not errors:errors.append({'type':'RuntimeError','message':'original unit left process group'})
  try:child.wait(timeout=max(.001,min(10,HARD-time.monotonic())))
  except BaseException as exc:errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]})
 sel.close()
 for p in (() if child is None else (child.stdout,child.stderr)):p.close()
 for out in streams.values():out.flush();os.fsync(out.fileno());out.close()
after={name:pin(BASE/name) for name in NAMES}
pid_absent=child is not None and not Path('/proc',str(child.pid)).exists()
group_absent=False
if child is not None:
 try:os.killpg(child.pid,0)
 except ProcessLookupError:group_absent=True
record.update({'returncode':None if child is None else child.returncode,'source_after':after,'source_before_after_equal':before==after,
 'original_pid_absent':pid_absent,'original_group_absent':group_absent,'errors':errors,'elapsed_s':time.monotonic()-START,
 'channels':{name:pin(OUT/(name+'.raw')) for name in streams},'setup_clone_engine_model_native_work':False})
write('execution.v1.json',record)
print(json.dumps({'returncode':record['returncode'],'elapsed_s':record['elapsed_s'],'source_equal':before==after,'pid_absent':pid_absent,'group_absent':group_absent,'errors':errors}))
sys.exit(0 if record['returncode']==0 and before==after and pid_absent and group_absent and not errors else 78)

