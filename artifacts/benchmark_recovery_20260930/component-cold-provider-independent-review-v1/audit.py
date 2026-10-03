"""Read-only byte/AST review; imports no production module and runs no test."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930/component-cold-provider-seam-repair-v1'
OUT = Path(__file__).parent / 'review.v1.json'

def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def methods(raw):
    return {f'{cls.name}.{node.name}': ast.dump(node, include_attributes=False)
            for cls in ast.parse(raw).body if isinstance(cls, ast.ClassDef)
            for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

source = ROOT / 'scripts/publication_gstreamer_component_runtime_v1.py'
test = ROOT / 'tests/test_publication_gstreamer_component_runtime_v1.py'
old_source = BASE / 'before/publication_gstreamer_component_runtime_v1.py'
old_test = BASE / 'before/test_publication_gstreamer_component_runtime_v1.py'
old, new = old_source.read_bytes(), source.read_bytes()
before_import = b'from publication_operational_request_domain_v1 import load_operational_jsonl_header_v1'
after_import = b'from publication_operational_request_reconciliation_v1 import load_operational_jsonl_header_v1'
assert old.count(before_import) == 1 and old.replace(before_import, after_import) == new
assert descriptor(source)['sha256'] == '23202bc466cd53f60cc0b78eb7902b5cdb1be4c6242c04e5ed81d13609a0d49e'
assert descriptor(test)['sha256'] == 'b71447895a9b4e9f50d3893242c3be4e1d5bbea9516813df0dd54d66bbeb96b3'
old_methods, new_methods = methods(old_test.read_bytes()), methods(test.read_bytes())
assert all(new_methods[name] == body for name, body in old_methods.items())
added = sorted(set(new_methods) - set(old_methods))
assert added == ['ColdProviderBoundaryTests.test_actual_operational_header_reader_binds_physical_bytes',
                 'ColdProviderBoundaryTests.test_real_cold_provider_resolves_before_two_arm_cardinality_guard']
evidence = {}
for label in ('red-01', 'green-01'):
    terminal_path = BASE / label / 'terminal.v1.json'
    terminal = json.loads(terminal_path.read_bytes())
    assert terminal['source_before'] == terminal['source_after']
    assert terminal['original_child_current'] is None and terminal['original_group_members'] == []
    assert not terminal['timed_out'] and not terminal['capture_exceeded']
    for record in terminal['outputs'].values():
        actual = descriptor(Path(record['path']))
        assert all(actual[key] == value for key, value in record.items())
    evidence[label] = {'terminal': descriptor(terminal_path), 'returncode': terminal['original_child_returncode'],
                       'outputs': terminal['outputs'], 'capture_elapsed_s': terminal['elapsed_s']}
assert evidence['red-01']['returncode'] == 1 and evidence['green-01']['returncode'] == 0
red_log = (BASE / 'red-01/stderr.raw').read_text()
green_log = (BASE / 'green-01/stderr.raw').read_text()
assert 'Ran 2 tests' in red_log and 'FAILED (errors=1)' in red_log and 'ImportError' in red_log
assert 'Ran 14 tests in 3.215s' in green_log and green_log.rstrip().endswith('OK')
review = {
    'schema_version': 1, 'artifact_kind': 'vast_component_cold_provider_independent_review_v1',
    'disposition': 'approved_import_only_repair', 'source': [descriptor(source), descriptor(test)],
    'original_source': [descriptor(old_source), descriptor(old_test)],
    'exact_raw_inverse_import_only': True, 'all_original_method_asts_retained': True, 'added_tests': added,
    'evidence': evidence, 'red_tests': 2, 'red_import_errors': 1, 'red_successes': 1,
    'green_tests': 14, 'green_unittest_elapsed_s': 3.215,
    'scope': 'Actual cold provider/cardinality entry and physical header reader; existing fixtures retain their scope. No complete cold-pair acceptance is established.',
    'reviewer_executed_tests': False, 'reviewer_engine_or_workload_operations': False,
    'original_cpu04_cli_status': 'failed_immutable', 'separate_reader_execution_approved_by_this_receipt': False,
    'self_review': 'My earlier adjacent handoff review stopped before this local cold import. These regressions now cover that concrete seam; full retained-output cold validation remains necessary.',
    'review_script': descriptor(Path(__file__)),
}
with OUT.open('xb') as stream:
    stream.write((json.dumps(review, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps(descriptor(OUT), sort_keys=True))
