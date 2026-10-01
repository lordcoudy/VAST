"""One read-only full preserved-byte reconciliation of the FAILED original renewal."""
import hashlib,json,os,resource,stat,subprocess,time
from pathlib import Path
START=time.monotonic();END=START+600
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
BASE=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/component-supervisor-renewal-preparation-v1')
ORIGINAL=BASE/'original-checkout-renewal-attempt01';OUT=BASE/'failed-renewal-preserved-input-reconciliation-attempt01'
COMMIT='78b869e4f8bc101413ed00776bd89d1089a8318d';BROKER='scripts/backend_publication_process_supervisor_v3.py';EXPECTED='99f772665d0d271b24d98f2393a50a0f9e0bbfe5c2840e5ccce65d89a84ed13e'
held={};dirs={};failure=None;close_errors=[];report={}
def clock():
 if time.monotonic()>=END:raise TimeoutError('original fullbyte reconciliation600s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
def ancestors(p):
 for a in reversed((p,*p.parents)):
  clock();assert a.resolve(strict=True)==a and stat.S_ISDIR(a.lstat().st_mode)
  if a not in dirs:dirs[a]=(os.open(a,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW),identity(a.lstat()))
  fd,saved=dirs[a];assert identity(os.fstat(fd))==saved==identity(a.lstat())
def read(fd,p,maximum):
 clock();s=os.fstat(fd);e=epoch(s);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=maximum and e==epoch(p.lstat());ancestors(p.parent)
 os.lseek(fd,0,0);h=hashlib.sha256();blob=hashlib.sha1(('blob '+str(s.st_size)+'\0').encode());count=0
 while b:=os.read(fd,1048576):clock();count+=len(b);assert count<=maximum;h.update(b);blob.update(b)
 assert count==s.st_size and e==epoch(os.fstat(fd))==epoch(p.lstat());ancestors(p.parent)
 return {'path':p.relative_to(ROOT).as_posix(),'size_bytes':count,'sha256':h.hexdigest(),'git_blob_sha1':blob.hexdigest(),'epoch7':e}
def save(name,value):
 b=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(b)<=8*1024*1024
 with (OUT/name).open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
 return {'path':str(OUT/name),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def git(args):
 clock();c=subprocess.run(['/usr/bin/git','-c','core.longpaths=true','-C',str(ROOT),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=min(10,END-time.monotonic()),check=True,env=dict(os.environ,GIT_OPTIONAL_LOCKS='0'));assert len(c.stdout)<=8*1024*1024 and not c.stderr;return c.stdout
try:
 assert not OUT.exists();OUT.mkdir(mode=0o700);ancestors(ROOT);assert identity(ROOT.lstat())==[2096,545247,16832,1000,1000]
 me=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split();save('launch.v1.json',{'pid':os.getpid(),'ppid':os.getppid(),'pgid':os.getpgrp(),'startticks':int(me[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'uid':os.getuid(),'gid':os.getgid(),'work_s':600,'failed_original_not_accepted':True})
 forensic=json.loads((BASE/'failed-renewal-two-status-forensic.v1.json').read_bytes());assert all(not s['members'] and not s['errors'] and all(s['PIDs_absent'].values()) for s in forensic['two_actual_process_scans'])
 original=json.loads((ORIGINAL/'execution.v1.json').read_bytes());assert original['status']=='failed' and original['all_fds_retired'] and not original['close_errors']
 preserved=json.loads((ORIGINAL/'preserved-before.v1.json').read_bytes());oldraw=json.loads((ORIGINAL/'tracked-before.v1.json').read_bytes())
 index_epoch=epoch((ROOT/'.git/index').lstat());head=git(['rev-parse','HEAD']);assert head==(COMMIT+'\n').encode();status=git(['status','--porcelain=v1','-z','--untracked-files=no']);assert status==(ORIGINAL/'new-status.stdout.raw').read_bytes()
 tree={}
 for line in (ORIGINAL/'future-tree.stdout.raw').read_bytes().split(b'\0'):
  if line:
   meta,name=line.split(b'\t');mode,kind,sha=meta.decode().split();assert kind=='blob' and mode in ('100644','100755');tree[name.decode()]={'mode':mode,'sha1':sha}
 assert len(preserved)==3024 and len(preserved)+len(dirs)+256<resource.getrlimit(resource.RLIMIT_NOFILE)[0]
 current={}
 for name,saved in preserved.items():
  p=ROOT/name;ancestors(p.parent);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);held[name]=fd
  row=read(fd,p,2*1024**3);assert row==saved;current[name]=row
 first=save('preserved-current.v1.json',current);tracked={}
 for name,expected in tree.items():
  p=ROOT/name;ancestors(p.parent);fd=held.get(name);temporary=fd is None
  if temporary:fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
  try:
   row=current[name] if name in current else read(fd,p,256*1024**2)
   assert row['git_blob_sha1']==expected['sha1'] and bool(row['epoch7'][2]&stat.S_IXUSR)==(expected['mode']=='100755'),name;tracked[name]=row
  finally:
   if temporary:os.close(fd)
 tracked_ref=save('tracked-current.v1.json',tracked)
 inventory=json.loads((BASE.parent/'component-ext4-relocation-feasibility-v1/inventory.v1.json').read_bytes());names=set().union(*map(set,inventory['source_groups'].values()))|set(inventory['controller_files']);changes=[];scope={}
 for name in sorted(names):
  old=preserved.get(name,oldraw.get(name));now=current.get(name,tracked.get(name));assert old is not None and now is not None
  if old['sha256']!=now['sha256']:changes.append(name)
  scope[name]={'original':old,'current':now}
 assert changes==[BROKER] and tracked[BROKER]['sha256']==EXPECTED and tracked[BROKER]['size_bytes']==124707
 for group,names_group in inventory['source_groups'].items():
  if group!='host87':assert all(scope[n]['original']['sha256']==scope[n]['current']['sha256'] for n in names_group)
 scope_ref=save('source-union-current.v1.json',scope)
 for name,fd in held.items():assert read(fd,ROOT/name,2*1024**3)==preserved[name]
 assert head==git(['rev-parse','HEAD']) and status==git(['status','--porcelain=v1','-z','--untracked-files=no']) and index_epoch==epoch((ROOT/'.git/index').lstat())
 report={'status':'closed_readonly_original_preserved_bytes_reconciled','failed_original_remains_failed':True,'source_commit':COMMIT,'preserved_original_row_count':3024,'preserved_original_fullSHA_and_epoch7_before_current_final_equal':True,'preserved_current':first,'raw_tracked_git_blob_and_modes_equal':True,'tracked_count':len(tracked),'tracked_current':tracked_ref,'source_union_count':len(scope),'source_changed_paths':changes,'source_union':scope_ref,'actual_original_two_filter_status_paths_remain_exact':True,'new_stock_closure_launched':False,'checkout_retry_reset_or_rewrite':False}
except BaseException as e:failure={'type':type(e).__name__,'message':str(e)[:4096]};report={'status':'failed_readonly_reconciliation','failed_original_remains_failed':True,'first_failure':failure}
finally:
 for fd in held.values():
  try:os.close(fd)
  except BaseException as e:close_errors.append({'type':type(e).__name__,'message':str(e)[:4096]})
 for fd,_ in dirs.values():
  try:os.close(fd)
  except BaseException as e:close_errors.append({'type':type(e).__name__,'message':str(e)[:4096]})
 report['all_retained_FDs_released']=not close_errors;report['close_errors']=close_errors;report['elapsed_s']=time.monotonic()-START;ref=save('review.v1.json',report)
late=time.monotonic()>=END
if late:save('late-failure.v1.json',{'status':'failed','late':True,'original_report':ref})
print(json.dumps({'report':ref,'status':report['status'],'elapsed_s':report['elapsed_s'],'FDs_released':not close_errors}),flush=True)
raise SystemExit(0 if failure is None and not close_errors and not late else 1)
