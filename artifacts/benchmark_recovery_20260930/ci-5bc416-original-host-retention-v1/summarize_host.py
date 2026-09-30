"""Finite closed hosted diagnostic joins; no project imports or remote calls."""
import hashlib,json,zipfile
from pathlib import Path

ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
def read(path): return json.loads(path.read_bytes())
def ref(path):
    raw=path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
api=read(OUT/'provider-artifacts.original.json')['structuredContent']['artifacts']
jobs=read(OUT/'provider-jobs.snapshot01.original.json')['structuredContent']['jobs']
artifact=next(row for row in api if row['id']==11119852243)
host=next(row for row in jobs if row['id']==110056199870)
cpu=next(row for row in jobs if row['id']==110056199709)
review=read(OUT/'host-original-readonly-review.v1.json')
zip_path=OUT/'36764814739-host/original-artifact.zip'
inventory=read(OUT/'36764814739-host/zip-readonly-inventory.v1.json')
assert artifact['workflow_run']['head_sha']==review['source_commit']=='5bc416a2beab98b6cc60229dac56332b48cc6ca2'
assert host['status']=='completed' and host['conclusion']=='success'
assert cpu['status']=='in_progress' and cpu['conclusion'] is None
assert ref(zip_path)['sha256']==artifact['digest'].split(':')[1]==inventory['sha256']
assert ref(zip_path)['size_bytes']==artifact['size_in_bytes']==325635
assert inventory['all_member_crc_verified'] and inventory['zip_members']==51 and inventory['decoded_size_bytes']==1598160
log=read(OUT/'host-job-110056199870.decoded-tool-result.original.json')['structuredContent']['content']
assert (OUT/'host-job-110056199870.decoded.original.log').read_text()==log
with zipfile.ZipFile(zip_path) as archive:
    stderr=archive.read('host-prerequisites.stderr').decode('utf-8')
    events=[json.loads(line) for line in stderr.splitlines() if line.startswith('{')]
    starts=[row for row in events if row.get('event')=='test_started']
    terminals=[row for row in events if row.get('event')=='test_terminal']
    assert len(starts)==len(terminals)==2 and all(row['outcome']=='success' for row in terminals)
    assert [row['test_id'] for row in starts]==[row['test_id'] for row in terminals]==review['original_report']['test_ids']
    assert all(row['test_id'] in log for row in terminals)
    assets=json.loads(archive.read('model-acquisition/report.json'))
    assert assets['status']=='complete' and len(assets['assets'])==8
    assert all(row['status']=='downloaded' for row in assets['assets'])
    before=json.loads(archive.read('tracked-source.before.json'))
    assert before==json.loads(archive.read('tracked-source.after.json')) and len(before)==3549
    children=[json.loads(archive.read('model-acquisition/asset-%02d.terminal.json'%n)) for n in range(8)]
assert review['original_report']['diagnostic_passed'] and not review['original_report']['full_ci_successful']
assert review['original_prerequisites']['returncode']==0 and not review['original_prerequisites']['timed_out'] and review['original_prerequisites']['cleanup_error'] is None
result={
    'schema_version':1,'artifact_kind':'vast_5bc_original_host_ci_retention_review_v1',
    'run_id':36764814739,'host_job_id':110056199870,'source_commit':review['source_commit'],
    'original_host_conclusion':'success','actual_two_test_terminals':terminals,
    'original_process':review['original_prerequisites'],'original_model_acquisition_status':'complete',
    'original_downloaded_model_count':8,'original_model_acquisition_elapsed_s':assets['elapsed_s'],
    'archive':ref(zip_path),'original_provider_artifacts':ref(OUT/'provider-artifacts.original.json'),
    'original_jobs_snapshot':ref(OUT/'provider-jobs.snapshot01.original.json'),
    'original_decoded_joblog':ref(OUT/'host-job-110056199870.decoded.original.log'),
    'original_decoded_tool_result':ref(OUT/'host-job-110056199870.decoded-tool-result.original.json'),
    'zip_readonly_inventory':ref(OUT/'36764814739-host/zip-readonly-inventory.v1.json'),
    'finite_source_join':ref(OUT/'host-original-readonly-review.v1.json'),
    'zip_members':51,'decoded_bytes':1598160,'all_member_crc_verified':True,
    'source_before_after_equal':True,'tracked_path_count':3549,
    'four_declared_committed_sources_match_actual_hosted_source_bytes':True,
    'cpu_job_snapshot':{'id':cpu['id'],'status':cpu['status'],'conclusion':cpu['conclusion'],'full_result_pending':True},
    'full_ci_successful':False,'hardware_accepted':False,'namespace_denial_or_native_crash_cause':None,
    'scope':'One local original host archive retention and closed metadata/CRC/source/outcome joins; completed host prerequisite result only. No CPU pending archive/log retrieval, retry/cancel/model/native/engine/namespace/test execution by reviewer.',
    'temporary_signed_url_or_credentials_saved_or_output':False,'source_index_head_modified':False,
    'limitations':['Hosted model bytes were validated by original acquisition and model prerequisite; reviewer did not download or execute models.','Provider temporary file-reference URL was kept only in memory; stable IDs and authenticated original archive bytes are retained.','CPU suite was still in progress in this single recorded snapshot; host success does not establish full portable/native CI success.'],
}
path=OUT/'review.v1.json'
with path.open('x',encoding='utf-8',newline='\n') as stream:
    json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
print(json.dumps(ref(path),sort_keys=True))
