import argparse,hashlib,json,os,selectors,signal,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--project-root',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--selection',choices=['red','green'],required=True);a=p.parse_args()
root=Path(a.project_root).resolve(strict=True);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=False)
paths=['scripts/ci_namespace_diagnostic_v1.py','tests/test_ci_namespace_diagnostic_v1.py','scripts/ci_external_test_observer_v1.py']
def pins():return {n:{'size_bytes':(root/n).stat().st_size,'sha256':hashlib.sha256((root/n).read_bytes()).hexdigest()} for n in paths}
def save(name,value):
 with (out/name).open('xb') as f:f.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());f.flush();os.fsync(f.fileno())
before=pins();save('source.before.json',before)
code=r"""import json,pathlib,shutil,sys,unittest
root=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2]);sys.path[:0]=[str(root/'tests'),str(root/'scripts'),str(root)]
import test_ci_namespace_diagnostic_v1 as module
original_helper=module.NamespaceDiagnosticTests.helper
parser=[]
def helper(self):
 loaded=original_helper(self);real=loaded.capture_original_child
 def capture(argv,output,deadline,**kwargs):
  result=real(argv,output,deadline,**kwargs)
  if '--help' in argv and any(pathlib.Path(arg).name=='journalctl' for arg in argv):
   group=out/('actual-parser-%02d'%len(parser));group.mkdir()
   for source in pathlib.Path(output).iterdir():
    if source.is_file():
     assert source.stat().st_size<=16*1024
     shutil.copyfile(source,group/source.name)
   parser.append({'capture':result,'snapshot':group.name})
  return result
 loaded.capture_original_child=capture
 return loaded
module.NamespaceDiagnosticTests.helper=helper
name='test_ci_namespace_diagnostic_v1.NamespaceDiagnosticTests.test_actual_journalctl_parser_accepts_original_query_options_without_reading_journals' if sys.argv[3]=='red' else 'test_ci_namespace_diagnostic_v1'
suite=unittest.defaultTestLoader.loadTestsFromName(name);result=unittest.TextTestRunner(verbosity=2).run(suite)
value={'tests_run':result.testsRun,'errors':[{'test_id':t.id(),'traceback':e} for t,e in result.errors],'failures':[{'test_id':t.id(),'traceback':e} for t,e in result.failures],'skips':[{'test_id':t.id(),'reason':e} for t,e in result.skipped],'successful':result.wasSuccessful(),'real_parser_captures':parser,'no_namespace_or_journal_read':True}
(out/'test-results.json').open('x').write(json.dumps(value,sort_keys=True,indent=2)+'\n');sys.exit(0 if result.wasSuccessful() else 1)
"""
argv=[sys.executable,'-I','-B','-c',code,str(root),str(out),a.selection];start=time.monotonic();deadline=start+60;proc=None;owner=None;failure=None;timed_out=False;channels={};sizes={'stdout':0,'stderr':0};eof={'stdout':False,'stderr':False};sel=selectors.DefaultSelector()
try:
 channels={n:(out/(n+'.raw')).open('xb') for n in sizes};proc=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 f=Path('/proc/'+str(proc.pid)+'/stat').read_text().rsplit(')',1)[1].split();owner={'pid':proc.pid,'pgid':os.getpgid(proc.pid),'startticks':int(f[19]),'uid':os.getuid(),'gid':os.getgid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};save('launch.json',{'argv':argv,'owner':owner,'python':sys.version,'selection':a.selection,'test_controller_cap_seconds':60,'started_monotonic':start})
 for n,pipe in [('stdout',proc.stdout),('stderr',proc.stderr)]:os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,n)
 while sel.get_map() or proc.poll() is None:
  if time.monotonic()>=deadline:timed_out=True;raise TimeoutError('original60s scoped fixture controller')
  for key,_ in sel.select(.02):
   block=os.read(key.fileobj.fileno(),4096);n=key.data
   if not block:eof[n]=True;sel.unregister(key.fileobj);continue
   allowed=max(0,16384-sizes[n]);retained=block[:allowed];channels[n].write(retained);sizes[n]+=len(retained)
   if len(retained)!=len(block):raise RuntimeError('original16KiB focused test channel cap')
except BaseException as e:failure=type(e).__name__+': '+str(e)
finally:
 cleanup=time.monotonic()+3
 try:
  if proc is not None and proc.poll() is None:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=max(0,cleanup-time.monotonic()-1))
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=max(0,cleanup-time.monotonic()))
 finally:
  sel.close()
  if proc is not None:proc.stdout.close();proc.stderr.close()
  for channel in channels.values():channel.flush();os.fsync(channel.fileno());channel.close()
after=pins();save('source.after.json',after);remaining=[]
if owner:
 for item in Path('/proc').iterdir():
  if not item.name.isdigit():continue
  try:
   f=(item/'stat').read_text().rsplit(')',1)[1].split()
   if int(f[2])==owner['pgid']:remaining.append(int(item.name))
  except (OSError,IndexError,ValueError):pass
rc=proc.returncode if proc else None;completed=failure is None and before==after and not remaining and all(eof.values())
save('execution.json',{'returncode':rc,'timed_out':timed_out,'failure':failure,'elapsed_s':time.monotonic()-start,'owner':owner,'original_pid_absent':owner is not None and not Path('/proc/'+str(owner['pid'])).exists(),'original_group_members':remaining,'pipe_eof':eof,'channel_bytes':sizes,'source_stable':before==after,'original_capture_completed':completed,'successful':rc==0 and completed,'scope':'Parser-only --help and ordinary unit fixtures; no real namespace, kernel journal query, engine or model.'})
raise SystemExit(0 if rc==0 and completed else 1)
