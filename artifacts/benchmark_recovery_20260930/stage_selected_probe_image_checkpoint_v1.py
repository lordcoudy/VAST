from pathlib import Path
import hashlib,json,subprocess,sys
root=Path.cwd();base='artifacts/benchmark_recovery_20260930/';git=['git','-c','core.longpaths=true']
assert subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()=='a4e145b7bf32e0c870b114e303e9adb6a559d0ef'
assert not subprocess.check_output(git+['diff','--cached','--name-only'])
review_path,review_sha=sys.argv[1:];assert hashlib.sha256((root/review_path).read_bytes()).hexdigest()==review_sha
sources={'scripts/checkpoint_gstreamer_publication_runtime_v3.py':'ee0476b574e012b213bdc603a7a930234c0bb27d929859ef03acfdb99eb7a241','tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py':'5013163d54512a48702198b4778bf9d7eaf047a6f3d94a5d3f4cb1091d8c5910'}
for p,s in sources.items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==s
owned=list(sources)+['BENCHMARK_RECOVERY_PLAN.md',base+'stage_selected_probe_image_checkpoint_v1.py',base+'renew_selected_host_image_binding_v2.py',base+'renew_selected_runtime_test_binding_v1.py',base+'capture_selected_host_closure_v5.py']
for directory in ('selected-gstreamer-image-schema-preparation-v1','selected-gstreamer-build-a4e145b7-v1','selected-gstreamer-packaged-schema-preparation-v1','selected-gstreamer-packaged-a4e145b7-v1','component-host-image-binding-renewal-v3','selected-gstreamer-cpu04-controller-preparation-v1'):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/base/directory).rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
owned.extend(p.relative_to(root).as_posix() for p in sorted((root/base/'component-host-image-binding-renewal-focused-v1/attempt03-new-schema-image').rglob('*')) if p.is_file())
assert review_path not in owned;owned.append(review_path)
assert len(owned)==len(set(owned));physical={p:(root/p).read_bytes() for p in owned}
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
checks=[p for p in owned if not p.startswith('artifacts/') or p.endswith('.py')]
subprocess.run(git+['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*checks],check=True)
receipt=root/base/'selected-probe-image-host-checkpoint-freeze.v1.json';assert not receipt.exists();receipt.write_bytes((json.dumps({'previous_head':'a4e145b7bf32e0c870b114e303e9adb6a559d0ef','independent_review_sha256':review_sha,'physical_index_equal':True,'owned_files':{p:{'sha256':hashlib.sha256(b).hexdigest(),'size_bytes':len(b)} for p,b in physical.items()},'unfiltered_original_artifact_imports':carriers,'host_v5_executed':False,'CPU04_executed':False,'hardware_accepted':False},sort_keys=True,separators=(',',':'))+'\n').encode());subprocess.run(git+['add','-f','--',receipt.relative_to(root).as_posix()],check=True)
print(json.dumps({'staged':len(owned)+1,'physical_index_equal':True,'carriers':carriers}))
