import copy,json,sys
sys.path.insert(0,'/opt/vast/checkpoint')
import checkpoint_native_policy_runtime as runtime
cases=json.load(open('/tmp/external-manifest-cases.json'))
count=0
for system,manifest in cases['manifests'].items():
    def assess(value):
        return runtime.assess_gstreamer_native_policy_execution_manifest(value,system=system,capability_manifest=cases['policy'],preprocessing_contract_sha256=cases['preprocessing'])
    assert assess(manifest)['passed']
    for mutation in ('image','model','missing_gpu','policy','config'):
        altered=copy.deepcopy(manifest)
        if mutation=='image':altered['branches']['damage']['cpu']['worker_image_id']='sha256:'+'0'*64
        elif mutation=='model':altered['branches']['damage']['cpu']['source_model_sha256']='0'*64
        elif mutation=='missing_gpu':del altered['branches']['damage']['gpu']
        elif mutation=='policy':altered['policy_capability_manifest_sha256']='0'*64
        else:del altered['execution_config']
        assert not assess(altered)['passed'],mutation
        count+=1
print(json.dumps({'status':'packaged_external_manifest_contract_passed','valid_manifests':2,'rejected_mutations':count}))
