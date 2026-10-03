"""Finite read-only original-byte/metadata join; no reducer/renderer/contracts executed."""
import csv
import hashlib
import io
import json
import os
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
OUT=Path(__file__).resolve().parent
SCIENCE=BASE/'decision28-four-arm-science-preparation-v1/attempt01'
END=time.monotonic()+120
verified={}
def clock():assert time.monotonic()<END,'finite metadata review120s'
def local(path):
    if path.startswith('/mnt/e/'):
        p=Path('E:/'+path[len('/mnt/e/'):]);assert p.is_relative_to(ROOT);return p
    assert path.startswith('/')
    return Path(r'\\wsl.localhost\Ubuntu')/path.lstrip('/')
def read(path,maximum=1024*1024):
    clock()
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());raw=stream.read(maximum+1);after=os.fstat(stream.fileno())
    assert len(raw)<=maximum and len(raw)==before.st_size
    assert (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    return raw
def pin(path,label=None):
    raw=read(path)
    return {'path':str(path) if label is None else label,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def doc(path):return json.loads(read(path))
def join(row):
    path=local(row['path']);actual=pin(path,row['path'])
    assert actual['size_bytes']==row['size_bytes'] and actual['sha256']==row['sha256']
    return json.loads(read(path))
terminal=doc(SCIENCE/'terminal.v1.json')
custody=join(terminal['custody']);exports=join(terminal['exports']);summaries=join(terminal['recomputed_summaries'])
root_closure=doc(SCIENCE/'root-original-science-closure.v1.json')
assert pin(SCIENCE/'root-original-science-closure.v1.json')['sha256']=='0d8c6dab6237e9e1d7b16197c9000bb4da2343bf2f61d8dcbd7e3d397e6da199'
assert terminal['completed_pure_reduction'] is True and terminal['original_child_returncode']==0
assert terminal['primary_error'] is None and terminal['additional_errors']==[] and not terminal['timed_out'] and not terminal['capture_exceeded']
assert terminal['observed_eof']==['stderr','stdout'] and terminal['original_child_current'] is None and terminal['original_group_members']==[]
assert terminal['source_before']==terminal['source_after'] and terminal['elapsed_s']<120
assert custody['primary_error'] is None and custody['fd_holds_released'] is True and custody['reduced_arms']==4 and custody['all_fields_match'] is True
assert custody['before']==custody['after'] and len(custody['before'])==len({r['path'] for r in custody['before']})==220
assert not (SCIENCE/'late-failure.v1.json').exists()
total=0
for row in custody['before']:
    clock();p=local(row['path']);h=hashlib.sha256();size=0
    with p.open('rb') as stream:
        first=os.fstat(stream.fileno());assert first.st_size==row['size_bytes']<=64*1024*1024
        while raw:=stream.read(1024*1024):
            clock();size+=len(raw);assert size<=64*1024*1024;h.update(raw)
        after=os.fstat(stream.fileno())
    assert (first.st_size,first.st_mtime_ns,first.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    assert size==row['size_bytes'] and h.hexdigest()==row['sha256']
    total+=size;verified[row['path']]={'path':row['path'],'size_bytes':size,'sha256':h.hexdigest(),'physical_full_bytes_match':True}
assert total==root_closure['root_fresh_full_hash_read_bytes']==239657386
for directory,names in custody['namespaces'].items():
    assert len(names)==15 and sorted(p.name for p in local(directory).iterdir())==names
assert len(summaries)==len(exports['rows'])==4 and exports['rows']==root_closure['current_rows']
for name,row in terminal['outputs'].items():
    actual=pin(local(row['path']),row['path']);assert actual['size_bytes']==row['size_bytes'] and actual['sha256']==row['sha256']
    assert row['size_bytes']<=1048576
for name,row in terminal['source_before'].items():
    actual=pin(local(row['path']),row['path']);assert actual==row
for name,row in exports['exports'].items():
    actual=pin(local(row['path']),row['path']);assert actual==row and actual['size_bytes']<=1048576
csv_rows=list(csv.DictReader(io.StringIO(read(SCIENCE/'four_arm_metrics.csv').decode())))
assert len(csv_rows)==4
metrics=[]
original_cold={}
for resource,pair in [('cpu','cpu-pair-08'),('gpu','gpu-pair-02')]:
    coldpath='/home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/'+pair+'/cold-pair/component_pair_result.v1.json'
    assert coldpath in verified
    cold=doc(local(coldpath));original_cold[resource]=cold
    assert verified[coldpath]['sha256']==custody['original_receipts'][resource]['cold_sha256']
for index,(summary,row,csvrow) in enumerate(zip(summaries,exports['rows'],csv_rows,strict=True)):
    assert all(summary[k]['equal'] is True and summary[k]['differences']=={} for k in ['candidate_comparison','carried_arm_comparison','cold_summary_comparison','cold_descriptive_comparison'])
    assert len(summary['recomputed_legacy_summary'])==len(summary['recomputed_v2_summary'])==72
    cold=original_cold[row['resource']];position=index%2
    assert summary['recomputed_v2_summary']==cold['arms'][position]['summary']
    assert summary['recomputed_descriptive_metrics']==cold['arms'][position]['descriptive_metrics']
    evidence=summary['arguments']['run_dir'];candidate=doc(local(evidence+'/checkpoint_publication_candidate.json'))
    arm=doc(local(str(Path(evidence).parent).replace('\\','/')+'/component_arm_result.v1.json'))
    assert candidate['summary']==summary['recomputed_legacy_summary'] and arm['physical_validation']['summary']==summary['recomputed_v2_summary']
    assert all(csvrow[k]==('' if row[k] is None else str(row[k])) for k in csvrow)
    assert row['measurement_admitted']==1080 and row['measurement_censored']==0
    assert row['frames']+row['measurement_dropped']==1080
    assert row['on_time_completed']==row['frames']-row['completed_deadline_misses']
    assert row['completion_coverage']==row['frames']/1080 and row['on_time_ingress_coverage']==row['on_time_completed']/1080
    assert row['c_obs_is_partial'] is True and row['decoder_factory']=='nvh264dec' and row['decoder_required_resource']=='nvdec'
    assert row['confidence_interval'] is None and row['confidence_interval_reason']=='one_original_descriptive_pair_per_resource'
    metrics.append({k:row[k] for k in ['resource','scenario','measurement_admitted','frames','measurement_dropped','on_time_completed','latency_p50_ms','completion_coverage','on_time_ingress_coverage','c_obs_in_ms_per_ingress','c_obs_is_partial']})
assert [(r['frames'],r['measurement_dropped'],r['on_time_completed']) for r in metrics]==[(516,564,0),(664,416,0),(1070,10,3),(1075,5,1)]
assert [r['latency_p50_ms'] for r in metrics]==[5727.5,3621.0,2127.0,2168.0]
assert exports['scope']=='topology_load_proxy_only' and exports['latency_population']=='completed_measurement_frames' and exports['drops_have_no_latency'] is True
assert exports['original_cpu_on_time_completed_zero'] is True and exports['confidence_interval'] is None
assert all(exports[k] is False for k in ['measurement_acceptance','full_campaign_acceptance','true_nvdec_busy_time_claim','processor_work_or_energy_claim','accuracy_or_population_claim'])
assert exports['observed_deadline_failure_is_not_causal_overload_proof'] is True
assert exports['source_playback']['encoded_timeline_fps']==600 and exports['source_playback']['offered_playback_fps']==1 and exports['source_playback']['timestamp_scale']==600
assert len(exports['logical_stream_recordings'])==6 and len({r['source_id'] for r in exports['logical_stream_recordings']})==2
result={'schema_version':1,'reviewer':'/root/decision28_source_peer','reviewable':True,'blocking_findings':[],
 'reviewer_handles_released':True,'baseline_benchmark_commit':'a00aa57f7d9534f8e7920f14f70d6a75a23570ed',
 'actual_original_tool_cells':{'dispatch':'078c83','completion':'b666cd','reported_original_tool_returncode':root_closure['actual_tool_returncode']},
 'original_terminal':pin(SCIENCE/'terminal.v1.json'),'original_root_closure':pin(SCIENCE/'root-original-science-closure.v1.json'),
 'original_custody':pin(SCIENCE/'custody-and-comparison.v1.json'),'original_exports':pin(SCIENCE/'exports-and-interpretation.v1.json'),
 'original_recomputed_summaries':pin(SCIENCE/'recomputed-summaries.v1.json'),
 'all220_original_full_physical_hashes_current_equal':list(verified.values()),'physical_read_bytes':total,
 'original_Linux220_before_after_seven_epoch_records_equal':True,'Linux_fresh_seven_epoch_reconstruction_by_Windows_reviewer':False,
 'source_and_original_EOF_reap_and_final_late_metadata_join':True,'four_exact15_leaf_namespaces_current_equal':True,
 'all_four72_field_summary_comparisons_match_original_candidate_arm_cold_metadata':True,'all_CSV_fields_exactly_match_exports':True,
 'current_four_arm_metrics':metrics,'original_independent_FD_close_record':custody['fd_holds_released'],
 'original_numeric_FD_balance':None,'original_recorded_process_group_scan_count':1,'fresh_peer_process_scans':None,
 'target_reducer_renderer_contract_or_test_rerun':False,'measurement_acceptance':False,'hardware_acceptance':False,
 'limits':['Original wrapper records one postterminal process/group scan and no numeric FD count; no second scan or numeric FD restoration is invented.',
 'Windows physical reads establish full SHA/size equality and preserve original Linux220 epoch records; they do not recreate Linux stat identities.',
 'Only original science-owned outputs and custody-listed inputs were read; no model/engine/device/test/Git operation or raw contract/numeric reducer rerun.',
 'CPU zero on-time completions remain explicit; GPU on-time3/1 of1080. One descriptive pair/resource, completed-only latency and partial attributed C_obs do not establish causal overload, true NVDEC busy time, processor work, energy, accuracy/population/noninferiority or full campaign acceptance.']}
clock()
with (OUT/'review.v1.json').open('xb') as stream:
    data=json.dumps(result,sort_keys=True,indent=2).encode()+b'\n';assert len(data)<=1024*1024
    assert stream.write(data)==len(data);stream.flush();os.fsync(stream.fileno())
clock();print(json.dumps({'review':pin(OUT/'review.v1.json'),'reviewable':True,'physical_hash_count':len(verified),'physical_read_bytes':total,'elapsed_source_metadata_review_s':120-(END-time.monotonic())}))
