"""Close the original CI diagnosis without upgrading historical outcomes."""
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

unit = json.loads((BASE / 'original-member-copies-v1/unittest-child.report.json.original.raw').read_bytes())
facts = json.loads((BASE / 'original-facts.v1.json').read_bytes())
log = (BASE / 'original-member-copies-v1/unittest.original.log.original.raw').read_text()
events = [json.loads(line) for line in log.splitlines() if line.startswith('{') and line.endswith('}')]
ids = ('test_backend_publication_output_transaction_v3.BackendPublicationOutputTransactionV3Tests.test_two_coordinators_spawn_at_most_once',
       'test_publication_operational_process_custody_v1.ProcessCustodyTests.test_caught_invalid_phase_remains_sticky_and_call_capacity_is_bounded')
required = ['test_checkpoint_analytics_execution_client_cpp.CheckpointAnalyticsExecutionClientCppTest.' + name
    for name in ('test_native_client_regression', 'test_native_policy_topology_regression', 'test_native_reset_queue_level_regression')]
assert all(name in unit['successful_test_ids'] for name in required)
assert len(unit['failures']) == 2 and not unit['errors'] and len(unit['skips']) == 88
assert len(unit['discovered_ids']) == 2969 and unit['tests_run'] == 2960
before = pin(BASE / 'original-member-copies-v1/tracked-source.before.json.original.raw')
after = pin(BASE / 'original-member-copies-v1/tracked-source.after.json.original.raw')
assert before['sha256'] == after['sha256']
source = pin(ROOT / 'scripts/backend_publication_process_supervisor_v3.py')
capacity = json.loads((BASE / 'capacity-fixture-repair-v1/author-review.v1.json').read_bytes())
value = {'schema_version': 1, 'artifact_kind': 'vast_original_4cb_two_failure_diagnosis_v1',
    'accepted': False, 'status': 'original_failure_retained_scoped_repairs_pending_independent_review_and_current_checks',
    'original': {'run_id': 36783010512, 'job_id': 110117643414,
        'commit': '4cb9d8313cca71256179bc3b59cc6f9137e7b8ba', 'zip': facts['original_zip'],
        'discovered': 2969, 'portable_selected': 2960, 'declared_integrations_unexecuted': 9,
        'successful_tests': len(unit['successful_test_ids']), 'failures': unit['failures'], 'errors': 0,
        'skips': 88, 'full_job_elapsed_s': facts['original_full_elapsed_s'], 'successful': False,
        'six_native_builds': facts['original_native_build'], 'required_native_ids_successful': required,
        'original_profile_observation': unit['profile_observation'],
        'profile_load_unload': facts['original_profile'], 'source_before': before, 'source_after': after,
        'exact_failure_events': [row for row in events if row.get('test_id') in ids]},
    'diagnosis': [
        {'id': ids[0], 'proven_original': 'Both outcomes were errors: foreign immutable broker owner mismatch and POSIX broker process failed; exactly-one-result assertion failed.',
         'proven_source_defect': 'A validated request journal was passed to early terminal emission even when this candidate failed immutable owner commit. A losing candidate could write into the elected owner journal.',
         'deterministic_proof': 'Both genuine pipe-gated normal/held owner-collision tests failed before source fix because the losing candidate created terminal intent. After private owner-only journal promotion, the same tests pass and the winner alone emits response.',
         'unknown': 'The archived failure does not retain the exact racing child journal messages or prove the precise hosted timing. Fixture five-second release timing is not itself a demonstrated cause.',
         'repair': 'Only after successful immutable owner commit promote local terminal_journal; early failure writes durable terminal only through that private promoted reference. No startup lock/schema/timeout/namespace/parent cleanup changes.',
         'source': source, 'host87': True, 'selected73': False, 'finite2693': True,
         'all9_allowlist_membership': [], 'review': pin(BROKER / 'author-review.v1.json'),
         'latest_test_supplement': pin(BROKER / 'author-review.v2.supplement.json')},
        {'id': ids[1], 'proven_original': 'Receipt call_count was11 rather than32; generic expected ValueError scope hid the first error.',
         'local_original_reproduction': 'The unchanged original ID passed once locally with32 calls and intended33rd capacity refusal; observation wrappers always forwarded real validators.',
         'controlled_facts': 'A deliberately reaped genuine child is refused with FileNotFoundError. A genuine child held at READY registers before release and passes actual cold process validation. A child failing before READY cannot register. Unreaped zombie semantics remain supported.',
         'unknown': 'Original hosted first swallowed ValueError remains unavailable; controlled reaped error is not that error and does not establish original hosted causality.',
         'repair': 'A capacity-only real pipe/stdin gate keeps that fixture child alive until actual registration, then releases it. Exact33rd capacity error is asserted. Original process()/run_child() and all other original methods are AST-identical.',
         'source': capacity['test'], 'host87': False, 'selected73': False, 'finite2693': False,
         'unchanged_production': capacity['unchanged_production_process_helper'],
         'review': pin(BASE / 'capacity-fixture-repair-v1/author-review.v1.json')}],
    'future_requirements': ['Independent final source review and root exact source commit before new current CI.',
        'Supervisor is in host87: renew genuine current host closure and current CPU/GPU acceptance after root source checkpoint; preserve original0ad accepted pairs, no authority rebind.',
        'No image rebuild follows solely from this supervisor/test-only change; actual selected73/native3/worker2 scope proof must remain current.',
        'Current independent CI checkout is prepared only; stock CI invocation count remains0 and the original hosted failure remains failed.'],
    'limits': ['No production process-helper or transaction edit, profile/policy operation, model/engine/native workload, full CI launch, benchmark dispatch or Git mutation by this diagnosis.',
               'Focused broker12 plus corrected-helper2 and capacity6 are scoped units, not green full CI or hardware acceptance.'],
    'author_observation_failures': [{'tool_chunk': 'c99458', 'scope': 'Read-only metadata command printed an unintentionally nested report then failed a missing top-level key; no source/output authority change.'},
        {'tool_chunk': '932ac4', 'scope': 'Read-only compact field inspection assumed list was dict; source/receipt unchanged.'},
        {'path': str(BASE / 'capacity-fixture-focused-attempt01/prelaunch-failure.v1.json'), 'scope': 'Collector Git metadata prelaunch failure before any unit child. Corrected collector and new namespace are separate.'}]}
path = BASE / 'diagnosis.v1.json'
with path.open('xb') as output:
    output.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    output.flush()
    os.fsync(output.fileno())
print(json.dumps({'diagnosis': pin(path), 'broker_source': source,
                  'broker_test': pin(ROOT / 'tests/test_backend_publication_broker_terminal_v3.py'),
                  'capacity_test': capacity['test']}))
