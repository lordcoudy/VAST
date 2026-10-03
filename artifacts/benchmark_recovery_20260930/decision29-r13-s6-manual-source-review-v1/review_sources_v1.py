"""Static byte/AST review only; never imports or executes reviewed source."""
import ast
import hashlib
import json
import os
from pathlib import Path
import time

WORK = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = WORK / 'artifacts/benchmark_recovery_20260930'
OUT = Path(__file__).parent
D = Path(r'\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-current-source-ci-20261003-decision29-D')
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
START = time.monotonic()
DEADLINE = START + 120
SOURCES = {
    'scripts/publication_guardian_component_preprocessing_contract_v1.py': ['validate_component_guardian_preprocessing_authority_v1'],
    'scripts/publication_guardian_preprocessing_contract_v1.py': ['validate_guardian_preprocessing_authority_v1', 'load_guardian_preprocessing_contract_v1'],
    'scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py': ['validate_accepted_policy_guardian_preprocessing_authority_v1', 'load_accepted_policy_guardian_preprocessing_contract_v1', '_source_material'],
    'scripts/publication_policy_qualification_pilot_executor_v2.py': ['_load_qualification_inputs', '_default_preprocessing_contract_loader', '_load_operational_inputs'],
    'scripts/publication_policy_qualification.py': ['_verify_execution_closure', 'assess_policy_qualification', 'promote_policy_qualification'],
    'scripts/full_resource_qualification.py': ['_verify_execution_closure', 'assess_full_resource_qualification', 'promote_full_resource_qualification'],
    'scripts/publication_q4_authority_source_material_v1.py': ['validate_publication_q4_authority_source_material_request_v1', 'build_publication_q4_authority_source_material_v1'],
    'scripts/publication_q4_authority_plan_pipeline_v1.py': ['validate_publication_q4_authority_source_spec_v1'],
    'scripts/backend_publication_runtime_authority_v2.py': ['validate_backend_publication_runtime_authority_v2'],
    'scripts/publication_q4_runtime_contract_v4.py': ['_authority_snapshot'],
    'scripts/backend_runtime_qualification_v4_input_index.py': ['validate_backend_runtime_qualification_v4_input_index'],
    'scripts/backend_q4_two_phase_executor_v1.py': ['_accepted_guardian_pins_v1', '_validate_source_registry', '_default_recheck_pins', 'execute_backend_q4_two_phase_v1'],
    'scripts/publication_q4_evidence_runner_v4.py': ['_validate_runner_authority', '_validate_validator_authority', '_validate_runtime_authority', 'run_publication_q4_evidence_validation_v4'],
    'scripts/full_publication_identity_artifacts.py': ['_validate_policy', '_validate_resource_binding', '_validate_resource_capability', '_load_full_publication_identity_artifacts_with_custody'],
    'scripts/full_publication_entrypoint.py': ['create_application', '_validated_accepted_policy_capability_manifest'],
}
TESTS = {
    'tests/test_publication_guardian_component_preprocessing_contract_v1.py': ['test_physical_receipt_last_roundtrip_nonpromotion_and_all_eight_worker_pins', 'test_legacy_kind_still_requires_original_image_patch_and_component_exact_four_projection'],
    'tests/test_publication_guardian_accepted_policy_preprocessing_contract_v1.py': ['test_receipt_last_cold_load_proves_promotion_closure_and_consensus', 'test_rejects_candidate_to_accepted_drift_and_cross_run_replay'],
    'tests/test_qualification_complete_operational_promotion_gate_v1.py': ['test_policy_assessment_requires_strict_cold_accounting', 'test_full_resource_assessment_requires_strict_cold_accounting', 'test_current_accepted_policy_guardian_requires_strict_cold_accounting'],
    'tests/test_qualification_promotion_clis.py': ['test_policy_cli_invokes_physical_promotion_and_prints_redacted_result', 'test_resource_cli_invokes_physical_promotion_and_prints_redacted_result'],
    'tests/test_backend_runtime_qualification_v4_input_index.py': ['test_closed_top_and_external_pins', 'test_old_abi_and_runtime_v1_refs_rejected'],
    'tests/test_full_publication_identity_artifacts.py': ['test_descriptor_drift_and_unaccepted_receipt_fail_closed'],
    'tests/test_publication_q4_evidence_runner_v4.py': ['test_authority_protocol_drift_and_argv_drift_fail_closed'],
}

def read(path, maximum):
    assert time.monotonic() < DEADLINE, 'metadata review deadline exceeded'
    before = path.stat()
    assert path.is_file() and not path.is_symlink() and 0 < before.st_size <= maximum
    with path.open('rb') as handle:
        raw = handle.read(maximum + 1)
    after = path.stat()
    signature = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_nlink, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    assert signature(before) == signature(after) and len(raw) == after.st_size
    return raw

def pin(path, raw):
    return {'path': path, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def node_record(node):
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            calls.append({'line': child.lineno, 'callee': ast.unparse(child.func)})
    assertions = [
        {'line': child.lineno, 'AST': ast.dump(child, include_attributes=False)}
        for child in ast.walk(node)
        if isinstance(child, ast.Assert) or isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute) and child.func.attr.startswith('assert')
    ]
    return {'name': node.name, 'line': node.lineno, 'end_line': node.end_lineno,
            'function_AST_sha256': hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest(),
            'ordered_call_sites': sorted(calls, key=lambda row: row['line']), 'assertions': assertions}

manifest_path = BASE / 'decision29-successor-ci-D-preparation-v1/original-setup-attempt01/tracked-raw-source.v1.json'
manifest_raw = read(manifest_path, 8 * 1024 * 1024)
assert pin('', manifest_raw)['sha256'] == '2aa2d4a507a0e0676b0afaadbc2b6b269c038431dc9ea79228fdc8a9f6b7451d'
manifest = json.loads(manifest_raw)
by_path = {row['path']: row for row in manifest}
assert len(by_path) == len(manifest) == 5577
pins, source_AST, test_AST, stored = [], {}, {}, {}
for relative, selected in {**SOURCES, **TESTS}.items():
    raw = read(D / relative, 2 * 1024 * 1024)
    descriptor = pin(relative, raw)
    assert (descriptor['size_bytes'], descriptor['sha256']) == (by_path[relative]['size_bytes'], by_path[relative]['sha256']), relative
    stored[relative] = raw
    pins.append({**descriptor, 'physical_root': '/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D',
                 'original_D_setup_git_oid': by_path[relative]['git_oid'], 'actual_original_D_setup_raw_descriptor_equal': True})
    tree = ast.parse(raw.decode('utf-8-sig'), filename=relative)
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert all(name in functions for name in selected), relative
    entry = {'selected_function_records': [node_record(functions[name]) for name in selected]}
    if relative in SOURCES:
        literals = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                key = node.targets[0].id
                if key in {'SCHEMA_VERSION', 'RECEIPT_KIND', 'AUTHORITY_KIND', 'MANIFEST_KIND', 'BINDING_KIND', 'ARTIFACT_KIND', 'SOURCE_REGISTRY_KIND'}:
                    try:
                        literals[key] = ast.literal_eval(node.value)
                    except ValueError:
                        pass
        entry['literal_kind_contracts'] = literals
        source_AST[relative] = entry
    else:
        test_AST[relative] = entry

for relative, raw in stored.items():
    assert read(D / relative, 2 * 1024 * 1024) == raw, 'source changed during manual review: ' + relative

review = {
    'schema_version': 1, 'artifact_kind': 'vast_decision29_R13_S6_manual_independent_source_review_v1',
    'reviewed_commit': COMMIT, 'baseline_commit': COMMIT, 'reviewable': True, 'blocking_findings': [],
    'reviewer_handles_released': True, 'reviewer_target_execution_count': 0, 'reviewer_test_execution_count': 0,
    'scope': 'Manual source proof of Component authority reaches a full entrypoint; static source/test reads from the clean D checkout only.',
    'owned_source_pins': pins, 'source_before_after_bytes_identical': True,
    'D_setup_manifest': pin(str(manifest_path), manifest_raw),
    'source_function_AST_and_callsite_inventory': source_AST,
    'selected_test_source_assertion_inventory': test_AST,
    'manual_consumer_proofs': [
        {
            'consumer': 'Full qualification preprocessing loader and authority validator',
            'source': 'scripts/publication_guardian_preprocessing_contract_v1.py',
            'guard_order': [
                'load_guardian_preprocessing_contract_v1: physical contract/receipt reads and fixed sibling names at lines1606-1624 precede receipt schema check.',
                'Exact receipt fields/schema/kind RECEIPT_KIND, status materialized_from_verified_v4_acceptance, SCOPE and nonauthorizing flags at1627-1646 precede self hash, transaction/candidate and acceptance loader.',
                'validate_guardian_preprocessing_authority_v1 at1462-1480 requires exact authority fields and its own AUTHORITY_KIND; component and unknown kinds fail.',
                'A complete historical manifest cannot replace the required accepted v4 model-parity/transaction/preprocessing chain. accepted=false is one conjunct, not dispatch authority.'
            ],
            'outcome': 'Component receipt can fail even earlier at fixed namespace. If named as a full receipt, exact field/kind check still rejects before accepted-model loader/authority return.'
        },
        {
            'consumer': 'Full qualification native pilot executor',
            'source': 'scripts/publication_policy_qualification_pilot_executor_v2.py',
            'guard_order': [
                '_load_qualification_inputs requires full v2 qualification index kind, exactly32 binding coordinates and original candidate receipt kind/status/scope at1206-1269.',
                '_default_preprocessing_contract_loader at1934 directly delegates only load_guardian_preprocessing_contract_v1.',
                '_load_operational_inputs at1999 calls this loader before service authority validation; full transaction/file/receipt/runtime expectation cross-bindings remain mandatory.',
                'The executor calls _load_operational_inputs at4232 before cell preflight/child native execution.'
            ],
            'filesystem_limit': 'Pilot/output/checkpoint directories can be created before the later preprocessing check. Rejection before native execution does not mean zero filesystem effects.',
            'outcome': 'Default production call path has no component-loader dispatch. Dependency injection used by fixtures is not the production CLI authority.'
        },
        {
            'consumer': 'Accepted-policy preprocessing loader and authority validator',
            'source': 'scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py',
            'guard_order': [
                'Loader physical/fixed sibling namespace guards at1053-1065 precede exact receipt fields/schema/RECEIPT_KIND/status/scope/flags at1074-1087.',
                'Only after this check does it parse predecessor descriptors and call _source_material at1125.',
                '_source_material delegates the full qualification predecessor and requires the exact accepted full policy receipt kind/status/complete coverage at550-558.',
                'validate_accepted_policy_guardian_preprocessing_authority_v1 at856-879 requires its own exact authority kind, fields, SHA values and exact resource image set.'
            ],
            'outcome': 'Raw component and unknown authority/receipt kinds reject; accepted=false matches ordinary full preprocessing nonpromotion but does not bypass kind or full predecessor validation.'
        },
        {
            'consumer': 'Policy and resource assessment/promotion',
            'sources': ['scripts/publication_policy_qualification.py', 'scripts/full_resource_qualification.py'],
            'guard_order': [
                'Policy assessment at945-964 checks exact supported full index fields/schema/kind before execution closure, descriptors, full binding/pilot validation and validator callbacks.',
                'Resource assessment at908-923 checks its distinct exact full-resource index before cold execution closure/descriptors/datasets/32 pilots.',
                'Both execution-closure helpers delegate require_complete_operational_accounting=True and require the distinct full32 closure kind/status/32 cells.',
                'promote_policy_qualification at1305-1313 and promote_full_resource_qualification at1271-1278 assess and reject passed=false before output-directory custody or writes.'
            ],
            'outcome': 'A component receipt supplied as index/closure is not any supported full index/closure kind. Historical complete data cannot replace the actual complete cold accounting and accepted calibration.'
        },
        {
            'consumer': 'Q4 source material, authority plan and runtime contract/input graph',
            'sources': ['scripts/publication_q4_authority_source_material_v1.py', 'scripts/publication_q4_authority_plan_pipeline_v1.py',
                        'scripts/backend_publication_runtime_authority_v2.py', 'scripts/publication_q4_runtime_contract_v4.py',
                        'scripts/backend_runtime_qualification_v4_input_index.py'],
            'guard_order': [
                'Source request/spec validators require exact Q4 request/spec kinds and complete ordered coordinate/launcher/validator/runner coverage; false authorization flags alone do not admit another kind.',
                'Source build validates request then physical descriptors before actual full runtime/launcher/validator/runner authority builders.',
                'Runtime authority v2 validator at183-193 requires exact fields/schema/kind before upstream/hash/lossless full v1 projection and external lineage checks.',
                'Runtime snapshot at650-735 requires exact snapshot kind plus separately typed runtime v2, launcher, invocation, Q4 validator and runner kinds.',
                'Q4 input validator at469-506 requires exact full Q4 input kind, external pins, exactlyfour ordered systems and typed nested authorities; finally globally unique112 runtime authorities.'
            ],
            'outcome': 'Component/unknown receipt or authority is not a full typed graph node. A historical systems table by itself supplies neither typed full authorities nor physical/external trust pins.'
        },
        {
            'consumer': 'Q4 two-phase production executor and evidence runner',
            'sources': ['scripts/backend_q4_two_phase_executor_v1.py', 'scripts/publication_q4_evidence_runner_v4.py'],
            'guard_order': [
                'execute_backend_q4_two_phase_v1 forbids self-supplied Q4/backend grants, opens held root and ensures work directory before _validate_source_registry at6211.',
                'Registry at3932-3939 requires exact source-registry kind/status/accepted=true. _accepted_guardian_pins_v1 at3204-3214 calls only the full accepted-policy preprocessing authority validator.',
                'These registry/guardian guards precede exclusive checkpoint lock, _pin_recheck (including live sockets/image queries) and new phase-A native cells.',
                'Evidence runner first physically loads exact runner/validator authorities, exact request and raw manifest, then typed runtime v2 reference; all precede _load_validator_module and validation invocation at925.'
            ],
            'filesystem_limit': 'Q4 work directory creation can precede source-registry rejection. No claim of side-effect-free rejection is made.',
            'outcome': 'An accepted=false component receipt cannot stand in as accepted Q4 registry, full accepted-policy guardian authority or exact runner/validator/runtime request node.'
        },
        {
            'consumer': 'Full publication identity loader and production entrypoint',
            'sources': ['scripts/full_publication_identity_artifacts.py', 'scripts/full_publication_entrypoint.py'],
            'guard_order': [
                'Identity loader at1834-1839 requires exact full identity manifest kind/schema and exact five binding roles.',
                '_validate_policy at667-684 requires accepted full policy receipt kind/status and exact32 bindings/32 pilots/3840 samples/30 per branch cell; _validate_resource_binding at718-741 requires full accepted resource receipt and capability kind/scope/coverage.',
                'Remaining model parity/execution/backend validators and dataset lineage are invoked before the canonical identity binding is returned.',
                'create_application at3407 loads this exact identity, then physically reopens accepted policy capability and derives model/resource/backend grants at3422-3438.',
                'All this precedes cloud links at3439, identity hardware/material gathering, store at3504, arm runner at3505, runtime at3522 and runner at3532. The plan command returns only an offline plan.'
            ],
            'outcome': 'Raw component or unknown receipt cannot be a full identity manifest/binding. Complete historical table plus accepted=false does not satisfy accepted full receipt/status/coverage or mandatory distinct grants.'
        }
    ],
    'test_coverage_findings': [
        'Existing component roundtrip negative calls only the qualification preprocessing loader and uses generic Exception. The supplied component filenames fail the earlier full namespace check, so that test alone does not isolate the exact kind predicate.',
        'The mapped legacy/component projection test proves preservation of the full five-field image patch requirement and component four-field projection; it does not exercise qualification/promotion/Q4/full publication entrypoints.',
        'Accepted-policy tests exercise predecessor/promotion consensus and physical/cross-run drift using injected dependencies, not a direct component-kind input to every full consumer.',
        'Strict cold accounting tests prove delegation of require_complete_operational_accounting=True through sentinel loaders. They do not prove rejection of a raw component receipt at each full entrypoint.',
        'Promotion CLI tests mock the promotion function and prove argument delegation/redacted result only.',
        'Q4 input source tests cover unknown launcher kind and legacy runtime/ABI kinds with re-sealed graph fixtures; they are relevant typed-kind guards, not direct component receipt entrypoint negatives.',
        'Full identity source test re-seals an engineering-canary policy status and proves rejection of unaccepted full receipt. It does not substitute a component receipt into every full consumer.',
        'Direct component-kind negative coverage of all named full consumers remains incomplete. This receipt supplies manual source proof and preserves that limitation; it does not rename it exhaustive behavioral test coverage.'
    ],
    'limits': [
        'No reviewed source was imported, compiled or executed; no tests, Git, target, model, device, Docker, engine, network or CI operation ran.',
        'Hashes are fresh Windows UNC byte/size observations joined to the original D setup raw source manifest. This does not claim fresh Linux seven-epoch observations or a new Git validation.',
        'Function AST/callsite inventory is a static locator, not execution evidence. Manual conclusions apply to the named default production call paths, not arbitrary caller-injected dependencies/private primitives.',
        'No full qualification, policy acceptance, Q4 campaign or full publication grant is created. Current118-scenario mapping is a separate later review; no mutable generator output is inspected here.',
        'The original corrected local D full-CI attempt is still owned by ROOT; this receipt neither polls it nor claims its outcome. The earlier wrapper usage failure is not labelled a CI execution.'
    ],
    'reviewer_closure': {'all_binary_read_contexts_closed_before_receipt': True, 'numeric_FD_balance_observed': False,
                         'Linux_process_absence_observed': False, 'target_processes_created': 0, 'metadata_elapsed_s': time.monotonic() - START}
}
payload = (json.dumps(review, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()
assert len(payload) < 512 * 1024 and time.monotonic() < DEADLINE
with (OUT / 'review.v1.json').open('xb') as handle:
    handle.write(payload)
print(json.dumps({'review': pin(str(OUT / 'review.v1.json'), payload), 'source_count': len(SOURCES), 'test_source_count': len(TESTS),
                  'reviewable': True, 'blocking_findings': [], 'reviewer_handles_released': True}))
