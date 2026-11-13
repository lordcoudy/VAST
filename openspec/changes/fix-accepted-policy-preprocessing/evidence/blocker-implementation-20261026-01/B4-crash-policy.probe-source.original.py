import hashlib,json,os,resource,stat
from pathlib import Path
def read(path,cap):
 with Path(path).open("rb") as f: raw=f.read(cap+1)
 if len(raw)>cap: raise ValueError("read-only crash observation bound")
 return raw.decode("ascii").strip()
facts={"scope":"read_only_crash_policy_observation_not_qualification","boot_id":read("/proc/sys/kernel/random/boot_id",64)}
facts["kernel"]={name:read(path,4096) for name,path in (("release","/proc/sys/kernel/osrelease"),("core_pattern","/proc/sys/kernel/core_pattern"),("core_pipe_limit","/proc/sys/kernel/core_pipe_limit"),("suid_dumpable","/proc/sys/fs/suid_dumpable"),("pid_max","/proc/sys/kernel/pid_max"),("threads_max","/proc/sys/kernel/threads-max"))}
facts["observer"]={"uid":os.geteuid(),"core_limit":list(resource.getrlimit(resource.RLIMIT_CORE)),"coredump_filter":read("/proc/self/coredump_filter",64)}
pids=[]
with os.scandir("/proc") as entries:
 for index,entry in enumerate(entries):
  if index>=8192: raise ValueError("process observation count")
  if entry.name.isdecimal(): pids.append(entry.name)
rows=[]
for pid in pids:
 try: comm=read("/proc/"+pid+"/comm",64)
 except FileNotFoundError: continue
 if comm not in ("dockerd","containerd"): continue
 if len(rows)>=4: raise ValueError("ambiguous native daemon count")
 status=read("/proc/"+pid+"/status",16384)
 selected={line.split(":",1)[0]:line.split(":",1)[1].strip() for line in status.splitlines() if line.split(":",1)[0] in ("Name","Pid","PPid","Threads","VmRSS")}
 limits=read("/proc/"+pid+"/limits",8192)
 core=[line for line in limits.splitlines() if line.startswith("Max core file size")]
 if len(core)!=1: raise ValueError("core observation shape")
 rows.append({"pid":int(pid),"comm":comm,"status":selected,"core_limit_line":core[0],"coredump_filter":read("/proc/"+pid+"/coredump_filter",64)})
facts["claimed_daemon_names"]=rows
handler=Path("/usr/lib/wsl/lib/wsl-capture-crash")
if facts["kernel"]["core_pattern"].startswith("|/usr/lib/wsl/lib/wsl-capture-crash "):
 before=handler.stat(follow_symlinks=False)
 if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=16*1024**2: raise ValueError("handler kind/size")
 digest=hashlib.sha256();total=0
 with handler.open("rb") as stream:
  while raw:=stream.read(65536):
   total+=len(raw)
   if total>16*1024**2: raise ValueError("handler growth")
   digest.update(raw)
 after=handler.stat(follow_symlinks=False)
 identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns,row.st_ctime_ns)
 if identity(before)!=identity(after) or total!=before.st_size: raise ValueError("handler changed")
 facts["handler"]={"path":str(handler),"size_bytes":total,"sha256":digest.hexdigest()}
raw=json.dumps(facts,sort_keys=True,separators=(",",":"))
if len(raw)>4096: raise ValueError("crash observation output bound")
print(raw)