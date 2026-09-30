"""Finite read-only metadata review. Writes only new provisional review artifacts."""
import ast
import collections
import copy
import hashlib
import json
import pathlib
import re
import subprocess
import zipfile

ROOT = pathlib.Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
OUT = BASE / 'final-conformance-mapping-skeleton-v1'
EXPECTED_HEAD = '5bc416a2beab98b6cc60229dac56332b48cc6ca2'
CHANGE = 'openspec/changes/fix-benchmark-preparations-spec/'


def raw(rel):
    p = ROOT / rel
    assert p.stat().st_size <= 8 * 1024 * 1024, rel
    return p.read_bytes()


def descriptor(rel):
    data = raw(rel)
    return {'path': rel, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def evidence_path(rel):
    return 'artifacts/benchmark_recovery_20260930/' + rel


def metadata(rel):
    return json.loads(raw(evidence_path(rel)))


def write_new(name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    with (OUT / name).open('xb') as f:
        f.write(data)
    return descriptor((OUT / name).relative_to(ROOT).as_posix())


def git(*args):
    result = subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(ROOT), *args],
                            capture_output=True, timeout=15, check=True)
    assert len(result.stdout) <= 1024 * 1024
    return result.stdout


def ast_index(rel):
    data = raw(rel)
    tree = ast.parse(data, filename=rel)
    definitions = [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    tests = {}
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef):
            for n in cls.body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_'):
                    tests[f'{pathlib.Path(rel).stem}.{cls.name}.{n.name}'] = n.lineno
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_'):
            tests[f'{pathlib.Path(rel).stem}.{n.name}'] = n.lineno
    return definitions, tests


assert git('rev-parse', 'HEAD').decode().strip() == EXPECTED_HEAD
doc_paths = [CHANGE + p for p in ('proposal.md', 'design.md', 'tasks.md',
                                  'specs/benchmark-launch-preparation/spec.md',
                                  'verification-plan.md', 'conformance-progress.md')]
doc_paths += ['BENCHMARK_RECOVERY_PLAN.md', 'docs/gstreamer-component-benchmark-runbook.md']
doc_pins = {p: descriptor(p) for p in doc_paths}
spec_lines = raw(CHANGE + 'specs/benchmark-launch-preparation/spec.md').decode().splitlines()
tasks_path = CHANGE + 'tasks.md'
working_tasks = raw(tasks_path).decode()
committed_tasks_raw = git('show', EXPECTED_HEAD + ':' + tasks_path)
committed_tasks = committed_tasks_raw.decode()


def tasks(text):
    return {m.group(2): {'checked': m.group(1) == 'x', 'clause': m.group(3), 'line': i}
            for i, line in enumerate(text.splitlines(), 1)
            if (m := re.match(r'^- \[([ x])\] (\d+(?:\.\d+)+) (.+)$', line))}


wt, ct = tasks(working_tasks), tasks(committed_tasks)
assert len(wt) == len(ct) == 65
assert sum(v['checked'] for v in wt.values()) == 38
assert sum(v['checked'] for v in ct.values()) == 37
assert [k for k in wt if wt[k] != ct[k]] == ['22.1']
assert wt['22.1']['checked'] and not ct['22.1']['checked']

old_rel = evidence_path('final-conformance-mapping-skeleton-v1/mapping.v3.json')
old_pin = descriptor(old_rel)
assert old_pin['sha256'] == 'f1db2751aa2750992229f7281adad3e8151dcfa2113faf86887358f2036cf043'
old = json.loads(raw(old_rel))
mapping = copy.deepcopy(old)
old_scenarios = {s['name']: s for req in old['requirements'] for s in req['scenarios']}
assert len(old_scenarios) == 109

refs = {
    'pre_implementation_direction_peer': 'gstreamer-release-proposal-independent-review-v1/review.v1.json',
    'seam1_pre_edit': 'gstreamer-component-seam1-preparation-v1/dependency-inventory.v1.json',
    'seam1_peer': 'gstreamer-component-seam1-independent-review-v1/review.v1.json',
    'seam2_pre_edit': 'component-seam2-pre-edit-v1/inventory.v1.json',
    'seam2_author': 'component-seam2-final-review-v1/review.v1.json',
    'seam2_peer': 'component-seam2-independent-review-v1/review.v1.json',
    'model_inspect_repair_peer': 'component-model-inspect-adapter-independent-review-v1/review.v1.json',
    'probe_schema_repair_peer': 'component-probe-authority-schema-independent-review-v1/review.v1.json',
    'runtime_peer': 'component-runtime-independent-review-v1/review.v1.json',
    'cli_peer': 'component-cli-independent-review-v1/review.v1.json',
    'held_session_peer': 'component-held-session-independent-review-v1/review.v1.json',
    'held_session_scope': 'component-held-session-host-image-scope-v1/review.v1.json',
    'held_dispatch_peer': 'component-held-session-dispatch-independent-review-v1/review.v1.json',
    'selected_host_renewal_peer': 'component-host-renewal-v3-independent-review-v1/review.v1.json',
    'selected_build_terminal': 'selected-gstreamer-build-a4e145b7-v1/operation.terminal.v1.json',
    'selected_image': 'selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json',
    'selected_packaged_terminal': 'selected-gstreamer-packaged-a4e145b7-v1/operation.terminal.v1.json',
    'cpu05_postterminal_peer': 'component-cpu05-postterminal-audit-preparation-v1/review.v1.json',
    'cpu05_scientific': 'component-cpu05-sidecar-independent-reduction-v2/scientific-report.v1.json',
    'cpu05_reader_provenance': 'component-cpu05-sidecar-independent-reduction-v2/reader-adaptation-provenance.v1.json',
    'cpu05_scientific_peer': 'component-cpu05-sidecar-scientific-peer-review-v1/review.v1.json',
    'ci_observer_peer': 'decision24-ci-independent-review-v1/review.v1.json',
    'ci_prerequisite_author': 'decision25-ci-prerequisites-v1/author-review.v1.json',
    'ci_prerequisite_peer': 'decision25-ci-parent-review-v1/review.v1.json',
    'sibling_packaging_original': 'decision25-sibling-packaging-v1/green-01/terminal.v1.json',
    'sibling_scope': 'decision25-sibling-packaging-v1/current-scope.v1.json',
    'sibling_packaging_peer': 'decision25-ci-root-independent-review-v1/scope-review.v1.json',
    'portable_fixture_author': 'ci-2f409-portable-fixture-repairs-v1/author-review.v1.json',
    'portable_fixture_peer': 'ci-2f409-portable-fixture-independent-review-v1/review.v1.json',
    'journalctl_author': 'ci-journalctl-argument-seam-repair-v1/author-review.v1.json',
    'journalctl_peer': 'ci-journalctl-argument-independent-review-v1/review.v1.json',
    'ci8f_failure': 'ci-8fefa-readonly-failure-diagnosis-v1/summary.v1.json',
    'relocation_feasibility': 'component-ext4-relocation-feasibility-v1/review.v1.json',
    'relocation_inventory': 'component-ext4-relocation-feasibility-v1/inventory.v1.json',
    'relocation_classification': 'component-ext4-relocation-feasibility-v1/git-input-classification.v1.json',
    'decision27_planning_peer': 'decision27-planning-independent-review-v1/review.v1.json',
    'runbook_peer': 'component-runbook-independent-review-v1/review.v2.json',
}
evidence = {key: descriptor(evidence_path(rel)) for key, rel in refs.items()}
direction_bytes = raw(evidence_path(refs['pre_implementation_direction_peer']))
assert git('show', '9ad1a52b38cd5028de6b04bcc08192309ef192cf:' +
           evidence_path(refs['pre_implementation_direction_peer'])) == direction_bytes
pre_edit = metadata(refs['seam1_pre_edit'])
assert pre_edit['authorization'] == 'Read-only preparation plus artifact inventory only; exact Decision23 committed PR implementation authorization pending'
pre_edit_source_joins = []
for row in pre_edit['modules']:
    original = git('show', '9ad1a52b38cd5028de6b04bcc08192309ef192cf:' + row['path'])
    assert len(original) == row['size_bytes'] and hashlib.sha256(original).hexdigest() == row['sha256'], row['path']
    pre_edit_source_joins.append({k: row[k] for k in ('path', 'size_bytes', 'sha256')})
cpu = metadata(refs['cpu05_postterminal_peer'])
science = metadata(refs['cpu05_scientific'])
science_peer = metadata(refs['cpu05_scientific_peer'])
ci = metadata(refs['ci8f_failure'])
assert cpu['hold_release'] is True and cpu['original_cli_returncode'] == 78
assert cpu['task_18_8_complete'] is False
assert science['measurement_acceptance'] is False and science['original_cpu05_cli_exit_code'] == 78
assert science_peer['task_18_8_complete'] is False
assert ci['source_commit'] == '8fefa4ba0c5b135c66f85a6eb7f4fd1aaebfdc21'

requirements = []
all_missing = ('Final exact-current-source complete hosted/ext4 portable execution, original skip '
               'inventory, active conformance, archive and final review remain pending.')
pair_missing = ('CPU05 original CLI78 after2125.861229s exceeded2100s and remains failed. '
                'Authentic retained cold/scientific results do not complete18.8. Fresh successful '
                'original CPU and separately owned GPU pairs, all-phase cold/cleanup and four-arm '
                'descriptive reduction are still required.')
for i, line in enumerate(spec_lines):
    if line.startswith('### Requirement: '):
        requirements.append({'id': f'R{len(requirements)+1}', 'name': line[17:], 'line': i+1,
                             'implementation_profile_ref': f'R{len(requirements)+1}', 'scenarios': []})
    elif line.startswith('#### Scenario: '):
        req = requirements[-1]
        name = line[15:]
        end = i + 1
        while end < len(spec_lines) and not spec_lines[end].startswith(('#### Scenario: ', '### Requirement: ')):
            end += 1
        clause = '\n'.join(spec_lines[i:end]).strip()
        if name in old_scenarios:
            row = copy.deepcopy(old_scenarios[name])
            assert clause == row['exact_clause'], name
            row['explicit_missing_gates'] = [g.replace('CPU05 is active, GPU01 is absent',
                                                        'CPU05 remains failed after its original late CLI78; GPU01 is absent')
                                               for g in row['explicit_missing_gates']]
        else:
            row = {'name': name, 'historical_register_id': None,
                   'scope': 'active_selected_component_or_repository_behavior',
                   'scope_reason': 'Decision27 relocation is an active future physical gate, not a copied historical authority grant.',
                   'mapping_status': 'skeleton_no_final_acceptance',
                   'explicit_missing_gates': [
                       all_missing, pair_missing,
                       'Actual exclusive ext4 checkout/finite genuine copy, destination/source byte+epoch+membership proof, new stock87-source closure, current image/model/socket/UID/space checks and genuine daemon bind reachability are pending.',
                       'Existing strict root/descriptor/epoch APIs and a planning feasibility review are source evidence only. No actual relocated setup or copied-authority negative execution is claimed here.'],
                   'final_source_test_evidence_join': None, 'physical_final_gate_descriptor': None}
        row.update({'id': f"{req['id']}/S{len(req['scenarios'])+1}", 'name': name, 'line': i+1,
                    'exact_clause': clause, 'implementation_and_current_test_name_ref': req['id']})
        assert row['final_source_test_evidence_join'] is None
        assert row['physical_final_gate_descriptor'] is None
        req['scenarios'].append(row)

assert len(requirements) == 20
assert sum(len(r['scenarios']) for r in requirements) == 112
assert all(name in {s['name'] for r in requirements for s in r['scenarios']} for name in old_scenarios)
historical = [s for r in requirements for s in r['scenarios'] if s['historical_register_id'] is not None]
assert len(historical) == 82

profiles = mapping['profiles']
profiles['R20'] = {
    'sources': copy.deepcopy(profiles['R5']['sources'][:2] + profiles['R19']['sources']),
    'current_test_modules': copy.deepcopy(profiles['R5']['current_test_modules'][:1] + profiles['R19']['current_test_modules']),
    'closed_existing_evidence': [evidence[k] for k in ('relocation_feasibility', 'relocation_inventory',
                                                    'relocation_classification', 'decision27_planning_peer')],
    'evidence_interpretation': 'Existing stock path/physical-source/epoch/private-session APIs are candidate mechanisms. These source/test indices do not prove actual relocated copy, copied-authority rejection, daemon reachability or successful relocated pairs.',
    'unresolved_source_candidates': [], 'unresolved_test_candidates': [],
}
profile_extra = {
    'R1': ['cpu05_postterminal_peer'], 'R3': ['cpu05_postterminal_peer'],
    'R4': ['cpu05_postterminal_peer'], 'R5': ['relocation_feasibility', 'selected_host_renewal_peer'],
    'R8': ['cpu05_postterminal_peer'], 'R12': ['ci8f_failure', 'portable_fixture_peer', 'journalctl_peer'],
    'R13': ['model_inspect_repair_peer', 'probe_schema_repair_peer', 'selected_host_renewal_peer', 'cpu05_postterminal_peer'],
    'R14': ['cpu05_postterminal_peer'],
    'R15': ['cpu05_scientific', 'cpu05_reader_provenance', 'cpu05_scientific_peer'],
    'R16': ['cpu05_scientific', 'cpu05_scientific_peer', 'cpu05_postterminal_peer'],
    'R17': ['ci_observer_peer', 'ci8f_failure', 'journalctl_peer'],
    'R18': ['portable_fixture_peer', 'sibling_packaging_original', 'ci8f_failure', 'journalctl_peer'],
    'R19': ['cpu05_postterminal_peer', 'cpu05_scientific_peer'],
}
ast_cache = {}
for rid, profile in profiles.items():
    for key in profile_extra.get(rid, []):
        if evidence[key] not in profile['closed_existing_evidence']:
            profile['closed_existing_evidence'].append(evidence[key])
    for source in profile['sources']:
        rel = source['path']
        source['exists'] = (ROOT / rel).is_file()
        if not source['exists']:
            continue
        source['current_physical_descriptor'] = descriptor(rel)
        if not rel.endswith('.py'):
            continue
        defs, _ = ast_cache.setdefault(rel, ast_index(rel))
        source['current_symbol_count'] = len(defs)
        current = {n.name: n.lineno for n in defs}
        for example in source.get('current_symbol_examples', []):
            example['line'] = current.get(example['name'])
            if example['line'] is None:
                example['current_symbol_unresolved'] = True
    for test in profile['current_test_modules']:
        rel = test['path']
        if not (ROOT / rel).is_file():
            profile['unresolved_test_candidates'].append(rel)
            continue
        test['current_physical_descriptor'] = descriptor(rel)
        _, names = ast_cache.setdefault(rel, ast_index(rel))
        test['current_source_test_method_count'] = len(names)
        for candidate in test['candidate_test_names']:
            candidate['line'] = names.get(candidate['test_id'])
            if candidate['line'] is None:
                candidate['current_test_name_unresolved'] = True

mapping.update({
    'mapping_revision': 4,
    'current_requirements': 20, 'current_scenarios': 112, 'new_scenarios': 30,
    'requirements': requirements,
    'current_source_commit': EXPECTED_HEAD,
    'publication_ready': False, 'measurement_acceptance': False,
    'accepted_hardware_descriptor': None,
    'source_docs': list(doc_pins.values()),
    'supersedes': {**old_pin, 'reason': 'Append exact Decision27 three scenarios, refresh static current-source indices and closed CPU05/CI/scientific facts; preserve all109 earlier clauses and granular82-register classifications.'},
    'scope_counts': dict(collections.Counter(s['scope'] for r in requirements for s in r['scenarios'])),
    'evidence': evidence,
    'task_source_points': {
        'committed': {'commit': EXPECTED_HEAD, 'checked': 37, 'total': 65,
                      'tasks_descriptor': {'path': tasks_path, 'size_bytes': len(committed_tasks_raw),
                                           'sha256': hashlib.sha256(committed_tasks_raw).hexdigest()}},
        'current_working': {'checked': 38, 'total': 65, 'tasks_descriptor': doc_pins[tasks_path],
                            'only_difference_from_commit': '22.1 changed to checked with exact Decision27 planning/PR evidence; no setup or pair acceptance.'},
        'mapping_changes_tasks': False,
    },
    'state_as_reported_by_original_owner': {
        'cpu04': 'Original cold ImportError failed; no historical producer-byte/epoch restoration or acceptance.',
        'cpu05': {'state': 'closed_failed_original', 'cli_returncode': 78, 'pair_elapsed_s': 2125.861229321,
                  'original_pair_budget_s': 2100, '95_hold_release': True,
                  'retained_cold_result': 'authentic complete, does not override late original CLI failure',
                  '18.8_complete': False, 'evidence_ref': 'cpu05_postterminal_peer'},
        'cpu05_scientific': {'status': 'closed_source_and_original_evidence_peer_review',
                             'report_ref': 'cpu05_scientific', 'peer_ref': 'cpu05_scientific_peer',
                             'accepted': False, 'four_arm_gate_complete': False,
                             'field_comparisons_per_arm': {'candidate': 72, 'carried_arm': 72, 'cold_summary': 72, 'csv': 14},
                             'limitation': 'Single descriptive CPU pair; C_obs partial attributed elapsed/topology proxy only; completed-only latency excludes drops; zero completed frames on time in both arms. SVG is descriptor-bound, not independently rerendered.'},
        'gpu01': 'Absent; fresh separately owned original forced-GPU pair remains mandatory.',
        'CI8f': {'run_id': 36751014399, 'source_commit': ci['source_commit'], 'state': 'closed_failed_original',
                 'six_builds': 'all observed zero', 'required_native_success_ids': ci['exact_native_three_success_ids'],
                 'missing_required_native_successes': ci['missing_required_successes'], 'evidence_ref': 'ci8f_failure'},
        'CI5bc': {'run_id': 36764814739, 'state': 'active_as_reported_by_original_owner',
                  'full_job': 110056199709, 'host_job': 110056199870,
                  'host_job_state': 'two prerequisites completed success as reported; original logs not retained/read by this mapping',
                  'current_source_acceptance': False},
        'CI2_parser_repair': {'original_tests': 16, 'successes': 16, 'peer_ref': 'journalctl_peer',
                              'scope': 'Real journalctl --help parser only; no actual journal read or namespace/policy proof.'},
        'portable_fixture_slice': {'original_tests': 99, 'successes': 96, 'existing_windows_skips': 3,
                                    'author_ref': 'portable_fixture_author', 'peer_ref': 'portable_fixture_peer',
                                    'scope': 'Finite fixture repair; not full portable or hardware acceptance.'},
        'relocation': {'decision27': 'closed exact planning only', 'full_inventory_leaves': 2693,
                       'exclusive_copy_leaves': 2504, 'tracked_identical_leaves': 189,
                       'actual_setup_or_daemon_bind_or_new_pair_claimed': False,
                       'new_stock_host_closure_required': True},
        'archive': 'Pending; no sync/archive/merge by this task.',
    },
    'limitations': [
        'Exact current scenario clauses and static AST indices are mapping candidates only. No test discovery/execution, model/engine/native/namespace query, workflow rerun, source/planning/tasks/Git mutation occurred.',
        'All109 earlier exact scenario clauses and their individual scopes are retained; register membership is provenance, not blanket82-scenario deferral.',
        'Historical source approvals remain dated and are supplemented by explicit later repair/packaging/current original CPU05 references; old unit receipts are not relabeled as current full-source checks.',
        'CPU05 genuine measurement/cold/scientific consistency is distinct from original CLI deadline acceptance. Final accepted hardware descriptor and every per-scenario final gate/join remain null.',
        'Decision27 feasibility/stock APIs do not establish actual relocated bytes, daemon binds, successful pairs, or an executed copied-authority negative. All three new physical scenario gates remain pending.',
        'Current tasks working38/65 differs from committed5bc37/65 solely by planning-only22.1. This artifact does not edit or check any task.',
        'Original current CI is active as reported by parent; no active output was read and no outcome is predicted.',
        'Unresolved candidate names/paths remain explicit; static names are nonexhaustive and do not prove scenario coverage.',
    ],
})

# Small, genuine hosted package facts retained from the original CRC-checked ZIP;
# this is a read-only archive join, not a new plugin/tool invocation.
zip_rel = evidence_path('ci-8fefa-original-retention-v1/36751014399-cpu/original-artifact.zip')
archive_pin = descriptor(zip_rel)
assert archive_pin == ci['original_archives']['cpu']
plugin_entries = []
with zipfile.ZipFile(ROOT / zip_rel) as archive:
    for factory in ('appsrc', 'queue', 'videoconvert'):
        call_name = f'factory-{factory}.json'
        stdout_name = f'factory-{factory}.stdout'
        call_bytes, stdout = archive.read(call_name), archive.read(stdout_name)
        assert len(call_bytes) <= 16384 and len(stdout) <= 65536
        call = json.loads(call_bytes)
        assert call['returncode'] == 0 and call['timed_out'] is False
        text = stdout.decode()
        filename = re.search(r'^\s*Filename\s+(.+)$', text, re.M).group(1)
        version = re.search(r'^\s*Version\s+(.+)$', text, re.M).group(1)
        plugin_entries.append({'factory': factory, 'plugin_filename_observed': filename,
                               'version_observed': version, 'original_returncode': 0,
                               'archive': archive_pin,
                               'call_entry': {'name': call_name, 'size_bytes': len(call_bytes), 'sha256': hashlib.sha256(call_bytes).hexdigest()},
                               'stdout_entry': {'name': stdout_name, 'size_bytes': len(stdout), 'sha256': hashlib.sha256(stdout).hexdigest()}})

recommendations = []


def recommend(task_id, sources, tests_, keys, basis, limitation):
    assert task_id in wt and not wt[task_id]['checked']
    recommendations.append({
        'task_id': task_id, 'exact_current_task_clause': wt[task_id]['clause'],
        'current_task_line': wt[task_id]['line'], 'recommendation': 'may_check_implementation_and_its_specified_local_validation',
        'source_paths': sources, 'current_test_module_paths': tests_, 'evidence_refs': keys,
        'concrete_completion_basis': basis, 'remaining_acceptance_and_freshness_limits': limitation,
        'task_was_checked_by_this_review': False, 'hardware_or_final_ci_acceptance': False,
    })

inputs = 'scripts/publication_gstreamer_component_inputs_v1.py'
authority = 'scripts/publication_gstreamer_component_authority_v1.py'
runtime = 'scripts/publication_gstreamer_component_runtime_v1.py'
cli = 'scripts/publication_gstreamer_component_cli_v1.py'
input_test = 'tests/test_publication_gstreamer_component_inputs_v1.py'
runtime_test = 'tests/test_publication_gstreamer_component_runtime_v1.py'
cli_test = 'tests/test_publication_gstreamer_component_cli_v1.py'
future = 'Fresh relocated CPU/GPU successful original CLI, current four-arm science, final full hosted/ext4 checks, active conformance/archive/merge remain separate unchecked gates.'
recommend('18.2', [inputs, authority, 'scripts/publication_guardian_runtime_expectations_v1.py'],
          [input_test], ['pre_implementation_direction_peer', 'seam1_pre_edit', 'seam2_pre_edit', 'held_session_scope', 'selected_host_renewal_peer', 'relocation_feasibility'],
          'Source-grounded dependency/seam reviewfdaa3ab3 is present byte-exact in the9ad planning commit before implementation. Original pre-edit inventory9a439387 records approval pending and all11 original module hashes independently equal9ad blobs, all9-image memberships, host78/source165 and minimum pure factoring. Separate seam2 inventory4b2cc7a7 retains original owned-source before hashes and native3/worker2 member baselines. Later host87/selected73/deps6 and finite relocation inventory supplement these original maps.',
          'The two pre-edit inventories were not themselves committed in9ad; current physical/Git existence alone cannot establish their creation time. Original author dispatch order and pending-approval record support chronology and need the parent reviewer\'s explicit assessment before checking the literal before-edits clause. Later358e implementation review is not retrospective chronology evidence. ' + future)
recommend('18.3', [inputs, authority, 'scripts/publication_policy_qualification_runtime_inputs_v2.py'],
          [input_test], ['seam1_peer', 'model_inspect_repair_peer', 'probe_schema_repair_peer', 'held_session_peer', 'cpu05_postterminal_peer'],
          'The physical selected inventory/pure factoring is implemented. Original49 default-and-selected tests and later exact real stock inspect/probe regressions close two actual schema defects. CPU05 source/context phases completed genuine complete model/numeric/calibration/current worker checks before two native arms; >=30-per-cell and historical selected-row equality remain strict predicates. Foreign/stale/owner/epoch rejection is covered by original focused methods; full wrappers were not fabricated.',
          'Initial seam1/source tests were metadata fixtures; current genuine stock validation is supplied by the later CPU05 phases. Original CPU05CLI78 is not measurement acceptance. ' + future)
recommend('18.4', ['scripts/publication_guardian_component_preprocessing_contract_v1.py', 'scripts/publication_guardian_runtime_expectations_v1.py', 'scripts/checkpoint_gstreamer_analytics_sidecar.py', authority],
          ['tests/test_publication_guardian_component_preprocessing_contract_v1.py', 'tests/test_checkpoint_gstreamer_analytics_sidecar.py'],
          ['seam2_author', 'seam2_peer', 'selected_packaged_terminal', 'cpu05_postterminal_peer'],
          'Distinct component authority/preprocessing and exact three-kind dispatch, original seven native role/source front-worker joins and active two-operation before-inference guards are implemented. Original72 tests include10 component and62 legacy; genuine selected image19 packaged fixtures supplement physical CPU05 all8-worker activation/accounting. Old kinds, unknown/foreign and component full-entrypoint refusal remain strict.', future)
recommend('18.5', [runtime, cli, 'scripts/publication_operational_process_custody_v1.py', 'scripts/publication_operational_container_custody_v1.py'],
          [runtime_test, cli_test], ['runtime_peer', 'cli_peer', 'held_session_peer', 'cpu05_postterminal_peer', 'cpu05_scientific_peer'],
          'Executor/cold implementation delegates to original stock runtime, collector, physical custody/full-resource/ingress/all-phase validators. Original24 runtime/staging and14 CLI tests were supplemented by provider and58 private-session tests. CPU05 produced two real nativeCLI0/1080-ingress arms, genuine process/CID records, authenticated guardian shutdown and8371-request cold reconciliation; all full/qualification/Q4 flags remain false. Late original failure and cleanup were preserved.',
          'Implementation/consumer behavior is complete; original CPU05pair did not meet2100s, and --rm leaves final daemon exit/OOM unknown where not observed. Do not infer final measurement acceptance or grant from cold presence. ' + future)
recommend('18.6', ['scripts/checkpoint_gstreamer_publication_runtime_v3.py', 'deploy/gstreamer_custom/publication/Dockerfile', 'deploy/gstreamer_custom/publication/runtime-source-allowlist.txt'],
          ['tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py', 'tests/test_publication_runtime_frozen_identity_constants_v1.py'],
          ['selected_build_terminal', 'selected_image', 'selected_packaged_terminal', 'selected_host_renewal_peer', 'held_session_scope', 'cpu05_postterminal_peer'],
          'Actual selected deterministic A/B/final build/capture and19 packaged fixtures pass with imagee474/receipt61874c718; exact embedded/import/current image projection and six host-only constants/three test-literal renewal were reviewed. Native3/worker2 remain physically unchanged. CPU05 complete original stock selected model/raw-numeric/calibration assessment ran without rebinding historical aggregate acceptance.',
          'Other three runtime images remain historical/ineligible. Fresh ext4 source epochs require a new host closure; relocation does not by itself require image rebuild when relative raw scope remains identical. ' + future)
recommend('18.7', [cli, runtime, inputs], [cli_test, input_test, runtime_test],
          ['cli_peer', 'held_dispatch_peer', 'cpu05_postterminal_peer', 'relocation_feasibility'],
          'Original CPU05 genuinely created fresh bounded namespaces, physically allocated/verified/released20GiB reserves, held six selected inputs and current source/model/resource/owner/socket authority, and executed exact six-stream/four-branch baseline/shared source plans. Focused occupied/aliased/stale/unsupported and reserve replacement negatives remain intact.',
          'This check closes the implemented and genuinely observed CPU05 preflight only. It is no readiness certificate for a new root, future GPU, volume or daemon bind. Decision27 task22.2 must repeat actual destination and resource preflight before any new pair. ' + future)
recommend('19.2', ['scripts/ci_external_test_observer_v1.py', 'scripts/run_ci_checks.py', '.github/workflows/ci.yml'],
          ['tests/test_ci_external_test_observer_v1.py', 'tests/test_run_ci_checks.py'], ['ci_observer_peer', 'ci_prerequisite_peer', 'ci8f_failure'],
          'One external original parent/one fresh canonicalCP3.12.3 full-suite child and synchronous safe-GIL SIGUSR1 handler are implemented without native watchdog thread. Focused26 tests and original hosted8f24 requests/24 completed responses, both EOF and original status prove observation behavior. Full discovery,90m,600000/615000 and mandatory native criteria remain explicit unchanged constraints; trace/control/capture failures are sticky.',
          'Original8f full suite failed; handler timing can be delayed/coalesced and original-child status does not establish descendant quiescence. Implementation completion does not close19.5/18.11/current full-CI acceptance.')
recommend('19.3', ['scripts/ci_external_test_observer_v1.py', 'scripts/run_ci_checks.py'],
          ['tests/test_ci_external_test_observer_v1.py', 'tests/test_run_ci_checks.py'], ['ci_observer_peer', 'ci_prerequisite_author'],
          'Original26 focused tests cover actual child/signal/native-task1, conflict/disposition, capture overflow/write/EOF/drain, original nonzero/cancellation and pidfd-acquisition-failure cleanup via the unreaped original Popen handle. Source before/after and actual PID/group/FD retirement are recorded; production namespace/subreaper/WSL andCP3.12.3 predicates were not weakened.',
          'No native139 cause is proven and no namespace/profile remedy follows from focused success. Original hosted/current full checks remain separate.')
recommend('20.2', ['scripts/run_ci_checks.py', 'scripts/ci_test_selection_v1.py'],
          ['tests/test_run_ci_checks.py', 'tests/test_ci_test_selection_v1.py'], ['ci_prerequisite_author', 'ci_prerequisite_peer', 'ci8f_failure'],
          'Canonical actualCP3.12.3 child argv and fixed project import path preserve-I/-B, complete inventory, original IDs, native/observer/budget gates. Original meaningful canonical-alias and contained-import regressions pass; real hosted8f uses that canonical child and complete2943 inventory/2934 portable selection.',
          'The old8f original80 declaration vs88 actual skips failed honestly; subsequent finite88 correction is independently recorded, but final current full portable run is pending.')
recommend('20.3', ['scripts/run_ci_checks.py', '.github/workflows/ci.yml'],
          ['tests/test_run_ci_checks.py', 'tests/test_checkpoint_analytics_execution_client_cpp.py'], ['ci_prerequisite_peer', 'ci8f_failure'],
          'Actual8f package query and original gst-inspect appsrc/queue/videoconvert stdout retain loaded factory filenames/version1.24.2. Same original run configures/builds all six targets with zero statuses and reports all three mandatory native methods successful with no missing required native successes.',
          'This closes the individual prerequisites/build/native task. Overall8f/current hosted/ext4 complete portable and hardware gates remain failed/pending; package installation alone would not have sufficed.')
recommend('20.4', ['deploy/deepstream/checkpoint/runtime-source-allowlist.txt', 'deploy/openvino_gva/publication/runtime-source-allowlist.txt', 'deploy/savant/publication/runtime-source-allowlist.txt', 'deploy/deepstream/checkpoint/Dockerfile.runtime', 'deploy/openvino_gva/publication/Dockerfile', 'deploy/savant/publication/Dockerfile'],
          ['tests/test_checkpoint_deepstream_runtime_source_closure_v3.py', 'tests/test_checkpoint_openvino_gva_runtime_source_closure_v3.py', 'tests/test_checkpoint_savant_runtime_source_closure_v3.py', 'tests/test_runtime_build_context_v3.py'],
          ['sibling_packaging_original', 'sibling_scope', 'sibling_packaging_peer', 'selected_host_renewal_peer'],
          'Exact two reachable helpers are added to three sibling LF allowlists/COPY blocks. Original23 exact source-closure/COPY/negative tests pass with stable sources; actual inventory/native3/worker2 controls and finite rule preservation were reviewed. Subsequent selected renewal has its separate actual image receipt.',
          'Original sibling images are historical/ineligible, not rebuilt or rebound. Actual current selected image is e474, not the historical887 control named in the earlier scope receipt.')
recommend('20.5', ['scripts/ci_test_selection_v1.py', '.ci/integration-test-selection.v1.json'],
          ['tests/test_ci_test_selection_v1.py', 'tests/test_checkpoint_model_parity_materializer_v4.py', 'tests/test_publication_runtime_frozen_identity_constants_v1.py'],
          ['portable_fixture_author', 'portable_fixture_peer', 'ci_prerequisite_peer', 'sibling_packaging_peer', 'selected_host_renewal_peer'],
          'Finite metadata/temp-root/probe/forensic fixture repairs preserve original method IDs/decorators/assertion purposes. Original99 methods comprise96 successes and3 existing Windows skips, not99 successes; meaningful lexical import negatives remain detectable. Exact9 integration declarations and original80 skip rows remain,8 actual source-attested existing skips yield88; mandatory-test deferral is rejected. Selected-current tests bind genuinee474 receipt while oldg/full integration remains deferred/ineligible.',
          'The finite focused slice and selector safeguards do not prove complete current hosted/ext4 portable success or physical full-integration execution; existing unsupported integration obligations remain explicit.')

assert [r['task_id'] for r in recommendations] == ['18.2','18.3','18.4','18.5','18.6','18.7','19.2','19.3','20.2','20.3','20.4','20.5']
for row in recommendations:
    for path in row['source_paths'] + row['current_test_module_paths']:
        assert (ROOT / path).is_file(), path
recommendation = {
    'schema_version': 1, 'artifact_kind': 'vast_scoped_task_completion_recommendation_v1',
    'status': 'read_only_recommendation_not_task_mutation_or_final_conformance',
    'current_commit': EXPECTED_HEAD, 'task_source_points': mapping['task_source_points'],
    'source_docs': list(doc_pins.values()), 'evidence': evidence,
    'recommendations': recommendations, 'actual_hosted_plugin_entry_joins': plugin_entries,
    'pre_edit_chronology_evidence': {
        'original_direction_review_physically_equals_9ad_blob': evidence['pre_implementation_direction_peer'],
        'seam1_pre_edit_original_modules_exact_9ad_blobs': pre_edit_source_joins,
        'inventory_records_approval_pending': True,
        'inventory_itself_in_9ad_commit': False,
        'limit': 'Baseline identity is independently reproduced; pre-edit author dispatch order must be assessed by parent. No filesystem current timestamp or later implementation review is used as chronology proof.'},
    'actual_observer_message_semantics': {'requests_sent': 24, 'responses_started': 24,
                                         'responses_completed': 24, 'response_received_records': 51,
                                         '51_records_mean': 'raw control chunks plus ready/stop messages; not51 completed dumps'},
    'actual_cpu05_cold_observation': cpu['cold_pair']['reconciliation'],
    'historical_register_policy': mapping['scope_policy'],
    'must_remain_pending': ['18.8','18.9','18.10','18.11','18.12','18.13','18.14','19.4','19.5','20.6','20.7','21.4','21.5','22.2','22.3'],
    'separate_planning_only_task': '22.1 is already checked only in current working tasks38/65; committed5bc remains37/65.',
    'physical_final_gate_descriptor': None, 'accepted_hardware_descriptor': None,
    'publication_ready': False, 'full_ci_acceptance': False, 'measurement_acceptance': False,
    'scope_limits': ['No source/test/planning/task/index/HEAD edit or checkboxes changed.',
                     'No test execution, discovery, engine/model/namespace/native/hardware operation or workflow dispatch/read of active output.',
                     'Exact old source receipts remain historical; later actual repairs/packaged results/CPU05 evidence are explicitly supplementary.',
                     '18.7 closes original observed CPU05 preflight, never future relocated/GPU readiness.22.2 must acquire genuine new destination/resource facts.',
                     'Retained CPU05 cold/scientific truth cannot turn its late originalCLI78 into accepted18.8 or close four-arm18.10.',
                     'Checking implementation tasks leaves current full portable/final source/build/native evidence and four-arm acceptance mandatory.'],
}

assert git('rev-parse', 'HEAD').decode().strip() == EXPECTED_HEAD
assert {p: descriptor(p) for p in doc_paths} == doc_pins
assert descriptor(old_rel) == old_pin
mapping_pin = write_new('mapping.v4.json', mapping)
recommendation_pin = write_new('task-completion-recommendation.v1.json', recommendation)
summary = '\n'.join([
    'Provisional mapping at5bc416a2:20 requirements,112 exact scenarios; all109 previous clauses and82 historical-register classifications preserved.',
    'Working tasks38/65; committed5bc37/65. Only current22.1 planning-only completion differs. No task is edited by this review.',
    '',
    'Recommend checking implementation/local-validation tasks18.2–18.7,19.2–19.3,20.2–20.5 using the exact evidence in task-completion-recommendation.v1.json.',
    '18.7 covers genuine CPU05 preflight only; new ext4/GPU/current-volume readiness remains22.2.',
    '20.3 has actual8f six build successes, three mandatory native successes and loaded appsrc/queue/videoconvert1.24.2; overall8f is failed.',
    '',
    'CPU05 remains CLOSED FAILED:CLI78 after2125.861229s exceeded2100s. Authentic retained8371-request cold reconciliation and peer-reviewed raw scientific consistency do not close18.8.',
    'Finite portable99 methods =96 successes+3 existing Windows skips; journalctl parser16 successes prove --dmesg/--help parsing only.',
    'CI36764814739 is active as reported by owner. Genuine ext4 setup/new closure/daemon binds/CPU and GPU acceptance, all-four-arm reduction, complete current hosted/ext4 portable conformance/archive remain pending.',
    'Every per-scenario final evidence/gate join and final accepted hardware descriptor remains null. No execution/Git/source/planning mutation.',
    '',
])
with (OUT / 'task-completion-recommendation.v1.md').open('xb') as f:
    f.write(summary.encode())
ledger = {
    'schema_version': 1, 'artifact_kind': 'vast_mapping_v4_preparation_ledger_v1',
    'source_commit_before_after': EXPECTED_HEAD, 'input_document_descriptors_before_after_equal': list(doc_pins.values()),
    'preserved_previous_mapping': old_pin, 'source_point_distinction': mapping['task_source_points'],
    'output_descriptors': [mapping_pin, recommendation_pin, descriptor((OUT/'task-completion-recommendation.v1.md').relative_to(ROOT).as_posix())],
    'static_ast_modules_read': len(ast_cache), 'scenario_scope_counts': mapping['scope_counts'],
    'earlier109_clauses_exact': True, '82_register_rows_exact_name_and_scope': True,
    'new_three_physical_gates_pending': True, 'tests_or_engine_or_hardware_or_git_mutation': False,
    'preparation_failed_attempts': [
        {'original_tool_exit_code': 1, 'failure': 'Task parser omitted existing nested ID10.8.1; task-count assertion stopped before any output writes. Only the metadata parser was corrected; no task content or selection changed.'},
        {'original_tool_exit_code': 1, 'failure': 'Artifact reader Git-output256KiB guard rejected genuine293953B original sidecar baseline; no output writes. Finite source-read cap adjusted to1MiB; no producer, source or authority budget changed.'}],
    'authoring_script': descriptor((OUT/'prepare_mapping_v4.py').relative_to(ROOT).as_posix()),
}
ledger_pin = write_new('mapping.v4-preparation-ledger.v1.json', ledger)
print(json.dumps({'mapping': mapping_pin, 'recommendations': recommendation_pin, 'ledger': ledger_pin,
                  'scenario_scopes': mapping['scope_counts'], 'tasks_working': 38, 'tasks_committed': 37}, sort_keys=True))
