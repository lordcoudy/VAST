"""Read-only AST/byte audit; imports no project code and executes no tests."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).parent
BASE = ROOT / 'artifacts/benchmark_recovery_20260930/component-held-session-implementation-v1'
receipt_path = BASE / 'attempt-04-focused/execution.json'
receipt = json.loads(receipt_path.read_bytes())
assert receipt['returncode'] == 0 and receipt['source_stable']
assert not receipt['timed_out'] and not receipt['capture_errors']
assert receipt['original_pid_absent'] and receipt['process_group_members_after'] == []

def ref(path):
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}

def methods(tree):
    return {node.name + '.' + method.name: ast.dump(method, include_attributes=False)
            for node in tree.body if isinstance(node, ast.ClassDef)
            for method in node.body if isinstance(method, ast.FunctionDef) and method.name.startswith('test_')}

sources, comparisons = [], []
for relative, expected in receipt['source_before'].items():
    path = ROOT / relative
    actual = ref(path)
    assert {k: actual[k] for k in ('size_bytes', 'sha256')} == expected == receipt['source_after'][relative]
    old = BASE / 'originals' / relative.replace('/', '__')
    before = ast.parse(old.read_bytes())
    after = ast.parse(path.read_bytes())
    sources.append(actual)
    if relative.startswith('tests/'):
        previous, current = methods(before), methods(after)
        comparisons.append({'path': relative, 'original_test_count': len(previous),
            'removed_original_tests': sorted(set(previous) - set(current)),
            'changed_original_tests': sorted(k for k in previous if k in current and previous[k] != current[k]),
            'added_tests': sorted(set(current) - set(previous))})

for name, channel in receipt['channels'].items():
    assert {k: ref(BASE / 'attempt-04-focused' / (name + '.bin'))[k]
            for k in ('size_bytes', 'sha256')} == channel
stderr = (BASE / 'attempt-04-focused/stderr.bin').read_text()
assert 'Ran 58 tests in 7.740s' in stderr and stderr.rstrip().endswith('OK')
document = {'sources': sources, 'original_execution': ref(receipt_path),
    'old_test_ast_comparisons': comparisons, 'reviewer_tests_executed': False,
    'project_modules_imported': False, 'engine_or_model_calls': False}
raw = (json.dumps(document, indent=2, sort_keys=True) + '\n').encode()
with (HERE / 'static-audit.v1.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'review': ref(HERE / 'static-audit.v1.json'), 'comparisons': comparisons}))
