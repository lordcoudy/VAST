"""Finite read-only Decision27 document/inventory review; no project imports."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = Path(__file__).parent
ART = ROOT / 'artifacts/benchmark_recovery_20260930'
SNAP = ART / 'decision27-planning-originals-v1'
FEAS = ART / 'component-ext4-relocation-feasibility-v1'

def ref(path):
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def original_json(path):
    return json.loads(path.read_bytes())

def save(name, value):
    with (OUT / name).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
    return ref(OUT / name)

rows = original_json(SNAP / 'inventory.json')
docs = []
for row in rows:
    before = SNAP / row['original_file']
    after = ROOT / row['path']
    old, new = before.read_bytes(), after.read_bytes()
    assert ref(before)['size_bytes'] == row['size_bytes'] and ref(before)['sha256'] == row['sha256']
    assert new.startswith(old), row['path']
    docs.append({'before': ref(before), 'after': ref(after), 'original_bytes_preserved_as_prefix': True})
    if row['path'].endswith(('proposal.md', 'design.md', 'verification-plan.md', 'BENCHMARK_RECOVERY_PLAN.md')):
        added = new[len(old):]
        assert b'2693' in added and b'4,379,009,017' in added and b'180' in added
        assert b'189' in added and b'2504' in added

spec_row = next(row for row in rows if row['path'].endswith('/spec.md'))
task_row = next(row for row in rows if row['path'].endswith('/tasks.md'))
def spec_counts(raw):
    return {'requirements': len(re.findall(rb'^### Requirement:', raw, re.M)), 'scenarios': len(re.findall(rb'^#### Scenario:', raw, re.M))}
def task_lines(raw):
    return re.findall(rb'^- \[([x ])\] (.+)$', raw, re.M)
old_spec = (SNAP / spec_row['original_file']).read_bytes()
new_spec = (ROOT / spec_row['path']).read_bytes()
old_tasks = task_lines((SNAP / task_row['original_file']).read_bytes())
new_tasks = task_lines((ROOT / task_row['path']).read_bytes())
assert spec_counts(old_spec) == {'requirements': 19, 'scenarios': 109}
assert spec_counts(new_spec) == {'requirements': 20, 'scenarios': 112}
assert len(old_tasks) == 62 and len(new_tasks) == 65 and new_tasks[:62] == old_tasks
assert sum(s == b'x' for s, _ in old_tasks) == sum(s == b'x' for s, _ in new_tasks) == 37
assert all(s == b' ' and text.startswith(b'22.') for s, text in new_tasks[62:])

expected = {
    'inventory.v1.json': ('8a03751c4f3e18a2590d04874496559cc77dab7ffebc8184269c0b9bb81dc364', 2087679),
    'git-input-classification.v1.json': ('ed2858413c0dca784f05bff2ca4551b0d6f7879baf6624d07a54c1227a320e3c', 469891),
    'review.v1.json': ('08f057794b0a4033d4b52853bbc0420e7d4cb6674b4a6fa03779e4f515b4f58e', 12127),
}
refs = {}
for name, (digest, size) in expected.items():
    refs[name] = ref(FEAS / name)
    assert refs[name]['sha256'] == digest and refs[name]['size_bytes'] == size
inventory = original_json(FEAS / 'inventory.v1.json')
classification = original_json(FEAS / 'git-input-classification.v1.json')
feasibility = original_json(FEAS / 'review.v1.json')
inputs = {row['path']: row for row in inventory['copy_inputs']}
assert len(inputs) == len(inventory['copy_inputs']) == inventory['copy_input_leaf_count'] == 2693
assert sum(row['size_bytes'] for row in inputs.values()) == inventory['copy_input_size_bytes'] == 4379009017
assert inventory['descriptor_conflicts'] == [] and classification['tracked_descriptor_differences'] == []
tracked = {row['path']: row for row in classification['tracked_inputs']}
untracked = set(classification['untracked_inputs'])
assert len(tracked) == classification['tracked_input_count'] == 189
assert len(untracked) == classification['untracked_input_count'] == 2504
assert set(tracked).isdisjoint(untracked) and set(tracked) | untracked == set(inputs)
assert sum(inputs[path]['size_bytes'] for path in tracked) == classification['tracked_bytes'] == 67707574
assert sum(inputs[path]['size_bytes'] for path in untracked) == classification['untracked_declared_bytes'] == 4311301443
comparison = inventory['current_commit_source_comparison']
assert comparison['count'] == len(comparison['records']) == 180
assert comparison['different'] == comparison['missing'] == [] and comparison['git_returncode'] == 0
assert sum(row['size_bytes'] for row in comparison['records']) == comparison['size_bytes'] == 67504578
assert inventory['source_commit'] == classification['source_commit'] == feasibility['source_commit'] == '8fefa4ba0c5b135c66f85a6eb7f4fd1aaebfdc21'
assert {key: len(value) for key, value in inventory['model_namespace'].items()} == {'.bin': 8, '.engine': 4, '.onnx': 4, '.plan': 0, '.xml': 8}
assert feasibility['daemon_reachability']['finding'].startswith('Original completed CPU05')
assert feasibility['accepted'] is False and feasibility['publication_ready'] is False

static = save('static-prefix-audit.v2.json', {
    'schema_version': 1, 'artifact_kind': 'vast_decision27_planning_preservation_audit_v2',
    'six_documents': docs, 'original_counts': {**spec_counts(old_spec), 'tasks': 62, 'checked': 37},
    'current_counts': {**spec_counts(new_spec), 'tasks': 65, 'checked': 37},
    'all_original_task_ID_text_state_lines_preserved': True, 'three_new_22_tasks_unchecked': True,
    'legacy_register_scope': 'Original six document bytes including unchanged original82-scenario/72-task register references remain exact prefixes; no campaign obligation or state is replaced.',
    'scope': 'Pure document/closed JSON reads and finite arithmetic. No source, model, engine, copy, setup, workload or test execution.',
})
result = {
    'schema_version': 1, 'artifact_kind': 'vast_decision27_independent_planning_review_v1',
    'disposition': 'approved_planning_only', 'reviewable': True, 'accepted': False, 'publication_ready': False,
    'change': 'fix-benchmark-preparations-spec', 'source_basis_commit': inventory['source_commit'],
    'six_reviewed_documents': [row['after'] for row in docs], 'preservation_audit': static,
    'original_snapshot_inventory': ref(SNAP / 'inventory.json'), 'closed_feasibility': refs,
    'independently_recomputed_inventory': {
        'leaves': 2693, 'declared_bytes': 4379009017, 'source_dependency_controller_leaves': 180,
        'source_dependency_controller_bytes': 67504578, 'tracked_identical_leaves': 189,
        'tracked_bytes': 67707574, 'exclusive_untracked_leaves': 2504, 'exclusive_untracked_bytes': 4311301443,
        'no_descriptor_or_tracked_byte_conflicts': True, 'terminal_model_count': 24,
    },
    'findings': [
        'Existing project_root and strict project-relative descriptor APIs permit genuine relocation without a production API delta. Historical transaction stable_stat stays sealed history; physical readers freshly verify relocated names, bytes and epochs.',
        'Original19 requirements/109 scenarios/62 tasks and37 checked states remain byte-exact prefixes. One requirement, three scenarios and three unchecked22.x tasks are appended; preserved legacy82/72 campaign obligations remain unexecuted.',
        'CPU05 original late CLI78 after2125.861229s remains failed despite authentic cold/CSV output. Independent95 custody release is retained;18.8 and21.4 are not completed by setup or relocation.',
        'New stock87-source/interpreter closure and newly produced selected/capture/preprocessing/runtime/guardian/arm/cold authority are mandatory. No oldv6 epoch or CPU05 execution receipt is rebound.',
        'Setup600/10 and stock capture120/10 are preparation-only. Original2100/2250/15 and fixed6stream/4branch/seed100ms/30-180-10 experiment, source/image/model/device/full cold/CI/campaign predicates remain unchanged.',
        'Original daemon access to /tmp does not prove future /home bind reachability. Actual destination root/UID/ext4/space/byte closure and a bounded genuine bind check remain setup gates; no daemon facts are inferred by this review.',
        'The shared Git clone is an explicit retained-object dependency with isolated HEAD/index. It is not a model hardlink or source validation shortcut; retained same-PR source ancestry must not be pruned.',
    ],
    'source_anchors': [
        'scripts/checkpoint_model_parity_acceptance.py:403-450 (historical source_inventory seal versus fresh descriptor registry)',
        'scripts/checkpoint_model_parity_v4.py:138-224 (canonical physical root, strict relative descriptors and current verification)',
        'scripts/checkpoint_model_parity_acceptance_v4.py:545-598 (unchanged full transaction/numeric assessment and accepted binding)',
        'scripts/publication_gstreamer_component_inputs_v1.py:_proof_inputs (full original accepted binding and current recipe inputs)',
        'https://git-scm.com/docs/git-clone (shared alternates and source object dependency)',
    ],
    'limitations': [
        'Reviewed metadata inventories and recorded180 actual raw Git comparisons; this reviewer did not freshly stream4.38GB media/numeric bytes. Their declared hashes/current size/epoch are provisional until genuine setup transfer/rechecks.',
        'No destination created, copy/clone/helper/capture executed, image/model/daemon queried, native/GPU/workload or behavior test launched by this review.',
        'No ext4 speedup, storage causal attribution, current model/image grant, green CI, accepted pair, archive or merge approval follows from this planning review.',
        'Future artifact-only setup/controller implementations and exact final source/closure binding need their own review before original one-shot CPU then separately authorized GPU dispatch.',
    ],
    'blockers': [], 'workloads_started_by_reviewer': [],
}
print(json.dumps(save('review.v1.json', result), sort_keys=True))
