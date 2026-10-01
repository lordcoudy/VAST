"""One future metadata-only recovery from actual78b; preserve every original. No hardware."""
import hashlib,json,os,resource,selectors,signal,stat,subprocess,sys,time
from pathlib import Path,PurePosixPath
START=time.monotonic();END=START+600;HARD=END+10
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
WINDOWS=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).parent;OUT=HERE/'original-checkout-recovery-attempt01'
OLD='78b869e4f8bc101413ed00776bd89d1089a8318d'
BROKER='scripts/backend_publication_process_supervisor_v3.py'
FILTER_CASES={
 'artifacts/benchmark_recovery_20260930/ci-4cb9-original-host-retention-v1/host-download-source-review.v1.json':('a014c6a345b082274424e21d68ec4c1bc7f8c4fd','5782753256d37677ccdb841305dca285f07a6630'),
 'artifacts/benchmark_recovery_20260930/component-current-source-ci-supervisor-preparation-v1/capture-literal-preparation.v1.json':('966f7390f6c816a7ac7654a85351efb9500cf84c','b7afd1fc29845c90ca4e2783b8875475414316b2'),
}
OLD_STATUS=b''.join((' M '+n+'\0').encode() for n in FILTER_CASES)
EXPECTED_BROKER='99f772665d0d271b24d98f2393a50a0f9e0bbfe5c2840e5ccce65d89a84ed13e'
INVENTORY=WINDOWS/'artifacts/benchmark_recovery_20260930/component-ext4-relocation-feasibility-v1/inventory.v1.json'
INVENTORY_SHA='8a03751c4f3e18a2590d04874496559cc77dab7ffebc8184269c0b9bb81dc364'
CLASSIFICATION=INVENTORY.with_name('git-input-classification.v1.json')
CLASSIFICATION_SHA='ed2858413c0dca784f05bff2ca4551b0d6f7879baf6624d07a54c1227a320e3c'
RECON_BASE=WINDOWS/'artifacts/benchmark_recovery_20260930/component-supervisor-renewal-preparation-v1'
RECON_DIR=RECON_BASE/'failed-renewal-preserved-input-reconciliation-attempt01'
RECON_REPORT_SHA='3478c3386b325483aaa0478dc1a60932f90900912f68c2fd8feb8c051f0a15c2'
RECON_CAPTURE_SHA='2d8f51c5d61ed615fd74093c82697115b14945a464fef0a8d77eaec9b7878882'
RECON_PRESERVED_SHA='4532d7e1b5740d5c6b5d44024c7095b5547c41ccbc0d06ebcd903319a4a92267'
RECON_TRACKED_SHA='88400bf3105f55284cd88a1e41a3edc89e0e7a7a38375a81b8507216718d0e8e'

assert len(sys.argv)==2,'renewal FUTURE_SOURCE_COMMIT'
COMMIT=sys.argv[1];assert len(COMMIT)==40 and all(c in '0123456789abcdef' for c in COMMIT) and COMMIT!=OLD
commands=[];dirs={};pins={};primary=None;close_errors=[];facts={};owner_ids=[];output_owned=False

def clock(cleanup=False):
 if time.monotonic()>=(HARD if cleanup else END):raise TimeoutError('source renewal600+10 absolute bound')

def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
def error(e):return {'type':type(e).__name__,'message':str(e)[:4096]}

def relative(name):
 p=PurePosixPath(name);assert isinstance(name,str) and name and not p.is_absolute() and '..' not in p.parts and '\\' not in name and p.as_posix()==name
 return ROOT/name

def ancestors(p):
 for a in reversed((p,*p.parents)):
  clock();assert a.resolve(strict=True)==a and not a.is_symlink() and stat.S_ISDIR(a.lstat().st_mode)
  if a not in dirs:
   fd=os.open(a,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
   try:dirs[a]=(fd,identity(os.fstat(fd)))
   except BaseException:os.close(fd);raise
  fd,original=dirs[a];assert identity(os.fstat(fd))==original==identity(a.lstat())

def digest(fd,p,maximum=2*1024*1024*1024):
 ancestors(p.parent);s=os.fstat(fd);before=epoch(s)
 assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and 0<=s.st_size<=maximum and before==epoch(p.lstat()),f'original regular/single-link/size/name custody failed: {p}'
 h=hashlib.sha256();blob=hashlib.sha1(('blob '+str(s.st_size)+'\0').encode());count=0;os.lseek(fd,0,os.SEEK_SET)
 while b:=os.read(fd,1024*1024):clock();count+=len(b);assert count<=maximum;h.update(b);blob.update(b)
 assert count==s.st_size and before==epoch(os.fstat(fd))==epoch(p.lstat()),f'original read/epoch custody changed: {p}'
 ancestors(p.parent)
 return {'path':p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p),'size_bytes':count,'sha256':h.hexdigest(),'git_blob_sha1':blob.hexdigest(),'epoch7':before}

def pin(p,maximum=2*1024*1024*1024):
 ancestors(p.parent);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  row=digest(fd,p,maximum);pins[p]=(fd,row);return row
 except BaseException:os.close(fd);raise

def write(name,value):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=8*1024*1024
 with (OUT/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())

def doc(p,expected):
 row=pin(p,8*1024*1024);assert row['sha256']==expected
 fd,_=pins[p];os.lseek(fd,0,os.SEEK_SET);b=b''
 while x:=os.read(fd,65536):clock();b+=x;assert len(b)<=8*1024*1024
 assert hashlib.sha256(b).hexdigest()==expected;return json.loads(b)

def owner(pid):
 p=Path('/proc',str(pid));f=(p/'stat').read_text().rsplit(')',1)[1].split()
 ids=dict(line.split(':',1) for line in (p/'status').read_text().splitlines() if ':' in line)
 return {'pid':pid,'ppid':int(f[1]),'pgid':int(f[2]),'session':int(f[3]),'startticks':int(f[19]),'uid':int(ids['Uid'].split()[0]),'gid':int(ids['Gid'].split()[0]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

def git(args,label,maximum=8*1024*1024):
 clock();argv=['/usr/bin/git','-c','core.longpaths=true','-c','core.hooksPath=/dev/null','-C',str(ROOT),*args]
 paths={n:OUT/(label+'.'+n+'.raw') for n in ('stdout','stderr')};streams={};sel=selectors.DefaultSelector();child=None;fault=None;signals=[];counts={n:0 for n in paths};eof=set()
 try:
  for n,p in paths.items():streams[n]=p.open('xb')
  child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  original=owner(child.pid);owner_ids.append(original);write(label+'.launch.v1.json',{'argv':argv,'owner':original})
  for n,pipe in [('stdout',child.stdout),('stderr',child.stderr)]:os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,n)
  while sel.get_map() or child.poll() is None:
   clock()
   for key,_ in sel.select(.05):
    b=os.read(key.fd,65536)
    if not b:sel.unregister(key.fileobj);eof.add(key.data);continue
    assert counts[key.data]+len(b)<=maximum;streams[key.data].write(b);counts[key.data]+=len(b)
  child.wait(timeout=max(.001,END-time.monotonic()))
 except BaseException as e:fault=error(e)
 finally:
  if child is not None:
   try:
    os.killpg(child.pid,0)
   except ProcessLookupError:pass
   except BaseException as e:close_errors.append(error(e))
   else:
    if fault is None:fault=error(RuntimeError('original Git command left a process group'))
    try:os.killpg(child.pid,signal.SIGKILL);signals.append('SIGKILL')
    except ProcessLookupError:pass
    except BaseException as e:close_errors.append(error(e))
   try:child.wait(timeout=max(.001,HARD-time.monotonic()))
   except BaseException as e:close_errors.append(error(e))
  try:sel.close()
  except BaseException as e:close_errors.append(error(e))
  for pipe in (() if child is None else (child.stdout,child.stderr)):
   try:pipe.close()
   except BaseException as e:close_errors.append(error(e))
  for f in streams.values():
   try:f.flush();os.fsync(f.fileno())
   except BaseException as e:close_errors.append(error(e))
   finally:
    try:f.close()
    except BaseException as e:close_errors.append(error(e))
 record={'argv':argv,'returncode':None if child is None else child.returncode,'fault':fault,'signals':signals,'eof':sorted(eof),'counts':counts,'original_pid_absent':child is not None and not Path('/proc',str(child.pid)).exists()}
 if child is not None:
  try:os.killpg(child.pid,0);record['original_group_absent']=False
  except ProcessLookupError:record['original_group_absent']=True
 commands.append(record);write(label+'.terminal.v1.json',record)
 assert fault is None and record['returncode']==0 and record['eof']==['stderr','stdout'] and record['original_pid_absent'] and record['original_group_absent'] and not close_errors
 clock();return paths['stdout'].read_bytes()

def objects(commit,label):
 result={}
 for line in git(['ls-tree','-r','-z',commit],label).split(b'\0'):
  if not line:continue
  head,name=line.split(b'\t',1);mode,kind,sha=head.decode('ascii').split();name=name.decode('utf-8');relative(name)
  assert kind=='blob' and mode in ('100644','100755') and len(sha)==40 and name not in result
  result[name]={'mode':mode,'sha1':sha}
 assert 0<len(result)<=20000;return result

def raw_tracked(tree):
 rows={}
 for name,v in tree.items():
  p=relative(name);ancestors(p.parent);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
  try:
   row=digest(fd,p,256*1024*1024);assert row['git_blob_sha1']==v['sha1'] and bool(row['epoch7'][2]&stat.S_IXUSR)==(v['mode']=='100755'),f'raw Git blob/mode differs: {name}'
   rows[name]=row
  finally:os.close(fd)
 return rows

def members():
 result={}
 for parent,ds,fs in os.walk(ROOT,followlinks=False):
  clock();p=Path(parent);ancestors(p)
  if p==ROOT:assert '.git' in ds;ds.remove('.git')
  for n in ds:ancestors(p/n)
  for n in fs:
   q=p/n;s=q.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not q.is_symlink();result[q.relative_to(ROOT).as_posix()]=epoch(s)
 assert len(result)<=20000;return result

try:
 assert os.getuid()==os.getgid()==1000;ancestors(ROOT);assert identity(ROOT.lstat())==[2096,545247,16832,1000,1000]
 mount=next(s for s in Path('/proc/self/mountinfo').read_text().splitlines() if s.split()[4]=='/');assert mount.split(' - ')[1].split()[0]=='ext4' and ROOT.stat().st_dev==Path('/').stat().st_dev
 assert not OUT.exists();OUT.mkdir(mode=0o700);output_owned=True;write('dispatch.v1.json',{'source_commit':COMMIT,'previous_source_commit':OLD,'controller':owner(os.getpid()),'timeout_s':600,'cleanup_s':10,'hardware_acceptance':False})
 inventory=doc(INVENTORY,INVENTORY_SHA);classification=doc(CLASSIFICATION,CLASSIFICATION_SHA)
 reconciliation=doc(RECON_DIR/'review.v1.json',RECON_REPORT_SHA)
 capture=doc(RECON_BASE/'failed-renewal-reconciliation-capture.v1.json',RECON_CAPTURE_SHA)
 sealed_preserved=doc(RECON_DIR/'preserved-current.v1.json',RECON_PRESERVED_SHA)
 sealed_tracked=doc(RECON_DIR/'tracked-current.v1.json',RECON_TRACKED_SHA)
 assert pins[RECON_DIR/'review.v1.json'][1]['size_bytes']==1879 and pins[RECON_BASE/'failed-renewal-reconciliation-capture.v1.json'][1]['size_bytes']==1383
 assert pins[RECON_DIR/'preserved-current.v1.json'][1]['size_bytes']==1964699 and pins[RECON_DIR/'tracked-current.v1.json'][1]['size_bytes']==2600094
 assert reconciliation['status']=='closed_readonly_original_preserved_bytes_reconciled' and reconciliation['source_commit']==OLD and reconciliation['all_retained_FDs_released'] and not reconciliation['close_errors']
 assert reconciliation['preserved_original_fullSHA_and_epoch7_before_current_final_equal'] and reconciliation['preserved_original_row_count']==len(sealed_preserved)==3024
 assert reconciliation['raw_tracked_git_blob_and_modes_equal'] and reconciliation['tracked_count']==len(sealed_tracked)==4721
 assert reconciliation['preserved_current']=={'path':str(RECON_DIR/'preserved-current.v1.json'),'size_bytes':1964699,'sha256':RECON_PRESERVED_SHA}
 assert reconciliation['tracked_current']=={'path':str(RECON_DIR/'tracked-current.v1.json'),'size_bytes':2600094,'sha256':RECON_TRACKED_SHA}
 assert capture['status']=='closed_readonly_reconciliation_capture' and capture['original_tool_exit_code']==0 and capture['all_review_FDs_released']
 assert capture['report']=={'path':str(RECON_DIR/'review.v1.json'),'size_bytes':1879,'sha256':RECON_REPORT_SHA}
 assert all(not scan['members'] and not scan['errors'] and all(scan['PIDs_absent'].values()) for scan in capture['two_actual_process_scans'])

 original_members={r['path'] for r in inventory['copy_inputs']};assert len(original_members)==2693 and len(classification['untracked_inputs'])==2504
 assert git(['rev-parse','HEAD'],'old-head')==(OLD+'\n').encode();assert git(['status','--porcelain=v1','-z','--untracked-files=no'],'old-status')==OLD_STATUS
 git(['cat-file','-e',COMMIT+'^{commit}'],'new-object');git(['merge-base','--is-ancestor',OLD,COMMIT],'ancestry')
 pin(ROOT/'.git/config',1024*1024);alt=pin(ROOT/'.git/objects/info/alternates',1024);fd,_=pins[ROOT/'.git/objects/info/alternates'];os.lseek(fd,0,os.SEEK_SET);assert os.read(fd,1024)==b'/mnt/e/STUDY/VAST/.git/objects\n';ancestors(Path('/mnt/e/STUDY/VAST/.git/objects'))
 old_tree=objects(OLD,'old-tree');new_tree=objects(COMMIT,'future-tree');old_raw=raw_tracked(old_tree);assert old_raw==sealed_tracked,'actual current4721 raw bytes/epochs differ from closed reconciliation'
 for index,(name,(raw_id,clean_id)) in enumerate(FILTER_CASES.items()):
  assert old_tree[name]['sha1']==old_raw[name]['git_blob_sha1']==raw_id and raw_id!=clean_id
  assert git(['hash-object','--path='+name,name],'old-filter-'+str(index))==(clean_id+'\n').encode()
  assert git(['check-attr','text','eol','--',name],'old-attrs-'+str(index))==(name+': text: set\n'+name+': eol: lf\n').encode()
 before_members=members();assert original_members.issubset(before_members)
 untracked=set(before_members)-set(old_tree);assert set(classification['untracked_inputs']).issubset(untracked)
 protected=untracked|original_members|set(FILTER_CASES);assert len(protected)+len(dirs)+64<resource.getrlimit(resource.RLIMIT_NOFILE)[0]
 collision=set(new_tree)&untracked
 assert not collision,f'future tree would adopt original untracked leaves: count={len(collision)}, first={min(collision) if collision else None}'
 protected_tree_changes={n for n in protected if n in old_tree and new_tree.get(n)!=old_tree[n]}
 assert not protected_tree_changes,f'future tree changes protected original blob/mode: count={len(protected_tree_changes)}, first={min(protected_tree_changes) if protected_tree_changes else None}'
 for n in sorted(protected):pin(relative(n))
 before={n:pins[relative(n)][1] for n in sorted(protected)}
 assert set(sealed_preserved).issubset(before),'closed3024 original rows absent from actual held protection'
 for name,saved in sealed_preserved.items():assert before[name]==saved,f'closed original fullbytes/epoch7 drift before checkout: {name}'
 for name in (BROKER,*FILTER_CASES):assert before[name]==sealed_tracked[name],f'current broker/filter fullbytes/epoch7 drift: {name}'
 write('preserved-before.v1.json',before);write('tracked-before.v1.json',old_raw)
 # Ordinary checkout preserves untracked files; no force/reset/clean/filter bypass.
 git(['checkout','--detach',COMMIT],'checkout');assert git(['rev-parse','HEAD'],'new-head')==(COMMIT+'\n').encode();assert git(['status','--porcelain=v1','-z','--untracked-files=no'],'new-status')==b''
 assert objects(COMMIT,'new-tree')==new_tree;new_raw=raw_tracked(new_tree);after_members=members();assert set(before_members).issubset(after_members)
 after={}
 for n in sorted(protected):
  p=relative(n);fd,original=pins[p]
  assert original['epoch7']==epoch(os.fstat(fd))==epoch(p.lstat()),f'preserved original epoch changed during checkout: {n}'
  after[n]=digest(fd,p)
 assert before==after;write('preserved-after.v1.json',after);write('tracked-after.v1.json',new_raw)
 for index,(name,(raw_id,_)) in enumerate(FILTER_CASES.items()):
  assert new_tree[name]==old_tree[name] and new_raw[name]['git_blob_sha1']==raw_id
  assert git(['hash-object','--path='+name,name],'new-filter-'+str(index))==(raw_id+'\n').encode()
  assert git(['check-attr','text','eol','--',name],'new-attrs-'+str(index))==(name+': text: unset\n'+name+': eol: unspecified\n').encode()
 scope_names=set().union(*map(set,inventory['source_groups'].values()))|set(inventory['controller_files'])
 old_scope={n:(before[n] if n in before else old_raw[n]) for n in scope_names}
 new_scope={n:(after[n] if n in after else new_raw[n]) for n in scope_names}
 scope_changes=sorted(n for n in scope_names if old_scope[n]['sha256']!=new_scope[n]['sha256'])
 assert scope_changes==[] and old_raw[BROKER]['size_bytes']==new_raw[BROKER]['size_bytes']==124707 and old_raw[BROKER]['sha256']==new_raw[BROKER]['sha256']==EXPECTED_BROKER
 for group,names in inventory['source_groups'].items():
  if group!='host87':assert all(old_scope[n]['sha256']==new_scope[n]['sha256'] for n in names)
 for p,(fd,row) in pins.items():
  assert row['epoch7']==epoch(os.fstat(fd))==epoch(p.lstat()),f'held original epoch changed: {p}'
  assert digest(fd,p)==row
 facts={'preserved_file_count':len(protected),'preserved_bytes':sum(r['size_bytes'] for r in before.values()),'original_untracked_names_retained':True,'original_input_presence_count':2693,'raw_tracked_old_count':len(old_raw),'raw_tracked_new_count':len(new_raw),'raw_byte_Git_blob_mode_equality':True,'protected_full_sha_and_epoch7_before_after_equal':True,'host87_changed_paths':scope_changes,'unchanged_image_source_groups':sorted(k for k in inventory['source_groups'] if k!='host87'),'root_filesystem':'ext4','root_identity':identity(ROOT.lstat()),'shared_git_objects':'/mnt/e/STUDY/VAST/.git/objects','historical_inventory_used_only_for_finite_paths_not_new_authority':True,'all_original2693_including_current_broker_protected':True,'only_two_proven_initial_filter_status_cases_allowed':list(FILTER_CASES),'two_metadata_payload_bytes_preserved_and_filters_corrected':True,'closed3024_and_current4721_before_gate_physically_joined':True,'closed_original_reconciliation_sha256':RECON_REPORT_SHA}
except BaseException as e:primary=error(e)
finally:
 for fd,_ in pins.values():
  try:os.close(fd)
  except BaseException as e:close_errors.append(error(e))
 for fd,_ in dirs.values():
  try:os.close(fd)
  except BaseException as e:close_errors.append(error(e))
 if output_owned:write('execution.v1.json',{'status':'renewed_non_authority_checkout' if primary is None and not close_errors else 'failed','source_commit':COMMIT,'previous_source_commit':OLD,'elapsed_s':time.monotonic()-START,'first_error':primary,'close_errors':close_errors,'all_fds_retired':not close_errors,'commands':commands,'facts':facts,'hardware_acceptance':False})
 if time.monotonic()>=END and primary is None:
  primary=error(TimeoutError('renewal receipt-last600s bound'))
  if output_owned:write('late-failure.v1.json',{'status':'failed','first_error':primary,'elapsed_s':time.monotonic()-START})
 clock(cleanup=True)
 print(json.dumps({'status':'renewed_non_authority_checkout' if primary is None and not close_errors else 'failed','source_commit':COMMIT,'elapsed_s':time.monotonic()-START,'first_error':primary,'close_errors':close_errors}),flush=True)
sys.exit(0 if primary is None and not close_errors else 78)
