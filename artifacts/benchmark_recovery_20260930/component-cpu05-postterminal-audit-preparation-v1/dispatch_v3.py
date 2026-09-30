"""One original finite CPU05 closed-boundary audit capture; no project imports."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).parent
argv=[sys.executable,'-I','-B',str(root/'audit_v3.py'),'603df9b501dfcd578aac0570eed08983c5ef8fc72c36a7980c19c23b480e310c','91708']
def descriptor(p):
 raw=p.read_bytes();return {'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,value):
 with (root/name).open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
started=time.time_ns();mono=time.monotonic();timeout=False
save('dispatch.launch.v3.json',{'argv':argv,'pid':os.getpid(),'ppid':os.getppid(),'started_at_ns':started,'source':descriptor(Path(__file__)),'reader':descriptor(root/'audit_v3.py'),'mode':'one read-only retained-output audit'})
with (root/'audit.stdout.v3.raw').open('xb') as stdout,(root/'audit.stderr.v3.raw').open('xb') as stderr:
 child=subprocess.Popen(argv,stdout=stdout,stderr=stderr,start_new_session=True)
 try:code=child.wait(timeout=135)
 except subprocess.TimeoutExpired:
  timeout=True;child.kill();code=child.wait(timeout=5)
 stdout.flush();os.fsync(stdout.fileno());stderr.flush();os.fsync(stderr.fileno())
terminal={'schema_version':1,'argv':argv,'original_child_pid':child.pid,'returncode':code,'timed_out':timeout,'elapsed_s':time.monotonic()-mono,'started_at_ns':started,'terminal_at_ns':time.time_ns(),'reader':descriptor(root/'audit_v3.py'),'stdout':descriptor(root/'audit.stdout.v3.raw'),'stderr':descriptor(root/'audit.stderr.v3.raw'),'original_child_reaped':True}
save('dispatch.terminal.v3.json',terminal)
print(json.dumps(terminal,sort_keys=True));sys.exit(0 if code==0 and not timeout else 1)