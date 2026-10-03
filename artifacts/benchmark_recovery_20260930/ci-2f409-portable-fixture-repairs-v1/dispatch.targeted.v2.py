import argparse, hashlib, json, os, selectors, signal, subprocess, sys, time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--project-root',required=True);p.add_argument('--output-dir',required=True);a=p.parse_args()
root=Path(a.project_root).resolve(strict=True);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=False)
modules=['test_checkpoint_model_parity_materializer_v4','test_checkpoint_deepstream_qualification_fragment_v1','test_checkpoint_openvino_gva_qualification_fragment_v3','test_checkpoint_savant_qualification_fragment_v3','test_publication_policy_qualification_fragments_from_authority_v2','test_publication_operational_container_custody_v1','test_backend_runtime_replay_runner_authority_v2','test_checkpoint_source_runtime_closure_authority_v1','test_replay_broker_artifact_bytes_observation_v4','test_ci_test_selection_v1']
paths=['tests/'+n+'.py' for n in modules]+['.ci/integration-test-selection.v1.json','scripts/ci_test_selection_v1.py','scripts/run_ci_checks.py','scripts/publication_physical_io_v1.py','scripts/checkpoint_deepstream_qualification_fragment_v1.py','scripts/checkpoint_savant_qualification_fragment_v3.py','scripts/checkpoint_openvino_gva_qualification_fragment_v3.py','scripts/publication_policy_qualification_fragments_from_authority_v2.py','scripts/publication_operational_process_custody_v1.py','scripts/publication_operational_container_custody_v1.py']
paths+=sorted(p.relative_to(root).as_posix() for d in ('publication_worker_manifest_v1','gstreamer_fragment_unit_v1') for p in (root/'.ci/fixtures'/d).rglob('*') if p.is_file())
paths+=sorted(p.relative_to(root).as_posix() for p in (root/'deploy/deepstream/checkpoint/wheels').glob('*.whl'))
paths+=['deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt','deploy/deepstream/checkpoint/requirements.lock']
def pins():
    return {n:{'size_bytes':(root/n).stat().st_size,'sha256':hashlib.sha256((root/n).read_bytes()).hexdigest()} for n in paths}
def save(name,value):
    raw=json.dumps(value,sort_keys=True,indent=2).encode()+b'\n'
    with (out/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
before=pins();save('source.before.json',before)
code='''import json,pathlib,sys,unittest
root=pathlib.Path(sys.argv[1]);sys.path[:0]=[str(root/'tests'),str(root/'scripts'),str(root)]
import run_ci_checks as checks,ci_test_selection_v1 as selection
manifest=json.loads((root/'.ci/integration-test-selection.v1.json').read_bytes())
original=json.loads((root/'artifacts/benchmark_recovery_20260930/ci-2f409-readonly-failure-diagnosis-v1/failure-index.v1.json').read_bytes())
assert len(manifest['allowed_portable_skips'])==88
selection.validate_portable_skips_v1(original['original_skips'],{'allowed_portable_skips':manifest['allowed_portable_skips']})
suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3:]);r=unittest.TextTestRunner(verbosity=2,resultclass=checks.RecordedResult).run(suite)
value={'tests_run':r.testsRun,'successes':r.successes,'errors':[{'test_id':t.id(),'traceback':x} for t,x in r.errors],'failures':[{'test_id':t.id(),'traceback':x} for t,x in r.failures],'skips':[{'test_id':t.id(),'reason':x} for t,x in r.skipped],'successful':r.wasSuccessful(),'exact_existing_skip_declarations':88,'no_full_suite_or_hardware_claim':True}
pathlib.Path(sys.argv[2]).open('x').write(json.dumps(value,sort_keys=True,indent=2)+'\\n')
sys.exit(0 if r.wasSuccessful() else 1)
'''
test_names=['test_checkpoint_openvino_gva_qualification_fragment_v3.OpenVINOGVAQualificationFragmentV3Tests.test_exact_worker_receipt_and_resource_v2_evidence_are_bound', 'test_checkpoint_openvino_gva_qualification_fragment_v3.OpenVINOGVAQualificationFragmentV3Tests.test_phase_one_materializes_exact_policy_and_resource_bindings', 'test_checkpoint_openvino_gva_qualification_fragment_v3.OpenVINOGVAQualificationFragmentV3Tests.test_policy_identity_is_the_external_worker_and_topology_v2_is_invariant', 'test_checkpoint_savant_qualification_fragment_v3.SavantQualificationFragmentV3Tests.test_phase_one_materializes_ten_physical_bindings_and_no_pilots', 'test_checkpoint_savant_qualification_fragment_v3.SavantQualificationFragmentV3Tests.test_refreeze_and_exact_runtime_identity_fields_are_bound', 'test_publication_operational_container_custody_v1.OriginalContainerCompositionTests.test_actual_retained_terminal_and_resealed_invalid_times_are_checked', 'test_publication_policy_qualification_fragments_from_authority_v2.QualificationFragmentsFromAuthorityV2Tests.test_dangling_system_collision_is_never_treated_as_absent', 'test_ci_test_selection_v1.SelectionContracts.test_all_original_platform_and_retired_skip_ids_remain_nonexecution']
argv=[sys.executable,'-I','-B','-c',code,str(root),str(out/'test-results.json'),*test_names]
begin=time.monotonic();deadline=begin+600;process=None;selector=selectors.DefaultSelector();streams={};size={'stdout':0,'stderr':0};eof={'stdout':False,'stderr':False};failure=None;timed_out=False;owner=None
try:
    streams={n:(out/(n+'.raw')).open('xb') for n in size}
    process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    fields=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split();owner={'pid':process.pid,'pgid':os.getpgid(process.pid),'startticks':int(fields[19]),'uid':os.getuid(),'gid':os.getgid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    save('launch.json',{'argv':argv,'owner':owner,'python':sys.version,'deadline_seconds':600,'started_monotonic':begin})
    for n,pipe in [('stdout',process.stdout),('stderr',process.stderr)]:os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,n)
    while selector.get_map() or process.poll() is None:
        if time.monotonic()>=deadline:timed_out=True;raise TimeoutError('original focused600s cap')
        for key,_ in selector.select(.1):
            block=os.read(key.fileobj.fileno(),65536);n=key.data
            if not block:eof[n]=True;selector.unregister(key.fileobj);continue
            allowed=max(0,1024*1024-size[n]);retained=block[:allowed];streams[n].write(retained);size[n]+=len(retained)
            if len(retained)!=len(block):raise RuntimeError('original focused channel exceeds1MiB')
except BaseException as e:
    failure=type(e).__name__+': '+str(e)
finally:
    cleanup_end=time.monotonic()+15
    if process is not None and process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=max(0,cleanup_end-time.monotonic()-2))
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=max(0,cleanup_end-time.monotonic()))
    selector.close()
    if process is not None:
        process.stdout.close();process.stderr.close()
    for stream in streams.values():stream.flush();os.fsync(stream.fileno());stream.close()
after=pins();save('source.after.json',after)
remaining=[]
if owner:
    for item in Path('/proc').iterdir():
        if not item.name.isdigit():continue
        try:
            f=(item/'stat').read_text().rsplit(')',1)[1].split()
            if int(f[2])==owner['pgid']:remaining.append(int(item.name))
        except (OSError,ValueError,IndexError):pass
rc=process.returncode if process else None
save('execution.json',{'returncode':rc,'failure':failure,'timed_out':timed_out,'pipe_eof':eof,'channel_bytes':size,'elapsed_s':time.monotonic()-begin,'owner':owner,'original_pid_absent':owner is not None and not Path('/proc/'+str(owner['pid'])).exists(),'original_group_members':remaining,'source_stable':before==after,'source_path_count':len(before),'fixture_only_no_real_engine_or_model_execution':True,'successful':rc==0 and failure is None and before==after and not remaining and all(eof.values())})
raise SystemExit(0 if rc==0 and failure is None and before==after and not remaining and all(eof.values()) else 1)
