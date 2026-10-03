from pathlib import Path
import hashlib,json,subprocess
root=Path.cwd();base='artifacts/benchmark_recovery_20260930/';git=['git','-c','core.longpaths=true']
assert subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip()=='78f50184362c1bd77f9dc5eadd8cd69d6ab3c5ac'
assert not subprocess.check_output(git+['diff','--cached','--name-only'])
terminal=root/'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04-original-controller/original.terminal.v1.json'
assert terminal.is_file(),'CPU04 original terminal and independent hold-release audit required before staging'
audit_path=root/base/'component-cpu04-postterminal-independent-review-v1/review.v1.json';assert audit_path.is_file(),'CPU04 independent release not yet closed'
audit_raw=audit_path.read_bytes();assert hashlib.sha256(audit_raw).hexdigest()=='595e40bf132d8041995a13baa6f42435e0889be13a4fd53d003f8ac90d306709'
audit=json.loads(audit_raw);assert audit['hold_release'] is True and audit['reviewer_held_fds_released'] is True and audit['original95_before_after_current_full7epochs_equal'] is True and audit['reserve_released_and_absent'] is True
assert hashlib.sha256(terminal.read_bytes()).hexdigest()=='88b9c117f75b45454b8facc781e1bb291750de388b85f03c31fe7135b1496b0e'
reviews={'decision25-ci-parent-review-v1/review.v1.json':'b1b27754474f4328d177938f94fb2e8eaf6e369a1b80c3270640aa485d3f45c1','decision25-ci-root-independent-review-v1/scope-review.v1.json':'2ea522f8d4e792c7e094c3c172d921851df7b40a097c6cde692fb1b99704d2b6','ci-fixture-scope-readonly-review-v1/firstslice-independent-review.v1.json':'6a7410ee49309ff9acd2b83af513fbdddb141ee6bacf76d50e2330caf8cd56ae','ci-fixture-scope-readonly-review-v1/additional-author-scope.v2.json':'ec805cd5d7af24d00ce5a5179a7993ecbd9aff96dfa2549ffbc06318721fe6bc','ci-fixture-scope-readonly-review-v1/finite-attributes-independent-review.v1.json':'3e51edff0177b762f5bf6c70aec78475a97afaf5d4cae769212bfb9f791cd718'}
for p,s in reviews.items():assert hashlib.sha256((root/base/p).read_bytes()).hexdigest()==s
review=json.loads((root/base/'decision25-ci-parent-review-v1/review.v1.json').read_bytes())
for row in review['approved_source_scope']+[review['manifest']]:
 raw=(root/row['path']).read_bytes();assert len(raw)==row['size_bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
owned=[row['path'] for row in review['approved_source_scope']]+['.ci/integration-test-selection.v1.json','.gitattributes','BENCHMARK_RECOVERY_PLAN.md',base+'decision25_ci_parent_review_v1.py',base+'stage_decision25_ci_sources_v1.py']
owned += ['deploy/deepstream/checkpoint/runtime-source-allowlist.txt','deploy/savant/publication/runtime-source-allowlist.txt','deploy/openvino_gva/publication/runtime-source-allowlist.txt','deploy/deepstream/checkpoint/Dockerfile.runtime','deploy/savant/publication/Dockerfile','deploy/openvino_gva/publication/Dockerfile']
owned += ['tests/test_checkpoint_external_execution_manifest.py','tests/test_kpp_legacy_iss_v2_secondary_sensitivity_executor.py','tests/test_publication_immutable_directory_v1.py','tests/test_publication_policy_qualification_runtime_inputs_v2.py','tests/test_publication_runtime_frozen_identity_constants_v1.py','tests/test_kpp_frozen_reconstruction_v1_dataset_integration.py','tests/test_kpp_iss_publication_v3_dataset_integration.py','tests/test_checkpoint_gstreamer_custom_qualification_fragment_v3.py']
owned.extend(p.relative_to(root).as_posix() for p in sorted((root/'.ci/fixtures').rglob('*')) if p.is_file())
for directory in ('decision25-ci-prerequisites-v1','decision25-ci-selection-v1','decision25-ci-selector-safeguards-v1','decision25-ci-root-independent-review-v1','decision25-ci-parent-review-v1','decision25-sibling-packaging-v1','decision25-finite-attributes-v1','ci-hermetic-fixture-audit-v1','ci-hermetic-fixtures-focused-v1','ci-hermetic-fixtures-author-review-v1','ci-additional-pure-fixtures-focused-v1','ci-fixture-scope-readonly-review-v1','ci-selected-current-identity-renewal-v1','component-host-renewal-v3-independent-review-v1'):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/base/directory).rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
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
changed=set(subprocess.check_output(git+['diff','--cached','--name-only'],text=True).splitlines());assert changed.issubset(owned)
checks=[p for p in owned if not p.startswith('artifacts/')]+[base+'decision25_ci_parent_review_v1.py',base+'stage_decision25_ci_sources_v1.py']
subprocess.run(git+['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check','--',*checks],check=True)
receipt=root/base/'decision25-ci-source-freeze.v1.json';assert not receipt.exists();receipt.write_bytes((json.dumps({'previous_head':'78f50184362c1bd77f9dc5eadd8cd69d6ab3c5ac','reviews':reviews,'physical_index_equal':True,'owned_files':{p:{'sha256':hashlib.sha256(b).hexdigest(),'size_bytes':len(b)} for p,b in physical.items()},'changed_paths':sorted(changed),'unfiltered_original_artifact_imports':carriers,'hosted_portable_or_ext4_executed':False,'hardware_accepted':False},sort_keys=True,separators=(',',':'))+'\n').encode());subprocess.run(git+['add','-f','--',receipt.relative_to(root).as_posix()],check=True)
print(json.dumps({'owned':len(owned),'changed':len(changed)+1,'physical_index_equal':True,'carriers':carriers}))
