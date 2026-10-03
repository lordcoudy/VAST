"""Offline literal source authoring; prepared collector/capture are never executed."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=HERE.parent/'component-current95-ci-successor-preparation-v1'
changes={}
def replace(text,before,after,kind):
    assert text.count(before)==1,(kind,before[:100],text.count(before))
    changes.setdefault(kind,[]).append({'before':before,'after':after})
    return text.replace(before,after,1)

scan_source=(HERE.parent/'decision28-host-cpu08-renewal-preparation-v2/capture_selected_host_closure_ext4_decision28_v4.py').read_text()
scan_tree=ast.parse(scan_source)
scan_node=next(node for node in scan_tree.body if isinstance(node,ast.FunctionDef) and node.name=='scan_original_group')
SCAN='\n'.join(scan_source.splitlines()[scan_node.lineno-1:scan_node.end_lineno])+'\n'

original=(OLD/'collect_current95_v1.py').read_bytes()
collector=original.decode()
collector=replace(collector,'import hashlib,json,os,stat,subprocess,sys,time','import hashlib,json,os,selectors,signal,stat,subprocess,sys,time','collector')
collector=replace(collector,"OUT=HERE/'current95-original-attempt01'","OUT=HERE/'decision28-current95-original-attempt01'",'collector')
collector=replace(collector,"START=time.monotonic();END=START+120\nheld=[];directories={};commands=[];first=None;close_errors=[];manifest=None\n", "START=time.monotonic();END=START+120;HARD=END+10\nheld=[];directories={};commands=[];first=None;close_errors=[];manifest=None\nerror_records=[];error_overflow=0;output_owned=False;fd_before=fd_after=None;collector_owner=None\n",'collector')
collector=replace(collector,"artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json", "artifacts/benchmark_recovery_20260930/decision28-gstreamer-build-2a6a42c9-v1/gstreamer_custom.runtime.freeze.json",'collector')
collector=replace(collector,'execution-code-closure.ext4-supervisor.v2.json','execution-code-closure.ext4-decision28.v4.json','collector')
collector=replace(collector,'component-supervisor-renewal-preparation-v1/run_original_cpu_component_pair_ext4_supervisor_v2.py','decision28-host-cpu08-final-binding-v1/run_original_cpu_component_pair_ext4_decision28_v4.py','collector')
collector=replace(collector,"'size_bytes':15100,'sha256':'b4488d87a4c0feb500d7fdbca77af76e4745efeafb4927003ea1e932227ec8fd'", "'size_bytes':23631,'sha256':'445535a2ea9176effbe97e5de1db53aae614645e40db65bc1debf74489371f36'",'collector')
collector=replace(collector,'61874c718d6140d0d5cf745988bc301b916077af8f80e96742184f80a0805db7','0b8a34e67773572a27885b931c50427de8bbd59b23eba837c5d2319ea7e9abca','collector')
collector=replace(collector,'def clock():', '''def error(exc):
 return {'type':type(exc).__name__,'message':str(exc)[:4096]}
def fail(phase,exc,closing=False):
 global first,error_overflow
 row={'phase':phase,**error(exc)}
 if first is None:first=error(exc)
 if len(error_records)<64:error_records.append(row)
 else:error_overflow+=1
 if closing and len(close_errors)<64:close_errors.append(row)
def fd_count():return len(os.listdir('/proc/self/fd'))
'''+SCAN+'''def hard_clock():
 if time.monotonic()>=HARD:raise TimeoutError('current95 metadata original120+10s cleanup bound')
def clock():''','collector')
start=collector.index('def ancestors(p):')
end=collector.index('def observe(fd,p):',start)
collector=replace(collector,collector[start:end],'''def ancestors(p):
 for q in reversed(p.parents):
  clock();assert q.resolve(strict=True)==q
  if q not in directories:
   directories[q]=(None,None)
   fd=os.open(q,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
   directories[q]=(fd,None)
   s=os.fstat(fd);assert stat.S_ISDIR(s.st_mode) and identity(s)==identity(q.lstat())
   directories[q]=(fd,identity(s))
  fd,before=directories[q]
  assert fd is not None and before is not None and identity(os.fstat(fd))==before==identity(q.lstat())
''','collector')
collector=replace(collector,' while block:=os.read(fd,65536):clock();h.update(block);size+=len(block)', ' while block:=os.read(fd,65536):clock();h.update(block);size+=len(block);assert size<=16*1048576','collector')
start=collector.index('def hold(p,expected=None):');end=collector.index('def owner(pid):',start)
collector=replace(collector,collector[start:end],'''def hold(p,expected=None):
 p=Path(p);assert p.is_absolute() and p.resolve(strict=True)==p
 assert p not in {x[1] for x in held},'current95/control duplicate path'
 ancestors(p);index=len(held);held.append((None,p,None))
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK);held[index]=(fd,p,None)
 row=observe(fd,p)
 if expected is not None:assert row['descriptor']==expected,'current physical descriptor mismatch:'+str(p)
 held[index]=(fd,p,row);return row
''','collector')
start=collector.index('def head(label):');end=collector.index('try:\n assert os.getuid()',start)
collector=replace(collector,collector[start:end],'''def head(label):
 clock();argv=['/usr/bin/git','-c','core.longpaths=true','-C',str(ROOT),'rev-parse','HEAD']
 child=None;actual=None;selector=None;stdout=bytearray();stderr=bytearray();scans=[];eof=set();fault=None;reaped=False
 command_fd_before=fd_count();deadline=min(END,time.monotonic()+10)
 try:
  selector=selectors.DefaultSelector()
  child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  actual=owner(child.pid)
  for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
   os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,name)
  while selector.get_map() or child.poll() is None:
   clock();assert time.monotonic()<deadline,'original Git-head10s timeout'
   for key,_ in selector.select(.02):
    raw=os.read(key.fd,65536)
    if not raw:eof.add(key.data);selector.unregister(key.fileobj);continue
    target=stdout if key.data=='stdout' else stderr
    maximum=128 if key.data=='stdout' else 0
    assert len(target)+len(raw)<=maximum,'original Git-head stdout128/stderr-empty cap'
    target.extend(raw)
  child.wait(timeout=max(.001,deadline-time.monotonic()));reaped=True
  assert child.returncode==0,'original Git-head nonzero'
 except BaseException as exc:fault=error(exc);fail(label+':body',exc)
 finally:
  cleanup_deadline=min(HARD,time.monotonic()+10)
  if child is not None:
   try:
    if child.poll() is None:os.killpg(child.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   except BaseException as exc:fail(label+':owned_kill',exc)
   try:child.wait(timeout=max(.001,min(5,cleanup_deadline-time.monotonic())));reaped=True
   except BaseException as exc:fail(label+':reap',exc)
  if selector is not None:
   try:selector.close()
   except BaseException as exc:fail(label+':selector_close',exc,closing=True)
  if child is not None:
   for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
    if pipe is not None:
     try:pipe.close()
     except BaseException as exc:fail(label+':'+name+'_close',exc,closing=True)
   original=actual or {'pid':child.pid,'pgid':child.pid,'startticks':None}
   if actual is None:fail(label+':owner',RuntimeError('original Git owner unavailable'))
   for index in range(2):
    try:
     scan=scan_original_group(original,cleanup_deadline);scans.append(scan)
     assert not scan['members'] and not scan['member_overflow'] and not scan['errors'] and not scan['error_overflow'] and scan['original_pid_identity']=='absent','original Git PID/group absence uncertain'
    except BaseException as exc:fail(label+':scan'+str(index),exc)
  try:
   assert fd_count()==command_fd_before,'original Git-head FD baseline not restored'
   assert time.monotonic()<cleanup_deadline,'original Git-head cleanup10s elapsed'
  except BaseException as exc:fail(label+':closure',exc)
 commands.append({'label':label,'argv':argv,'owner':actual,'returncode':None if child is None else child.returncode,
  'reaped':reaped,'stdout_ascii':stdout.decode('ascii'),'stderr_hex':stderr.hex(),'EOF':sorted(eof),'process_scans':scans,'failure':fault})
 assert first is None and reaped and len(scans)==2 and eof=={'stdout','stderr'},'original Git-head closure failed'
 return stdout.decode('ascii').strip()
def save(name,value,late_metadata=False):
 if not late_metadata:clock()
 raw=(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\\n').encode('ascii');assert len(raw)<=(65536 if late_metadata else 1048576)
 stream=None;failed=None
 try:
  assert output_owned,'collector does not own exclusive output'
  stream=(OUT/name).open('xb');assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
 except BaseException as exc:failed=exc;fail('save:'+name,exc)
 finally:
  if stream is not None:
   try:stream.close()
   except BaseException as exc:
    fail('save_close:'+name,exc,closing=True)
    if failed is None:failed=exc
 if failed is not None:raise failed
 if not late_metadata:clock()
 return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
''','collector')
collector=replace(collector,"try:\n assert os.getuid()==os.getgid()==1000", "try:\n fd_before=fd_count();collector_owner=owner(os.getpid())\n assert os.getuid()==os.getgid()==1000",'collector')
collector=replace(collector," assert ROOT.resolve(strict=True)==ROOT and identity(ROOT.lstat())[3:]==[1000,1000] and not OUT.exists()\n", " assert ROOT.resolve(strict=True)==ROOT and identity(ROOT.lstat())[3:]==[1000,1000] and not os.path.lexists(OUT)\n OUT.mkdir(mode=0o700);output_owned=True\n",'collector')
collector=replace(collector," assert binding['current_controller_descriptor']==EXPECTED_CONTROLLER\n", " assert binding['current_controller_descriptor']==EXPECTED_CONTROLLER\n assert binding['role_descriptors']['runtime_image_receipt_path']['size_bytes']==7001\n",'collector')
collector=replace(collector," for role in ROLE_PATHS:rows.append(hold(ROOT/ROLE_PATHS[role],binding['role_descriptors'][role]))\n", " for role in ROLE_PATHS:rows.append(hold(ROOT/ROLE_PATHS[role],binding['role_descriptors'][role]))\n runtime_fd=next(fd for fd,p,_ in held if p==ROOT/ROLE_PATHS['runtime_image_receipt_path'])\n os.lseek(runtime_fd,0,os.SEEK_SET);runtime_raw=os.read(runtime_fd,7002)\n assert len(runtime_raw)==7001 and hashlib.sha256(runtime_raw).hexdigest()==EXPECTED_ROLE_SHA['runtime_image_receipt_path']\n runtime=json.loads(runtime_raw)\n assert runtime['candidate_binding_eligible'] is True and runtime['blockers']==[] and runtime['physical_identity']['image_id']=='sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1'\n unsigned=dict(runtime);del unsigned['receipt_sha256']\n assert hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()==runtime['receipt_sha256']=='8dbd48381495beddc23abab774055ebb3ce89af7f8d56901580da2612092e093'\n",'collector')
start=collector.index("except BaseException as exc:first={'type':")
collector=replace(collector,collector[start:],'''except BaseException as exc:fail('collection_body',exc)
finally:
 source_checks=[];pin_closes=[];directory_closes=[]
 for fd,p,row in held:
  try:
   assert fd is not None and row is not None,'current held acquisition incomplete'
   assert observe(fd,p)==row,'current held full SHA/epoch drift at finalization'
   source_checks.append({'path':str(p),'verified':True})
  except BaseException as exc:source_checks.append({'path':str(p),'verified':False});fail('source_final:'+str(p),exc)
 for p,(fd,before) in directories.items():
  try:assert fd is not None and before is not None and identity(os.fstat(fd))==before==identity(p.lstat()) and p.resolve(strict=True)==p
  except BaseException as exc:fail('directory_final:'+str(p),exc)
 for fd,p,_ in held:
  if fd is None:continue
  try:os.close(fd);pin_closes.append({'path':str(p),'closed':True})
  except BaseException as exc:pin_closes.append({'path':str(p),'closed':False});fail('held_close:'+str(p),exc,closing=True)
 for p,(fd,_) in directories.items():
  if fd is None:continue
  try:os.close(fd);directory_closes.append({'path':str(p),'closed':True})
  except BaseException as exc:directory_closes.append({'path':str(p),'closed':False});fail('directory_close:'+str(p),exc,closing=True)
 try:
  fd_after=fd_count();assert fd_before is not None and fd_after==fd_before,'current95 FD baseline not restored'
 except BaseException as exc:fail('FD_baseline',exc,closing=True)
 late=time.monotonic()>=END
 if late:fail('whole_deadline_before_manifest',TimeoutError('current95 collection120s elapsed'))
 manifest_ref=None;report_ref=None;terminal_error=first;terminal_count=len(error_records);terminal_overflow=error_overflow
 if output_owned:
  if first is None and not close_errors:
   try:manifest_ref=save('current95-inputs.v1.json',manifest)
   except BaseException as exc:fail('manifest_persist',exc)
  report={'schema_version':1,'status':'current95_collected' if first is None and not close_errors else 'failed_no_current95_grant',
   'first_error':first,'close_errors':close_errors,'error_records':error_records,'error_overflow':error_overflow,'owner':collector_owner,'commands':commands,
   'held_input_count':len(held),'held_ancestor_count':len(directories),'all_collection_fds_released':not close_errors and fd_before is not None and fd_before==fd_after,
   'all_close_attempts_finished':True,'fd_before':fd_before,'fd_after':fd_after,'source_checks':source_checks,'pin_closes':pin_closes,'directory_closes':directory_closes,
   'work_limit_s':120,'cleanup_s':10,'elapsed_before_final_report_s':time.monotonic()-START,'manifest':manifest_ref}
  terminal_error=first;terminal_count=len(error_records);terminal_overflow=error_overflow
  try:
   report_ref=save('execution.v1.json',report)
   print(json.dumps({'report':report_ref,'manifest':manifest_ref,'late':late}),flush=True)
  except BaseException as exc:fail('report_persist_or_print',exc)
 try:
  fd_after=fd_count();assert fd_before is not None and fd_after==fd_before,'current95 final metadata FD baseline not restored'
 except BaseException as exc:fail('post_terminal_FD',exc,closing=True)
 if time.monotonic()>=END:
  if not late:fail('whole_deadline_after_report',TimeoutError('current95 collection120s closed late'))
  late=True
 if output_owned and (first is not None or report_ref is None or first!=terminal_error or len(error_records)!=terminal_count or error_overflow!=terminal_overflow or late):
  try:
   save('failure.v1.json',{'status':'failed_no_current95_grant','first_error':first,'report':report_ref,'manifest':manifest_ref,
    'terminal_path':str(OUT/'execution.v1.json'),'late':late,'recent_errors':error_records[-8:],'error_overflow':error_overflow,
    'fd_before':fd_before,'fd_after':fd_after,'all_close_attempts_finished':True,'metadata_only_no_model_image_runtime_acceptance':True},late_metadata=True)
  except BaseException as exc:
   fail('failure_companion',exc)
   try:print(json.dumps({'status':'failed_no_current95_grant','first_error':first,'companion_error':error(exc)}),file=sys.stderr,flush=True)
   except BaseException as report_exc:fail('failure_companion_report',report_exc)
 if output_owned and time.monotonic()>=END and not late:
  late=True;fail('whole_deadline_after_companion',TimeoutError('current95 collection120s final metadata elapsed'))
  try:save('late-failure.v1.json',{'status':'failed_no_current95_grant','first_error':first,'late':True,'report':report_ref,'manifest':manifest_ref},late_metadata=True)
  except BaseException as exc:fail('late_companion',exc)
 if not output_owned:
  try:print(json.dumps({'status':'failed_no_current95_grant','first_error':first,'output_namespace_owned':False}),file=sys.stderr,flush=True)
  except BaseException as exc:fail('unowned_failure_report',exc)
 try:hard_clock()
 except BaseException as exc:fail('absolute120+10_bound',exc)
sys.exit(0 if first is None and not close_errors and not late else 1)
''','collector')

collector_raw=collector.encode()
collector_sha=hashlib.sha256(collector_raw).hexdigest()
capture_original=(OLD/'capture_original_current95_v1.py').read_bytes()
capture=capture_original.decode()
capture=replace(capture,'import hashlib,json,os,signal,stat,subprocess,sys,time','import hashlib,json,os,selectors,signal,stat,subprocess,sys,time','capture')
capture=replace(capture,'component-current95-ci-successor-preparation-v1','decision28-current95-preparation-v1','capture')
start=capture.index('def descriptor(p):');end=capture.index('def owner(pid):',start)
capture=replace(capture,capture[start:end],'''START=time.monotonic();HARD=START+130
failure=None;cleanup_errors=[];error_overflow=0;pins=[];fd_before=fd_after=None
def error(exc):return {'type':type(exc).__name__,'message':str(exc)[:4096]}
def fail(phase,exc):
 global failure,error_overflow
 if failure is None:failure=error(exc)
 if len(cleanup_errors)<64:cleanup_errors.append({'phase':phase,**error(exc)})
 else:error_overflow+=1
def fd_count():return len(os.listdir('/proc/self/fd'))
def clock():
 if time.monotonic()>=HARD:raise TimeoutError('original current95 capture130s envelope')
def descriptor(p,maximum=16*1048576):
 clock();fd=None;failed=None;info=p.lstat();digest=hashlib.sha256();count=0
 epoch=lambda s:[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
 assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and p.resolve(strict=True)==p and info.st_size<=maximum
 try:
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
  assert epoch(info)==epoch(os.fstat(fd))
  while raw:=os.read(fd,65536):clock();count+=len(raw);assert count<=maximum;digest.update(raw)
  assert count==info.st_size and epoch(info)==epoch(os.fstat(fd))==epoch(p.lstat())
 except BaseException as exc:failed=exc;fail('descriptor:'+str(p),exc)
 finally:
  if fd is not None:
   try:os.close(fd)
   except BaseException as exc:
    fail('descriptor_close:'+str(p),exc)
    if failed is None:failed=exc
 if failed is not None:raise failed
 return {'path':str(p),'size_bytes':count,'sha256':digest.hexdigest(),'epoch7':epoch(info)}
def hold(p,expected=None,maximum=16*1048576):
 p=Path(p);assert p.is_absolute() and p.resolve(strict=True)==p
 row={'path':p,'fd':None,'descriptor':None,'maximum':maximum};pins.append(row)
 row['fd']=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
 row['descriptor']=descriptor(p,maximum)
 if expected is not None:
  assert row['descriptor']['size_bytes']==expected[0] and row['descriptor']['sha256']==expected[1],'exact capture source/binding descriptor differs'
 s=os.fstat(row['fd']);assert row['descriptor']['epoch7']==[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
 return row
def save(name,value,late_metadata=False):
 if not late_metadata:clock()
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\\n').encode();assert len(raw)<=(65536 if late_metadata else 1048576)
 stream=None;failed=None
 try:
  stream=(here/name).open('xb');assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
 except BaseException as exc:failed=exc;fail('save:'+name,exc)
 finally:
  if stream is not None:
   try:stream.close()
   except BaseException as exc:
    fail('save_close:'+name,exc)
    if failed is None:failed=exc
 if failed is not None:raise failed
 if not late_metadata:clock()
 return {'path':str(here/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
''','capture')
start=capture.index('def scan(ids):');end=len(capture)
capture=replace(capture,capture[start:end],SCAN+'''streams={};selector=None;child=None;actual=None;timeout_owner=None;signals=[];code=None;reaped=False
EOF={'stdout':False,'stderr':False};counts={'stdout':0,'stderr':0};process_scans=[];before=after=None;started=time.time_ns();capture_owned=False;capture_owner=None
try:
 fd_before=fd_count();capture_owner=owner(os.getpid())
 assert here.resolve(strict=True)==here
 assert not any(os.path.lexists(here/name) for name in ('original-current95.stdout.raw','original-current95.stderr.raw','original-current95.capture-launch.v1.json','original-current95.child-owner.v1.json','original-current95.capture-terminal.v1.json','original-current95.failure.v1.json','original-current95.late.v1.json')),'original current95 capture namespace occupied'
 for name in ('stdout','stderr'):
  streams[name]=(here/('original-current95.'+name+'.raw')).open('xb');capture_owned=True
 selector=selectors.DefaultSelector()
 source_pin=hold(source,('''+str(len(collector_raw))+''','''+repr(collector_sha)+'''))
 hold(Path(__file__))
 hold(Path(python).resolve(strict=True))
 assert len(sys.argv)==3 and 0<int(sys.argv[1])<=1048576 and len(sys.argv[2])==64 and all(c in '0123456789abcdef' for c in sys.argv[2])
 hold(here/'collection.bound.v1.json',(int(sys.argv[1]),sys.argv[2]),1048576)
 before=source_pin['descriptor']
 child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 timeout_owner=owner(child.pid)
 save('original-current95.capture-launch.v1.json',{'argv':argv,'capture_owner':capture_owner,'timeout_owner':timeout_owner,'source_before':before,'started_at_ns':started,'work_s':120,'cleanup_s':10})
 for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
  os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,name)
 child_owner_written=False
 while selector.get_map() or child.poll() is None:
  clock()
  if actual is None and Path('/proc',str(child.pid)).exists():
   for pid in Path('/proc',str(child.pid),'task',str(child.pid),'children').read_text().split():
    try:
     candidate=owner(int(pid))
     if str(source) in candidate['argv']:actual=candidate
    except FileNotFoundError:pass
  if actual is not None and not child_owner_written:
   save('original-current95.child-owner.v1.json',actual);child_owner_written=True
  for key,_ in selector.select(.02):
   raw=os.read(key.fd,65536)
   if not raw:EOF[key.data]=True;selector.unregister(key.fileobj);continue
   assert counts[key.data]+len(raw)<=1048576,'original capture exceeds1MiB'
   assert streams[key.data].write(raw)==len(raw),'short original current95 capture write'
   counts[key.data]+=len(raw)
 code=child.wait(timeout=max(.001,HARD-time.monotonic()));reaped=True
 assert actual is not None,'original collector owner not observed'
 assert code==0,'original collector returned nonzero'
except BaseException as exc:fail('capture_body',exc)
finally:
 if child is not None:
  try:
   if child.poll() is None:signals.append('SIGKILL');os.killpg(child.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  except BaseException as exc:fail('original_group_kill',exc)
  try:code=child.wait(timeout=max(.001,min(5,HARD-time.monotonic())));reaped=True
  except BaseException as exc:fail('original_reap',exc)
 if selector is not None:
  try:
   while selector.get_map() and time.monotonic()<HARD:
    for key,_ in selector.select(.02):
     raw=os.read(key.fd,65536)
     if not raw:EOF[key.data]=True;selector.unregister(key.fileobj);continue
     assert counts[key.data]+len(raw)<=1048576,'original capture exceeds1MiB during drain'
     assert streams[key.data].write(raw)==len(raw);counts[key.data]+=len(raw)
  except BaseException as exc:fail('original_drain',exc)
  try:selector.close()
  except BaseException as exc:fail('selector_close',exc)
 if child is not None:
  for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
   if pipe is not None:
    try:pipe.close()
    except BaseException as exc:fail(name+'_pipe_close',exc)
 for name,stream in streams.items():
  for action in (stream.flush,lambda stream=stream:os.fsync(stream.fileno()),stream.close):
   try:action()
   except BaseException as exc:fail(name+'_capture_close',exc)
 if child is not None:
  if not reaped:fail('original_reap',RuntimeError('original timeout child not reaped'))
  if not all(EOF.values()):fail('original_EOF',RuntimeError('original capture EOF not observed'))
  originals=[timeout_owner or {'pid':child.pid,'pgid':child.pid,'startticks':None}]
  if timeout_owner is None:fail('original_owner',RuntimeError('original timeout owner not observed'))
  if actual is not None:originals.append(actual)
  else:fail('collector_owner',RuntimeError('original collector owner not observed'))
  for index in range(2):
   scans=[]
   for original in originals:
    try:
     scan=scan_original_group(original,HARD);scans.append(scan)
     assert not scan['members'] and not scan['member_overflow'] and not scan['errors'] and not scan['error_overflow'] and scan['original_pid_identity']=='absent','original timeout/collector PID/group uncertain'
    except BaseException as exc:fail('process_scan'+str(index),exc)
   process_scans.append(scans)
 source_checks=[];pin_closes=[]
 for row in pins:
  try:
   assert row['fd'] is not None and row['descriptor'] is not None,'capture source acquisition incomplete'
   current=descriptor(row['path'],row['maximum']);info=os.fstat(row['fd'])
   assert current==row['descriptor'] and current['epoch7']==[info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns]
   source_checks.append({'path':str(row['path']),'verified':True})
   if row['path']==source:after=current
  except BaseException as exc:source_checks.append({'path':str(row['path']),'verified':False});fail('source_final:'+str(row['path']),exc)
 channels={}
 for name in ('stdout','stderr'):
  try:channels[name]=descriptor(here/('original-current95.'+name+'.raw'),1048576)
  except BaseException as exc:channels[name]=None;fail(name+'_channel_descriptor',exc)
 for row in pins:
  if row['fd'] is None:continue
  try:os.close(row['fd']);row['fd']=None;pin_closes.append({'path':str(row['path']),'closed':True})
  except BaseException as exc:pin_closes.append({'path':str(row['path']),'closed':False});fail('pin_close:'+str(row['path']),exc)
 try:
  fd_after=fd_count();assert fd_before is not None and fd_after==fd_before,'capture FD baseline not restored'
 except BaseException as exc:fail('capture_FD_baseline',exc)
 collector_companions_absent=not any(os.path.lexists(here/('decision28-current95-original-attempt01/'+name)) for name in ('failure.v1.json','late-failure.v1.json'))
 if not collector_companions_absent:fail('collector_failure_companion',RuntimeError('original collector failure/late companion present'))
 late=time.monotonic()>=HARD
 if late:fail('whole130s_before_terminal',TimeoutError('original current95 capture130s elapsed'))
 terminal_ref=None;terminal_failure=failure;terminal_count=len(cleanup_errors);terminal_overflow=error_overflow
 if capture_owned:
  try:
   terminal_ref=save('original-current95.capture-terminal.v1.json',{'schema_version':1,'kind':'original_current95_collection_capture_v1','argv':argv,
    'source_before':before,'source_after':after,'capture_owner':capture_owner,'timeout_owner':timeout_owner,'collector_owner':actual,'started_at_ns':started,'terminal_at_ns':time.time_ns(),
    'elapsed_s':time.monotonic()-START,'returncode':code,'original_child_reaped':reaped,'failure':failure,'cleanup_errors':cleanup_errors,'error_overflow':error_overflow,
    'signals':signals,'stdout':channels['stdout'],'stderr':channels['stderr'],'EOF':EOF,'process_scans':process_scans,
    'late_failure_absent':collector_companions_absent,
    'source_checks':source_checks,'pin_closes':pin_closes,'fd_before':fd_before,'fd_after':fd_after,'all_close_attempts_finished':True,
    'capture_fds_closed':fd_before is not None and fd_after==fd_before,'metadata_only_no_model_image_runtime_acceptance':True})
   print(json.dumps(terminal_ref),flush=True)
  except BaseException as exc:fail('capture_terminal_persist_or_report',exc)
 try:
  fd_after=fd_count();assert fd_before is not None and fd_after==fd_before,'capture final metadata FD baseline not restored'
 except BaseException as exc:fail('capture_post_terminal_FD',exc)
 if time.monotonic()>=HARD:
  if not late:fail('whole130s_after_terminal',TimeoutError('original current95 capture130s closed late'))
  late=True
 if capture_owned and (failure is not None or terminal_ref is None or failure!=terminal_failure or len(cleanup_errors)!=terminal_count or error_overflow!=terminal_overflow or late):
  try:save('original-current95.failure.v1.json',{'status':'failed_no_current95_grant','failure':failure,'terminal':terminal_ref,'late':late,
   'terminal_path':str(here/'original-current95.capture-terminal.v1.json'),'recent_errors':cleanup_errors[-8:],'error_overflow':error_overflow,
   'fd_before':fd_before,'fd_after':fd_after,'all_close_attempts_finished':True},late_metadata=True)
  except BaseException as exc:
   fail('capture_failure_companion',exc)
   try:print(json.dumps({'status':'failed_no_current95_grant','failure':failure,'companion_error':error(exc)}),file=sys.stderr,flush=True)
   except BaseException as report_exc:fail('capture_failure_report',report_exc)
 if capture_owned and time.monotonic()>=HARD and not late:
  late=True;fail('whole130s_after_companion',TimeoutError('original current95 capture130s final metadata elapsed'))
  try:save('original-current95.late.v1.json',{'status':'failed_no_current95_grant','failure':failure,'terminal':terminal_ref,'late':True},late_metadata=True)
  except BaseException as exc:fail('capture_late_companion',exc)
 if not capture_owned:
  try:print(json.dumps({'status':'failed_no_current95_grant','failure':failure,'capture_namespace_owned':False}),file=sys.stderr,flush=True)
  except BaseException as exc:fail('capture_unowned_report',exc)
sys.exit(0 if failure is None and code==0 and not late else 1)
''','capture')

def facts(path,raw=None):
    raw=path.read_bytes() if raw is None else raw
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

ACTUAL_B='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
closed_host_dir=HERE.parent/'decision28-stock-host-original-copy-v1'
closed_host=json.loads((closed_host_dir/'root-original-closure.v1.json').read_bytes())
host_execution=json.loads((closed_host_dir/'execution.v1.json').read_bytes())
host_receipt_raw=(closed_host_dir/'execution-code-closure.ext4-decision28.v4.json').read_bytes()
host_receipt=json.loads(host_receipt_raw)
assert len(host_receipt_raw)==30266 and hashlib.sha256(host_receipt_raw).hexdigest()=='3c91339d43f6154dd76afe8a89c02d82f60a4b1e5da16623039f691fdc6701f2'
unsigned=dict(host_receipt);del unsigned['receipt_sha256']
assert hashlib.sha256(json.dumps(unsigned,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()==host_receipt['receipt_sha256']=='792f7c8369f2aced26fe5b32282999cb625ed168e20df5e8f40ed369d6e8b754'
assert closed_host['source_commit_B']==host_execution['source_commit']==ACTUAL_B
assert (closed_host_dir/'source-head.stdout.raw').read_bytes()==(ACTUAL_B+'\n').encode()
assert closed_host['original_tool_exit_code']==0 and closed_host['blocking_findings']==[] and closed_host['FD_before_after']==[6,6]
assert closed_host['dispatch_bookkeeping_failure_retained'] is True and closed_host['pre_dispatch_grant_file_claimed'] is False
assert host_execution['status']=='captured' and host_execution['primary_error'] is None and host_execution['additional_errors']==[] and host_execution['error_overflow']==0
assert host_execution['fd_before']==host_execution['fd_after']==6 and host_execution['all_pin_close_attempts_finished'] is True
assert host_execution['before']==host_execution['after'] and len(host_execution['before'])==87
assert len(host_execution['held_source_checks'])==len(host_execution['pin_closes'])==89
assert all(row['verified'] is True for row in host_execution['held_source_checks']) and all(row['closed'] is True for row in host_execution['pin_closes'])
assert len(host_execution['commands'])==2
for command in host_execution['commands']:
    assert command['returncode']==0 and command['reaped'] is True and command['EOF']=={'stdout':True,'stderr':True}
    assert command['errors']==[] and command['error_overflow']==0 and command['fd_before']==command['fd_after']
    assert len(command['process_group_scans'])==2
    for scan in command['process_group_scans']:
        assert scan['original_pid_identity']=='absent' and scan['members']==[] and scan['member_overflow']==0 and scan['errors']==[] and scan['error_overflow']==0
for row in closed_host['retained_originals']:
    retained=ROOT/row['retained_path'];actual=facts(retained)
    assert actual['size_bytes']==row['size_bytes'] and actual['sha256']==row['sha256']
closed_host_evidence=[facts(closed_host_dir/name) for name in ('root-original-closure.v1.json','execution.v1.json','execution-code-closure.ext4-decision28.v4.json','source-head.stdout.raw','source-head.terminal.v1.json','stock-closure.terminal.v1.json')]
old_text=original.decode()
loader_block=lambda text:text[text.index(" sys.path.insert(0,str(ROOT/'scripts'))"):text.index(' rows=[]')]
assert loader_block(old_text)==loader_block(collector)
source_snapshot_block=lambda text:text[text.index(" snapshot_keys="):text.index('except BaseException as exc:',text.index(" snapshot_keys="))]
assert source_snapshot_block(old_text)==source_snapshot_block(collector)
fixed_roles=('capability_manifest_path','calibration_path','model_parity_receipt_path','worker_freeze_receipt_path')
role_values=lambda text:next(ast.literal_eval(node.value) for node in ast.parse(text).body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='EXPECTED_ROLE_SHA' for target in node.targets))
assert all(role_values(old_text)[role]==role_values(collector)[role] for role in fixed_roles)

audits=[]
for kind,old,text,name in [('collector',original,collector,'collect_current95_v1.py'),('capture',capture_original,capture,'capture_original_current95_v1.py')]:
    inverse=text
    for row in reversed(changes[kind]):
        assert inverse.count(row['after'])==1
        inverse=inverse.replace(row['after'],row['before'],1)
    assert inverse.encode()==old
    old_tree,new_tree=ast.parse(old),ast.parse(text)
    functions=lambda tree:{x.name:ast.dump(x,include_attributes=False) for x in ast.walk(tree) if isinstance(x,ast.FunctionDef)}
    old_funcs,new_funcs=functions(old_tree),functions(new_tree)
    argv_assignments=lambda tree:[ast.dump(node,include_attributes=False) for node in ast.walk(tree) if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='argv' for target in node.targets)]
    assert argv_assignments(old_tree)==argv_assignments(new_tree)
    popen_calls=lambda tree:[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='subprocess' and node.func.attr=='Popen']
    old_popen,new_popen=popen_calls(old_tree),popen_calls(new_tree)
    assert len(old_popen)==len(new_popen)==1
    if kind=='capture':
        for keyword in new_popen[0].keywords:
            if keyword.arg in ('stdout','stderr'):keyword.value=ast.Name(id=keyword.arg,ctx=ast.Load())
    assert ast.dump(old_popen[0],include_attributes=False)==ast.dump(new_popen[0],include_attributes=False)
    audits.append({'kind':kind,'exact_raw_inverse':True,'literal_replacement_count':len(changes[kind]),
        'unchanged_original_functions':[x for x in old_funcs if old_funcs[x]==new_funcs.get(x)],
        'changed_original_functions':[x for x in old_funcs if old_funcs[x]!=new_funcs.get(x)],
        'removed_original_functions':[x for x in old_funcs if x not in new_funcs],
        'added_functions':[x for x in new_funcs if x not in old_funcs],
        'original_all_argv_assignment_ASTs_unchanged':True,'Popen_AST_exact_except_capture_stdout_stderr_pipe_plumbing':True})
    with (HERE/name).open('xb') as stream:assert stream.write(text.encode())==len(text.encode())
    with (HERE/(kind+'.source.diff')).open('xb') as stream:stream.write(''.join(difflib.unified_diff(old.decode().splitlines(True),text.splitlines(True),fromfile='immutable-original-current95',tofile='decision28-custody-successor')).encode())
    with (HERE/('original-'+kind+'.raw')).open('xb') as stream:stream.write(old)
with (HERE/'literal-replacements.v1.json').open('xb') as stream:stream.write((json.dumps(changes,sort_keys=True,indent=2)+'\n').encode())
template={'schema_version':1,'artifact_kind':'vast_current95_collection_binding_v1','source_commit':None,
    'project_root':'/home/s-a-balashov/work/vast-component-release-20260930-d27','stock_closure_descriptor':None,'current_controller_descriptor':None,'role_descriptors':None}
with (HERE/'collection.binding.template.v1.json').open('xb') as stream:stream.write((json.dumps(template,sort_keys=True,indent=2)+'\n').encode())
sources=[facts(HERE/name) for name in ('collect_current95_v1.py','capture_original_current95_v1.py')]
prep={'schema_version':1,'scope':'Unexecuted Decision28 current95 metadata collector and original capture; no CI/model/engine/scientific grant.',
    'planning_commit':'958a036bc5a55821c712204577fdf4c51c2181c7','source_checkpoint_A':'2a6a42c924ae3447ceda4bd9d1b6db33765c6466',
    'actual_source_commit_B':ACTUAL_B,'actual_stock_host_v4_descriptor':{'path':'/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json','size_bytes':30266,'sha256':'3c91339d43f6154dd76afe8a89c02d82f60a4b1e5da16623039f691fdc6701f2','sealed_sha256':host_receipt['receipt_sha256']},
    'actual_stock_host_closed_evidence':closed_host_evidence,'historical_dispatch_bookkeeping_failure_retained_no_prior_grant_claim':True,
    'future_binding_descriptor':None,'future_manifest':None,'future_owner':None,'future_terminal':None,
    'source_descriptors':sources,'original_sources':[facts(OLD/name) for name in ('collect_current95_v1.py','capture_original_current95_v1.py')],
    'actual_image_id':'sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1',
    'actual_runtime_receipt':{'root_relative_path':'artifacts/benchmark_recovery_20260930/decision28-gstreamer-build-2a6a42c9-v1/gstreamer_custom.runtime.freeze.json','size_bytes':7001,'sha256':'0b8a34e67773572a27885b931c50427de8bbd59b23eba837c5d2319ea7e9abca','sealed_sha256':'8dbd48381495beddc23abab774055ebb3ce89af7f8d56901580da2612092e093'},
    'final_CPU08_controller':facts(HERE.parent/'decision28-host-cpu08-final-binding-v1/run_original_cpu_component_pair_ext4_decision28_v4.py'),
    'fresh_host_role':'artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json',
    'composition':{'role_documents':6,'fresh_project_sources':87,'canonical_interpreter':1,'exact_current_controller':1,'unique_total':95},
    'bounds':{'work_s':120,'cleanup_s':10,'outer_capture_s':130,'metadata_and_capture_channel_bytes':1048576,'input_leaf_bytes':16*1048576,'input95_aggregate_bytes':64*1048576,'Git_stdout_bytes':128,'Git_stderr_bytes':0,'failure_companion_bytes':65536},
    'stock_loader_body_and_fresh_source_interpreter_snapshot_checks_unchanged':True,'four_fixed_original_role_pins_unchanged':True,'no_historical_epoch_rows_reused':True,
    'binding_schema_and_original_two_size_SHA_arguments_unchanged':True,'binding_template':facts(HERE/'collection.binding.template.v1.json'),
    'collector_command_pending':['/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python','-I','-B','/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/'+sources[1]['path'],None,None],
    'status':'prepared_unexecuted_requires_independent_source_review_actual_size_SHA_binding_and_once_only_observation_grant'}
with (HERE/'preparation.v1.json').open('xb') as stream:stream.write((json.dumps(prep,sort_keys=True,indent=2)+'\n').encode())
author={'schema_version':1,'scope':'Source-only author static audit; independent ROOT review required.','source_descriptors':sources,'audits':audits,
    'preparation':facts(HERE/'preparation.v1.json'),'literal_ledger':facts(HERE/'literal-replacements.v1.json'),
    'actual_closed_stock_evidence':closed_host_evidence,'actual_source_commit_B':ACTUAL_B,
    'original_stock_loader_call_and87_cardinality_block_exact':True,'fresh87_interpreter_controller95_snapshot_manifest_block_exact':True,'four_fixed_role_SHA_values_exact':True,
    'original_metadata_only_author_and_source_reviews':[facts(OLD/'source-preparation.v1.json'),facts(OLD/'actual-current95-setup-author-review.v1.json'),facts(HERE.parent/'component-current95-ci-successor-independent-source-review-v1/review.v1.json')],
    'target_helpers_imported_compiled_executed':False,'tests_Git_engine_model_hardware_or_CI_operations':False,'metadata_handles_released':True,
    'concrete_inherited_gaps_repaired':['Partial acquisitions register FDs before risky observations.','First cause latched before cleanup; every close attempted independently.','Original Git-head channels remain128/empty and prove EOF/reap/two zero-error scans.','Source/current95 full SHA and fresh seven-field epochs checked while held.','FD baseline restored before and after receipt publication.','Manifest and terminal after held/ancestor release; late/exclusive failure companion denies grant.','Outer capture retains argv120+10, bounded raw pipes, held source epochs and original timeout/collector identities.'],
    'limits':['Actual B and v4 stock-host descriptors joined only from retained genuinely closed ROOT evidence; no new current95/owner/terminal fact exists.','collection.bound.v1.json is uncreated; its original seven-field schema and two physical size/SHA arguments require controlled ROOT binding after independent source review.','No setup or full CI changes; metadata95 is not model/image/runtime/benchmark acceptance.']}
with (HERE/'author-review.v1.json').open('xb') as stream:stream.write((json.dumps(author,sort_keys=True,indent=2)+'\n').encode())
assert (OLD/'collect_current95_v1.py').read_bytes()==original and (OLD/'capture_original_current95_v1.py').read_bytes()==capture_original
print(json.dumps({'source_descriptors':sources,'audits':audits,'preparation':facts(HERE/'preparation.v1.json'),'author':facts(HERE/'author-review.v1.json')},indent=2))
