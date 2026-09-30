"""One saved external capture for the reviewed artifact-v3 attempt03; no automatic retry.

The single 600s deadline starts before preflight and never restarts at Popen.
Any later containment is failed teardown, not additional research time/acceptance.
The original source controller owns Docker cleanup; host PID absence proves none of it.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time

PYTHON='/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
PLANNING='a84e0e734678aa9ecc9e0a4f16dcc3036c5c8f02'
RECOVERY='artifacts/benchmark_recovery_20260930'
CHANNEL=1024*1024
CODE={
 'README.md':(12345,'f78efe8f031aa614d90c05f2158bb7810ca9de778cced002076fb9f7f6d55261'),
 'controller.py':(36891,'f886bc344e526db320dedeb7c999561811f06840b0ebab9495628deaa02951c8'),
 'guest_consumer.py':(49239,'1ed940a62b30c2527c5c9f76242e8d00d1461c792b6972e7fb573b7c9d31dc84'),
 'research_protocol.py':(23656,'206972dc7742f75ca354a27b20b312e6531952cc3cf94a2b8941c02eb9553124'),
 'test_pin_diagnostics_v3.py':(10773,'c7e917daa2e09f24625e7011924895b84ecd4baaa59439fab16bc396648d0c8d'),
 'test_research_protocol.py':(17449,'2dbcec646c9d641f93ccbac4b633ad3513f5e2eb37161f6f9abdb39717255a45'),
 'test_setup_v2.py':(17070,'f2b44bb02e30abfa502d61dcd754900149a009d62b51f7558839c9a760a79f23'),
}
CORE={
 'proposal.md':(12199,'a36ee79884363abaef0e356056db122a77392729637faeabcafdddba4a733ccd'),
 'design.md':(85520,'ec3a8db57a9cdb05717fe7791b1c5fff4ed6ab886f9d338a1763f0f089fa5d22'),
 'tasks.md':(44420,'efb80391a17644a668ca01382c7eb27380c58a4765d4522931da6b9aa4f327d4'),
 'specs/benchmark-launch-preparation/spec.md':(46296,'8250736c3b65e73ec5e2a4e63b19966146300f48ca73a0d107265a20a9276c63'),
}


def require(value,message):
 if not value:raise RuntimeError(message)


def canonical(value):
 return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def epoch(info):
 return [info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns]


def owner(pid):
 suffix=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
 fields=dict((row.split(':',1)[0],row.split()[1:]) for row in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in row)
 return {'pid':pid,'ppid':int(suffix[1]),'starttime_ticks':int(suffix[19]),
  'uid':int(fields['Uid'][0]),'gid':int(fields['Gid'][0]),
  'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
  'process_group_id':os.getpgid(pid),'session_id':os.getsid(pid)}


def descriptor(path):
 raw=path.read_bytes()
 return {'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def document(path,value):
 require(not path.exists(),'original external document already exists')
 raw=canonical(dict(value,sha256=hashlib.sha256(canonical(value)).hexdigest()))+b'\n'
 require(len(raw)<=65536,'external metadata64KiB cap')
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  view=memoryview(raw)
  while view:
   count=os.write(fd,view);require(count>0,'external metadata write made no progress');view=view[count:]
  os.fsync(fd)
 finally:os.close(fd)
 return descriptor(path)


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--project-root',required=True)
 parser.add_argument('--source-commit',required=True,help='Exact final reviewed implementation commit, not a branch/ref.')
 args=parser.parse_args()
 root=Path(args.project_root).resolve(strict=True)
 require(re.fullmatch('[0-9a-f]{40}',args.source_commit) is not None,'exact reviewed source commit required')
 require(sys.version_info[:3]==(3,12,3) and sys.executable==PYTHON and sys.flags.isolated==1 and sys.dont_write_bytecode,
  'invoke only pinned CPython3.12.3 -I -B')
 recovery=root/RECOVERY;require(recovery.is_dir() and not recovery.is_symlink(),'original recovery parent unavailable')
 research=recovery/'decoder-research-attempt-03'
 destination=recovery/'decoder-research-attempt03-original-controller'
 require(not research.exists() and not destination.exists(),'attempt03 namespace already consumed; no resume/retry')
 began=time.monotonic();deadline=began+600;started_at=time.time_ns()
 destination.mkdir(mode=0o700)  # This consumes this external attempt only when dispatched.
 failures=[];canceled=threading.Event();capture_exceeded=[];held=[];directories={}
 process=None;child=None;argv=None;launch=None;timed_out=False;containment=None
 python_fd=git_fd=None
 outputs={};threads=[];git_observations=[];sources=[];sources_after=[];all_sources_rechecked=False
 def interrupted(number,frame):
  failures.append('external original signal '+str(number));canceled.set()
 signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
 def hold(path,expected=None):
  require(time.monotonic()<deadline,'single original600s deadline during preflight')
  require(path.is_absolute() and not path.is_symlink(),'external held path must be actual nonsymlink file')
  for parent in reversed(path.parents):
   if parent not in directories:
    fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    info=os.fstat(fd);directories[parent]=(fd,(info.st_dev,info.st_ino,info.st_mode))
  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
  try:
   before=os.fstat(fd)
   require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=64*1024*1024,
    'external held regular single-link source cap')
   digest=hashlib.sha256();offset=0
   while block:=os.pread(fd,65536,offset):
    require(time.monotonic()<deadline,'original preflight/hash600s deadline');digest.update(block);offset+=len(block)
   desc={'path':str(path),'size_bytes':offset,'sha256':digest.hexdigest()}
   require(epoch(before)==epoch(os.fstat(fd))==epoch(path.lstat()),'source changed while held')
   if expected is not None:require((offset,desc['sha256'])==expected,'reviewed source physical bytes differ')
   row={'descriptor':desc,'epoch':epoch(before)};held.append((path,fd,row));return row
  except BaseException:os.close(fd);raise
 def verify_held():
  for path,fd,row in held:
   require(time.monotonic()<deadline,'original postflight/hash600s deadline')
   require(epoch(os.fstat(fd))==row['epoch']==epoch(path.lstat()),'held original source epoch changed')
   digest=hashlib.sha256();offset=0
   while block:=os.pread(fd,65536,offset):
    require(time.monotonic()<deadline,'original postflight/hash600s deadline');digest.update(block);offset+=len(block)
   require(digest.hexdigest()==row['descriptor']['sha256'],'held original source bytes changed')
  for path,(fd,identity) in directories.items():
   for info in (os.fstat(fd),path.lstat()):
    require((info.st_dev,info.st_ino,info.st_mode)==identity,'held original source ancestor changed')
 def git_blob(relative,commit,expected):
  git=['/usr/bin/git','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec',
   '--work-tree='+str(root)]
  for tail,limit in ((['cat-file','-s',commit+':'+relative],64),(['show',commit+':'+relative],expected[0])):
   require(time.monotonic()<deadline,'original Git preflight600s deadline')
   completed=subprocess.run(git+tail,stdin=subprocess.DEVNULL,capture_output=True,
    executable=f'/proc/self/fd/{git_fd}',pass_fds=(git_fd,),
    timeout=min(5,max(0.01,deadline-time.monotonic())))
   require(len(completed.stdout)<=limit and len(completed.stderr)<=4096,'bounded Git proof output cap')
   git_observations.append({'argv':git+tail,'returncode':completed.returncode,
    'stdout_size_bytes':len(completed.stdout),'stdout_sha256':hashlib.sha256(completed.stdout).hexdigest(),
    'stderr_size_bytes':len(completed.stderr),'stderr_sha256':hashlib.sha256(completed.stderr).hexdigest()})
   require(completed.returncode==0 and completed.stderr==b'','original reviewed Git blob unavailable')
   if tail[0]=='cat-file':require(completed.stdout==str(expected[0]).encode()+b'\n','reviewed Git blob size differs')
   else:require(hashlib.sha256(completed.stdout).hexdigest()==expected[1],'reviewed raw Git blob differs from physical source')
 def drain(stream,name):
  fd=outputs[name];written=0
  try:
   while True:
    if not select.select([stream.fileno()],[],[],0.1)[0]:continue
    raw=os.read(stream.fileno(),min(65536,CHANNEL-written+1))
    if not raw:break
    remaining=CHANNEL-written;retained=raw[:remaining]
    if retained:
     view=memoryview(retained)
     while view:
      size=os.write(fd,view);require(size>0,'original external channel made no write progress');view=view[size:]
     written+=len(retained)
    if len(raw)>remaining:
     capture_exceeded.append({'channel':name,'retained_bytes':written,
      'observed_unretained_bytes':len(raw)-remaining,'observed_unretained_sha256':hashlib.sha256(raw[remaining:]).hexdigest()})
     failures.append('original external channel1MiB cap exceeded');canceled.set();break
  except BaseException as exc:failures.append('original external pipe: '+str(exc));canceled.set()
 try:
  for name in ('original.stdout','original.stderr'):
   outputs[name]=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  interpreter=hold(Path(PYTHON).resolve(strict=True));python_fd=held[-1][1]
  hold(Path('/usr/bin/git').resolve(strict=True));git_fd=held[-1][1]
  code=root/RECOVERY/'decoder-research-implementation-v3'
  for name,expected in CODE.items():
   path=code/name;row=hold(path,expected);git_blob(path.relative_to(root).as_posix(),args.source_commit,expected);sources.append(row)
  for name,expected in CORE.items():
   path=root/'openspec/changes/fix-benchmark-preparations-spec'/name
   row=hold(path,expected);git_blob(path.relative_to(root).as_posix(),PLANNING,expected);sources.append(row)
  own=hold(Path(__file__).resolve(strict=True));git_blob(Path(__file__).resolve().relative_to(root).as_posix(),
   args.source_commit,(own['descriptor']['size_bytes'],own['descriptor']['sha256']))
  verify_held();require(not canceled.is_set() and not research.exists(),'dispatch canceled or research namespace consumed')
  argv=[PYTHON,'-I','-B',str(code/'controller.py'),'--project-root',str(root),'--output-dir',str(research)]
  launch=document(destination/'launch.v1.json',{'schema_version':1,
   'artifact_kind':'vast_decoder_research_external_original_controller_launch_v1','argv':argv,
   'source_commit':args.source_commit,'planning_commit':PLANNING,'controller':owner(os.getpid()),
   'started_at_ns':started_at,'single_deadline_monotonic_s':deadline,'sources':sources,
   'dispatch_source':own,'interpreter':interpreter,'git_observations':git_observations,
   'accepted':False,'publication_ready':False})
  process=subprocess.Popen(argv,executable=f'/proc/self/fd/{python_fd}',pass_fds=(python_fd,),
   stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  child=owner(process.pid);require(child['ppid']==os.getpid() and child['process_group_id']==process.pid,
   'original controller child/group owner mismatch')
  document(destination/'process-start.v1.json',{'schema_version':1,
   'artifact_kind':'vast_decoder_research_external_original_controller_started_v1','argv':argv,
   'child':child,'controller':owner(os.getpid()),'observed_at_ns':time.time_ns(),'accepted':False})
  for stream,name in ((process.stdout,'original.stdout'),(process.stderr,'original.stderr')):
   thread=threading.Thread(target=drain,args=(stream,name),daemon=True);thread.start();threads.append(thread)
  while process.poll() is None:
   if time.monotonic()>=deadline:timed_out=True;failures.append('single original600s deadline exceeded');break
   if canceled.is_set():break
   time.sleep(min(0.05,max(0,deadline-time.monotonic())))
  if timed_out or canceled.is_set():raise RuntimeError('original controller failed; containment only')
  process.wait(timeout=min(1,max(0.01,deadline-time.monotonic())))
  require(process.returncode==0,'original controller returned nonzero')
 except BaseException as exc:
  failures.append(str(exc))
 finally:
  if process is not None:
   if process.poll() is None:
    containment_start=time.monotonic();actions=[];containment_errors=[];containment_owner=None
    try:
     current=owner(process.pid)
     require(current['ppid']==os.getpid() and current['process_group_id']==process.pid and
      (child is None or all(current[key]==child[key] for key in ('pid','starttime_ticks','uid','gid','boot_id','process_group_id'))),
      'original PID custody changed; no signal to unknown owner')
     containment_owner=current  # Late current-owner fact stays separate if launch observation failed.
     os.kill(process.pid,signal.SIGTERM);actions.append('SIGTERM exact original controller PID')
     try:process.wait(timeout=15)
     except subprocess.TimeoutExpired:
      current=owner(process.pid)
      require(all(current[key]==containment_owner[key] for key in ('pid','starttime_ticks','uid','gid','boot_id','process_group_id')),
       'original PID custody changed before forced reap')
      os.kill(process.pid,signal.SIGKILL);actions.append('SIGKILL exact original controller PID');process.wait(timeout=2)
    except BaseException as exc:containment_errors.append(str(exc));failures.append('original containment: '+str(exc))
    containment={'started_monotonic_s':containment_start,'finished_monotonic_s':time.monotonic(),
     'current_owner':containment_owner,'actions':actions,'errors':containment_errors,'returncode':process.returncode,
     'scope':'Failed containment only; no Docker state/cleanup, OOM or quiescence inference'}
    if not failures:failures.append('original controller required external termination')
   for thread in threads:thread.join(timeout=1)
   if any(thread.is_alive() for thread in threads):failures.append('original external pipe EOF unresolved')
   for stream in (process.stdout,process.stderr):stream.close()
  for fd in outputs.values():
   try:os.fsync(fd)
   except OSError as exc:failures.append('original raw finalization: '+str(exc))
   finally:os.close(fd)
  try:
   verify_held();sources_after=[dict(row) for row in sources];all_sources_rechecked=True
  except BaseException as exc:failures.append('original postflight custody: '+str(exc))
  if time.monotonic()>=deadline:timed_out=True;failures.append('original600s finalization exceeded')
  successful=process is not None and process.returncode==0 and not failures and all_sources_rechecked
  terminal=document(destination/'terminal.v1.json',{'schema_version':1,
   'artifact_kind':'vast_decoder_research_external_original_controller_terminal_v1','source_commit':args.source_commit,
   'planning_commit':PLANNING,'argv':argv,'controller':owner(os.getpid()),'original_child':child,
   'original_controller_returncode':None if process is None else process.returncode,
   'started_at_ns':started_at,'finished_at_ns':time.time_ns(),'elapsed_s':time.monotonic()-began,
   'single_deadline_monotonic_s':deadline,'timed_out':timed_out,'capture_exceeded':capture_exceeded,
   'failures':failures,'containment':containment,'launch':launch,'sources_before':sources,'sources_after':sources_after,
   'all_source_epochs_rechecked':all_sources_rechecked,'stdout':descriptor(destination/'original.stdout'),
   'stderr':descriptor(destination/'original.stderr'),'external_capture_completed':successful,
   'container_cleanup_verified':False,'container_oom_observed':None,
   'scope':'Original CPython controller custody/capture only; provisional process completion. Independent raw cold replay required.',
   'accepted':False,'publication_ready':False,'research_conclusion_authorized':False})
  for _,fd,_ in reversed(held):os.close(fd)
  for fd,_ in directories.values():os.close(fd)
  late=None
  if time.monotonic()>=deadline:
   successful=False
   late=document(destination/'receipt-time-limit-failure.v1.json',{'schema_version':1,
    'artifact_kind':'vast_decoder_research_external_original_controller_late_terminal_v1',
    'original_terminal':terminal,'observed_after_close_monotonic_s':time.monotonic(),
    'single_deadline_monotonic_s':deadline,'failed':True,'accepted':False,'publication_ready':False})
  print(canonical({'receipt':terminal,'external_capture_completed':successful,'late_terminal':late}).decode(),flush=True)
 return 0 if successful else 1


if __name__=='__main__':sys.exit(main())
