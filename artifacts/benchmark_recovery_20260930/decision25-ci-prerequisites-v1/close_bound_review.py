"""Close aggregate-bound repair evidence only; no workload execution."""
from pathlib import Path
import ast
import hashlib
import json
import os

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def pin(path):
    raw=path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),
            'sha256':hashlib.sha256(raw).hexdigest()}
old=json.loads((HERE/'author-review.v1.json').read_bytes())
green=json.loads((HERE/'aggregate-bound-green-01/terminal.json').read_bytes())
red=json.loads((HERE/'aggregate-bound-red-01/terminal.json').read_bytes())
assert green['returncode']==0 and red['returncode']==1
assert green['source_before']==green['source_after'] and red['source_before']==red['source_after']
for name,p in green['source_after'].items():
    now=pin(ROOT/name)
    assert {k:now[k] for k in ('size_bytes','sha256')}==p
assert b'Ran 28 tests' in (HERE/'aggregate-bound-green-01/stderr.raw').read_bytes()
assert b'AssertionError: False is not true' in (HERE/'aggregate-bound-red-01/stderr.raw').read_bytes()
assert not Path('/proc/'+str(green['pid'])).exists()
assert not Path('/proc/'+str(red['pid'])).exists()
before=(HERE/'aggregate-bound-before/ci_namespace_diagnostic_v1.py').read_text()
after=(ROOT/'scripts/ci_namespace_diagnostic_v1.py').read_text()
b,a=ast.parse(before),ast.parse(after)
for tree in (b,a):
    tree.body=[n for n in tree.body if not (isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)
                                         and n.targets[0].id in {'RAW_LIMIT','REPORT_LIMIT','DENIAL_LIMIT','EMITTED_LIMIT'})]
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant) and isinstance(node.value,str):
            node.value=node.value.replace('40KiB','16KiB').replace('16KiB','12KiB reserve') if node.value=='namespace report exceeds16KiB' else node.value
            node.value=node.value.replace('namespace capture exceeds40KiB','namespace capture exceeds16KiB').replace('observations exceed32KiB','observations exceed12KiB').replace('facts exceed8KiB','facts exceed4KiB')
        if isinstance(node,ast.Compare) and isinstance(node.left,ast.Name) and node.left.id=='emitted':
            node.comparators=[ast.Name(id='EMITTED_LIMIT',ctx=ast.Load())]
assert ast.dump(b,include_attributes=False)==ast.dump(a,include_attributes=False)
value={'schema_version':1,'artifact_kind':'vast_decision25_ci_prerequisites_author_review_v2',
 'reviewable':True,'independent_review':False,'supersedes':pin(HERE/'author-review.v1.json'),
 'reason':'Peer review rejected the earlier broad-domain122880-byte bound. All prepared namespace evidence now has one conservative61440-byte bound below65536.',
 'owned_sources':[pin(ROOT/p['path']) for p in old['owned_sources']],
 'aggregate_bound':{'per_capture_raw_bytes':16384,'per_capture_report_bytes':12032,
    'per_capture_reserved_late_leaf_bytes':256,'captures_max':2,'denial_leaf_bytes':4096,
    'formula':'2*(16384+12032+256)+4096','conservative_bytes':61440,'reviewed_max_bytes':65536,
    'direct_kernel_read_bytes':4096,'worker_emission_bytes':12288,
    'failure_behavior':'Original consumed prefixes retained; overflow and late closure stay failed. No refreshed deadline or policy change.'},
 'original_red':pin(HERE/'aggregate-bound-red-01/terminal.json'),
 'original_green':{**pin(HERE/'aggregate-bound-green-01/terminal.json'),'tests':28,
    'returncode':green['returncode'],'elapsed_s':green['elapsed_s'],'pid':green['pid'],
    'source_before_after_equal':True,'actual_current_pid_absent':True,
    'channels':[pin(HERE/'aggregate-bound-green-01'/name) for name in ['stdout.raw','stderr.raw']]},
 'original_before':pin(HERE/'aggregate-bound-before/inventory.json'),
 'normalized_ast_unchanged_except_declared_caps_and_failure_text':True,
 'other_three_owned_sources_unchanged':True,
 'source_scope':pin(HERE/'source-scope.v1.json'),
 'unchanged_constraints':old['preserved_constraints'],
 'limitations':old['self_review'],
 'no_actual_namespace_or_kernel_query':True}
with (HERE/'author-review.v2.json').open('xb') as stream:
    stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
print(json.dumps(pin(HERE/'author-review.v2.json')))
