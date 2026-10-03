"""Bounded original native-custody fixture capture; no Docker/model/namespace."""
import hashlib,json,os,signal,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=Path(__file__).resolve().parent
PYTHON='/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
NEW=('test_failed_measurement_retains_actual_binary_channels_and_unchanged_terminal',
     'test_success_and_nonmeasurement_failure_write_no_measurement_adjunct',
     'test_failed_measurement_empty_channels_and_actual_timeout_are_retained',
     'test_failed_measurement_capture_flags_keep_original_prefix_and_bounds',
     'test_failed_measurement_exclusive_collision_preserves_primary_and_written_channel',
     'test_failed_measurement_adjunct_persistence_error_keeps_original_wrapper_error')
def pin(path):
 raw=path.read_bytes();s=path.stat()
 return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
 'epoch':[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]}
def write(path,value):
 with path.open('xb') as f:f.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());f.flush();os.fsync(f.fileno())
def owner(pid):
 r=Path(f'/proc/{pid}/stat').read_text();x=r[r.rfind(')')+2:].split();s=Path(f'/proc/{pid}').stat()
 return {'pid':pid,'ppid':int(x[1]),'pgid':int(x[2]),'startticks':int(x[19]),'uid':s.st_uid,'gid':s.st_gid,
 'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
mode=sys.argv[1]
if mode=='child':
 import unittest
 out=Path(sys.argv[2]);scope=sys.argv[3];sys.path.insert(0,str(ROOT/'tests'))
 import test_publication_operational_process_custody_v1 as test
 methods=NEW if scope=='red' else tuple(n for n in dir(test.ProcessCustodyTests) if n.startswith('test_'))
 ids=['test_publication_operational_process_custody_v1.ProcessCustodyTests.'+n for n in methods]
 before=[pin(Path(m.__file__).resolve()) for m in list(sys.modules.values()) if getattr(m,'__file__',None)
 and Path(m.__file__).resolve().is_relative_to(ROOT) and Path(m.__file__).resolve().is_file()]
 class Result(unittest.TextTestResult):
  def startTest(self,t):
   super().startTest(t);self.fd_before=len(os.listdir('/proc/self/fd'))
  def stopTest(self,t):
   self.fd_rows.append({'id':t.id(),'before':self.fd_before,'after':len(os.listdir('/proc/self/fd'))});super().stopTest(t)
 Result.fd_rows=[]
 result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in ids))
 after=[pin(Path(r['path'])) for r in before]
 write(out/'unit-result.v1.json',{'ids':ids,'tests_run':result.testsRun,'failures':[{'id':t.id(),'traceback':e} for t,e in result.failures],
 'errors':[{'id':t.id(),'traceback':e} for t,e in result.errors],'skips':[{'id':t.id(),'reason':r} for t,r in result.skipped],
 'source_before':before,'source_after':after,'sources_unchanged':before==after,'fd_rows':result.fd_rows,
 'scope':'genuine small CPython ELF children and physical temporary custody; explicit fault/flag fixtures; no real Docker or backend/model proof'})
 raise SystemExit(0 if result.wasSuccessful() and before==after and all(r['before']==r['after'] for r in result.fd_rows) else 1)
assert mode in ('red','green')
started=time.monotonic();out=BASE/(sys.argv[2] if len(sys.argv)>2 else mode+'-01');out.mkdir()
before=[pin(ROOT/n) for n in ('scripts/publication_operational_process_custody_v1.py','tests/test_publication_operational_process_custody_v1.py')]+[pin(Path(__file__).resolve())]
argv=[PYTHON,'-I','-B',str(Path(__file__).resolve()),'child',str(out),mode]
process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
identity=owner(process.pid);write(out/'launch.v1.json',{'argv':argv,'owner':identity,'source_before':before,'execution_s':120,'cleanup_s':10})
flags={'exceeded':False,'read_errors':[],'stdout_eof':False,'stderr_eof':False};threads=[]
def drain(pipe,name):
 total=0
 try:
  with (out/(name+'.raw')).open('xb') as f:
   while raw:=pipe.read(65536):
    if total+len(raw)>1024*1024:
     flags['exceeded']=True;os.killpg(process.pid,signal.SIGTERM);break
    f.write(raw);total+=len(raw)
   else:flags[name+'_eof']=True
   f.flush();os.fsync(f.fileno())
 except BaseException as e:flags['read_errors'].append(type(e).__name__+': '+str(e))
 finally:pipe.close()
for pipe,name in ((process.stdout,'stdout'),(process.stderr,'stderr')):
 t=threading.Thread(target=drain,args=(pipe,name));threads.append(t);t.start()
timed_out=False
try:process.wait(timeout=max(.001,120-(time.monotonic()-started)))
except subprocess.TimeoutExpired:
 timed_out=True;os.killpg(process.pid,signal.SIGTERM)
 try:process.wait(timeout=5)
 except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
for t in threads:t.join(timeout=max(.001,130-(time.monotonic()-started)))
assert not any(t.is_alive() for t in threads)
after=[pin(Path(r['path'])) for r in before];scans=[]
for _ in range(2):
 members=[];errors=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   fact=owner(int(p.name))
   if fact['pgid']==identity['pgid'] and fact['uid']==identity['uid']:members.append(fact)
  except (FileNotFoundError,ProcessLookupError):pass
  except BaseException as e:errors.append({'pid':p.name,'type':type(e).__name__})
 scans.append({'owned_group_members':members,'read_errors':errors})
write(out/'execution.v1.json',{'owner':identity,'returncode':process.returncode,'timed_out':timed_out,'elapsed_s':time.monotonic()-started,
 'capture':flags,'source_before':before,'source_after':after,'stdout':pin(out/'stdout.raw'),'stderr':pin(out/'stderr.raw'),
 'process_scans':scans,'all_capture_fds_closed':True,'sources_unchanged':before==after,'hardware_acceptance':False})
assert before==after and not timed_out and not flags['exceeded'] and not flags['read_errors']
assert flags['stdout_eof'] and flags['stderr_eof'] and all(not r['owned_group_members'] for r in scans)
assert time.monotonic()-started<=120
print(json.dumps({'execution':pin(out/'execution.v1.json'),'original_unit_returncode':process.returncode}))
raise SystemExit(process.returncode)
