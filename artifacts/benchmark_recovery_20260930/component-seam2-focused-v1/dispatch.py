"""Original bounded local-fixture test process; no hardware acceptance."""
import hashlib, json, os, selectors, signal, subprocess, sys, time
from pathlib import Path
root=Path(sys.argv[1]); name=sys.argv[2]; out=Path(__file__).parent/name
out.mkdir(mode=0o700)
paths=["scripts/publication_guardian_component_preprocessing_contract_v1.py", "scripts/publication_guardian_runtime_expectations_v1.py", "scripts/checkpoint_gstreamer_analytics_sidecar.py", "scripts/publication_gstreamer_component_authority_v1.py", "tests/test_publication_guardian_component_preprocessing_contract_v1.py"]
def pins():
 return {p:{"size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()} for p in paths for raw in [(root/p).read_bytes()]}
def save(n,v):
 raw=json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n"
 (out/n).write_bytes(raw)
 return {"path":str(out/n),"size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
before=pins(); start=time.monotonic(); argv=[sys.executable,"-I","-B","-m","unittest","discover","-s","tests","-p",sys.argv[3],"-v"]
child=subprocess.Popen(argv,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
stat=Path(f"/proc/{child.pid}/stat").read_text(); ticks=int(stat[stat.rfind(")")+2:].split()[19])
launch=save("launch.v1.json",{"argv":argv,"pid":child.pid,"proc_stat_starttime_ticks":ticks,"pgid":os.getpgid(child.pid),"uid":os.getuid(),"gid":os.getgid(),"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"source_before":before,"fixture_only":True})
selector=selectors.DefaultSelector(); counts={"stdout":0,"stderr":0}; writers={n:(out/(n+".raw")).open("xb") for n in counts}; timed_out=False; exceeded=False
for n,pipe in (("stdout",child.stdout),("stderr",child.stderr)):
 os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,n)
try:
 while selector.get_map():
  if time.monotonic()-start>120:
   timed_out=True; os.killpg(child.pid,signal.SIGKILL);break
  for key,_ in selector.select(.1):
   raw=os.read(key.fd,65536)
   if not raw:selector.unregister(key.fileobj);continue
   n=key.data
   if counts[n]+len(raw)>1048576:
    exceeded=True;os.killpg(child.pid,signal.SIGKILL);break
   writers[n].write(raw);counts[n]+=len(raw)
  if exceeded:break
 child.wait(timeout=10)
finally:
 if child.poll() is None:
  os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=10)
 selector.close()
 for pipe in (child.stdout,child.stderr):pipe.close()
 for writer in writers.values():writer.flush();os.fsync(writer.fileno());writer.close()
after=pins()
terminal=save("terminal.v1.json",{"launch":launch,"returncode":child.returncode,"timed_out":timed_out,"capture_exceeded":exceeded,"elapsed_s":time.monotonic()-start,"source_after":after,"source_stable":before==after,"channels":{n:{"size_bytes":(out/(n+".raw")).stat().st_size,"sha256":hashlib.sha256((out/(n+".raw")).read_bytes()).hexdigest()} for n in counts},"fixture_only":True,"hardware_acceptance":False})
print(json.dumps(terminal));sys.exit(0 if child.returncode==0 and not timed_out and not exceeded and before==after else 1)
