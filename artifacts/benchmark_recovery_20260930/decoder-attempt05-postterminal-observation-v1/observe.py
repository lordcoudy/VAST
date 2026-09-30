from pathlib import Path
import hashlib,json,os,stat,time
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
OUT=BASE/'decoder-attempt05-postterminal-observation-v1'
rows=[]
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def epoch(x):return [x.st_dev,x.st_ino,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns]
def read(path,maximum=32768):
 path=Path(path);info=path.lstat();assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=maximum
 with path.open('rb') as f:
  before=epoch(os.fstat(f.fileno()));raw=f.read(maximum+1);after=epoch(os.fstat(f.fileno()))
 assert len(raw)<=maximum and before==after==epoch(path.lstat())
 d={'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()};rows.append({'descriptor':d,'epoch':before});return raw,d

def doc(path):
 raw,d=read(path);value=json.loads(raw);copy=dict(value);seal=copy.pop('sha256');assert seal==hashlib.sha256(canonical(copy)).hexdigest();return value,d
external,ed=doc(BASE/'decoder-research-attempt05-original-controller/terminal.v1.json')
controller,cd=doc(BASE/'decoder-research-attempt-05/controller/terminal.v1.json')
guest,gd=doc(BASE/'decoder-research-attempt-05/guest/metadata/research-terminal.v1.json')
primary,pd=doc(BASE/'decoder-research-attempt-05/guest/metadata/original-inner-failure.v1.json')
maps,md=doc(BASE/'decoder-research-attempt-05/guest/metadata/mapped-inputs-01.v1.json')
reservation,rd=doc(BASE/'decoder-research-attempt-05/controller/reservation.v1.json')
assert guest['original_primary_failure']['sha256']==pd['sha256'] and guest['original_primary_failure']['size_bytes']==pd['size_bytes']
assert primary['pin_rejection']['mapping_snapshot']['sha256']==md['sha256']
assert external['original_controller_returncode']==controller['original_cli_returncode']==1 and not external['timed_out']
assert guest['runs_completed']==0 and guest['result'] is None and guest['primary_failure_capture_error'] is None
assert controller['container_not_found_after_owned_remove']
cid=controller['container_id'];name=controller['name'];image=controller['image_id'];label=controller['label']
engine=[]
for i in (6,7,8,9):
 value,d=doc(BASE/f'decoder-research-attempt-05/controller/engine-{i:02d}.v1.json')
 stdout,sd=read(BASE/f'decoder-research-attempt-05/controller/engine-{i:02d}.stdout',1048576)
 stderr,se=read(BASE/f'decoder-research-attempt-05/controller/engine-{i:02d}.stderr',1048576)
 assert value['stdout']['sha256']==sd['sha256'] and value['stderr']['sha256']==se['sha256']
 assert value['stdout']['size_bytes']==sd['size_bytes'] and value['stderr']['size_bytes']==se['size_bytes']
 assert not value['timed_out'] and not value['errors'] and value['argv'][0]==reservation['engine']['path']
 engine.append({'record':d,'stdout':sd,'stderr':se,'argv':value['argv'],'returncode':value['returncode'],'observed_realtime_ns':value['observed_realtime_ns']})
 if i==6:
  state=json.loads(stdout);assert state==controller['final_observed_state'];assert state['Id']==cid and state['Name']=='/'+name and state['Image']==image and state['Operation']==label
  assert state['Running'] is False and state['Pid']==0 and state['ExitCode']==1 and state['OOMKilled'] is False
 elif i==7:
  assert value['argv']==[reservation['engine']['path'],'container','rm',cid] and value['returncode']==0 and stdout==(cid+'\n').encode() and stderr==b''
 else:
  identifier=cid if i==8 else name
  assert value['argv'][-1]==identifier and value['returncode']==1 and stdout==b'\n' and stderr==('Error response from daemon: No such container: '+identifier+'\n').encode()
assert [x['observed_realtime_ns']for x in engine]==sorted(x['observed_realtime_ns']for x in engine)
processes=[external['controller'],external['original_child'],controller['child']]
assert len({p['pid']for p in processes})==3
ids={p['pid']for p in processes};boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert all(p['boot_id']==boot for p in processes)
scans=[]
for i in range(2):
 began=time.time_ns();members=[];observations=[]
 for p in processes:
  path=Path(f"/proc/{p['pid']}")
  observations.append({'pid':p['pid'],'exists':path.exists(),'original_starttime_ticks':p['starttime_ticks']})
 for directory in Path('/proc').iterdir():
  if not directory.name.isdigit():continue
  try:
   tail=(directory/'stat').read_text().rsplit(')',1)[1].split()
  except (FileNotFoundError,ProcessLookupError,PermissionError):continue
  pid=int(directory.name);pgid=int(tail[2]);session=int(tail[3]);ppid=int(tail[1])
  if pid in ids or pgid in ids or session in ids or ppid in ids:
   members.append({'pid':pid,'ppid':ppid,'process_group_id':pgid,'session_id':session,'starttime_ticks':int(tail[19])})
 scans.append({'begun_at_ns':began,'finished_at_ns':time.time_ns(),'original_pid_observations':observations,'original_group_members':members})
 assert not members and not any(x['exists']for x in observations)
record={'schema_version':1,'artifact_kind':'vast_decoder_research_postterminal_failed_observation_v1','observed_at_ns':time.time_ns(),'source_commit':external['source_commit'],'planning_commit':external['planning_commit'],'pr_authorization_comment':5906812116,'external_terminal':ed,'controller_terminal':cd,'guest_terminal':gd,'original_primary_failure':pd,'original_mapping_snapshot':md,'original_external_returncode':external['original_controller_returncode'],'original_cli_returncode':controller['original_cli_returncode'],'original_process_owners':processes,'actual_postterminal_process_observations':scans,'original_retained_engine_state':state,'original_container_id':cid,'original_retained_owned_remove_then_CID_name_absence':True,'original_retained_engine_join':engine,'original_failure':primary['message'],'original_failure_stage':primary['stage'],'failed_pin_path':primary['pin_rejection']['requested_path'],'original_pin_rejection':primary['pin_rejection'],'original_failure_traceback':primary['traceback'],'primary_capture_error':guest['primary_failure_capture_error'],'runs_completed':guest['runs_completed'],'result':guest['result'],'actual_run_directories':[str(p)for p in sorted((BASE/'decoder-research-attempt-05/guest').glob('run-*'))],'original_source_epoch_recheck':external['all_source_epochs_rechecked'],'retained_inputs':rows,'limits':['No new Docker/daemon/container query or mutation; state/OOM/removal/absence derive only from physically joined original engine records','Two current bounded proc scans of original three PID/session/group tokens; host absence does not establish container state','Original maps device2112 and opened/named device77 disagreement is observed; topology explanation remains unproven','No retry/source/AU/frame/scientific/model/parity/qualification/benchmark result'],'accepted':False,'publication_ready':False}
assert not record['actual_run_directories']
record['sha256']=hashlib.sha256(canonical(record)).hexdigest();path=OUT/'observation.v1.json'
with path.open('xb') as f:f.write(canonical(record)+b'\n');f.flush();os.fsync(f.fileno())
raw=path.read_bytes();print(json.dumps({'receipt':{'path':str(path),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'original_pids':[p['pid']for p in processes],'two_scans_absent':True,'retained_engine_remove_then_both_absences':True}))
