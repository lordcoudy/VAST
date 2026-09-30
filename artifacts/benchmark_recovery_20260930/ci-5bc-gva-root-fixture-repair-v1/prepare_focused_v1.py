"""Reuse the retained bounded fixture observer for only the genuine GVA module."""
from pathlib import Path
import ast, hashlib, json
root=Path(__file__).resolve().parents[3]
out=Path(__file__).parent
old=root/'artifacts/benchmark_recovery_20260930/ci-2f409-portable-fixture-repairs-v1/dispatch.final.v2.py'
source=old.read_text()
lines=source.splitlines(keepends=True)
kept=[]
for line in lines:
    if line.startswith('modules='):
        line="modules=['test_checkpoint_openvino_gva_qualification_fragment_v3']\n"
    if line.startswith("paths+=sorted(p.relative_to(root).as_posix() for p in (root/'models')"):
        continue
    kept.append(line)
source=''.join(kept)
ast.parse(source)
target=out/'dispatch_focused_v1.py'
assert not target.exists()
target.write_bytes(source.encode())
before=(out/'original-test.raw').read_bytes()
after=(root/'tests/test_checkpoint_openvino_gva_qualification_fragment_v3.py').read_bytes()
def methods(raw):
    return {n.name:ast.dump(n,include_attributes=False) for c in ast.parse(raw).body
            if isinstance(c,ast.ClassDef) for n in c.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
original_methods=methods(before);current_methods=methods(after)
assert original_methods.keys()==current_methods.keys()
changed=[n for n in original_methods if original_methods[n]!=current_methods[n]]
assert changed==['test_policy_identity_is_the_external_worker_and_topology_v2_is_invariant']
def normalized(raw):
    tree=ast.parse(raw)
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='expected_terminal_detector' and len(node.args)==3:
            node.args.pop()
    return methods(ast.unparse(tree).encode())
assert normalized(after)==original_methods
value={'scope':'actual original5bc RED; one test helper reads the already owned physical fixture root',
       'original_test_methods_preserved':len(original_methods),'original_assertion_ASTs_preserved':True,
       'changed_method_call_only':changed,'test_before_sha256':hashlib.sha256(before).hexdigest(),
       'test_after_sha256':hashlib.sha256(after).hexdigest(),'dispatch_sha256':hashlib.sha256(source.encode()).hexdigest(),
       'production_source_change':False,'image_or_authority_change':False,'hardware_acceptance':False}
(out/'preparation.v1.json').open('xb').write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps(value))
