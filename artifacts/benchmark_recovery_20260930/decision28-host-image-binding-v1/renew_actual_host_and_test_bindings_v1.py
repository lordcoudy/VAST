"""Renew only six host constants and three test literals from the closed stock receipt."""
import ast
import hashlib
import json
from pathlib import Path
import pprint

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
SOURCE = ROOT/'scripts/checkpoint_gstreamer_publication_runtime_v3.py'
TEST = ROOT/'tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py'
RECEIPT = ROOT/'artifacts/benchmark_recovery_20260930/decision28-selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json'

def facts(path):
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

assert facts(SOURCE)['sha256'] == 'ee0476b574e012b213bdc603a7a930234c0bb27d929859ef03acfdb99eb7a241'
assert facts(TEST)['sha256'] == '5013163d54512a48702198b4778bf9d7eaf047a6f3d94a5d3f4cb1091d8c5910'
assert facts(RECEIPT)['size_bytes'] == 7001
assert facts(RECEIPT)['sha256'] == '0b8a34e67773572a27885b931c50427de8bbd59b23eba837c5d2319ea7e9abca'
receipt = json.loads(RECEIPT.read_bytes())
assert receipt['receipt_sha256'] == '8dbd48381495beddc23abab774055ebb3ce89af7f8d56901580da2612092e093'
unsigned = dict(receipt)
del unsigned['receipt_sha256']
assert hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest() == receipt['receipt_sha256']
assert receipt['candidate_binding_eligible'] is True and receipt['blockers'] == []
physical = receipt['physical_identity']
assert physical['image_id'] == 'sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1'
assert physical['base']['image_id'] == 'sha256:b102aafc0f88f8cfad92349e6a55d0f9755a3f5bff109a70ebdb8936d4a8e84c'
assert physical['entrypoint'] == ['/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3']
assert physical['user'] == 'dlstreamer' and physical['architecture'] == 'amd64' and physical['os'] == 'linux'
assert physical['created'] == '1970-01-01T00:00:00Z'
assert physical['observed_repository_digests'] == [physical['canonical_repository_digest']]
changes = {
    'EXPECTED_IMAGE_REFERENCE': physical['final_reference'],
    'EXPECTED_IMAGE_ID': physical['image_id'],
    'EXPECTED_REPOSITORY_DIGEST': physical['canonical_repository_digest'],
    'EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256': physical['inspect_projection_sha256'],
    'EXPECTED_IMAGE_LABELS': physical['labels'],
    'EXPECTED_EMBEDDED_ARTIFACTS': physical['embedded_files'],
}
before = SOURCE.read_bytes()
test_before = TEST.read_bytes()
tree = ast.parse(before)
assignments = {n.targets[0].id:n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
old = {name:ast.literal_eval(assignments[name].value) for name in changes}
assert old['EXPECTED_IMAGE_ID'] == 'sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6'
assert set(old['EXPECTED_IMAGE_LABELS']) == set(changes['EXPECTED_IMAGE_LABELS'])
assert set(old['EXPECTED_EMBEDDED_ARTIFACTS']) == set(changes['EXPECTED_EMBEDDED_ARTIFACTS']) and len(physical['embedded_files']) == 11
allowlist = (ROOT/'deploy/gstreamer_custom/publication/runtime-source-allowlist.txt').read_text().splitlines()
assert len(allowlist) == 73 and SOURCE.relative_to(ROOT).as_posix() not in allowlist
selected_before = {name:facts(ROOT/name) for name in allowlist}
lines = before.splitlines(keepends=True)
newline = b'\r\n' if before.count(b'\r\n') == before.count(b'\n') else b'\n'
for name,node in sorted(((name,assignments[name]) for name in changes),key=lambda row:row[1].lineno,reverse=True):
    text = name+' = '+pprint.pformat(changes[name],sort_dicts=True,width=100)
    lines[node.lineno-1:node.end_lineno] = [newline.join(text.encode().splitlines())+newline]
after = b''.join(lines)
def nonbindings(value):
    return ast.dump(ast.Module(body=[n for n in value.body if not (isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in changes)],type_ignores=[]),include_attributes=False)
assert nonbindings(tree) == nonbindings(ast.parse(after))
test_after = test_before
test_literals = {}
for name in ('EXPECTED_IMAGE_REFERENCE','EXPECTED_IMAGE_ID','EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256'):
    old_raw,new_raw = old[name].encode(),changes[name].encode()
    assert test_after.count(old_raw) == 1
    test_after = test_after.replace(old_raw,new_raw)
    test_literals[old[name]] = changes[name]
restored = test_after
for old_value,new_value in test_literals.items():
    assert restored.count(new_value.encode()) == 1
    restored = restored.replace(new_value.encode(),old_value.encode())
assert restored == test_before and test_before.count(b'\r\n') == test_after.count(b'\r\n')
ast.parse(test_after)
for name,raw in [('original-host-wrapper.raw',before),('original-runtime-test.raw',test_before)]:
    with (HERE/name).open('xb') as stream: assert stream.write(raw) == len(raw)
record = {'schema_version':1,'source_before':facts(SOURCE),'test_before':facts(TEST),'receipt':facts(RECEIPT),'original_bindings':old,'actual_proposed_bindings':changes,'selected73_before':selected_before,'scope':'Six host constants and three matching test literals only; no model or measurement execution'}
with (HERE/'before-edit.v1.json').open('xb') as stream: stream.write((json.dumps(record,sort_keys=True,indent=2)+'\n').encode())
assert SOURCE.read_bytes() == before and TEST.read_bytes() == test_before
SOURCE.write_bytes(after)
TEST.write_bytes(test_after)
selected_after = {name:facts(ROOT/name) for name in allowlist}
assert selected_before == selected_after
result = {'schema_version':1,'source_before':record['source_before'],'source_after':facts(SOURCE),'test_before':record['test_before'],'test_after':facts(TEST),'receipt':facts(RECEIPT),'renewed_constants':changes,'test_literal_changes':test_literals,'nonbinding_AST_unchanged':True,'test_literal_inverse_restores_original':True,'selected73_before_after_equal':True,'host_module_outside_selected73':True,'old_host_closure_invalidated':True,'new_host_closure_required':True,'hardware_acceptance':False,'publication_ready':False}
with (HERE/'renewal.v1.json').open('xb') as stream: stream.write((json.dumps(result,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'source_after':result['source_after'],'test_after':result['test_after'],'selected73_unchanged':True}))
