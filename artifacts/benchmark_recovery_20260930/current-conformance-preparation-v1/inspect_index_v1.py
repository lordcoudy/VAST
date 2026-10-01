import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930/current-conformance-preparation-v1'
old = json.loads((ROOT / 'artifacts/benchmark_recovery_20260930/final-conformance-mapping-skeleton-v1/mapping.v4.json').read_bytes())
profiles = old['profiles']
for req in sys.argv[1:]:
    print('\n' + req)
    for module in profiles[req]['current_test_modules']:
        path = ROOT / module['path']
        tree = ast.parse(path.read_bytes())
        print(module['path'])
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for method in cls.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or not method.name.startswith('test_'):
                    continue
                statements = []
                for node in ast.walk(method):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.startswith('assert'):
                        statements.append(ast.unparse(node)[:180])
                print(f'{cls.name}.{method.name}:{method.lineno} ' + ' | '.join(statements[:4]))
