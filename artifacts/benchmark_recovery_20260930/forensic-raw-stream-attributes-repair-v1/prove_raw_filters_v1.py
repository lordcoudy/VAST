"""Finite original Git-filter proof only: no checkout, stage, payload edit or runtime."""
import ast, hashlib, json, os, stat, subprocess, sys, time
from pathlib import Path

ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
HERE=Path(__file__).resolve().parent
assert len(sys.argv)==2 and sys.argv[1] in ('red','green')
PHASE=sys.argv[1];OUT=HERE/(PHASE+'-original-attempt01')
START=time.monotonic();END=START+120
OLD_SHA='504ceb16d7ab7cff66925251859ccb453bfb3b0190b12f6ad0eba64ed79a9acd'
APPEND=b'\n# Captured forensic raw streams are byte evidence; disable automatic EOL conversion.\n/artifacts/benchmark_recovery_20260930/**/*.raw -text !eol\n'
GIT=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
commands=[]

def clock():
 if time.monotonic()>=END:raise TimeoutError('finite raw-filter proof120s')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(p):
 clock();p=Path(p);assert p.resolve(strict=True)==p
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  before=os.fstat(fd);assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=8*1048576
  raw=b''
  while block:=os.read(fd,65536):clock();raw+=block
  assert len(raw)==before.st_size and epoch(before)==epoch(os.fstat(fd))==epoch(p.lstat())
  return raw,{'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch7':epoch(before)}
 finally:os.close(fd)
def save(name,value,raw=False):
 b=value if raw else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode('ascii')
 with (OUT/name).open('xb') as f:assert f.write(b)==len(b);f.flush();os.fsync(f.fileno())
 return pin(OUT/name)[1]
def owner(pid):
 p=Path('/proc',str(pid));v=(p/'stat').read_text().rsplit(')',1)[1].split()
 ids=dict(x.split(':',1) for x in (p/'status').read_text().splitlines() if ':' in x)
 return {'pid':pid,'ppid':int(v[1]),'pgid':int(v[2]),'sid':int(v[3]),'startticks':int(v[19]),'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0]),'state':v[0],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def command(label,args,data=None):
 clock();argv=GIT+args;child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 try:
  observed=owner(child.pid);launched=time.monotonic()
  stdout,stderr=child.communicate(data,timeout=max(.001,min(20,END-time.monotonic())))
 except BaseException:
  child.kill();child.wait(timeout=5);raise
 finally:
  for channel in (child.stdin,child.stdout,child.stderr):
   if channel is not None and not channel.closed:channel.close()
 assert len(stdout)<=1048576 and len(stderr)<=1048576
 row={'argv':argv,'owner':observed,'returncode':child.returncode,'elapsed_s':time.monotonic()-launched,'reaped':True,'stdout':save(label+'.stdout.raw',stdout,True),'stderr':save(label+'.stderr.raw',stderr,True)}
 commands.append(row);assert child.returncode==0,row
 return stdout
def scans():
 ids={r['owner']['pid'] for r in commands};groups=ids;result=[]
 for unused in range(2):
  members=[];errors=[]
  for p in Path('/proc').iterdir():
   if not p.name.isdigit():continue
   try:
    v=(p/'stat').read_text().rsplit(')',1)[1].split()
    if int(p.name) in ids or int(v[2]) in groups or int(v[3]) in groups:members.append(owner(int(p.name)))
   except FileNotFoundError:pass
   except (OSError,ValueError) as exc:errors.append({'pid':int(p.name),'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
  result.append({'at_ns':time.time_ns(),'members':members,'errors':errors,'pids_absent':{str(p):not Path('/proc',str(p)).exists() for p in ids}})
 assert all(not x['members'] and not x['errors'] and all(x['pids_absent'].values()) for x in result)
 return result

assert not OUT.exists();OUT.mkdir(mode=0o700)
first=None
try:
 attrs,attrs_pin=pin(ROOT/'.gitattributes')
 if PHASE=='red':assert len(attrs)==16430 and hashlib.sha256(attrs).hexdigest()==OLD_SHA
 else:
  old=(HERE/'red-original-attempt01/gitattributes.before.raw').read_bytes()
  assert len(old)==16430 and hashlib.sha256(old).hexdigest()==OLD_SHA and attrs==old+APPEND
 source=BASE/'owned-raw-evidence-filter-followup-checkpoint-v1/prepare_finite_inventory_v1.py'
 source_raw,source_pin=pin(source);tree=ast.parse(source_raw)
 names=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='names' for t in n.targets)))
 paths={'.gitattributes','BENCHMARK_RECOVERY_PLAN.md','artifacts/benchmark_recovery_20260930/owned-raw-evidence-attributes-checkpoint-v1/commit-proof.v1.json',source.relative_to(ROOT).as_posix(),(source.parent/'verify_commit_bytes_v1.py').relative_to(ROOT).as_posix()}
 for name in (*names,HERE.name):
  for p in (BASE/name).rglob('*'):
   assert not p.is_symlink() and '.git' not in p.parts
   if p.is_file():
    assert '__pycache__' not in p.parts and p.suffix.lower() not in {'.pyc','.onnx','.engine','.plan','.bin','.whl','.rgb'}
    if OUT not in p.parents:paths.add(p.relative_to(ROOT).as_posix())
 paths=sorted(paths);assert len(paths)<=2000
 raw_ids={};physical={};total=0
 for relative in paths:
  raw,ref=pin(ROOT/relative);total+=len(raw);assert total<=64*1048576
  physical[relative]=ref;raw_ids[relative]=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 save('gitattributes.before.raw' if PHASE=='red' else 'gitattributes.after.raw',attrs,True)
 filters={};mismatches={}
 for setting in ('false','true'):
  output=command('filters-'+setting,['-c','core.autocrlf='+setting,'hash-object','--stdin-paths'],('\n'.join(paths)+'\n').encode())
  values=output.decode('ascii').splitlines();assert len(values)==len(paths)
  filters[setting]=dict(zip(paths,values,strict=True));mismatches[setting]=[p for p in paths if filters[setting][p]!=raw_ids[p]]
 raw_paths=[p for p in paths if p.startswith('artifacts/benchmark_recovery_20260930/') and p.endswith('.raw')]
 attrs_output=command('effective-raw-attributes',['check-attr','-z','--stdin','text','eol'],('\0'.join(raw_paths)+'\0').encode())
 triples=attrs_output.decode('utf8').split('\0');assert triples[-1]=='';triples.pop();assert len(triples)==len(raw_paths)*6
 raw_effective={}
 for i in range(0,len(triples),3):raw_effective.setdefault(triples[i],{})[triples[i+1]]=triples[i+2]
 inventory_raw,inventory_pin=pin(BASE/'component-ext4-relocation-feasibility-v1/inventory.v1.json');inventory=json.loads(inventory_raw)
 source_groups={p for group in inventory['source_groups'].values() for p in group}
 protected=set(inventory['controller_files'])|source_groups
 input_paths={r['path'] for r in inventory['copy_inputs']}
 matches=lambda paths:{p for p in paths if p.startswith('artifacts/benchmark_recovery_20260930/') and p.endswith('.raw')}
 assert len(input_paths)==2693 and not matches(protected) and not matches(input_paths)
 all_raw=[]
 for p in BASE.rglob('*.raw'):
  s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not p.is_symlink()
  all_raw.append({'path':p.relative_to(ROOT).as_posix(),'size_bytes':s.st_size})
 for relative,ref in physical.items():assert pin(ROOT/relative)[1]==ref
 assert pin(ROOT/'.gitattributes')[1]==attrs_pin
 if PHASE=='red':
  assert mismatches['true'] and 'artifacts/benchmark_recovery_20260930/forensic-raw-json-attributes-followup-v1/original-1.raw' in mismatches['true']
 else:
  assert not mismatches['false'] and not mismatches['true'],mismatches
  assert all(x=={'text':'unset','eol':'unspecified'} for x in raw_effective.values())
 report={'schema_version':1,'artifact_kind':'vast_finite_raw_filter_original_proof_v1','phase':PHASE,'status':'proved_original_filter_conflicts' if PHASE=='red' else 'all_finite_owned_raw_filter_ids_equal','observer':owner(os.getpid()),'attrs':attrs_pin,'guard_source':source_pin,'original_guard_rejection':'Root reported rejected before Git mutation and before inventory publication; this original finite proof independently retains exact filtered-object conflicts.','scope_paths':paths,'scope_count':len(paths),'scope_bytes':total,'physical':physical,'raw_ids':raw_ids,'filtered_ids':filters,'mismatches':mismatches,'other_extension_mismatches':{k:[p for p in v if not p.endswith('.raw')] for k,v in mismatches.items()},'raw_effective_attributes':raw_effective,'all_current_raw_stat_only':all_raw,'raw_family_protected_membership':{'inventory':inventory_pin,'source_group_union':len(source_groups),'controller_union':len(protected),'copy_input_count':len(input_paths),'source_controller_matches':[],'copy_input_matches':[]},'commands':commands,'process_scans':scans(),'all_read_fds_released':True,'payloads_rewritten':False,'git_mutation':False,'runtime_or_ci_acceptance':False,'work_limit_s':120,'elapsed_before_final_receipt_s':time.monotonic()-START}
 ref=save('execution.v1.json',report)
except BaseException as exc:
 first={'type':type(exc).__name__,'message':str(exc)[:4096]};ref=save('failed.v1.json',{'first_error':first,'commands':commands,'phase':PHASE,'no_retry':True})
late=time.monotonic()>=END
if late:save('late-failure.v1.json',{'closed_report':ref,'first_error':first,'elapsed_s':time.monotonic()-START})
print(json.dumps({'result':ref,'error':first,'late':late}),flush=True)
sys.exit(0 if first is None and not late else 1)
