"""Finite source/provenance closure for the two independently scoped repairs."""
import ast
import hashlib
import json
import os
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = Path(__file__).resolve().parent
BROKER = ROOT / 'artifacts/benchmark_recovery_20260930/broker-terminal-owner-repair-v1'

def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def write(path, value):
    with path.open('xb') as output:
        output.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        output.flush()
        os.fsync(output.fileno())

def test_methods(tree):
    return {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}

broker_path = ROOT / 'tests/test_backend_publication_broker_terminal_v3.py'
broker_tree = ast.parse(broker_path.read_bytes())
before_broker = ast.parse((BROKER / 'test_backend_publication_broker_terminal_v3.py.before.raw').read_bytes())
assert all(test_methods(broker_tree)[name] == body for name, body in test_methods(before_broker).items())
helper = next(node for node in ast.walk(broker_tree) if isinstance(node, ast.FunctionDef) and node.name == '_losing_owner_cannot_publish')
trial = next(node for node in helper.body if isinstance(node, ast.Try))
observations = [node for node in ast.walk(trial) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id in ('original_stat', 'original_session') for target in node.targets)]
assert len(observations) == 2 and trial.finalbody
assert not any(isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
               and any(isinstance(target, ast.Name) and target.id in ('original_stat', 'original_session') for target in node.targets)
               for node in helper.body)
latest_broker_exec = BROKER / 'attempt-03-observation-cleanup-green/execution.v1.json'
latest_broker_unit = json.loads((BROKER / 'attempt-03-observation-cleanup-green/unit-result.v1.json').read_bytes())
assert latest_broker_unit['tests_run'] == 2 and not latest_broker_unit['errors'] and not latest_broker_unit['failures']
supplement = {'schema_version': 1, 'artifact_kind': 'vast_broker_owner_repair_observation_cleanup_supplement_v1',
    'status': 'frozen_pending_independent_peer', 'accepted': False,
    'production': pin(ROOT / 'scripts/backend_publication_process_supervisor_v3.py'),
    'test': pin(broker_path), 'prior_author_review': pin(BROKER / 'author-review.v1.json'),
    'prior_test_snapshot': pin(BROKER / 'test_before_observation_cleanup_fix.raw'),
    'fresh_two_methods_execution': pin(latest_broker_exec),
    'fresh_two_methods_result': pin(BROKER / 'attempt-03-observation-cleanup-green/unit-result.v1.json'),
    'fresh_raw_stderr': pin(BROKER / 'attempt-03-observation-cleanup-green/stderr.raw'),
    'all11_original_methods_AST_identical': True,
    'winner_observations_inside_existing_try_finally_AST_verified': True,
    'delta': 'Initialize original_stat/original_session to null; read both genuine observations only inside existing containment/finally. No other source change.',
    'limits': ['Two actual positive owner-election cases revalidated after the helper fix; no injected metadata-fault execution claimed.',
               'Prior original12 GREEN and two RED are preserved with their exact prior test bytes.',
               'Production99f and selected image source bytes remain unchanged by this test-only correction.']}
write(BROKER / 'author-review.v2.supplement.json', supplement)

test_path = ROOT / 'tests/test_publication_operational_process_custody_v1.py'
old_raw = (BASE / 'capacity-fixture-repair-v1/test_publication_operational_process_custody_v1.py.before.raw').read_bytes()
old = ast.parse(old_raw)
current = ast.parse(test_path.read_bytes())
original_methods = test_methods(old)
current_methods = test_methods(current)
method_name = 'test_caught_invalid_phase_remains_sticky_and_call_capacity_is_bounded'
assert all(current_methods[name] == body for name, body in original_methods.items() if name != method_name)
original_helpers = {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(old)
                    if isinstance(node, ast.FunctionDef) and node.name in ('process', 'run_child')}
new_helpers = {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(current)
               if isinstance(node, ast.FunctionDef) and node.name in original_helpers}
assert original_helpers == new_helpers
klass = next(node for node in current.body if isinstance(node, ast.ClassDef) and node.name == 'ProcessCustodyTests')
klass.body = [node for node in klass.body if not (isinstance(node, ast.FunctionDef)
    and node.name in ('_capacity_ready', '_run_capacity_child', 'test_capacity_fixture_failed_ready_child_never_registers'))]
method = next(node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
for node in ast.walk(method):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == '_run_capacity_child':
        node.func.attr = 'run_child'
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'assertRaisesRegex':
        assert ast.literal_eval(node.args[1]) == 'original engine phase missing or call capacity exhausted'
        node.func.attr = 'assertRaises'
        node.args = node.args[:1]
assert ast.dump(current, include_attributes=False) == ast.dump(old, include_attributes=False)
focused = BASE / 'capacity-fixture-focused-attempt02'
terminal = json.loads((focused / 'terminal.v1.json').read_bytes())
observations = json.loads((focused / 'original-observations.v1.json').read_bytes())
log = (focused / 'stderr.raw').read_text()
assert '\nRan 6 tests in ' in log and log.endswith('\nOK\n')
assert terminal['returncode'] == 0 and not terminal['timed_out'] and terminal['source_before'] == terminal['source_after']
assert terminal['all_capture_fds_closed']
assert all(not row['group_members'] and not row['read_errors'] for row in terminal['process_scans'])
capacity_records = [row for row in observations['receipts'] if '/capacity/' in row['original_descriptor']['path']]
assert len(capacity_records) == 1
capacity = capacity_records[0]
assert capacity['call_count'] == 32 and capacity['body_error'] == 'original engine phase missing or call capacity exhausted'
unchanged_production = pin(ROOT / 'scripts/publication_operational_process_custody_v1.py')
assert unchanged_production['sha256'] == '5ea8477e527bf57438ce81cea9b8b19fb628c555cb808711438e2036bcaee923'
value = {'schema_version': 1, 'artifact_kind': 'vast_capacity_fixture_author_review_v1',
    'status': 'frozen_pending_independent_peer', 'accepted': False,
    'test': pin(test_path), 'unchanged_production_process_helper': unchanged_production,
    'original_test_method_count': len(original_methods),
    'all_other_original_methods_AST_identical': True,
    'process_and_run_child_AST_identical': True,
    'whole_original_module_AST_equal_after_exact_capacity_delta_inverse': True,
    'changed_original_method': method_name,
    'scope': 'capacity-only real readiness/registration/release helper plus one real pre-readiness failure unit; exact33rd capacity error assertion,32 and failed-status assertions retained',
    'evidence': [pin(BASE / 'capacity-fixture-repair-v1/preedit-authorization.v1.json'),
        pin(BASE / 'capacity-original-reproduction-attempt01/terminal.v1.json'),
        pin(BASE / 'capacity-controlled-lifecycle-attempt01/terminal.v1.json'),
        pin(BASE / 'capacity-controlled-lifecycle-attempt01/original-lifecycle-probe.v1.json'),
        pin(focused / 'terminal.v1.json'), pin(focused / 'original-observations.v1.json'), pin(focused / 'stderr.raw'),
        pin(BASE / 'capacity-fixture-focused-attempt01/prelaunch-failure.v1.json')],
    'original_focused_owner': terminal['owner'], 'elapsed_s': terminal['elapsed_s'],
    'two_actual_process_scans': terminal['process_scans'], 'capture_fds_closed': True,
    'actual_capacity_receipt': capacity,
    'self_review': ['Readiness gate is only used by the capacity loop; it holds an actual child alive until the unchanged original observer registers it.',
        'All observed stdout includes the real consumed READY prefix before hashing terminal bytes.',
        'The33rd actual child reaches the original capacity validator, which refuses the exact intended condition; fixture finally kills/reaps its blocked child.',
        'The actual child failing before READY registers zero calls and cannot emit complete capture.',
        'Existing intentional fast/zombie process helpers and units remain unchanged; actual zombie and nonzero/timeout units passed in the six-case capture.',
        'No source87/selected73/native3/worker2 production bytes are changed by this test-only fix.',
        'Hosted first swallowed ValueError remains unknown; original unchanged local unit passed, controlled reaped refusal was FileNotFoundError, not a hosted-cause proof.'],
    'limitations': ['First focused collector failed only in Git prelaunch, before any unit child. Its source/namespace/error remain immutable.',
                    'No full CI, model, namespace policy, engine, native or benchmark dispatch.']}
write(BASE / 'capacity-fixture-repair-v1/author-review.v1.json', value)
print(json.dumps({'broker_supplement': pin(BROKER / 'author-review.v2.supplement.json'),
    'broker_test': pin(broker_path), 'capacity_review': pin(BASE / 'capacity-fixture-repair-v1/author-review.v1.json'),
    'capacity_test': pin(test_path), 'capacity_execution': pin(focused / 'terminal.v1.json')}))
