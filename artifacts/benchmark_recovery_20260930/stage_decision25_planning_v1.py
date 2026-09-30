"""Stage the independently reviewed amendment and closed original prerequisites."""
from pathlib import Path
import hashlib, json, subprocess
root=Path.cwd();base='artifacts/benchmark_recovery_20260930/'
git=['git','-c','core.longpaths=true']
assert subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()=='f51273005165281e290a791d794902f3e722086d'
assert not subprocess.check_output(git+['diff','--cached','--name-only'])
review=base+'decision25-planning-independent-review-v1/review.v1.json'
assert hashlib.sha256((root/review).read_bytes()).hexdigest()=='5bf757a4cadfb1016e6e59a8abe9adb0457340dd7b1ef6d1cd28063575862bf3'
author=json.loads((root/base/'decision25-author-planning-review.v1.json').read_bytes())
owned=[]
for row in author['planning_files']:
 raw=(root/row['path']).read_bytes();assert len(raw)==row['size_bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'],row['path']
 owned.append(row['path'])
owned += [base+'stage_decision25_planning_v1.py',base+'decision25-author-planning-review.v1.json',
          base+'ci-a3-original-retention-v1/finite-diagnosis.v1.json',base+'capture_selected_host_closure_v2.py',
          base+'selected-image-host-checkpoint-commit-proof.v1.json',
          'artifacts/gstreamer_component_release_20260930_a3e976d0/host/execution-code-closure.v2.json']
for directory in ('decision25-planning-originals-v1','decision25-planning-independent-review-v1',
                  'ci-hermetic-fixture-audit-v1','component-selected-host-closure-v2-original',
                  'selected-gstreamer-cpu-controller-preparation-v1'):
 owned += [p.relative_to(root).as_posix() for p in sorted((root/base/directory).rglob('*'))
           if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
for directory in ('cpu-pair-01','cpu-pair-01-original-controller'):
 owned += [p.relative_to(root).as_posix() for p in sorted((root/'artifacts/gstreamer_component_release_20260930_a3e976d0'/directory).rglob('*')) if p.is_file()]
assert len(owned)==len(set(owned))
physical={p:(root/p).read_bytes() for p in owned}
subprocess.run(git+['add','-f','--',*owned],check=True)
def blobs(paths):
 raw=subprocess.run(git+['cat-file','--batch'],input=''.join(':'+p+'\n' for p in paths).encode(),stdout=subprocess.PIPE,check=True).stdout
 offset=0;result={}
 for path in paths:
  end=raw.index(b'\n',offset);header=raw[offset:end].split();assert len(header)==3 and header[1]==b'blob'
  size=int(header[2]);offset=end+1;result[path]=raw[offset:offset+size];offset+=size
  assert raw[offset:offset+1]==b'\n';offset+=1
 assert offset==len(raw)
 return result
carriers=[]
for path,blob in blobs(owned).items():
 if blob!=physical[path]:
  assert path.startswith('artifacts/'),path
  oid=subprocess.check_output(git+['hash-object','-w','--stdin'],input=physical[path]).decode().strip()
  subprocess.run(git+['update-index','--add','--cacheinfo','100644,'+oid+','+path],check=True);carriers.append(path)
report=base+'decision25-planning-freeze.v1.json';assert not (root/report).exists()
result={'previous_head':'f51273005165281e290a791d794902f3e722086d','independent_review_sha256':'5bf757a4cadfb1016e6e59a8abe9adb0457340dd7b1ef6d1cd28063575862bf3',
        'planning_files':author['planning_files'],'owned_files':{p:{'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for p,b in physical.items()},
        'original_unfiltered_artifact_imports':carriers,'source25_implemented':False,'cpu01_failed_before_source_model_guardian_native':True,
        'current_hardware_acceptance':False,'current_full_ci_acceptance':False,'unrelated_dirt_preserved':True}
(root/report).write_bytes((json.dumps(result,sort_keys=True,separators=(',',':'))+'\n').encode())
subprocess.run(git+['add','-f','--',report],check=True);owned.append(report);physical[report]=(root/report).read_bytes()
assert set(subprocess.check_output(git+['diff','--cached','--name-only'],text=True).splitlines())==set(owned)
assert blobs(owned)==physical
subprocess.run(git+['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*[r['path'] for r in author['planning_files']],base+'stage_decision25_planning_v1.py'],check=True)
print(json.dumps({'owned_paths':len(owned),'planning_files':6,'physical_index_equal':True,'original_unfiltered_artifacts':carriers}))
