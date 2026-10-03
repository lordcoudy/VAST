"""Original bounded local socket/FD unit capture; no model/engine/hardware grant."""
import gc, hashlib, json, os, signal, subprocess, sys, threading, time, unittest
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=Path(__file__).resolve().parent
PYTHON='/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
NAMES=['scripts/checkpoint_gstreamer_analytics_sidecar.py','tests/test_checkpoint_gstreamer_analytics_sidecar.py','tests/test_publication_worker_termination_facts_v1.py']
NEW_SIDE=['test_response_send_epipe_captures_live_validated_worker_before_teardown','test_inference_failure_snapshot_retains_first_route_when_diagnostic_write_fails','test_inference_stage_and_observer_refusal_do_not_replace_or_repeat_primary_failure','test_first_failure_route_is_selected_under_persistence_lock_and_later_route_is_not_observed','test_unattributed_first_failure_does_not_borrow_later_validated_route']
NEW_WORKER=['test_real_shared_capture_offset_is_preserved_for_the_original_writer','test_bytesio_capture_does_not_change_fixture_cursor_and_pipe_is_unavailable','test_terminal_event_argv_is_original_cid_only_and_unchanged_bounded','test_live_frontend_is_snapshot_and_healthcheck_event_is_not_terminal']
def pin(path):
 raw=path.read_bytes();s=path.stat()
 return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch':[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]}
def save(path,value):
 with path.open('xb') as f:f.write(json.dumps(value,sort_keys=True,indent=2).encode()+b'\n');f.flush();os.fsync(f.fileno())
def owner(pid):
 fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split();s=Path('/proc/%d'%pid).stat()
 return {'pid':pid,'ppid':int(fields[1]),'pgid':int(fields[2]),'startticks':int(fields[19]),'uid':s.st_uid,'gid':s.st_gid,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
mode=sys.argv[1]
if mode=='child':
 out=Path(sys.argv[2]);scope=sys.argv[3];sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts')]
 ids=(['test_checkpoint_gstreamer_analytics_sidecar.GStreamerAnalyticsSidecarTests.'+name for name in NEW_SIDE]+['test_publication_worker_termination_facts_v1.TerminationTests.'+name for name in NEW_WORKER]) if scope=='new' else ['test_checkpoint_gstreamer_analytics_sidecar','test_publication_worker_termination_facts_v1']
 suite=unittest.defaultTestLoader.loadTestsFromNames(ids)
 before=[pin(Path(m.__file__).resolve()) for m in tuple(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT) and Path(m.__file__).resolve().is_file()]
 facts=[]
 class Result(unittest.TextTestResult):
  def startTest(self,test):
   gc.collect();self.current={'id':test.id(),'fd_before':len(os.listdir('/proc/self/fd')),'start_monotonic_ns':time.monotonic_ns()};super().startTest(test)
  def stopTest(self,test):
   super().stopTest(test);gc.collect();self.current.update(fd_after=len(os.listdir('/proc/self/fd')),terminal_monotonic_ns=time.monotonic_ns());facts.append(self.current)
 result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
 after=[pin(Path(row['path'])) for row in before]
 save(out/'unit-result.v1.json',{'ids':ids,'tests_run':result.testsRun,'failures':[{'id':t.id(),'traceback':error} for t,error in result.failures],'errors':[{'id':t.id(),'traceback':error} for t,error in result.errors],'skips':[{'id':t.id(),'reason':reason} for t,reason in result.skipped],'fd_timing_facts':facts,'source_before':before,'source_after':after,'source_stable':before==after,'classification':'local real seqpacket/memfd/pipe/shared FD and controlled original socket children; fixture inference and injected engine observations only'})
 raise SystemExit(0 if result.wasSuccessful() and before==after else 1)
assert mode=='capture'
out=BASE/sys.argv[2];out.mkdir();scope=sys.argv[3];start=time.monotonic();fds_before=len(os.listdir('/proc/self/fd'))
before=[pin(ROOT/n) for n in NAMES]+[pin(Path(__file__).resolve())]
argv=[PYTHON,'-I','-B',str(Path(__file__).resolve()),'child',str(out),scope]
save(out/'dispatch.v1.json',{'argv':argv,'source_before':before,'execution_s':120,'cleanup_s':10,'owner':owner(os.getpid()),'original_scope':scope})
p=None;flags={'timed_out':False,'overflow':False,'reader_errors':[]};threads=[];eofs={};failure=None
try:
 p=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 identity=owner(p.pid);save(out/'launch.v1.json',{'argv':argv,'owner':identity})
 def drain(name,pipe):
  try:
   total=0
   with (out/(name+'.raw')).open('xb') as f:
    while raw:=pipe.read(8192):
     available=1024*1024-total
     f.write(raw[:available]);total+=min(len(raw),available)
     if len(raw)>available:
      flags['overflow']=True;break
    else:eofs[name]=True
    f.flush();os.fsync(f.fileno())
  except BaseException as error:flags['reader_errors'].append(type(error).__name__+': '+str(error))
  finally:pipe.close()
 for name in ('stdout','stderr'):
  t=threading.Thread(target=drain,args=(name,getattr(p,name)));threads.append(t);t.start()
 while p.poll() is None:
  if flags['overflow'] or flags['reader_errors'] or time.monotonic()-start>=120:
   flags['timed_out']=time.monotonic()-start>=120;break
  time.sleep(.02)
except BaseException as error:failure=type(error).__name__+': '+str(error)
finally:
 if p is not None and p.poll() is None:
  os.killpg(p.pid,signal.SIGTERM)
  try:p.wait(timeout=min(5,max(.001,130-(time.monotonic()-start))))
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=max(.001,130-(time.monotonic()-start)))
 if p is not None:p.wait(timeout=max(.001,130-(time.monotonic()-start)))
 for t in threads:t.join(timeout=max(.001,130-(time.monotonic()-start)))
 for name in ('stdout','stderr'):
  stream=None if p is None else getattr(p,name)
  if stream is not None and not stream.closed:stream.close()
after=[pin(Path(row['path'])) for row in before];scans=[]
for _ in range(2):
 members=[];errors=[]
 for q in Path('/proc').iterdir():
  if not q.name.isdigit():continue
  try:
   fact=owner(int(q.name))
   if p is not None and fact['pgid']==p.pid and fact['uid']==identity['uid']:members.append(fact)
  except (FileNotFoundError,ProcessLookupError):pass
  except BaseException as error:errors.append({'pid':q.name,'type':type(error).__name__})
 scans.append({'monotonic_ns':time.monotonic_ns(),'original_pid_absent':p is None or not Path('/proc/%d'%p.pid).exists(),'owned_group_members':members,'read_errors':errors});time.sleep(.01)
channels={name:pin(out/(name+'.raw')) for name in ('stdout','stderr') if (out/(name+'.raw')).exists()}
record={'owner':None if p is None else identity,'returncode':None if p is None else p.returncode,'elapsed_s':time.monotonic()-start,'failure':failure,'flags':flags,'eof':eofs,'readers_alive':any(t.is_alive() for t in threads),'source_before':before,'source_after':after,'source_stable':before==after,'channels':channels,'process_scans':scans,'fd_before':fds_before,'fd_after':len(os.listdir('/proc/self/fd')),'hardware_acceptance':False}
save(out/'execution.v1.json',record)
late=time.monotonic()-start>120
if late:save(out/'late-failure.v1.json',{'elapsed_s':time.monotonic()-start,'success':False})
print(json.dumps({'execution':pin(out/'execution.v1.json'),'original_returncode':record['returncode'],'late':late}))
raise SystemExit(record['returncode'] if not failure and not late and before==after and not any(flags.values()) and not record['readers_alive'] and all(not s['owned_group_members'] and not s['read_errors'] and s['original_pid_absent'] for s in scans) else 99)
