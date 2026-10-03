from pathlib import Path
import hashlib,json,subprocess,sys
root=Path.cwd();base='artifacts/benchmark_recovery_20260930/';git=['git','-c','core.longpaths=true']
assert subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()=='30ae1a400595e049cfdb3585629134630fe0f25b'
assert not subprocess.check_output(git+['diff','--cached','--name-only'])
review_path,review_sha=sys.argv[1:]
assert hashlib.sha256((root/review_path).read_bytes()).hexdigest()==review_sha
sources={'scripts/publication_gstreamer_component_authority_v1.py':'9f0e0e56a238ad26f8ab525bc9f3bc0ebdd0e136b7bc0f8853ab3a0745342c6f','tests/test_publication_gstreamer_component_inputs_v1.py':'3d90d2e684251a98df4d3156eccf5deb56ffaab480c9a2ec3ea7c1606f104d38'}
for p,s in sources.items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==s
owned=list(sources)+['BENCHMARK_RECOVERY_PLAN.md',base+'stage_component_probe_schema_repair_v1.py','artifacts/gstreamer_component_release_20260930_a3e976d0/host/execution-code-closure.v4.json']
for directory in ('component-probe-authority-schema-repair-v1','component-probe-authority-schema-independent-review-v1','component-cpu03-probe-schema-diagnosis-v1','component-selected-host-closure-v4-original'):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/base/directory).rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
for directory in ('cpu-pair-03','cpu-pair-03-original-controller'):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/'artifacts/gstreamer_component_release_20260930_a3e976d0'/directory).rglob('*')) if p.is_file())
assert review_path in owned and len(owned)==len(set(owned))
physical={p:(root/p).read_bytes() for p in owned}
subprocess.run(git+['add','-f','--',*owned],check=True)
def blobs():
 raw=subprocess.check_output(git+['cat-file','--batch'],input=''.join(':'+p+'\n' for p in owned).encode());pos=0;out={}
 for p in owned:
  end=raw.index(b'\n',pos);h=raw[pos:end].split();assert len(h)==3 and h[1]==b'blob';n=int(h[2]);pos=end+1;out[p]=raw[pos:pos+n];pos+=n;assert raw[pos:pos+1]==b'\n';pos+=1
 assert pos==len(raw);return out
carriers=[]
for p,b in blobs().items():
 if b!=physical[p]:
  assert p.startswith('artifacts/'),p
  oid=subprocess.check_output(git+['hash-object','-w','--stdin'],input=physical[p]).decode().strip();subprocess.run(git+['update-index','--add','--cacheinfo','100644,'+oid+','+p],check=True);carriers.append(p)
assert blobs()==physical
assert set(subprocess.check_output(git+['diff','--cached','--name-only'],text=True).splitlines())==set(owned)
subprocess.run(git+['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*sources,'BENCHMARK_RECOVERY_PLAN.md',base+'stage_component_probe_schema_repair_v1.py'],check=True)
receipt=root/base/'component-probe-schema-repair-freeze.v1.json';assert not receipt.exists();receipt.write_bytes((json.dumps({'previous_head':'30ae1a400595e049cfdb3585629134630fe0f25b','independent_review_sha256':review_sha,'physical_index_equal':True,'owned_files':{p:{'sha256':hashlib.sha256(b).hexdigest(),'size_bytes':len(b)} for p,b in physical.items()},'unfiltered_original_artifact_imports':carriers,'new_selected_build_executed':False,'CPU04_executed':False,'hardware_accepted':False},sort_keys=True,separators=(',',':'))+'\n').encode());subprocess.run(git+['add','-f','--',receipt.relative_to(root).as_posix()],check=True)
print(json.dumps({'staged':len(owned)+1,'physical_index_equal':True,'carriers':carriers}))
