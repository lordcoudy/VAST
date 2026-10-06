"""Amendment4: one-off owned transfer (also SHA-pinned patch receipts) of original inputs under the zero-offset clock-domain label; no acceptance or model execution."""
import argparse,hashlib,json,os,shutil,stat,time
from pathlib import Path,PurePosixPath
import yaml

parser=argparse.ArgumentParser()
parser.add_argument('--source-root',required=True,type=Path)
parser.add_argument('--project-root',required=True,type=Path)
parser.add_argument('--clock',required=True,type=Path)
args=parser.parse_args()
LABEL='timens-offsets:monotonic=0,0;boottime=0,0'
def clock_domain_label():
    own,child=os.readlink('/proc/self/ns/time'),os.readlink('/proc/self/ns/time_for_children')
    rows=[r.split() for r in Path('/proc/self/timens_offsets').read_text().splitlines()]
    assert own==child and rows==[['monotonic','0','0'],['boottime','0','0']],'attempt F clock domain is not the zero-offset initial clock'
    return LABEL
source=args.source_root.resolve(strict=True);root=args.project_root.resolve(strict=True)
clock=json.loads(args.clock.read_bytes());deadline=clock['deadline_monotonic_ns']
assert clock['clock']=='CLOCK_MONOTONIC' and clock['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert clock['time_namespace']==clock_domain_label()
def remaining():
    assert time.monotonic_ns()<deadline-15_000_000_000,'original bootstrap preparation clock expired'
remaining()
assert source!=root and not (root/'bootstrap-model-transfer.original.json').exists()
def epoch(s):return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def path_for(base,name):
    p=PurePosixPath(name)
    assert not p.is_absolute() and '..' not in p.parts and str(p)==name
    current=base
    for part in p.parts[:-1]:
        current=current/part
        info=current.lstat();assert stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    return base.joinpath(*p.parts)
def metadata(name,*,yaml_doc=False):
    remaining();p=path_for(source,name);before=p.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=16*1024**2
    with p.open('rb') as stream:
        assert epoch(before)==epoch(os.fstat(stream.fileno()))
        raw=stream.read(16*1024**2+1);assert len(raw)==before.st_size and len(raw)<=16*1024**2
        assert epoch(before)==epoch(os.fstat(stream.fileno()))==epoch(p.lstat())
    return yaml.safe_load(raw) if yaml_doc else json.loads(raw)
wanted={}
def add(name,ref=None):
    p=PurePosixPath(name)
    assert not p.is_absolute() and '..' not in p.parts and str(p)==name
    if ref is not None and {'size_bytes','sha256'}<=set(ref):
        value={'size_bytes':ref['size_bytes'],'sha256':ref['sha256']}
        assert name not in wanted or wanted[name] is None or wanted[name]==value
        wanted[name]=value
    else:wanted.setdefault(name,None)
def descriptors(value):
    if isinstance(value,dict):
        if {'path','sha256','size_bytes'}<=set(value) and isinstance(value['path'],str):add(value['path'],value)
        for child in value.values():descriptors(child)
    elif isinstance(value,list):
        for child in value:descriptors(child)
receipt_name='configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json'
receipt=metadata(receipt_name);descriptors(receipt)
add(receipt_name);add(receipt['acceptance_binding_path'])
binding=metadata(receipt['acceptance_binding_path']);descriptors(binding)
transaction_ref=receipt['transaction_index'];index=metadata(transaction_ref['path'])
assert isinstance(index['files'],list) and len(index['files'])==2453
descriptors(index['files'])
manifest=metadata(receipt['accepted_manifest']['path'],yaml_doc=True);descriptors(manifest)
prefix='artifacts/fix_benchmark_preparations_20260928g'
patch_name=prefix+'/qualification_image_identity_patch.json'
add(patch_name);patch_refs=[]
def patch_descriptors(value):
    if isinstance(value,dict):
        if {'path','sha256','size_bytes'}<=set(value) and isinstance(value['path'],str) and value['path'].startswith('artifacts/'):patch_refs.append(value)
        for child in value.values():patch_descriptors(child)
    elif isinstance(value,list):
        for child in value:patch_descriptors(child)
patch_descriptors(metadata(patch_name))
for ref in patch_refs:add(ref['path'],ref)  # SHA-pinned native/runtime freeze receipts (amendment4)
add(prefix+'/worker_images/analytics-worker.freeze.json')
add('artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/candidate/checkpoint_policy_capability_candidate_manifest.json')
add('artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.gstreamer_custom.v2.json')
dataset_name=prefix+'/model_parity_v4/materialization/support/dataset_manifest.json'
add(dataset_name);dataset=metadata(dataset_name)
assert len(dataset['files'])==4;descriptors(dataset['files'])
proxy=metadata('configs/checkpoint_analytics_models_openvino.yaml',yaml_doc=True)
for branch in proxy['branches'].values():
    for role in ('model','weights'):
        name=branch[role+'_path'];assert name.startswith('../models/')
        add(name[3:],{'sha256':branch[role+'_sha256'],'size_bytes':path_for(source,name[3:]).stat().st_size})
declared=sum(path_for(source,name).stat().st_size for name in wanted)
assert declared<=8*1024**3,'original input-transfer cap exceeded'
assert shutil.disk_usage(root).free>=declared+20*1024**3+8*1024**3+3*1024**3
rows=[];processed_total=0
for index,(name,ref) in enumerate(sorted(wanted.items())):
    remaining();p=path_for(source,name);before=p.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=4*1024**3
    assert processed_total+before.st_size<=8*1024**3,'actual original total transfer cap exceeded'
    target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
    check=path_for(root,name);assert check==target
    copied=not os.path.lexists(target);digest=hashlib.sha256();total=0
    with p.open('rb') as original:
        assert epoch(os.fstat(original.fileno()))==epoch(before)
        output=target.open('xb') if copied else None
        try:
            while True:
                remaining();raw=original.read(1024**2)
                if not raw:break
                assert total+len(raw)<=before.st_size,'original grew beyond initial finite size'
                assert processed_total+total+len(raw)<=8*1024**3,'actual original transfer cap exceeded'
                digest.update(raw);total+=len(raw)
                if output is not None:assert output.write(raw)==len(raw)
            if output is not None:output.flush();os.fsync(output.fileno())
            assert total==before.st_size and epoch(os.fstat(original.fileno()))==epoch(before)==epoch(p.lstat())
        finally:
            if output is not None:output.close()
    value={'size_bytes':total,'sha256':digest.hexdigest()}
    if ref is not None:assert value==ref,(name,'original descriptor drift')
    target_before=target.lstat();assert stat.S_ISREG(target_before.st_mode) and target_before.st_nlink==1
    target_digest=hashlib.sha256();target_total=0
    with target.open('rb') as transferred:
        while True:
            remaining();raw=transferred.read(1024**2)
            if not raw:break
            assert target_total+len(raw)<=target_before.st_size and target_total+len(raw)<=total,'destination grew beyond initial finite size'
            target_digest.update(raw);target_total+=len(raw)
        assert epoch(os.fstat(transferred.fileno()))==epoch(target_before)==epoch(target.lstat())
    assert target_total==total and target_digest.hexdigest()==value['sha256'],(name,'current destination differs; never overwritten')
    rows.append({'path':name,**value,'copied_exclusively':copied,'original_epochs':list(epoch(before)),'destination_epochs':list(epoch(target_before))})
    processed_total+=total
    if index%250==0:print(json.dumps({'transferred_or_verified':index+1,'total':len(wanted)}),flush=True)
remaining()
document={'schema_version':1,'kind':'original-model-input-transfer','clock':clock,'source_root':str(source),'project_root':str(root),
    'files':rows,'total_bytes':sum(r['size_bytes'] for r in rows),'no_original_overwrite':True,'model_acceptance':False,'closed_monotonic_ns':time.monotonic_ns()}
out=root/'bootstrap-model-transfer.original.json'
with out.open('xb') as stream:
    raw=(json.dumps(document,sort_keys=True,separators=(',',':'))+'\n').encode();assert stream.write(raw)==len(raw)
    stream.flush();os.fsync(stream.fileno())
remaining();print(json.dumps({'receipt':str(out),'files':len(rows),'total_bytes':document['total_bytes'],'accepted':False}),flush=True)
