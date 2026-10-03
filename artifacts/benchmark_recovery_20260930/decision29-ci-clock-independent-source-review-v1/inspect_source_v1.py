"""Static source review metadata only; target modules are never imported or executed."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
BEFORE = BASE / 'decision29-ci-clock-repair-v1/before'

def dump(node):
    return ast.dump(node, include_attributes=False)

for rel in ('scripts/ci_namespace_diagnostic_v1.py', 'scripts/ci_userns_profile_v1.py',
            'tests/test_ci_userns_profile_v1.py'):
    old = (BEFORE / (rel.replace('/', '__') + '.raw')).read_bytes()
    new = (ROOT / rel).read_bytes()
    a, b = ast.parse(old), ast.parse(new)
    af = {n.name: n for n in a.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    bf = {n.name: n for n in b.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    print(json.dumps({'source': rel, 'size_bytes': len(new), 'sha256': hashlib.sha256(new).hexdigest(),
          'original_module_functions': list(af), 'unchanged_module_functions': [n for n in af if n in bf and dump(af[n]) == dump(bf[n])],
          'changed_module_functions': [n for n in af if n in bf and dump(af[n]) != dump(bf[n])],
          'new_module_functions': sorted(set(bf) - set(af))}))
    if rel.startswith('tests/'):
        for c in (n for n in a.body if isinstance(n, ast.ClassDef)):
            bc = next(n for n in b.body if isinstance(n, ast.ClassDef) and n.name == c.name)
            am = {n.name:n for n in c.body if isinstance(n, ast.FunctionDef)}
            bm = {n.name:n for n in bc.body if isinstance(n, ast.FunctionDef)}
            print(json.dumps({'class':c.name, 'original_methods':list(am), 'unchanged_methods':[n for n in am if dump(am[n]) == dump(bm[n])],
                  'changed_methods':[n for n in am if dump(am[n]) != dump(bm[n])], 'new_methods':sorted(set(bm)-set(am))}))
    print(''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile=rel+' BEFORE', tofile=rel+' CURRENT')))

paths = [
 'decision28-host-identity-source-checkpoint-v1/committed-checkpoint-proof.v1.json',
 'decision28-ext4-renewal-preparation-v1/preparation.v1.json',
 'decision28-host-ext4-renewal-preparation-v1/preparation.v1.json',
 'decision28-selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json',
 'decision28-current95-preparation-v1/decision28-current95-original-attempt01/current95-inputs.v1.json',
 'decision28-cpu08-independent-audit-v1/review.v1.json',
]
for rel in paths:
    p=BASE/rel
    if not p.exists():
        print(json.dumps({'inventory':rel,'missing':True}));continue
    v=json.loads(p.read_bytes())
    print(json.dumps({'inventory':rel,'keys':{k: {'type':type(x).__name__,'count':len(x) if hasattr(x,'__len__') else None,
          'nested_keys':list(x)[:30] if isinstance(x,dict) else None} for k,x in v.items()}}))

