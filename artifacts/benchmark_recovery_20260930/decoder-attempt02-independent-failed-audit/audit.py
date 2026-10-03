"""One bounded read-only closed-leaf audit; no decoder or producer import."""
import hashlib,importlib.util,json,os,re,subprocess,time
from pathlib import Path

ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
A=ROOT/'artifacts/benchmark_recovery_20260930'
generic=A/'decoder-independent-cold-v1/cold_reader.py'
assert hashlib.sha256(generic.read_bytes()).hexdigest()=='242842aea976b50a3c27f9b54c574564c4e6f15dc3ee99412474fd42070465a1'
spec=importlib.util.spec_from_file_location('own_independent_custody',generic);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
attempt=A/'decoder-research-attempt-02';external=A/'decoder-research-attempt02-original-controller'
started=time.monotonic();h=g.Held(attempt,started+120)
def doc(p,kind):
 v=h.document(p,kind,under_root=p.is_relative_to(attempt));g.nonpromoting(v);return v
def guest_pin(row):
 p=attempt/'guest'/Path(row['path']).relative_to('/opt/vast/output');h.pin(p,dict(row,path=str(p)));return p
def raw(row):
 p=Path(row['path']);h.pin(p,row,under_root=False);return h.read(p,65536,under_root=False)
try:
 h.pin(Path(__file__).absolute(),under_root=False);h.pin(generic,under_root=False)
 inventory=g.namespace(h,attempt)
 e=doc(external/'terminal.v1.json','vast_decoder_research_external_original_controller_terminal_v1')
 c=doc(attempt/'controller/terminal.v1.json','vast_decoder_research_controller_terminal_v1')
 v=doc(attempt/'guest/metadata/research-terminal.v1.json','vast_decoder_research_guest_terminal_v1')
 run=doc(attempt/'guest/run-01-front_gate-default/terminal.v1.json','vast_decoder_research_run_terminal_v1')
 assert e['source_commit']=='70ef8d0a66d5d42f9a539fb2b414bf61aa1fdc9d' and e['planning_commit']==c['planning_commit']=='b244b5c71aaf1782f3aa54c8e1281191bb5e525a'
 assert e['original_controller_returncode']==1 and not e['timed_out'] and e['capture_exceeded']==[] and e['containment'] is None
 assert e['all_source_epochs_rechecked'] and e['sources_before']==e['sources_after'] and e['failures']==['original controller returned nonzero']
 assert c['original_cli_returncode']==1 and not c['original_execution_completed'] and c['container_not_found_after_owned_remove'] is True
 assert all(c['controller'][k]==e['original_child'][k] for k in c['controller'])
 assert v['runs_completed']==0 and v['result'] is None and v['failure_stage']=='original_run_1'
 assert run['source_returncode'] is None and run['observations'] is None and run['errors']==run['cleanup_errors']==['pin is not a bounded single-link regular file']
 assert {x.name for x in (attempt/'guest').iterdir()}=={'metadata','run-01-front_gate-default'}
 assert {x.name for x in (attempt/'guest/run-01-front_gate-default').iterdir()}=={'run-started.v1.json','events.jsonl','terminal.v1.json'}
 assert (attempt/'guest/run-01-front_gate-default/events.jsonl').stat().st_size==0
 trace=guest_pin(v['failure_traceback']);trace_text=h.read(trace,16384).decode()
 assert 'original research run failed; no retry or subsequent setting allowed' in trace_text
 init=doc(attempt/'guest/metadata/initialization-metadata.v1.json','vast_decoder_research_initialization_metadata_v1')
 pre=doc(attempt/'guest/metadata/prelaunch.v1.json','vast_decoder_research_guest_prelaunch_v1')
 events=[g.strict_json(x) for x in g.bounded_lines(h,attempt/'guest/metadata/events.jsonl')]
 assert init['intended_arguments']==[] and pre['gi_version']=='3.50.0' and pre['gst_version']==[1,28,2,0]
 assert len([x for x in events if x['kind']=='gst_initialization_before' and x['intended_arguments']==[]])==1
 assert len([x for x in events if x['kind']=='gst_initialization_after' and x['actual_initialized'] is True])==1
 for row in e['sources_before']:
  p=Path(row['descriptor']['path']);h.pin(p,row['descriptor'],under_root=False)
  assert h.files[str(p)][1]==row['epoch']
 for row in c['held_inputs']:
  h.pin(Path(row['path']),row,maximum=max(g.RAW_MAX,row['size_bytes']),under_root=False)
 for role in ('stdout','stderr'):raw(e[role])
 launch=doc(Path(e['launch']['path']),'vast_decoder_research_external_original_controller_launch_v1');h.pin(Path(e['launch']['path']),e['launch'],under_root=False)
 dispatch=launch['dispatch_source'];h.pin(Path(dispatch['descriptor']['path']),dispatch['descriptor'],under_root=False)
 assert dispatch['descriptor']['sha256']=='372cfec7e32be7747e21a9ef659d1f9037d5974b5bf04f458704236f377cd28f'
 manifest=doc(Path(c['closed_controller_leaves']['path']),'vast_decoder_research_closed_controller_leaves_v1');h.pin(Path(c['closed_controller_leaves']['path']),c['closed_controller_leaves'])
 assert {Path(x['path']).name for x in manifest['leaves']}=={x.name for x in (attempt/'controller').iterdir()}-{'terminal.v1.json','closed-controller-leaves.v1.json'}
 for row in manifest['leaves']:h.pin(Path(row['path']),row)
 for row in run['closed_original_leaves']:guest_pin(row)
 commands=[]
 for p in sorted((attempt/'controller').glob('engine-*.v1.json')):
  row=doc(p,'vast_decoder_research_engine_observation_v1');assert not row['timed_out'] and row['errors']==[];commands.append((row,raw(row['stdout']),raw(row['stderr'])))
 cid=c['container_id'];state=c['final_observed_state'];name=c['name']
 assert re.fullmatch('[0-9a-f]{64}',cid) and h.read(attempt/'controller/original.cid',65) in (cid.encode(),(cid+'\n').encode())
 assert state['Id']==cid and state['Name']=='/'+name and state['Image']==g.IMAGE and state['Operation']==c['label']
 assert state['Running'] is False and state['Pid']==0 and state['ExitCode']==1 and state['OOMKilled'] is False
 rm=[n for n,(row,out,err) in enumerate(commands) if row['argv']==['/usr/bin/docker','container','rm',cid]];assert len(rm)==1
 n=rm[0];row,out,err=commands[n];assert row['returncode']==0 and out==(cid+'\n').encode() and err==b''
 assert len(commands)>n+2
 for i,identifier in ((n+1,cid),(n+2,name)):
  row,out,err=commands[i];assert row['argv'][-1]==identifier and g.exact_absence(row,out,err,identifier)
 original_states=[g.strict_json(out,maximum=65536) for row,out,err in commands[:n] if row['argv'][1:3]==['container','inspect'] and row['returncode']==0]
 assert original_states and original_states[-1]==state
 assert all(row['returncode']==0 and out==g.canonical(g.DAEMON)+b'\n' and err==b'' for row,out,err in commands if row['argv'][1]=='info')
 reservation=doc(attempt/'controller/reservation.v1.json','vast_decoder_research_reservation_v1')
 assert reservation['daemon_id']==g.DAEMON and reservation['engine']['sha256']==g.ENGINE_SHA and reservation['name']==name and reservation['label']==c['label']
 owners=[e['controller'],e['original_child'],c['child'],*[row['child'] for row,_,_ in commands]]
 assert all(not Path(f'/proc/{x["pid"]}').exists() for x in owners)
 groups={x.get('process_group_id',x['pid']) for x in owners}
 for n,p in enumerate(Path('/proc').iterdir()):
  assert n<16384
  if p.name.isdigit():
   try:fields=(p/'stat').read_text().rsplit(')',1)[1].split()
   except (FileNotFoundError,ProcessLookupError):continue
   assert int(fields[2]) not in groups
 git=['/usr/bin/git','--no-optional-locks','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
 blobchecks=[]
 for row in e['sources_before']+[dispatch]:
  p=Path(row['descriptor']['path']);relative=p.relative_to(ROOT).as_posix()
  commit=e['planning_commit'] if relative.startswith('openspec/changes/') else e['source_commit']
  actual=subprocess.run(git+['show',commit+':'+relative],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5).stdout
  assert hashlib.sha256(actual).hexdigest()==row['descriptor']['sha256'];blobchecks.append({'path':str(p),'commit':commit,'sha256':row['descriptor']['sha256']})
 h.check(rehash=True)
 value={'schema_version':1,'artifact_kind':'vast_decoder_research_attempt02_independent_failed_audit_v1','verdict':'closed_failed_setup_no_science_cohort','planning_commit':e['planning_commit'],'implementation_commit':e['source_commit'],'external_returncode':1,'original_cli_returncode':1,'original_container_terminal':state,'exact_nonforce_remove_then_cid_and_name_absence':True,'host_original_processes_absent_groups_empty':True,'actual_gi_init_empty_list_completed':True,'actual_gst_version':[1,28,2,0],'failed_stage':'first default pipeline setup before source launch','run_error':run['errors'],'underlying_pin_path_stat_kind_size_nlink_unknown':True,'retained_traceback_scope':'Outer run-failed exception only; does not identify original failing Pin path/stat.','actual_source_launch_count':0,'actual_access_units':0,'actual_decoder_observations':0,'completed_runs':0,'remaining_settings_not_started':True,'core_and_code_final_blob_rechecks':blobchecks,'held_physical_inputs':h.observations(),'audit_elapsed_s':time.monotonic()-started,'accepted':False,'publication_ready':False,'native_pair_count':0,'benchmark_arm_count':0,'qualification_count':0,'model_or_parity_evidence':False,'limitations':['Successful Gst.init([]) in this attempt does not prove the original attempt01 failing call.','Pin regular/single-link/size predicate has several possible causes; the original failing file identity/stat is absent.','No decoder timing, RGB correctness, model/parity, six-stream or benchmark scientific conclusion exists.','This audit invokes read-only Git only; no Docker, GI, source, decoder, model or retry.']}
 value['sha256']=hashlib.sha256(g.canonical(value)).hexdigest();out=Path(__file__).parent/'review.v1.json';rawbytes=g.canonical(value)+b'\n'
 with out.open('xb') as f:f.write(rawbytes);f.flush();os.fsync(f.fileno())
 print(g.canonical({'path':str(out),'size_bytes':len(rawbytes),'sha256':hashlib.sha256(rawbytes).hexdigest(),'verdict':value['verdict']}).decode())
finally:h.close()
