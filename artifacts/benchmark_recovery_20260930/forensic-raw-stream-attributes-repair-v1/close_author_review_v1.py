"""Close finite source/effect/FD/process facts after original raw filter proof."""
import hashlib,json,os,stat,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent;START=time.monotonic()
def epoch(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def pin(p):
 assert p.resolve(strict=True)==p;fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  s=os.fstat(fd);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8*1048576
  h=hashlib.sha256();size=0
  while b:=os.read(fd,65536):h.update(b);size+=len(b);assert time.monotonic()-START<120
  assert size==s.st_size and epoch(s)==epoch(os.fstat(fd))==epoch(p.lstat())
  return {'path':str(p),'size_bytes':size,'sha256':h.hexdigest(),'epoch7':epoch(s)}
 finally:os.close(fd)
def save(name,value):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode('ascii')
 with (HERE/name).open('xb') as f:assert f.write(raw)==len(raw);f.flush();os.fsync(f.fileno())
 return pin(HERE/name)
proposal=json.loads((HERE/'preedit-proposal-and-authorization.v1.json').read_bytes())
red=json.loads((HERE/'red-original-attempt01/execution.v1.json').read_bytes())
green=json.loads((HERE/'green-original-attempt01/execution.v1.json').read_bytes())
assert green['mismatches']=={'false':[],'true':[]} and green['other_extension_mismatches']=={'false':[],'true':[]}
old=(HERE/'gitattributes.before.raw').read_bytes();new=(HERE/'gitattributes.after.raw').read_bytes()
append=b'\n# Captured forensic raw streams are byte evidence; disable automatic EOL conversion.\n/artifacts/benchmark_recovery_20260930/**/*.raw -text !eol\n'
assert len(old)==16430 and hashlib.sha256(old).hexdigest()=='504ceb16d7ab7cff66925251859ccb453bfb3b0190b12f6ad0eba64ed79a9acd'
assert new==old+append and (ROOT/'.gitattributes').read_bytes()==new
sources={p:pin(ROOT/p) for p in proposal['before_source_146']}
assert sources==proposal['before_source_146']
assert {p:epoch((ROOT/p).lstat()) for p in proposal['source_controller_180_metadata_before']}==proposal['source_controller_180_metadata_before']
payloads={p:pin(ROOT/p) for p in proposal['raw_payloads_before']};assert payloads==proposal['raw_payloads_before']
owned={p.relative_to(ROOT).as_posix():pin(p) for p in HERE.rglob('*') if p.is_file()}
assert all(not p.is_symlink() for p in HERE.rglob('*'))
ids={v['observer']['pid']:v['observer'] for v in (red,green)}
for v in (red,green):ids.update({r['owner']['pid']:r['owner'] for r in v['commands']})
groups={row['pgid'] for row in ids.values()}
sessions={row['sid'] for v in (red,green) for row in [r['owner'] for r in v['commands']]}
scans=[]
for unused in range(2):
 members=[];errors=[]
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   fields=(p/'stat').read_text().rsplit(')',1)[1].split();pid=int(p.name)
   if pid in ids or int(fields[2]) in groups or int(fields[3]) in sessions:
    members.append({'pid':pid,'pgid':int(fields[2]),'sid':int(fields[3]),'startticks':int(fields[19])})
  except FileNotFoundError:pass
  except (OSError,ValueError) as exc:errors.append({'pid':int(p.name),'type':type(exc).__name__,'errno':getattr(exc,'errno',None)})
 scans.append({'at_ns':time.time_ns(),'members':members,'errors':errors,'pids_absent':{str(p):not Path('/proc',str(p)).exists() for p in ids}})
assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
changed=[]
for relative in sorted(set(red['physical'])&set(green['physical'])):
 before=red['physical'][relative];after=green['physical'][relative]
 if (before['size_bytes'],before['sha256'])!=(after['size_bytes'],after['sha256']):changed.append(relative)
assert changed==['.gitattributes'],changed
value={'schema_version':1,'status':'author_verified_one_raw_family_ready_for_independent_peer','only_production_path':'.gitattributes','before_attributes':pin(HERE/'gitattributes.before.raw'),'current_attributes':pin(ROOT/'.gitattributes'),'exact_append':append.decode('ascii'),'whole16430_prefix_17JSON_45LF_preserved':True,'raw_stream_extension_semantics':'Captured original bytes, not parse/reserialize; no inference or source grants.','owned_evidence':owned,'original_preflight':proposal['root_original_preflight_rejection'],'red_original':pin(HERE/'red-original-attempt01/execution.v1.json'),'green_original':pin(HERE/'green-original-attempt01/execution.v1.json'),'red_scope':{'count':red['scope_count'],'bytes':red['scope_bytes'],'mismatches':red['mismatches']},'green_scope':{'count':green['scope_count'],'bytes':green['scope_bytes'],'mismatches':green['mismatches'],'other_extensions':green['other_extension_mismatches']},'all_raw_stat_inventory_count':len(green['all_current_raw_stat_only']),'protected_membership':green['raw_family_protected_membership'],'before_after_finite_common_byte_changed_paths':changed,'current146_full_source_pins':sources,'all146_bytes_named7epochs_unchanged':True,'all180_source_controller_metadata_unchanged':True,'raw_payloads':payloads,'original_closed_prior17JSON_authorities_unchanged':True,'actual_process_identities':list(ids.values()),'two_postterminal_process_scans':scans,'all_source_evidence_read_FDs_released':True,'no_git_stage_checkout_commit_or_payload_mutation':True,'no_runtime_model_or_CI_acceptance':True,'original_tool_terminals':[{'chunk_id':'6e7a9d','phase':'red','exit_code':0},{'chunk_id':'f77bbf','phase':'append','exit_code':0},{'chunk_id':'b38089','phase':'green','exit_code':0}],'limits_s':{'proof_work':120,'outer_teardown':10},'elapsed_before_final_receipt_s':time.monotonic()-START}
ref=save('author-review.v1.json',value)
late=time.monotonic()-START>=120
if late:save('late-failure.v1.json',{'closed_report':ref,'elapsed_s':time.monotonic()-START})
assert not late
print(json.dumps(ref),flush=True)
