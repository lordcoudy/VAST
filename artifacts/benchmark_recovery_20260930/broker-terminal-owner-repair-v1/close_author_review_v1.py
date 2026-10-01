"""Read-only exact source/body/evidence self-review after the scoped fix."""
import ast
import hashlib
import json
import os
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = Path(__file__).resolve().parent
BENCHMARK = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')

def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

before_raw = (BASE / 'backend_publication_process_supervisor_v3.py.before.raw').read_bytes()
current_path = ROOT / 'scripts/backend_publication_process_supervisor_v3.py'
current_raw = current_path.read_bytes()
before = ast.parse(before_raw)
current = ast.parse(current_raw)
changed = ('_posix_broker_entry_v3', '_posix_held_broker_entry_production_v3')
functions = {node.name: node for node in current.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in changed:
    function = functions[name]
    # Inverse only the reviewed private promotion in these two exact bodies.
    function.body = [node for node in function.body if not
        (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'terminal_journal')]
    trial = next(node for node in function.body if isinstance(node, ast.Try))
    conditional = next(node for node in trial.body if isinstance(node, ast.If))
    assert len([node for node in conditional.body if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'terminal_journal']) == 1
    conditional.body = [node for node in conditional.body if not
        (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'terminal_journal')]
    returns = [node for node in ast.walk(trial.handlers[0]) if isinstance(node, ast.Return)
               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
               and node.value.func.id == '_emit_broker_terminal_response_v3']
    assert len(returns) == 1 and returns[0].value.args[1].id == 'terminal_journal'
    returns[0].value.args[1].id = 'durable_journal'
assert ast.dump(current, include_attributes=False) == ast.dump(before, include_attributes=False)

old_tests = ast.parse((BASE / 'test_backend_publication_broker_terminal_v3.py.before.raw').read_bytes())
new_test_path = ROOT / 'tests/test_backend_publication_broker_terminal_v3.py'
new_tests = ast.parse(new_test_path.read_bytes())
def methods(tree):
    return {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}
old_methods, new_methods = methods(old_tests), methods(new_tests)
assert len(old_methods) == 11 and len(new_methods) == 13
assert all(new_methods[name] == body for name, body in old_methods.items())
closure_path = BENCHMARK / 'artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4.v1.json'
closure = json.loads(closure_path.read_bytes())
host_differences = []
original_root_differences = []
for row in closure['project_sources']:
    if pin(ROOT / row['path'])['sha256'] != row['sha256']:
        host_differences.append(row['path'])
    if pin(BENCHMARK / row['path'])['sha256'] != row['sha256']:
        original_root_differences.append(row['path'])
assert host_differences == ['scripts/backend_publication_process_supervisor_v3.py']
assert not original_root_differences
allowlists = sorted(ROOT.glob('deploy/**/*allowlist.txt'))
source_membership = [str(path.relative_to(ROOT)) for path in allowlists
                     if 'scripts/backend_publication_process_supervisor_v3.py' in path.read_text().splitlines()]
assert not source_membership
red = json.loads((BASE / 'attempt-01-red/unit-result.v1.json').read_bytes())
green = json.loads((BASE / 'attempt-02-green/unit-result.v1.json').read_bytes())
red_execution = json.loads((BASE / 'attempt-01-red/execution.v1.json').read_bytes())
green_execution = json.loads((BASE / 'attempt-02-green/execution.v1.json').read_bytes())
assert red['tests_run'] == 2 and len(red['failures']) == 2 and not red['errors']
assert green['tests_run'] == 12 and not green['failures'] and not green['errors'] and not green['skips']
for outcome in (red_execution, green_execution):
    assert not outcome['timed_out'] and outcome['source_unchanged'] and outcome['all_capture_fds_closed']
    assert all(not row['owned_group_members'] and not row['read_errors'] for row in outcome['process_scans'])
    assert all(row['original_process_absent'] for row in outcome['actual_child_terminals'])
artifact_pins = [pin(BASE / name) for name in ('preedit-proposal-and-authorization.v1.json',
    'attempt-01-red/execution.v1.json', 'attempt-01-red/unit-result.v1.json', 'attempt-01-red/stderr.raw',
    'attempt-02-green/execution.v1.json', 'attempt-02-green/unit-result.v1.json', 'attempt-02-green/stderr.raw',
    'run_focused_v1.py')]
value = {'schema_version': 1, 'artifact_kind': 'vast_broker_terminal_owner_author_review_v1',
    'status': 'scoped_source_and_journal_regressions_passed_pending_independent_review',
    'accepted': False, 'production': pin(current_path), 'test': pin(new_test_path), 'evidence': artifact_pins,
    'changed_function_names': list(changed), 'whole_original_module_AST_after_exact_inverse_equal': True,
    'all_original_test_methods_AST_identical': sorted(old_methods),
    'new_methods': sorted(set(new_methods) - set(old_methods)),
    'red': {'tests': 2, 'failures': 2, 'message': 'Actual losing owner writes elected owner terminal intent before fix.'},
    'green': {'tests': 12, 'failures': 0, 'errors': 0, 'skips': 0,
              'unit_elapsed_s': 5.099, 'capture_elapsed_s': green_execution['elapsed_s'],
              'original_owner': green_execution['owner'], 'capture_fds_closed': True,
              'two_actual_process_scans': green_execution['process_scans']},
    'source_impact': {'host87_current_differences': host_differences,
        'original_benchmark_root87_differences': original_root_differences,
        'actual_all9_allowlist_membership': source_membership,
        'actual_allowlists_checked': [pin(path) for path in allowlists],
        'finite2693_supervisor_membership': True,
        'process_helper_unchanged': pin(ROOT / 'scripts/publication_operational_process_custody_v1.py')},
    'self_review': ['The journal parsed from a request is not proof this candidate won immutable owner election.',
        'Only a successful owner commit promotes private terminal writer authority; its authorization and namespace failures still retain original durable facts.',
        'No startup lock or persisted/public schema is added. Parent owner mismatch/cleanup, causal settle, exclusive leaves and 600000/615000 values are unchanged by exact AST inverse.',
        'Controlled winner/loser tests expose the actual defect without relying on hosted race timing or sleep.',
        'The unchanged real-namespace normal completion test was not dispatched in this isolated no-policy journal slice. It remains mandatory in full CI.',
        'Host87 changed, so existing current host grants cannot be rebound. Original 0ad accepted pairs remain authentic historical successes; root must renew current host closure/pairs.',
        'Hosted capacity first ValueError is still unknown; one instrumented unchanged local unit passed. No process-helper or capacity-fixture edits.'],
    'limitations': ['No full suite, real namespace, model, daemon, native or GPU run was performed.',
                    'Two known original hosted failures do not become green by this scoped author review.']}
path = BASE / 'author-review.v1.json'
with path.open('xb') as output:
    output.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    output.flush()
    os.fsync(output.fileno())
print(json.dumps({'review': pin(path), 'production': value['production'], 'test': value['test'],
                  'capture_elapsed_s': green_execution['elapsed_s']}))
