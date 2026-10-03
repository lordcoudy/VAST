"""Close only the two implemented/tested/independently reviewed repair tasks."""
from pathlib import Path
import hashlib, json, os

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
PEER = ROOT / 'artifacts/benchmark_recovery_20260930/decision28-source-independent-review-v2/review.v2.json'
CORRECTION = PEER.with_name('count-correction.v1.json')
peer_raw, correction_raw = PEER.read_bytes(), CORRECTION.read_bytes()
assert hashlib.sha256(peer_raw).hexdigest() == '7de1386fc628424e90af3cbc21aea5ecdf6e433e9f9e594a86f9f83bf1c4e662'
assert hashlib.sha256(correction_raw).hexdigest() == 'fb038ad8bba5b92346f377c635c4f6a7a61522a98746df7a2e57ca643ad37343'
peer, correction = json.loads(peer_raw), json.loads(correction_raw)
for review in (peer, correction):
    assert review['reviewable'] and not review['blocking_findings'] and review['reviewer_handles_released']
    assert review['baseline_commit'] == '958a036bc5a55821c712204577fdf4c51c2181c7'
    for pin in review['owned_source_pins']:
        b = (ROOT/pin['path']).read_bytes()
        assert len(b) == pin['size_bytes'] and hashlib.sha256(b).hexdigest() == pin['sha256']
assert correction['focused_original_sidecar_plus_termination_methods'] == 53
assert correction['original_native_methods'] == 21
tasks = ROOT / 'openspec/changes/fix-benchmark-preparations-spec/tasks.md'
before = tasks.read_bytes()
assert len(before) == 32821 and hashlib.sha256(before).hexdigest() == '3eb2dc17f30b24fa0be14ef77fdf8ca46d00c75d19a9160754f98b58e7211a26'
assert before.count(b'- [x] ') == 57 and before.count(b'- [ ] ') == 13
annotations = {
    b'23.2': b' Actual meaningful original RED9/7failures2errors55c886d4 and finalGREEN62/0errors75f8e96e, all53 old assertions unchanged; authora71d828c and independent7de1386f with explicit unchanged legacy-test137 count addendumfb038ad8 close this behavior. Real shared-offset, snapshot/unknown/observer refusal and first-route/front-send/invocation checks pass; image/current95/hardware/CI/final gates remain pending.',
    b'23.3': b' Actual originalRED6/1failure5errorsee23937f and finalGREEN27/0errors9dae8853, all21 old assertions/constants/terminal/receipt/publicvalidators unchanged; author9356d0f8 and independent7de1386f/fb038ad8 close this behavior. Genuine binary/empty/nonzero/timeout and exclusive collisions/persistence tests pass; overflow/drain flags are explicitly wrapper fixtures. No hardware or final acceptance is implied.'}
lines = before.splitlines(keepends=True)
for task, annotation in annotations.items():
    indexes = [i for i,line in enumerate(lines) if line.startswith(b'- [ ] '+task+b' ')]
    assert len(indexes) == 1
    i = indexes[0]; line = lines[i]
    assert line.endswith(b'\n') and not line.endswith(b'\r\n')
    lines[i] = line.replace(b'- [ ] ', b'- [x] ', 1)[:-1] + annotation + b'\n'
after = b''.join(lines)
assert after.count(b'- [x] ') == 59 and after.count(b'- [ ] ') == 11
with (HERE/'tasks-before-repair-completion.raw').open('xb') as f:
    f.write(before); f.flush(); os.fsync(f.fileno())
with tasks.open('wb') as f:
    f.write(after); f.flush(); os.fsync(f.fileno())
plan = ROOT/'BENCHMARK_RECOVERY_PLAN.md'
plan_before = plan.read_bytes()
assert hashlib.sha256(plan_before).hexdigest() == peer['current_recovery_plan']['sha256']
old = b'Implementation progress57/70: only planning task23.1 is newly closed.'
new = b'Implementation progress59/70: planning23.1 and both fully tested, independently reviewed repair behaviors23.2/23.3 are closed; renewal/current-result/final gates remain pending.'
assert plan_before.count(old) == 1
plan_after = plan_before.replace(old,new)
with plan.open('wb') as f:
    f.write(plan_after); f.flush(); os.fsync(f.fileno())
receipt = {'artifact_kind':'decision28_two_repair_task_completion_v1', 'schema_version':1,
    'review_sha256':hashlib.sha256(peer_raw).hexdigest(), 'count_correction_sha256':hashlib.sha256(correction_raw).hexdigest(),
    'only_newly_closed_tasks':['23.2','23.3'], 'completed':59,'total':70,
    'previous_tasks':{'size_bytes':len(before),'sha256':hashlib.sha256(before).hexdigest()},
    'current_tasks':{'size_bytes':len(after),'sha256':hashlib.sha256(after).hexdigest()},
    'current_plan':{'size_bytes':len(plan_after),'sha256':hashlib.sha256(plan_after).hexdigest()},
    'source_or_test_bytes_changed':False, 'benchmark_or_final_acceptance':False}
raw = (json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
with (HERE/'two-repair-task-completion.v1.json').open('xb') as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
print(json.dumps(receipt))
