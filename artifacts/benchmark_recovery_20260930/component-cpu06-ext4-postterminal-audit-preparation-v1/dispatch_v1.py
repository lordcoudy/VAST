"""One original finite CPU06 closed-boundary audit capture; no project imports."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).parent
assert len(sys.argv)==4,'dispatch ORIGINAL_TERMINAL_SHA256 ORIGINAL_TERMINAL_SIZE ORIGINAL_CLI_PID'
assert len(sys.argv[1])==64 and all(c in '0123456789abcdef' for c in sys.argv[1])
assert sys.argv[2].isdigit() and 0<int(sys.argv[2])<=1048576 and sys.argv[3].isdigit() and int(sys.argv[3])>0
argv=[sys.executable,'-I','-B',str(root/'audit_v1.py'),*sys.argv[1:]]

def descriptor(p):
 raw=p.read_bytes();return {'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,value):
 with (root/name).open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
started=time.time_ns();mono=time.monotonic();timeout=False
save('dispatch.launch.v1.json',{'argv':argv,'pid':os.getpid(),'ppid':os.getppid(),'started_at_ns':started,'source':descriptor(Path(__file__)),'reader':descriptor(root/'audit_v1.py'),'mode':'one read-only retained-output audit'})
with (root/'audit.stdout.v1.raw').open('xb') as stdout,(root/'audit.stderr.v1.raw').open('xb') as stderr:
 child=subprocess.Popen(argv,stdout=stdout,stderr=stderr,start_new_session=True)
 try:code=child.wait(timeout=135)
 except subprocess.TimeoutExpired:
  timeout=True;child.kill();code=child.wait(timeout=5)
 stdout.flush();os.fsync(stdout.fileno());stderr.flush();os.fsync(stderr.fileno())
terminal={'schema_version':1,'argv':argv,'original_child_pid':child.pid,'returncode':code,'timed_out':timeout,'elapsed_s':time.monotonic()-mono,'started_at_ns':started,'terminal_at_ns':time.time_ns(),'reader':descriptor(root/'audit_v1.py'),'stdout':descriptor(root/'audit.stdout.v1.raw'),'stderr':descriptor(root/'audit.stderr.v1.raw'),'original_child_reaped':True}
save('dispatch.terminal.v1.json',terminal)
print(json.dumps(terminal,sort_keys=True));sys.exit(0 if code==0 and not timeout else 1)