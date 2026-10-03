import pathlib,os,sys,json,hashlib,time,subprocess,signal,threading
ROOT=pathlib.Path(__file__).resolve().parents[3]
OUT=pathlib.Path(__file__).resolve().parent/sys.argv[1]
OUT.mkdir(exist_ok=False)
NAMES=['scripts/publication_gstreamer_component_inputs_v1.py','scripts/publication_gstreamer_component_cli_v1.py','scripts/publication_gstreamer_component_runtime_v1.py','tests/test_publication_gstreamer_component_inputs_v1.py','tests/test_publication_gstreamer_component_cli_v1.py','tests/test_publication_gstreamer_component_runtime_v1.py']
def pins():
 return {n:{'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n in NAMES for b in [(ROOT/n).read_bytes()]}
def save(n,x):
 p=OUT/n
 with p.open('xb') as f:f.write(json.dumps(x,sort_keys=True,indent=2).encode()+b'\n');f.flush();os.fsync(f.fileno())
before=pins();ids=sys.argv[2:]
entry="import sys,unittest;sys.path[:0]="+repr([str(ROOT/'tests'),str(ROOT/'scripts')])+";s=unittest.defaultTestLoader.loadTestsFromNames("+repr(ids)+");r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() else 1)"
argv=[sys.executable,'-I','-B','-c',entry];save('dispatch.json',{'argv':argv,'original_ids':ids,'source_before':before,'timeout_s':120,'classification':'local controlled unit fixtures only'})
start=time.monotonic();child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
stat=(pathlib.Path('/proc')/str(child.pid)/'stat').read_text();save('started.json',{'pid':child.pid,'pgid':os.getpgid(child.pid),'startticks':int(stat.rsplit(')',1)[1].split()[19]),'parent_pid':os.getpid()})
errors=[];counts={};lock=threading.Lock()
def drain(name,stream):
 try:
  with (OUT/(name+'.bin')).open('xb') as f:
   total=0
   while b:=stream.read(8192):
    if total+len(b)>1024*1024:raise RuntimeError('unit channel exceeds1MiB')
    f.write(b);f.flush();total+=len(b)
   os.fsync(f.fileno());counts[name]=total
 except BaseException as e:
  with lock:errors.append(type(e).__name__+': '+str(e))
 finally:stream.close()
threads=[threading.Thread(target=drain,args=(n,getattr(child,n)),daemon=True) for n in ['stdout','stderr']]
for t in threads:t.start()
timed=False
while child.poll() is None:
 if errors or time.monotonic()-start>120:
  timed=time.monotonic()-start>120;os.killpg(child.pid,signal.SIGKILL);break
 time.sleep(.02)
rc=child.wait(timeout=10)
for t in threads:t.join(timeout=5)
after=pins();channels={n:{'size_bytes':(OUT/(n+'.bin')).stat().st_size,'sha256':hashlib.sha256((OUT/(n+'.bin')).read_bytes()).hexdigest()} for n in ['stdout','stderr']}
members=[]
for p in pathlib.Path('/proc').iterdir():
 if p.name.isdigit():
  try:
   fields=(p/'stat').read_text().rsplit(')',1)[1].split()
   if int(fields[2])==child.pid:members.append(int(p.name))
  except (OSError,ValueError):pass
save('execution.json',{'argv':argv,'original_ids':ids,'original_pid':child.pid,'original_pgid':child.pid,'returncode':rc,'timed_out':timed,'elapsed_s':time.monotonic()-start,'channels':channels,'capture_errors':errors,'readers_alive':any(t.is_alive() for t in threads),'process_group_members_after':members,'original_pid_absent':not (pathlib.Path('/proc')/str(child.pid)).exists(),'source_before':before,'source_after':after,'source_stable':before==after})
print(json.dumps({'out':str(OUT),'rc':rc,'elapsed_s':time.monotonic()-start,'capture_errors':errors,'group_members':members}));sys.exit(rc if not timed and not errors and before==after and not members else 99)
