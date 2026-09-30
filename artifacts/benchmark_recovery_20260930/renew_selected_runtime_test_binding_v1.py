from pathlib import Path
import ast,hashlib,json
root=Path.cwd();base=root/'artifacts/benchmark_recovery_20260930/component-host-image-binding-renewal-v3'
p=root/'tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py';before=p.read_bytes();assert hashlib.sha256(before).hexdigest()=='f59410fd2af9ecd42d9740323b93f0efd0f5c4421e3503be70f1438aa9dc1fe8'
changes={b'vast/gstreamer-custom-publication-runtime-v3:component-release-20260930-a3e976d0':b'vast/gstreamer-custom-publication-runtime-v3:component-release-20260930-a4e145b7',b'sha256:88778ac8b7b91ca90b8d0f03c48823898fc8438ab9b0ad1df7548746792e2f4f':b'sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6',b'68ce24371c674a936c82b0ef183b34103f1904f237d162cf1f99e31730fd559d':b'c2eea6d503a758860f9c40fef9164ce01f40084ee541dc6e89ca61a21d4ccb05'}
after=before
for old,new in changes.items():assert after.count(old)==1;after=after.replace(old,new)
restored=after
for old,new in changes.items():assert restored.count(new)==1;restored=restored.replace(new,old)
assert restored==before and before.count(b'\r\n')==after.count(b'\r\n');ast.parse(after)
(base/'original-runtime-test.raw').write_bytes(before);p.write_bytes(after)
(base/'test-renewal.v1.json').write_text(json.dumps({'path':p.relative_to(root).as_posix(),'source_before_sha256':hashlib.sha256(before).hexdigest(),'source_after_sha256':hashlib.sha256(after).hexdigest(),'size_bytes':len(after),'inverse_three_literal_changes_reproduce_original_bytes':True,'all_validation_assertions_unchanged':True,'physical_CRLF_preserved':True,'hardware_acceptance':False},sort_keys=True)+'\n')
print(hashlib.sha256(after).hexdigest())
