"""Real tiny existing-index checkout of the two actual raw blobs; fixture only."""
import hashlib,json,os,signal,subprocess,time,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
START=time.monotonic();END=START+120;HARD=END+10
BOOT=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
proposal=json.loads((HERE/'preedit-proposal-and-authorization.v1.json').read_bytes())
PATHS=[r['path'] for r in proposal['findings']]
OLD=(HERE/'gitattributes.before.raw').read_bytes();NEW=(HERE/'gitattributes.after.raw').read_bytes()
assert NEW.startswith(OLD) and (ROOT/'.gitattributes').read_bytes()==NEW
SCRATCH=Path('/var/tmp')/('vast-forensic-json-existing-index-'+uuid.uuid4().hex);SCRATCH.mkdir(mode=0o700)
OUT=HERE/'controlled-original-attempt01';OUT.mkdir(mode=0o700)
records=[];children=[]
def save(name,raw):
 with (OUT/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
 return {'path':str(OUT/name),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def owner(pid):
 p=Path('/proc',str(pid));v=(p/'stat').read_text().rsplit(')',1)[1].split();s=dict(l.split(':',1) for l in (p/'status').read_text().splitlines() if ':' in l)
 return {'pid':pid,'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19]),'uid':int(s['Uid'].split()[0]),'gid':int(s['Gid'].split()[0]),'boot_id':BOOT}
def git(root,*arguments,stdin=None,allowed=(0,)):
 assert time.monotonic()<END
 argv=['/usr/bin/git','-c','core.longpaths=true','-c','core.hooksPath=/dev/null','-C',str(root),*arguments]
 p=subprocess.Popen(argv,stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 o=None;out=b'';err=b'';failure=None
 try:
  o=owner(p.pid);children.append(o)
  out,err=p.communicate(stdin,timeout=min(15,END-time.monotonic()))
 except BaseException as e:
  failure={'type':type(e).__name__,'message':str(e)}
  if p.poll() is None:os.killpg(p.pid,signal.SIGKILL)
  out,err=p.communicate(timeout=max(.001,HARD-time.monotonic()))
  raise
 finally:
  for pipe in (p.stdin,p.stdout,p.stderr):
   if pipe is not None:pipe.close()
  row={'argv':argv,'owner':o,'returncode':p.returncode,'allowed_returncodes':list(allowed),'first_error':failure,
       'stdout':save(f'{len(records):03}.stdout.raw',out),'stderr':save(f'{len(records):03}.stderr.raw',err),
       'child_reaped':p.poll() is not None,'child_pid_absent':not Path('/proc',str(p.pid)).exists()}
  records.append(row)
 assert p.returncode in allowed and len(out)<=65536 and len(err)<=65536,row
 return out
def raw_file(root,name,raw):
 p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
def observed(root):
 raw_status=git(root,'status','--porcelain=v1','-z');rows=[]
 for r in proposal['findings']:
  raw=(root/r['path']).read_bytes()
  clean=git(root,'hash-object','--path='+r['path'],'--stdin',stdin=raw).decode().strip()
  assert len(raw)==r['original_git_and_primary']['size_bytes'] and hashlib.sha256(raw).hexdigest()==r['original_git_and_primary']['sha256']
  rows.append({'path':r['path'],'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'original_raw_oid':r['git_blob_id'],'actual_clean_oid':clean})
 return {'status_entries':[x.decode() for x in raw_status.split(b'\0') if x],'status_hex':raw_status.hex(),'raw_rows':rows}
def scan(ids):
 rows=[];errors=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   v=(p/'stat').read_text().rsplit(')',1)[1].split()
   if int(p.name) in ids or int(v[2]) in ids or int(v[3]) in ids:rows.append(owner(int(p.name)))
  except FileNotFoundError:pass
  except (OSError,ValueError) as e:errors.append({'pid':int(p.name),'type':type(e).__name__,'errno':getattr(e,'errno',None)})
 return {'at_ns':time.time_ns(),'members':rows,'errors':errors,'pids_absent':{str(i):not Path('/proc',str(i)).exists() for i in sorted(ids)}}
try:
 seed=SCRATCH/'seed';seed.mkdir()
 git(seed,'init','-q');git(seed,'config','core.autocrlf','false');git(seed,'config','user.name','Finite Git fixture');git(seed,'config','user.email','fixture.invalid@example.invalid')
 raw_file(seed,'.gitattributes',OLD);git(seed,'add','--','.gitattributes');git(seed,'commit','-q','-m','Old tree before the two new forensic blobs')
 old_commit=git(seed,'rev-parse','HEAD').decode().strip()
 for row in proposal['findings']:
  raw=Path(row['saved_original_git_blob']['path']).read_bytes()
  oid=git(seed,'hash-object','-w','--stdin',stdin=raw).decode().strip();assert oid==row['git_blob_id']
  git(seed,'update-index','--add','--cacheinfo','100644,'+oid+','+row['path'])
 git(seed,'commit','-q','-m','Raw new forensic blobs with inherited text LF contract')
 bad_commit=git(seed,'rev-parse','HEAD').decode().strip()
 (seed/'.gitattributes').write_bytes(NEW);git(seed,'add','--','.gitattributes');git(seed,'commit','-q','-m','Two exact raw byte rules')
 fixed_commit=git(seed,'rev-parse','HEAD').decode().strip()
 assert git(seed,'diff','--name-only','-z',bad_commit,fixed_commit)==b'.gitattributes\0'
 results=[]
 for autocrlf in ('false','true'):
  target=SCRATCH/('existing-'+autocrlf)
  git(SCRATCH,'clone','--no-local','--no-checkout',str(seed),str(target))
  git(target,'config','core.autocrlf',autocrlf);git(target,'checkout','--detach',old_commit)
  assert git(target,'status','--porcelain=v1','-z')==b'' and all(not (target/p).exists() for p in PATHS)
  # Ordinary checkout operates on an existing index; no reset/clean/rewrite.
  git(target,'checkout','--detach',bad_commit)
  immediate_red=observed(target)
  assert all(r['actual_clean_oid']!=r['original_raw_oid'] for r in immediate_red['raw_rows'])
  # Force an explicit real index refresh diagnostic, so a cached status cannot
  # hide clean-filter disagreement. This operates only on the tiny fixture.
  git(target,'update-index','--really-refresh',allowed=(0,1))
  confirmed_red=observed(target)
  assert confirmed_red['status_entries']==[' M '+p for p in PATHS],confirmed_red
  git(target,'checkout','--detach',fixed_commit)
  git(target,'update-index','--really-refresh')
  green=observed(target)
  assert green['status_entries']==[] and all(r['actual_clean_oid']==r['original_raw_oid'] for r in green['raw_rows'])
  effective=git(target,'check-attr','-z','text','eol','--stdin',stdin=('\0'.join(PATHS)+'\0').encode()).decode().split('\0')[:-1]
  assert all(effective[i+2]==('unset' if effective[i+1]=='text' else 'unspecified') for i in range(0,len(effective),3))
  results.append({'initial_autocrlf':autocrlf,'root':str(target),'old_head':old_commit,'bad_head':bad_commit,'fixed_head':fixed_commit,'immediate_after_ordinary_checkout':immediate_red,'confirmed_red_after_explicit_refresh':confirmed_red,'green_after_ordinary_checkout_and_refresh':green,'effective_attributes_nul_fields':effective})
 for row in proposal['findings']:
  raw=(ROOT/row['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['original_git_and_primary']['sha256']
 assert (ROOT/'.gitattributes').read_bytes()==NEW
 ids={o['pid'] for o in children};scans=[scan(ids),scan(ids)]
 assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
 report={'schema_version':1,'status':'passed_existing_index_fixture_only','controller':owner(os.getpid()),'scratch':str(SCRATCH),
  'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'existing_index_cases':results,'original_git_commands':records,
  'source_and_fixed_tree_only_difference':'.gitattributes','all_raw_payloads_preserved':True,'all_children_reaped_and_capture_fds_closed':True,
  'process_scans':scans,'elapsed_s':time.monotonic()-START,'no_full_checkout_ci_or_benchmark_acceptance':True,
  'stat_cache_limit':'Immediate clean status may be cached; explicit refresh plus clean/raw object equality is required by this fixture. Existing original roots were never refreshed or mutated.'}
 assert report['elapsed_s']<120
 ref=save('execution.v1.json',(json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
 assert time.monotonic()<END
 print(json.dumps({'execution':ref,'git_child_count':len(children),'elapsed_s':report['elapsed_s'],'status':report['status']}))
except BaseException as e:
 save('failed.v1.json',(json.dumps({'status':'failed_fixture','type':type(e).__name__,'message':str(e),'commands':records,'scratch':str(SCRATCH)},sort_keys=True,indent=2)+'\n').encode())
 raise
