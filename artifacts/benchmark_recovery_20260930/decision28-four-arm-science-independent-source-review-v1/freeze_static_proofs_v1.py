"""Read-only finite source and original receipt joins; no analysis target execution."""
import ast
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'artifacts/benchmark_recovery_20260930'
OUT=Path(__file__).resolve().parent
PREP=BASE/'decision28-four-arm-science-preparation-v1'
OLD=BASE/'component-four-arm-independent-science-preparation-v1'
LINUX='/home/s-a-balashov/work/vast-component-release-20260930-d27'
UNC=Path(r'\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-component-release-20260930-d27')

def raw(path):
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());value=stream.read(1024*1024+1);after=os.fstat(stream.fileno())
    assert len(value)<=1024*1024
    assert (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    assert len(value)==before.st_size
    return value

def pin(path,label=None):
    value=raw(path)
    return {'path':str(path) if label is None else label,'size_bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}

def physical(path):
    assert path.startswith(LINUX+'/')
    return UNC/path[len(LINUX)+1:]

def functions(value):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(value)) if isinstance(n,ast.FunctionDef)}

prep=json.loads(raw(PREP/'preparation.v1.json'))
sources=[]
for entry in prep['source_pins']:
    name=entry['name'];old=raw(OLD/name);snapshot=raw(PREP/(name+'.original.raw'));new=raw(PREP/name)
    assert old==snapshot
    forward=old.decode()
    for row in prep['ordered_exact_raw_replacements'][name]:
        assert forward.count(row['before'])==row['count']
        forward=forward.replace(row['before'],row['after'])
    assert forward.encode()==new
    inverse=new.decode()
    for row in reversed(prep['ordered_exact_raw_replacements'][name]):
        assert inverse.count(row['after'])==row['count']
        inverse=inverse.replace(row['after'],row['before'])
    assert inverse.encode()==snapshot and functions(old)==functions(new)
    actual=pin(PREP/name,str((PREP/name).relative_to(ROOT)))
    assert actual['size_bytes']==entry['size_bytes'] and actual['sha256']==entry['sha256']
    sources.append({'source':actual,'original_closed_source':pin(OLD/name),'snapshot':pin(PREP/(name+'.original.raw')),
       'exact_ordered_forward_and_inverse_equal':True,'all_original_function_ASTs_equal':True,
       'original_function_names':list(functions(old)),'replacement_occurrences':sum(r['count'] for r in prep['ordered_exact_raw_replacements'][name]),
       'renderer_raw_bytes_identical':old==new if name=='render.py' else None})
tree=ast.parse(raw(PREP/'reduce.py'))
auth=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='AUTHENTIC' for t in n.targets)))
receipts={}
for resource in ('cpu','gpu'):
    entry=prep['original_receipts'][resource];path=physical(entry['original_terminal_path'])
    descriptor=pin(path,entry['original_terminal_path'])
    assert (descriptor['size_bytes'],descriptor['sha256'])==auth[resource]['terminal']==(entry['size_bytes'],entry['sha256'])
    terminal=json.loads(raw(path));clirow=terminal['original_cli_terminal'];clipath=physical(clirow['path'])
    cli=json.loads(raw(clipath));coldrow=cli['pair_result'];coldpath=physical(coldrow['path'])
    cold=json.loads(raw(coldpath))
    for d,p in ((clirow,clipath),(coldrow,coldpath)):
        actual=pin(p,d['path']);assert actual['size_bytes']==d['size_bytes'] and actual['sha256']==d['sha256']
    assert clirow['sha256']==auth[resource]['cli'] and coldrow['sha256']==auth[resource]['cold']
    assert terminal['source_commit']=='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
    assert terminal['original_returncode']==0 and terminal['failure'] is None and not terminal['signals']
    assert not terminal['timed_out'] and not terminal['capture_exceeded'] and terminal['pins_before']==terminal['pins_after']
    owner=terminal['owner'];assert owner['pid']==auth[resource]['pid'] and owner['ppid']==auth[resource]['ppid'] and owner['startticks']==auth[resource]['startticks']
    assert owner['pgid']==owner['pid'] and owner['uid']==owner['gid']==1000 and owner['boot_id']=='dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
    assert cli['status']=='component_pair_complete' and cli['resource']==resource and cli['primary_error'] is None and cli['cleanup_errors']==[]
    assert cli['guardian_cleanup_verified'] is True and cli['capacity_reservation']['released'] is True
    assert cold['resource']==resource and cold['scientific_scope']=='topology_load_proxy_only' and cold['publication_ready'] is False
    assert len(cold['arms'])==len(cold['arm_results'])==2
    auditpath=BASE/('decision28-'+('cpu08' if resource=='cpu' else 'gpu02')+'-independent-audit-v1/review.v1.json')
    auditpin=pin(auditpath);assert auditpin['sha256']==entry['independent_audit_sha256']
    audit=json.loads(raw(auditpath));assert audit['original_cli_returncode']==0 and audit['original_first_error'] is None and audit['hold_release'] and audit['reserve_released_and_absent']
    assert audit['reviewer_fd_before']==audit['reviewer_fd_after']==6
    receipts[resource]={'original_terminal':descriptor,'original_cli':pin(clipath,clirow['path']),
      'original_cold':pin(coldpath,coldrow['path']),'retained_independent_audit':auditpin,
      'authentic_source_owner_and_descriptor_join':True,'no_scientific_values_recomputed_in_source_review':True}
closurepath=UNC/'artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json'
closure=pin(closurepath,LINUX+'/artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json')
assert closure['sha256']=='3c91339d43f6154dd76afe8a89c02d82f60a4b1e5da16623039f691fdc6701f2'
value={'schema_version':1,'source_proofs':sources,'preparation':pin(PREP/'preparation.v1.json'),
  'actual_original_receipt_joins':receipts,'actual_host_v4_closure':closure,
  'all_read_handles_released':True,'targets_imported_compiled_or_executed':False}
with (OUT/'static-proofs.v1.json').open('xb') as stream:
    stream.write(json.dumps(value,sort_keys=True,indent=2).encode()+b'\n');stream.flush();os.fsync(stream.fileno())
print(json.dumps({'proof':pin(OUT/'static-proofs.v1.json'),'source_pins':[r['source'] for r in sources],
                  'all_function_ASTs_equal':True,'actual_closed_CPU08_GPU02_bindings_verified':True}))
