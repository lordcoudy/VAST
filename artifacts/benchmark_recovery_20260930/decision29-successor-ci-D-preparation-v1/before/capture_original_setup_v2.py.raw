import hashlib,json,os,signal,stat,subprocess,sys,time
from pathlib import Path
here=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decision29-current-ci-preparation-v1')
source=here/'setup_original_current_ci_v2.py';python='/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
assert len(sys.argv)==3,'usage: capture ACTUAL_RECIPE_SIZE ACTUAL_RECIPE_SHA256'
argv=['/usr/bin/timeout','--signal=TERM','--kill-after=10s','300s',python,'-I','-B',str(source),*sys.argv[1:]]
def descriptor(p):
 raw=p.read_bytes();s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
 return {'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch7':[s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]}
def save(name,value):
 with (here/name).open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
def owner(pid):
 p=Path('/proc',str(pid));v=(p/'stat').read_text().rsplit(')',1)[1].split();status=dict(l.split(':',1) for l in (p/'status').read_text().splitlines() if ':' in l)
 return {'pid':pid,'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19]),'state':v[0],'uid':int(status['Uid'].split()[0]),'gid':int(status['Gid'].split()[0]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'argv':(p/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')}
def scan(ids):
 rows=[];errors=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   v=(p/'stat').read_text().rsplit(')',1)[1].split()
   if int(p.name) in ids or int(v[2]) in ids:rows.append(owner(int(p.name)))
  except FileNotFoundError:pass
  except (OSError,ValueError) as exc:errors.append({'pid':int(p.name),'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
 return {'at_ns':time.time_ns(),'members':rows,'errors':errors,'pids_absent':{str(p):not Path('/proc',str(p)).exists() for p in sorted(ids)}}
before=descriptor(source);assert before['size_bytes']==16786 and before['sha256']=='9aca35df5b1d4c87a555ac3d32d99c1a05b4772cf5bd841d778fec4e330ed3d3'
start=time.monotonic();started=time.time_ns();child=None;actual=None;failure=None;signals=[]
with (here/'original-setup.stdout.raw').open('xb') as stdout,(here/'original-setup.stderr.raw').open('xb') as stderr:
 child=subprocess.Popen(argv,stdout=stdout,stderr=stderr,start_new_session=True)
 timeout_owner=owner(child.pid);save('original-setup.capture-launch.v1.json',{'argv':argv,'capture_owner':owner(os.getpid()),'timeout_owner':timeout_owner,'source_before':before,'started_at_ns':started,'work_s':300,'cleanup_s':10})
 try:
  while child.poll() is None:
   for pid in (Path('/proc',str(child.pid),'task',str(child.pid),'children').read_text().split() if Path('/proc',str(child.pid)).exists() else []):
    try:
     candidate=owner(int(pid))
     if str(source) in candidate['argv']:actual=candidate
    except FileNotFoundError:pass
   if actual is not None and not (here/'original-setup.child-owner.v1.json').exists():save('original-setup.child-owner.v1.json',actual)
   if time.monotonic()-start>=310:raise TimeoutError('original outer310s')
   if os.fstat(stdout.fileno()).st_size>1048576 or os.fstat(stderr.fileno()).st_size>1048576:raise RuntimeError('original capture exceeds1MiB')
   time.sleep(.02)
  code=child.wait();assert actual is not None,'original setup owner not observed'
 except BaseException as exc:
  failure={'type':type(exc).__name__,'message':str(exc)[:4096]}
  if child.poll() is None:signals.append('SIGKILL');os.killpg(child.pid,signal.SIGKILL)
  code=child.wait(timeout=5)
 finally:stdout.flush();os.fsync(stdout.fileno());stderr.flush();os.fsync(stderr.fileno())
after=descriptor(source);assert after==before
ids={child.pid}
if actual is not None:ids.add(actual['pid'])
scans=[scan(ids),scan(ids)]
terminal={'schema_version':1,'kind':'original_current_source_ci_setup_capture_v1','argv':argv,'source_before':before,'source_after':after,'capture_owner':owner(os.getpid()),'timeout_owner':timeout_owner,'setup_owner':actual,'started_at_ns':started,'terminal_at_ns':time.time_ns(),'elapsed_s':time.monotonic()-start,'returncode':code,'original_child_reaped':True,'failure':failure,'signals':signals,'stdout':descriptor(here/'original-setup.stdout.raw'),'stderr':descriptor(here/'original-setup.stderr.raw'),'process_scans':scans,'late_failure_absent':not os.path.lexists(here/'original-setup-attempt01/late-failure.v1.json'),'capture_fds_closed':True}
save('original-setup.capture-terminal.v1.json',terminal);print(json.dumps(descriptor(here/'original-setup.capture-terminal.v1.json')),flush=True)
assert failure is None and code==0 and terminal['elapsed_s']<310 and terminal['late_failure_absent'] and all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)