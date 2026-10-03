"""Close finite attrs evidence; no original checkout or benchmark operation."""
import hashlib,json,os,stat,subprocess,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(p):
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8388608;h=hashlib.sha256();raw=b''
  while b:=os.read(fd,65536):h.update(b);raw+=b
  assert epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat()) and len(raw)==s.st_size
  return raw,{'path':str(p),'size_bytes':len(raw),'sha256':h.hexdigest(),'epoch':epoch(s)}
 finally:os.close(fd)
proposal=json.loads((HERE/'preedit-proposal-and-authorization.v1.json').read_bytes())
effect_path=HERE/'controlled-original-attempt01/execution.v1.json';effect_raw,effect_pin=pin(effect_path)
assert effect_pin['sha256']=='3722e20001bfb378d825d311aa3f63d5d910c4ddbe2ba561dfe3356cf7a62960'
effect=json.loads(effect_raw);assert effect['status']=='passed_existing_index_fixture_only'
old=(HERE/'gitattributes.before.raw').read_bytes();current,attrs=pin(ROOT/'.gitattributes')
assert attrs['sha256']=='504ceb16d7ab7cff66925251859ccb453bfb3b0190b12f6ad0eba64ed79a9acd'
rules=proposal['proposed_only_mutation']['append_exact_rules']
assert current==old+b'\n# Preserve the two additional original JSON blobs exposed by existing-index checkout.\n'+('\n'.join(rules)+'\n').encode()
source_after={}
for relative,ref in proposal['before_source_descriptors'].items():
 raw,after=pin(ROOT/relative);assert after==ref;source_after[relative]=after
payloads=[]
for row in proposal['findings']:
 raw,after=pin(ROOT/row['path']);assert after==row['original_git_and_primary']
 actual=Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')/row['path']
 assert epoch(actual.lstat())==row['failed_renewal_actual_epoch']
 payloads.append(after)
paths=sorted(set(proposal['finite_owned_scan']['paths'])|{p.relative_to(ROOT).as_posix() for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.json','.md')})
raw_ids={};after_scan=[]
for relative in paths:
 raw,ref=pin(ROOT/relative);raw_ids[relative]=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest();after_scan.append(ref)
git=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
clean=subprocess.run(git+['hash-object','--stdin-paths'],input=('\n'.join(paths)+'\n').encode(),capture_output=True,check=True,cwd=ROOT,timeout=20)
assert clean.stderr==b'';ids=clean.stdout.decode().splitlines();assert len(ids)==len(paths)
assert all(raw_ids[p]==i for p,i in zip(paths,ids,strict=True))
diff=subprocess.run(git+['diff','--','.gitattributes'],capture_output=True,check=True,timeout=10)
with (HERE/'only-production-attributes.diff').open('xb') as f:f.write(diff.stdout);f.flush();os.fsync(f.fileno())
owners=[effect['controller']]+[r['owner'] for r in effect['original_git_commands']]
target_ids={o['pid'] for o in owners};target_groups={o['pgid'] for o in owners};target_sessions={o['session'] for o in owners}
scans=[]
for ignored in range(2):
 found=[];errors=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   v=(p/'stat').read_text().rsplit(')',1)[1].split()
   if int(p.name) in target_ids or int(v[2]) in target_groups or int(v[3]) in target_sessions:found.append({'pid':int(p.name),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19])})
  except FileNotFoundError:pass
  except (OSError,ValueError) as e:errors.append({'pid':int(p.name),'type':type(e).__name__,'errno':getattr(e,'errno',None)})
 scans.append({'at_ns':time.time_ns(),'members':found,'errors':errors,'pids_absent':{str(i):not Path('/proc',str(i)).exists() for i in sorted(target_ids)}})
assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
owned=[]
for p in sorted(HERE.rglob('*')):
 if p.is_file():owned.append(pin(p)[1])
value={'schema_version':1,'status':'frozen_exact_two_attrs_repair_pending_peer_checkpoint',
 'only_production_path':'.gitattributes','after_attributes':attrs,'exact_rules':rules,
 'original_prefix_first15_and_all_LF_contracts_unchanged':True,'raw_payloads_and_epochs_unchanged':payloads,
 'source_146_after_equal_before':source_after,'all_two_excluded_87_73_native_worker_and_original_copy_scope':True,
 'finite_owned_raw_clean_after_scan':{'count':len(paths),'physical_rows':after_scan,'raw_blob_ids':raw_ids,'clean_blob_ids':dict(zip(paths,ids,strict=True)),'mismatch_paths':[]},
 'genuine_existing_index_effect':effect_pin,'ordinary_checkout_cases':effect['existing_index_cases'],
 'controller_and_53_children_postterminal_scans':scans,'all_metadata_read_fds_closed':True,
 'closed_owned_files':owned,'source_commit_before_checkpoint':'78b869e4f8bc101413ed00776bd89d1089a8318d',
 'original_failed_renewal_and_original_failed_CI_untouched':True,'no_full_ci_or_hardware_acceptance':True,
 'explicit_limit':'The genuine existing-index fixture includes scratch-only --really-refresh and object-ID comparisons to expose cached status. No original index refresh, normalization, reset, clean or renewal retry occurred. Source/campaign acceptance still needs genuine new checkpoint and stock gates.',
 'prepared_at_ns':time.time_ns()}
raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
with (HERE/'author-review.v1.json').open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
print(json.dumps({'path':str(HERE/'author-review.v1.json'),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'after_scan_count':len(paths),'owned_files':len(owned),'source_count':len(source_after),'no_holds':True}))
