"""One future clean checkpointA to reviewed host-bindingB checkout; original inputs remain strict. No hardware."""
import hashlib,json,os,resource,selectors,signal,stat,subprocess,sys,time
from pathlib import Path,PurePosixPath
START=time.monotonic();END=START+600;HARD=END+10
ROOT=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')
WINDOWS=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent;OUT=HERE/'original-host-binding-checkout-renewal-attempt01'
OLD='2a6a42c924ae3447ceda4bd9d1b6db33765c6466'
PLANNING='958a036bc5a55821c712204577fdf4c51c2181c7'
EXPECTED_BOOT='dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
BROKER='scripts/backend_publication_process_supervisor_v3.py'
CHANGED={'scripts/checkpoint_gstreamer_publication_runtime_v3.py'}
PRODUCTION_CANDIDATES={
 'scripts/checkpoint_gstreamer_analytics_sidecar.py':(299261,'4a853d79fe4296882d1f3e28774ccabb458e030c55d474b1bf34918b897f7fd6'),
 'scripts/publication_operational_process_custody_v1.py':(51141,'dc92e20512cc2e3e7265e75bfd3c01de0146f29cfd4720e1a6f1b199ceb52d97'),
 'tests/test_checkpoint_gstreamer_analytics_sidecar.py':(138071,'47f74ffd43d81dff567b7f04576446fab9f246fb3937d6c97a92b73bff90a78d'),
 'tests/test_publication_operational_process_custody_v1.py':(40344,'690212c96e47cb2a037e5b26ed24de9637e349515df3fb99b3ddc7d49c7b04c8'),
 'tests/test_publication_worker_termination_facts_v1.py':(6599,'149127245376786f398234edefbb197e03656cb11f98a6e7f6f86cb1ce98afd3'),
 '.gitattributes':(17102,'109eef60f5ed87e35b18a663c0e112cfc4040fe898dc09d38923d16de803c392'),
}
EXPECTED_CANDIDATES={
 'scripts/checkpoint_gstreamer_publication_runtime_v3.py':(59624,'0fee418bfa0c7e0e89f9c74210f107fa950d14cf65844d82b1a91330a398aa1c'),
 'tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py':(25066,'b6bc88d91a11eda378cb079ade41e473164db39f2dcb224e29f607dc106fd02c'),
}
HOST_PEER=WINDOWS/'artifacts/benchmark_recovery_20260930/decision28-host-image-independent-review-v1/review.v1.json'
SOURCE_PEER=WINDOWS/'artifacts/benchmark_recovery_20260930/decision28-source-independent-review-v2/review.v2.json'
SOURCE_PEER_SHA='7de1386fc628424e90af3cbc21aea5ecdf6e433e9f9e594a86f9f83bf1c4e662'
COUNT_PEER=SOURCE_PEER.with_name('count-correction.v1.json')
COUNT_PEER_SHA='fb038ad8bba5b92346f377c635c4f6a7a61522a98746df7a2e57ca643ad37343'
LOCK='.publication-atomic-staging-v1/.lock'
AFFECTED_GROUPS={'host87'}
UNCHANGED_GROUPS={'deepstream','gstreamer_custom','openvino_gva','savant','native_probe_deepstream','native_probe_openvino','native_probe_savant','analytics_worker_openvino','analytics_worker_tensorrt'}
EXPECTED_BROKER='99f772665d0d271b24d98f2393a50a0f9e0bbfe5c2840e5ccce65d89a84ed13e'
INVENTORY=WINDOWS/'artifacts/benchmark_recovery_20260930/component-ext4-relocation-feasibility-v1/inventory.v1.json'
INVENTORY_SHA='8a03751c4f3e18a2590d04874496559cc77dab7ffebc8184269c0b9bb81dc364'
CLASSIFICATION=INVENTORY.with_name('git-input-classification.v1.json')
CLASSIFICATION_SHA='ed2858413c0dca784f05bff2ca4551b0d6f7879baf6624d07a54c1227a320e3c'
assert len(sys.argv)==3,'renewal FUTURE_SOURCE_COMMIT CLOSED_HOST_PEER_SHA256'
HOST_PEER_SHA=sys.argv[2];assert len(HOST_PEER_SHA)==64 and all(c in '0123456789abcdef' for c in HOST_PEER_SHA)
COMMIT=sys.argv[1];assert len(COMMIT)==40 and all(c in '0123456789abcdef' for c in COMMIT) and COMMIT!=OLD
commands=[];dirs={};pins={};primary=None;close_errors=[];facts={};owner_ids=[];output_owned=False
error_records=[];error_overflow=0;fd_before=None;fd_after=None

def fail(phase,e,closing=False):
 global primary,error_overflow
 value=error(e)
 if primary is None:primary=value
 row={'phase':phase,**value}
 if len(error_records)<64:error_records.append(row)
 else:error_overflow+=1
 if closing and len(close_errors)<64:close_errors.append(row)
 return value

def fd_count():return len(os.listdir('/proc/self/fd'))

def scan_group(original):
 row={'original_pid':original['pid'],'original_pgid':original['pgid'],'original_startticks':original.get('startticks'),
  'original_pid_identity':'absent','members':[],'errors':[],'error_overflow':0,'vanished_during_scan':0,'started_at_ns':time.time_ns()}
 def refusal(phase,e):
  if len(row['errors'])<64:row['errors'].append({'phase':phase,**error(e)})
  else:row['error_overflow']+=1
 try:entries=os.listdir('/proc')
 except BaseException as e:refusal('enumeration',e);entries=[]
 for n in entries:
  if not n.isdigit():continue
  try:
   clock(cleanup=True)
   parts=Path('/proc',n,'stat').read_text().rsplit(')',1)[1].split();pid=int(n);pgid=int(parts[2]);ticks=int(parts[19])
   if pid==original['pid']:row['original_pid_identity']='original_present' if ticks==original.get('startticks') else 'different_startticks'
   if pgid==original['pgid']:row['members'].append({'pid':pid,'startticks':ticks,'state':parts[0]})
  except (FileNotFoundError,ProcessLookupError):row['vanished_during_scan']+=1
  except BaseException as e:
   refusal('pid:'+n,e)
   if isinstance(e,TimeoutError):break
 row['finished_at_ns']=time.time_ns();return row

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
   dirs[a]=(None,None)
   fd=os.open(a,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
   dirs[a]=(fd,None)
   dirs[a]=(fd,identity(os.fstat(fd)))
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
 ancestors(p.parent)
 if p in pins:
  fd,row=pins[p];assert row is not None and digest(fd,p,maximum)==row;return row
 pins[p]=(None,None)
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC);pins[p]=(fd,None)
 row=digest(fd,p,maximum);pins[p]=(fd,row);return row

def write(name,value,cleanup=False):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=8*1024*1024
 stream=None;first=None
 try:
  clock(cleanup=cleanup);stream=(OUT/name).open('xb')
  assert stream.write(raw)==len(raw);stream.flush();os.fsync(stream.fileno())
 except BaseException as e:first=e;fail('write:'+name,e)
 finally:
  if stream is not None:
   try:stream.close()
   except BaseException as e:
    fail('write_close:'+name,e,closing=True)
    if first is None:first=e
 if first is not None:raise first

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
 clock();argv=['/usr/bin/git','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true','-c','core.hooksPath=/dev/null','-C',str(ROOT),*args]
 paths={n:OUT/(label+'.'+n+'.raw') for n in ('stdout','stderr')};streams={};sel=None;child=None;original=None;fault=None;signals=[];counts={n:0 for n in paths};eof=set();scans=[];channel_rows={}
 def retirement(phase,e):
  nonlocal fault
  value=fail(label+':'+phase,e,closing=True)
  if fault is None:fault=value
 try:
  for n,p in paths.items():streams[n]=p.open('xb')
  sel=selectors.DefaultSelector()
  child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  original=owner(child.pid);assert original['uid']==original['gid']==1000 and original['boot_id']==EXPECTED_BOOT
  owner_ids.append(original);write(label+'.launch.v1.json',{'argv':argv,'owner':original})
  for n,pipe in [('stdout',child.stdout),('stderr',child.stderr)]:os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,n)
  while sel.get_map() or child.poll() is None:
   clock()
   for key,_ in sel.select(.05):
    b=os.read(key.fd,65536)
    if not b:sel.unregister(key.fileobj);eof.add(key.data);continue
    assert counts[key.data]+len(b)<=maximum
    assert streams[key.data].write(b)==len(b);counts[key.data]+=len(b)
  child.wait(timeout=max(.001,END-time.monotonic()))
  if child.returncode!=0:raise RuntimeError('original Git '+label+' returned '+str(child.returncode))
 except BaseException as e:fault=fail(label+':body',e)
 finally:
  if child is not None:
   try:os.killpg(child.pid,0)
   except ProcessLookupError:pass
   except BaseException as e:retirement('group_probe',e)
   else:
    if fault is None:fault=fail(label+':body',RuntimeError('original Git command left a process group'))
    try:os.killpg(child.pid,signal.SIGKILL);signals.append('SIGKILL')
    except ProcessLookupError:pass
    except BaseException as e:retirement('owned_SIGKILL',e)
   try:child.wait(timeout=max(.001,HARD-time.monotonic()))
   except BaseException as e:retirement('original_child_reap',e)
  if sel is not None:
   try:sel.close()
   except BaseException as e:retirement('selector_close',e)
  for n,pipe in (() if child is None else (('stdout',child.stdout),('stderr',child.stderr))):
   if pipe is not None:
    try:pipe.close()
    except BaseException as e:retirement(n+'_pipe_close',e)
  for n,f in streams.items():
   try:f.flush()
   except BaseException as e:retirement(n+'_flush',e)
   try:os.fsync(f.fileno())
   except BaseException as e:retirement(n+'_fsync',e)
   try:f.close()
   except BaseException as e:retirement(n+'_close',e)
  if child is not None:
   observed=original or {'pid':child.pid,'pgid':child.pid,'startticks':None}
   if original is None:retirement('original_owner_missing',RuntimeError('original child owner was unavailable'))
   for index in range(2):
    try:
     scan=scan_group(observed);scans.append(scan)
     assert not scan['errors'] and not scan['error_overflow'] and not scan['members'] and scan['original_pid_identity']!='original_present','uncertain or present original process group'
    except BaseException as e:retirement('original_group_scan_'+str(index),e)
  for n,p in paths.items():
   try:channel_rows[n]=pin(p,maximum)
   except BaseException as e:channel_rows[n]=None;retirement(n+'_raw_byte_custody',e)
 record={'argv':argv,'owner':original,'returncode':None if child is None else child.returncode,'fault':fault,'signals':signals,'eof':sorted(eof),'counts':counts,
  'original_child_reaped':child is not None and child.returncode is not None,'two_original_process_scans':scans,'original_pid_absent':len(scans)==2 and all(s['original_pid_identity']!='original_present' for s in scans),
  'original_group_absent':len(scans)==2 and all(not s['members'] and not s['errors'] and not s['error_overflow'] for s in scans),'stdout':channel_rows.get('stdout'),'stderr':channel_rows.get('stderr')}
 commands.append(record)
 try:write(label+'.terminal.v1.json',record,cleanup=True)
 except BaseException as e:retirement('command_terminal',e)
 assert fault is None and record['returncode']==0 and record['eof']==['stderr','stdout'] and record['original_child_reaped'] and record['original_pid_absent'] and record['original_group_absent'] and not close_errors
 clock();fd,row=pins[paths['stdout']];os.lseek(fd,0,os.SEEK_SET);raw=b''
 while b:=os.read(fd,65536):clock();raw+=b;assert len(raw)<=maximum
 assert hashlib.sha256(raw).hexdigest()==row['sha256'] and len(raw)==row['size_bytes'] and row['epoch7']==epoch(os.fstat(fd))==epoch(paths['stdout'].lstat())
 return raw

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
  p=relative(name);fd=None;first=None
  try:
   ancestors(p.parent);fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
   row=digest(fd,p,256*1024*1024);assert row['git_blob_sha1']==v['sha1'] and bool(row['epoch7'][2]&stat.S_IXUSR)==(v['mode']=='100755'),f'raw Git blob/mode differs: {name}'
   rows[name]=row
  except BaseException as e:first=e;fail('raw_tracked:'+name,e)
  finally:
   if fd is not None:
    try:os.close(fd)
    except BaseException as e:
     fail('raw_tracked_close:'+name,e,closing=True)
     if first is None:first=e
  if first is not None:raise first
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
 fd_before=fd_count()
 assert owner(os.getpid())['boot_id']==EXPECTED_BOOT
 assert os.getuid()==os.getgid()==1000;ancestors(ROOT);assert identity(ROOT.lstat())==[2096,545247,16832,1000,1000]
 mount=next(s for s in Path('/proc/self/mountinfo').read_text().splitlines() if s.split()[4]=='/');assert mount.split(' - ')[1].split()[0]=='ext4' and ROOT.stat().st_dev==Path('/').stat().st_dev
 assert not OUT.exists();OUT.mkdir(mode=0o700);output_owned=True;write('dispatch.v1.json',{'source_commit':COMMIT,'previous_source_commit':OLD,'controller':owner(os.getpid()),'timeout_s':600,'cleanup_s':10,'hardware_acceptance':False})
 inventory=doc(INVENTORY,INVENTORY_SHA);classification=doc(CLASSIFICATION,CLASSIFICATION_SHA)
 peer=doc(SOURCE_PEER,SOURCE_PEER_SHA);counts_peer=doc(COUNT_PEER,COUNT_PEER_SHA)
 assert peer['reviewable'] and not peer['blocking_findings'] and peer['reviewer_handles_released'] and peer['baseline_commit']==PLANNING
 assert counts_peer['reviewable'] and not counts_peer['blocking_findings'] and counts_peer['reviewer_handles_released'] and counts_peer['baseline_commit']==PLANNING
 assert counts_peer['parent_independent_review']=={'path':SOURCE_PEER.relative_to(WINDOWS).as_posix(),'size_bytes':26462,'sha256':SOURCE_PEER_SHA}
 assert counts_peer['focused_original_sidecar_plus_termination_methods']==53 and counts_peer['original_native_methods']==21
 declared={r['path']:(r['size_bytes'],r['sha256']) for r in peer['owned_source_pins']}
 assert declared==PRODUCTION_CANDIDATES and counts_peer['owned_source_pins']==peer['owned_source_pins']
 host_peer=doc(HOST_PEER,HOST_PEER_SHA)
 assert host_peer['reviewable'] and not host_peer['blocking_findings'] and host_peer['reviewer_handles_released'] and host_peer['reviewed_commit']==OLD
 assert {r['path']:(r['size_bytes'],r['sha256']) for r in host_peer['owned_source_pins']}==EXPECTED_CANDIDATES
 for n,wanted in (PRODUCTION_CANDIDATES|EXPECTED_CANDIDATES).items():
  row=pin(WINDOWS/n);assert (row['size_bytes'],row['sha256'])==wanted
 pin(Path(__file__).resolve(),8*1024*1024)
 original_members={r['path'] for r in inventory['copy_inputs']};assert len(original_members)==2693 and len(classification['untracked_inputs'])==2504
 assert git(['rev-parse','HEAD'],'old-head')==(OLD+'\n').encode();assert git(['status','--porcelain=v1','-z','--untracked-files=no'],'old-status')==b''
 git(['cat-file','-e',COMMIT+'^{commit}'],'new-object');git(['merge-base','--is-ancestor',OLD,COMMIT],'ancestry')
 pin(ROOT/'.git/config',1024*1024);alt=pin(ROOT/'.git/objects/info/alternates',1024);fd,_=pins[ROOT/'.git/objects/info/alternates'];os.lseek(fd,0,os.SEEK_SET);assert os.read(fd,1024)==b'/mnt/e/STUDY/VAST/.git/objects\n';ancestors(Path('/mnt/e/STUDY/VAST/.git/objects'))
 old_tree=objects(OLD,'old-tree');new_tree=objects(COMMIT,'future-tree');old_raw=raw_tracked(old_tree)
 assert all(n in old_tree and n in new_tree and old_tree[n]['mode']==new_tree[n]['mode'] for n in EXPECTED_CANDIDATES)
 before_members=members();assert original_members.issubset(before_members)
 untracked=set(before_members)-set(old_tree);assert set(classification['untracked_inputs']).issubset(untracked)
 assert CHANGED.issubset(original_members) and LOCK in untracked and LOCK not in original_members
 protected=(untracked|original_members)-CHANGED;assert len(protected)+len(dirs)+64<resource.getrlimit(resource.RLIMIT_NOFILE)[0]
 collision=set(new_tree)&untracked
 assert not collision,f'future tree would adopt original untracked leaves: count={len(collision)}, first={min(collision) if collision else None}'
 protected_tree_changes={n for n in protected if n in old_tree and new_tree.get(n)!=old_tree[n]}
 assert not protected_tree_changes,f'future tree changes protected original blob/mode: count={len(protected_tree_changes)}, first={min(protected_tree_changes) if protected_tree_changes else None}'
 for n in sorted(protected):pin(relative(n))
 before={n:pins[relative(n)][1] for n in sorted(protected)}
 assert before[LOCK]['size_bytes']==0 and before[LOCK]['sha256']==hashlib.sha256(b'').hexdigest()
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
 transitions={}
 for n,wanted in EXPECTED_CANDIDATES.items():
  assert (new_raw[n]['size_bytes'],new_raw[n]['sha256'])==wanted,f'future committed candidate differs from exact reviewed bytes: {n}'
  assert old_tree[n]['mode']==new_tree[n]['mode'] and old_tree[n]!=new_tree[n],f'candidate expected exact original to reviewed transition: {n}'
  transitions[n]={'old_commit':OLD,'new_commit':COMMIT,'old_git':old_tree[n],'new_git':new_tree[n],'before':old_raw[n],'after':new_raw[n]}
  pin(relative(n),256*1024*1024)
 write('intentional-reviewed-transitions.v1.json',transitions)
 scope_names=set().union(*map(set,inventory['source_groups'].values()))|set(inventory['controller_files']);assert len(scope_names)==180 and CHANGED.issubset(scope_names)
 assert not (set(EXPECTED_CANDIDATES)-CHANGED)&(scope_names|original_members)
 assert LOCK not in scope_names
 old_scope={n:(before[n] if n in before else old_raw[n]) for n in scope_names}
 new_scope={n:(after[n] if n in after else new_raw[n]) for n in scope_names}
 scope_changes=sorted(n for n in scope_names if old_scope[n]['sha256']!=new_scope[n]['sha256'])
 assert scope_changes==sorted(CHANGED)
 assert old_raw[BROKER]['size_bytes']==new_raw[BROKER]['size_bytes']==124707 and old_raw[BROKER]['sha256']==new_raw[BROKER]['sha256']==EXPECTED_BROKER
 group_changes={group:sorted(n for n in names if old_scope[n]['sha256']!=new_scope[n]['sha256']) for group,names in inventory['source_groups'].items()}
 assert set(group_changes)==AFFECTED_GROUPS|UNCHANGED_GROUPS
 assert {g for g,changes in group_changes.items() if changes}==AFFECTED_GROUPS
 assert all(group_changes[g]==sorted(CHANGED) for g in AFFECTED_GROUPS)
 assert all(group_changes[g]==[] for g in UNCHANGED_GROUPS)
 for p,(fd,row) in pins.items():
  assert row is not None and row['epoch7']==epoch(os.fstat(fd))==epoch(p.lstat()),f'held original epoch changed: {p}'
  assert digest(fd,p)==row
 facts={'preserved_file_count':len(protected),'preserved_bytes':sum(r['size_bytes'] for r in before.values()),'original_untracked_names_retained':True,'original_input_presence_count':2693,
  'raw_tracked_old_count':len(old_raw),'raw_tracked_new_count':len(new_raw),'raw_byte_Git_blob_mode_equality':True,'protected_full_sha_and_epoch7_before_after_equal':True,
  'intentional_reviewed_candidate_transitions':transitions,'source180_changed_paths':scope_changes,'source_group_changes':group_changes,'affected_source_groups':sorted(AFFECTED_GROUPS),'unchanged_source_groups':sorted(UNCHANGED_GROUPS),
  'native_three_worker_two_source_groups_unchanged':True,'sibling_runtime_images_current_eligible':False,'selected_runtime_image_renewal_required':False,'selected73_A_to_B_unchanged':True,
  'fresh_current_empty_lock':{'before':before[LOCK],'after':after[LOCK],'historical_epoch_reused':False},
  'root_filesystem':'ext4','root_identity':identity(ROOT.lstat()),'shared_git_objects':'/mnt/e/STUDY/VAST/.git/objects','historical_inventory_used_only_for_finite_paths_not_new_authority':True,
  'only_host_binding_original_input_transition':sorted(CHANGED),'original_models_numeric_corpus_other_inputs_and_untracked_outputs_preserved':True}
except BaseException as e:fail('operation_body',e)
finally:
 source_checks=[];pin_closes=[];directory_closes=[]
 for p,(fd,row) in pins.items():
  try:
   assert fd is not None and row is not None,'source acquisition incomplete'
   assert row['epoch7']==epoch(os.fstat(fd))==epoch(p.lstat()) and digest(fd,p)==row,'final held source/fullbyte epoch drift'
   source_checks.append({'path':str(p),'verified':True})
  except BaseException as e:source_checks.append({'path':str(p),'verified':False});fail('source_final_check:'+str(p),e)
 for p,(fd,_) in pins.items():
  if fd is None:continue
  try:os.close(fd);pin_closes.append({'path':str(p),'closed':True})
  except BaseException as e:pin_closes.append({'path':str(p),'closed':False});fail('pin_close:'+str(p),e,closing=True)
 for p,(fd,_) in dirs.items():
  if fd is None:continue
  try:os.close(fd);directory_closes.append({'path':str(p),'closed':True})
  except BaseException as e:directory_closes.append({'path':str(p),'closed':False});fail('directory_close:'+str(p),e,closing=True)
 try:
  fd_after=fd_count();assert fd_before is not None and fd_before==fd_after,'original FD baseline not restored'
 except BaseException as e:fail('final_FD_baseline',e,closing=True)
 late=time.monotonic()>=END
 if late:fail('whole_deadline_before_terminal',TimeoutError('renewal receipt-last600s bound'))
 saved_error=primary;saved_count=len(error_records);saved_overflow=error_overflow;terminal_written=False
 if output_owned:
  try:
   write('execution.v1.json',{'status':'renewed_non_authority_checkout' if primary is None and not close_errors else 'failed','source_commit':COMMIT,'previous_source_commit':OLD,
    'elapsed_s':time.monotonic()-START,'first_error':primary,'close_errors':close_errors,'error_records':error_records,'error_overflow':error_overflow,
    'all_FD_close_attempts_finished':True,'all_fds_retired':not close_errors and fd_before is not None and fd_before==fd_after,'fd_before':fd_before,'fd_after':fd_after,
    'source_checks':source_checks,'pin_closes':pin_closes,'directory_closes':directory_closes,'deadline_before_terminal':late,'commands':commands,'facts':facts,'hardware_acceptance':False},cleanup=True)
   terminal_written=True
  except BaseException as e:fail('operation_terminal',e)
 try:
  fd_after=fd_count();assert fd_before is not None and fd_before==fd_after,'final metadata FD baseline not restored'
 except BaseException as e:fail('post_terminal_FD_baseline',e,closing=True)
 if time.monotonic()>=END:
  late=True;fail('whole_deadline_after_terminal',TimeoutError('renewal actual finalization600s bound'))
 try:
  print(json.dumps({'status':'renewed_non_authority_checkout' if primary is None and not close_errors else 'failed','source_commit':COMMIT,'elapsed_s':time.monotonic()-START,'first_error':primary,'close_errors':close_errors}),flush=True)
 except BaseException as e:fail('final_report',e)
 if time.monotonic()>=END:
  late=True;fail('whole_deadline_after_report',TimeoutError('renewal actual final report600s bound'))
 if output_owned and (not terminal_written or primary!=saved_error or len(error_records)!=saved_count or error_overflow!=saved_overflow or late):
  try:
   value={'status':'failed','source_commit':COMMIT,'previous_source_commit':OLD,'first_error':primary,'late':late,'terminal_written':terminal_written,
    'terminal_path':str(OUT/'execution.v1.json'),'elapsed_s':time.monotonic()-START,'fd_before':fd_before,'fd_after':fd_after,'recent_error_records':error_records[-8:],'error_overflow':error_overflow,'hardware_acceptance':False}
   assert len((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())<=65536
   write('late-or-finalization-failure.v1.json',value,cleanup=True)
  except BaseException as e:
   fail('final_failure_companion',e)
   try:print(json.dumps({'status':'failed','first_error':primary,'companion_error':error(e),'hardware_acceptance':False}),file=sys.stderr,flush=True)
   except BaseException as reporting:fail('failure_companion_report',reporting)
 if time.monotonic()>=END and not late:
  late=True;fail('whole_deadline_after_companion',TimeoutError('renewal companion finalization600s bound'))
  if output_owned:
   try:write('late-failure.v1.json',{'status':'failed','source_commit':COMMIT,'first_error':primary,'elapsed_s':time.monotonic()-START,'hardware_acceptance':False},cleanup=True)
   except BaseException as e:fail('late_failure_companion',e)
 try:clock(cleanup=True)
 except BaseException as e:fail('absolute_cleanup_bound',e)
sys.exit(0 if primary is None and not close_errors else 78)
