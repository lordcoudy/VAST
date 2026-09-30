"""Read-only code/argument audit of a prepared consumer; never runs it."""
import ast
import hashlib
import json
import os
import stat
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930/component-cpu04-corrected-cold-reader-preparation-v1'
ORIGINAL = ROOT / 'artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-04'
OUT = Path(__file__).parent / 'review.v1.json'

def descriptor(path):
    raw = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def document(path):
    return json.loads(path.read_bytes())

original_terminal = ORIGINAL.parent / 'cpu-pair-04-original-controller/original.terminal.v1.json'
assert descriptor(original_terminal)['sha256'] == '88b9c117f75b45454b8facc781e1bb291750de388b85f03c31fe7135b1496b0e'
terminal = document(original_terminal)
paths = [Path(row['descriptor']['path']) for row in terminal['pins_before']]
assert len(set(paths)) == len(paths) == 95
# Current paths and inode types are reviewed, never presented as original execution epochs.
for path in paths:
    info = path.lstat()
    assert path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode) and info.st_nlink == 1, str(path)
original_runtime = ROOT / 'artifacts/benchmark_recovery_20260930/component-cold-provider-seam-repair-v1/before/publication_gstreamer_component_runtime_v1.py'
original_expected = next(row['descriptor'] for row in terminal['pins_before']
                         if row['descriptor']['path'] == str(ROOT / 'scripts/publication_gstreamer_component_runtime_v1.py'))
old_ref = descriptor(original_runtime)
assert all(old_ref[key] == original_expected[key] for key in ('size_bytes', 'sha256'))
copy = BASE / 'corrected_component_runtime_v1.py'
copy_raw = copy.read_bytes()
assert original_runtime.read_bytes().replace(
    b'from publication_operational_request_domain_v1 import load_operational_jsonl_header_v1',
    b'from publication_operational_request_reconciliation_v1 import load_operational_jsonl_header_v1') == copy_raw
assert descriptor(copy)['sha256'] == '23202bc466cd53f60cc0b78eb7902b5cdb1be4c6242c04e5ed81d13609a0d49e'
arguments = document(BASE / 'arguments.v1.json')
index = document(ORIGINAL / 'runtime/component_runtime_index.v1.json')
cli = document(ORIGINAL / 'component_cli_terminal.v1.json')
guardian = document(ORIGINAL / 'guardian/service_authority.v1.json')
assert cli['status'] == 'failed' and cli['component_pairs'] == 0
assert arguments['component_authority_path'] == index['component_authority']['path']
assert arguments['runtime_bundle_paths'] == [row['descriptor']['path'] for row in index['bundles']]
assert arguments['arm_result_paths'] == [str(ORIGINAL / 'operations/arms' / row['operation_id'] / 'component_arm_result.v1.json')
                                        for row in index['bundles']]
assert arguments['analytics_socket_path'] == guardian['front_socket']['path']
assert arguments['scratch_root'] == str(Path(cli['capacity_reservation']['path']).parent)
assert arguments['output_dir'] == str(ORIGINAL) + '-corrected-cold-01'
assert not os.path.lexists(arguments['output_dir'])
assert not os.path.lexists(BASE / 'attempt01')
assert len(index['bundles']) == 2
assert set(arguments) == {'project_root', 'component_authority_path', 'capture_plan_path', 'runtime_bundle_paths',
    'arm_result_paths', 'guardian_authority_path', 'guardian_lifecycle_path', 'preprocessing_contract_path',
    'preprocessing_receipt_path', 'analytics_socket_path', 'scratch_root', 'output_dir'}
for key, suffix in {'capture_plan_path': 'operations/capture-plan/capture_plan_index.v1.json',
    'guardian_authority_path': 'guardian/service_authority.v1.json', 'guardian_lifecycle_path': 'guardian/service_lifecycle.v1.json',
    'preprocessing_contract_path': 'preprocessing/guardian-preprocessing-contract.v1.json',
    'preprocessing_receipt_path': 'preprocessing/guardian-component-preprocessing-receipt.v1.json'}.items():
    assert arguments[key] == str(ORIGINAL / suffix)
assert arguments['project_root'] == str(ROOT)
preparation_path = BASE / 'preparation.v3.json'
preparation = document(preparation_path)
assert descriptor(preparation_path)['sha256'] == '157c2c27dd512ed512854b43b1fa50fc87af95f7bfca4f926df1d2c20dd39711'
for row in preparation['files']:
    path = ROOT / row['path'].replace('\\', '/')
    actual = descriptor(path)
    assert all(actual[key] == row[key] for key in ('size_bytes', 'sha256'))
    if path.suffix == '.py':
        ast.parse(path.read_bytes())
assert preparation['executed'] is False and preparation['source_restoration_not_performed'] is True
# A parent-reviewed final observer pin is supplied when this audit is dispatched.
import sys
assert len(sys.argv) == 2
observer = BASE / 'observe_v2.py'
assert descriptor(observer)['sha256'] == sys.argv[1]
closure_path = ORIGINAL.parent / 'host/execution-code-closure.v5.json'
closure = document(closure_path)
runtime_relative = 'scripts/publication_gstreamer_component_runtime_v1.py'
original_record = next(row for row in closure['project_sources'] if row['path'] == runtime_relative)
current_runtime = ROOT / runtime_relative
current_info = current_runtime.lstat()
current_snapshot = {key: int(getattr(current_info, key, 0)) for key in original_record['snapshot']}
current_record = {**descriptor(current_runtime), 'snapshot': current_snapshot}
assert current_record['sha256'] == '23202bc466cd53f60cc0b78eb7902b5cdb1be4c6242c04e5ed81d13609a0d49e'
assert original_record['snapshot']['st_ctime_ns'] != current_snapshot['st_ctime_ns']
assert original_record['snapshot']['st_mtime_ns'] != current_snapshot['st_mtime_ns']
loader_path = ROOT / 'scripts/publication_policy_qualification_execution_code_closure_v1.py'
loader_raw = loader_path.read_bytes()
assert b'"snapshot": _snapshot(named_after)' in loader_raw
assert b'_require(observed == expected_body, "execution code closure physical snapshot drifted")' in loader_raw
function_lines = {node.name: node.lineno for node in ast.parse(loader_raw).body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
review = {
    'schema_version': 1, 'artifact_kind': 'vast_cpu04_corrected_cold_reader_independent_review_v1',
    'disposition': 'blocked_unexecuted',
    'files': [descriptor(ROOT / row['path'].replace('\\', '/')) for row in preparation['files']],
    'preparation': descriptor(preparation_path), 'original_terminal': descriptor(original_terminal),
    'provider_review': descriptor(ROOT / 'artifacts/benchmark_recovery_20260930/component-cold-provider-independent-review-v1/review.v1.json'),
    'arguments_match_original_index_service_and_scratch': True,
    'corrected_consumer_exact_original_runtime_plus_one_import': True,
    'current_original_95_paths_canonical_regular_single_link': True,
    'new_output_and_observer_namespaces_absent': True,
    'original_producer_byte_pins': 95,
    'source_restoration_rule': 'Cancelled before restoration or dispatch. Exact byte restoration produces new current epochs and cannot satisfy the original strict source snapshot. Do not rebind the original closure or original execution witnesses.',
    'authority_scope': 'The distinct artifact module does not claim original 87-source membership. Its unchanged stock cold code validates original physical source/model/runtime/CLI/container/guardian/all-phase evidence, not an invented replacement authority.',
    'observer_scope': 'The repaired source composes the 600/15 bounds and preserves unverified terminal publication failures. This does not resolve the stock authority snapshot blocker, and dispatch is not approved.',
    'execution_approved': False, 'consumer_executed': False, 'production_byte_restoration_performed': False,
    'strict_loader': {'source': descriptor(loader_path), 'function_lines': function_lines,
        'predicate': '_receipt_body captures full source/interpreter snapshots; load_execution_code_closure_v1 compares the entire newly observed body to the immutable original body.',
        'call_chain': 'cold original arm -> held_component_runtime_v1 -> held_selected_component_inputs_v1 -> _verify_host_material -> load_execution_code_closure_v1',
        'original_closure': descriptor(closure_path), 'original_runtime_record': original_record,
        'current_runtime_record': current_record,
        'current_snapshot_differs': True,
        'byte_restoration_alone_sufficient': False},
    'original_cpu04_cli_status': 'failed_immutable', 'task_18_8_completed_by_this_consumer': False,
    'new_native_or_guardian_workload': False, 'reviewer_executed_consumer_or_tests': False,
    'science_limits': 'Offline descriptive pair validation only; carried legacy C_obs summary still requires the separate original-sidecar reduction before derived claims. No quality, native-engine accuracy or population inference.',
    'initial_observer': descriptor(BASE / 'observe.py'),
    'initial_observer_disposition': 'Rejected before execution for incomplete 600/15 composition and exceptional terminal retention; preserved unexecuted.',
    'self_review': 'I initially misread the closure comparison as byte-only. The detailed _source_record path retains snapshots, invalidating that feasibility statement. The correction was reported and the diagnostic cancelled before restoration or dispatch.',
    'next_path': 'Retain failed CPU04 and this unexecuted preparation. Renew the host source closure for the corrected production code and obtain a fresh normal production pair; a new offline historical provenance route would require explicit reviewed design.',
    'review_script': descriptor(Path(__file__)),
}
with OUT.open('xb') as stream:
    stream.write((json.dumps(review, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps(descriptor(OUT), sort_keys=True))
