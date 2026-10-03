"""One read-only original-envelope query; historical availability is not acceptance."""
import hashlib,json,os,re,selectors,signal,stat,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
PAIR=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-07'
OUT=HERE/'original-observation-attempt01'
ENGINE=Path('/usr/bin/docker'); SOCKET=Path('/run/docker.sock')
ENGINE_SHA='a429e235ef670ea83357a5c8c7451f0a69d485a6fee49f9032fd938a0ab4969d'
ENGINE_SIZE=45570705
LIFECYCLE='f5a8e4aa391f4df1b51562e60271fb07'
START_NS=1790823221323071118; END_NS=1790823586186876374
INPUTS={
 'component_cli_terminal.v1.json':None,
 'guardian/service_lifecycle.v1.json':'103e648055b54d1d901e807bc73bab1a6dc1833548aeab99bca0fd72bc2f8a0a',
 'guardian/service_authority.v1.json':'5834435d3f80ae8c72b4d1271bf6bf09261fac4be47fb2a41f7f95898515cc80',
 'guardian/protocol_failure_diagnostic.v1.json':'41c930a0f93d828dcb90116bd8fb31eca7cf83c5efb54f824c2c3b05b3c71e2c'}
NAMES={f'vast-gst-analytics-{LIFECYCLE[:16]}-{branch.replace("_","-")}-{resource}':
 {'branch':branch,'resource':resource,'image_id':image}
 for branch in ('plate_number','vehicle_type','damage','foreign_object')
 for resource,image in (('cpu','sha256:ce138982695ea6d8218a9137bb858090a782e83e687be8fc252a32dc0bd9d5f9'),
 ('gpu','sha256:e0af692307f5edebcfb768d6805cb2e76f32948e77144fbf5f10fcdac85b2870'))}
FORMAT='{"type":{{json .Type}},"action":{{json .Action}},"id":{{json .Actor.ID}},"name":{{json (index .Actor.Attributes "name")}},"image":{{json (index .Actor.Attributes "image")}},"exit_code":{{json (index .Actor.Attributes "exitCode")}},"signal":{{json (index .Actor.Attributes "signal")}},"time_ns":{{.TimeNano}}}'
ARGV=['ENGINE_FD','--host','unix:///run/docker.sock','events','--since','1790823221.323071118',
 '--until','1790823586.186876374','--filter','type=container']
for name in sorted(NAMES): ARGV+=['--filter','container='+name]
ARGV+=['--format',FORMAT]
START=time.monotonic();DEADLINE=START+30; HARD=DEADLINE+10
primary=None;additional=[];held=[];ancestors=[];child=None;child_owner=None;signals=[];output_owned=False
counts={'stdout':0,'stderr':0};caps={'stdout':65536,'stderr':16384};handles={};selector=None
timed_out=False;overflow=False;eof={'stdout':False,'stderr':False};records=[];validation_errors=[];scans=[]
fd_before=len(list(Path('/proc/self/fd').iterdir()))
selector=selectors.DefaultSelector()

def epoch(v): return [v.st_dev,v.st_ino,v.st_mode,v.st_nlink,v.st_size,v.st_mtime_ns,v.st_ctime_ns]
def latch(exc):
 global primary
 fact={'type':type(exc).__name__,'message':str(exc)[:4096]}
 if primary is None:primary=fact
 else:additional.append(fact)
def clock():
 if time.monotonic()>=DEADLINE:raise TimeoutError('whole observation30s work deadline')
def write(name,value):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode('ascii');assert len(raw)<=262144
 with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def descriptor(path,limit):
 p=Path(path);v=p.lstat();assert stat.S_ISREG(v.st_mode) and v.st_nlink==1 and not p.is_symlink() and v.st_size<=limit
 h=hashlib.sha256();n=0
 with p.open('rb') as f:
  while block:=f.read(1048576):clock();h.update(block);n+=len(block)
 assert epoch(v)==epoch(p.lstat()) and n==v.st_size
 return {'path':str(p),'size_bytes':n,'sha256':h.hexdigest()}
def hold(path,expected=None,limit=65536):
 p=Path(path);assert p.is_absolute() and p.resolve(strict=True)==p
 for parent in reversed(p.parents):
  if any(row[0]==parent for row in ancestors):continue
  v=parent.lstat();assert stat.S_ISDIR(v.st_mode) and not parent.is_symlink()
  fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
  assert (v.st_dev,v.st_ino,v.st_mode)==(os.fstat(fd).st_dev,os.fstat(fd).st_ino,os.fstat(fd).st_mode)
  ancestors.append((parent,fd,[v.st_dev,v.st_ino,v.st_mode]))
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  d=descriptor(p,limit);e=epoch(os.fstat(fd));assert e==epoch(p.lstat())
  if expected is not None:assert d['sha256']==expected
  held.append((p,fd,e,d,limit));return fd,d
 except BaseException:os.close(fd);raise

def owner(pid):
 raw=Path(f'/proc/{pid}/stat').read_text();values=raw.rsplit(')',1)[1].split()
 status=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
 return {'pid':pid,'ppid':int(values[1]),'pgid':int(values[2]),'startticks':int(values[19]),
  'state':values[0],'uid':int(status['Uid'].split()[0]),'gid':int(status['Gid'].split()[0]),
  'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def scan():
 matches=[]
 if child is not None:
  for p in Path('/proc').iterdir():
   if not p.name.isdigit():continue
   try:
    v=owner(int(p.name))
    if v['pgid']==child.pid:matches.append(v)
   except (OSError,ValueError,IndexError):pass
 return {'at_ns':time.time_ns(),'original_pid':None if child is None else child.pid,'group_members':matches}

try:
 assert not os.path.lexists(OUT),'observation namespace already exists'
 OUT.mkdir(mode=0o700);output_owned=True
 inputs={}
 for relative,sha in INPUTS.items():
  fd,d=hold(PAIR/relative,sha);inputs[relative]=d
 terminal=json.loads((PAIR/'component_cli_terminal.v1.json').read_bytes())
 authority=json.loads((PAIR/'guardian/service_authority.v1.json').read_bytes())
 assert terminal['started_at_ns']==START_NS and terminal['terminal_at_ns']==END_NS
 assert authority['lifecycle_id']==LIFECYCLE and authority['worker_count']==8
 assert authority['worker_image_ids']=={'cpu':NAMES[next(n for n,v in NAMES.items() if v['resource']=='cpu')]['image_id'],
  'gpu':NAMES[next(n for n,v in NAMES.items() if v['resource']=='gpu')]['image_id']}
 _,self_pin=hold(Path(__file__),limit=65536)
 engine_fd,engine=hold(ENGINE,ENGINE_SHA,ENGINE_SIZE);assert engine['size_bytes']==ENGINE_SIZE
 socket=SOCKET.lstat();assert SOCKET.resolve(strict=True)==SOCKET and stat.S_ISSOCK(socket.st_mode)
 socket_pin=[socket.st_dev,socket.st_ino,socket.st_mode,socket.st_uid,socket.st_gid]
 assert socket_pin[:2]==[61,1944],'original engine socket physical identity differs'
 argv=list(ARGV);argv[0]=f'/proc/self/fd/{engine_fd}'
 write('dispatch.v1.json',{'argv':argv,'controller':owner(os.getpid()),'engine':engine,'socket':socket_pin,
  'input_descriptors':inputs,'observer_source':self_pin,'names':NAMES,'start_ns':START_NS,'end_ns':END_NS,
  'command_seconds':2,'whole_work_seconds':30,'cleanup_seconds':10,'channel_caps':caps,
  'scope':'one read-only selected-name historical event query; no original daemon-ID witness available'})
 for name in counts:handles[name]=(OUT/(name+'.raw')).open('xb')
 clock();command_deadline=min(DEADLINE,time.monotonic()+2);child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
  pass_fds=(engine_fd,),start_new_session=True)
 try:
  try:child_owner=owner(child.pid)
  except (OSError,ValueError,IndexError) as exc:latch(exc)
  write('launch.v1.json',{'argv':argv,'original_child_pid':child.pid,'owner':child_owner,'at_ns':time.time_ns()})
  for name,pipe in (('stdout',child.stdout),('stderr',child.stderr)):
   os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,name)
  while selector.get_map() or child.poll() is None:
   if time.monotonic()>=command_deadline:timed_out=True;raise TimeoutError('original event command2s elapsed')
   for key,_ in selector.select(.02):
    raw=os.read(key.fd,65536)
    if not raw:eof[key.data]=True;selector.unregister(key.fileobj);continue
    room=caps[key.data]-counts[key.data];retained=raw[:max(0,room)]
    if retained:handles[key.data].write(retained);counts[key.data]+=len(retained)
    if len(raw)>room:overflow=True;raise ValueError('original query channel cap exceeded')
  child.wait(timeout=max(.001,command_deadline-time.monotonic()))
  if child.returncode!=0:raise ValueError('original event query returned'+str(child.returncode))
 finally:
  if child.poll() is None:
   child.terminate();signals.append({'signal':'SIGTERM','at_ns':time.time_ns()})
   try:child.wait(timeout=min(2,max(.001,HARD-time.monotonic())))
   except subprocess.TimeoutExpired:
    child.kill();signals.append({'signal':'SIGKILL','at_ns':time.time_ns()});child.wait(timeout=max(.001,HARD-time.monotonic()))
  while selector.get_map() and time.monotonic()<HARD:
   for key,_ in selector.select(.02):
    raw=os.read(key.fd,65536)
    if not raw:eof[key.data]=True;selector.unregister(key.fileobj);continue
    room=caps[key.data]-counts[key.data];retained=raw[:max(0,room)]
    if retained:handles[key.data].write(retained);counts[key.data]+=len(retained)
    if len(raw)>room:overflow=True;latch(ValueError('original drain channel cap'))
  if not all(eof.values()):latch(ValueError('original query EOF incomplete'))
except BaseException as exc:latch(exc)
finally:
 selector.close()
 if child is not None:
  for pipe in (child.stdout,child.stderr):
   if pipe is not None:pipe.close()
 for stream in handles.values():
  try:stream.flush();os.fsync(stream.fileno())
  except OSError as exc:latch(exc)
  finally:stream.close()
 if output_owned:
  if child is not None and child.returncode==0 and not overflow and not timed_out:
   try:
    raw=(OUT/'stdout.raw').read_bytes();assert len(raw)<=65536
    for line in raw.splitlines():
     assert len(records)<256 and 0<len(line)<=4096
     v=json.loads(line)
     assert set(v)=={'type','action','id','name','image','exit_code','signal','time_ns'}
     assert v['type']=='container' and v['name'] in NAMES and re.fullmatch('[0-9a-f]{64}',v['id'])
     assert v['image']==NAMES[v['name']]['image_id'] and type(v['time_ns']) is int and START_NS<=v['time_ns']<=END_NS
     assert all(type(v[k]) is str and len(v[k])<=128 for k in ('action','exit_code','signal'))
     records.append(v)
   except BaseException as exc:validation_errors.append({'type':type(exc).__name__,'message':str(exc)[:4096]});latch(exc)
  for p,fd,e,d,limit in held:
   try:assert epoch(os.fstat(fd))==e==epoch(p.lstat()) and descriptor(p,limit)==d
   except BaseException as exc:latch(exc)
  if 'socket_pin' in globals():
   try:v=SOCKET.lstat();assert [v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_gid]==socket_pin
   except BaseException as exc:latch(exc)
  for p,fd,identity in ancestors:
   try:v=p.lstat();f=os.fstat(fd);assert [v.st_dev,v.st_ino,v.st_mode]==identity==[f.st_dev,f.st_ino,f.st_mode]
   except BaseException as exc:latch(exc)
 for _,fd,_,_,_ in held:os.close(fd)
 for _,fd,_ in ancestors:os.close(fd)
 if output_owned:
  scans=[scan(),scan()]
  if any(row['group_members'] for row in scans):latch(ValueError('original query process group remains'))
  fd_after=len(list(Path('/proc/self/fd').iterdir()))
  if fd_after!=fd_before:latch(ValueError('observer file descriptors not released'))
  channels={}
  for name in counts:
   p=OUT/(name+'.raw')
   if p.exists():
    r=p.read_bytes();channels[name]={'path':str(p),'size_bytes':len(r),'sha256':hashlib.sha256(r).hexdigest()}
  report=write('execution.v1.json',{'status':'observed' if primary is None else 'failed_observation',
   'original_pid':None if child is None else child.pid,'owner':child_owner,
   'returncode':None if child is None else child.returncode,'timed_out':timed_out,'overflow':overflow,'eof':eof,
   'failure':primary,'additional_errors':additional,'signals':signals,'channels':channels,'events':records,
   'validation_errors':validation_errors,'process_scans':scans,'fd_before':fd_before,'fd_after':fd_after,
   'elapsed_s':time.monotonic()-START,'accepted':False,'publication_ready':False,
   'limitations':['only last256 daemon events available; empty is not proof of no death/OOM',
   'query is later historical daemon observation, not original contemporaneous worker terminal',
   'original daemon-ID witness absent; pinned CLI and same original socket observed',
   'die137 alone cannot prove OOM; causal ordering requires exact name/image/CID/time and oom event']})
  print(json.dumps({'report':report,'failure':primary}),flush=True)
  if time.monotonic()>=DEADLINE:
   write('late-failure.v1.json',{'status':'failed','original_report':report,'elapsed_s':time.monotonic()-START})
   latch(TimeoutError('final whole observation30s deadline exceeded'))
sys.exit(0 if primary is None else 78)