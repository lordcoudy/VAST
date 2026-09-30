"""Close finite author evidence; no namespace, engine or test execution."""
from pathlib import Path
import hashlib
import json
import os
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
def pin(path):
    raw = path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(), 'size_bytes':len(raw),
            'sha256':hashlib.sha256(raw).hexdigest()}

terminal_path = HERE/'final-green-03/terminal.json'
terminal = json.loads(terminal_path.read_bytes())
assert terminal['returncode'] == 0 and not terminal['timed_out']
assert terminal['source_before'] == terminal['source_after']
assert b'Ran 27 tests' in (HERE/'final-green-03/stderr.raw').read_bytes()
assert (HERE/'final-green-03/stderr.raw').read_bytes().rstrip().endswith(b'OK')
for name, descriptor in terminal['source_after'].items():
    actual = pin(ROOT/name)
    assert {k:actual[k] for k in ('size_bytes','sha256')} == descriptor
for name, descriptor in terminal['outputs'].items():
    actual = pin(HERE/'final-green-03'/name)
    assert {k:actual[k] for k in ('size_bytes','sha256')} == descriptor
pid = terminal['pid']
groups = []
for path in Path('/proc').iterdir():
    if not path.name.isdigit(): continue
    try:
        fields = (path/'stat').read_text().rsplit(')',1)[1].split()
        if int(fields[2]) == pid: groups.append(int(path.name))
    except (OSError,ValueError,IndexError): pass
assert not Path(f'/proc/{pid}').exists() and not groups
scope_path = HERE/'source-scope.v1.json'
scope = json.loads(scope_path.read_bytes())
assert scope['host_count'] == 87 and scope['selected_count'] == 73
assert not scope['owned_host_intersection'] and not scope['owned_selected_intersection']
owned = ['scripts/run_ci_checks.py','.github/workflows/ci.yml','tests/test_run_ci_checks.py',
         'scripts/ci_namespace_diagnostic_v1.py','tests/test_ci_namespace_diagnostic_v1.py']
value = {
 'schema_version':1, 'artifact_kind':'vast_decision25_ci_prerequisites_author_review_v1',
 'reviewable':True, 'independent_review':False,
 'change':'fix-benchmark-preparations-spec',
 'approved_planning_commit':'bec47b794ef9183fe9e3ce4cb1ec15541070f96f',
 'planning_pr_comments':['5911169971','5911177634'],
 'owned_sources':[pin(ROOT/path) for path in owned],
 'dependencies':[pin(ROOT/path) for path in terminal['source_after'] if path not in owned],
 'pre_edit_inventory':pin(HERE/'pre-edit.v1.json'),
 'original_final_test':{**pin(terminal_path),'count':27,'interpreter':'original CPython3.12.3 -I -B',
     'returncode':terminal['returncode'],'elapsed_s':terminal['elapsed_s'],
     'original_pid':pid,'actual_current_pid_absent':True,'actual_current_group_members':groups,
     'raw_channels':[pin(HERE/'final-green-03'/n) for n in ('stdout.raw','stderr.raw')]},
 'retained_meaningful_red_receipts':[pin(HERE/path/'terminal.json') for path in
      ['red-02','namespace-close-red-01','discovery-inventory-red-01','descendant-cleanup-red-01']],
 'behavior':[
    'Canonical original CPython3.12.3 argv without changing sys.executable; fixed ROOT isolated imports and containment before/after complete original-ID discovery/run.',
    'Root-owned selection API retains default discovered IDs on failure and explicit portable/integration/skip dispositions; required native criteria stay strict.',
    'Ephemeral plugins-base/tools installation; original loaded appsrc/queue/videoconvert stdout/status and bounded physical plugin hashes; six original CPU targets retained.',
    'One actual stock namespace call prepared behind original owner/pidfd start gate; bounded first instrumented syscall/type/errno/flags/path/PID/label/time and original channels.',
    'Immutable 20s execution plus 10s-or-remaining cleanup includes reap, EOF/group checks and evidence close; pidfd failure, overflow, write/close failure, retained descendants and late closure stay failed.',
    'At most one optional noninteractive read-only sudo journalctl query in the same remaining cleanup interval; exact original PID userns record filter, explicit unavailable facts, no policy mutation or automatic causal claim.'
 ],
 'budgets':{'execution_s':20,'cleanup_s_max':10,'namespace_channel_total_bytes':40960,
     'kernel_query_channel_total_bytes':40960,'per_capture_metadata_bytes_max':16384,
     'direct_kernel_consumed_bytes_max':8192,'relevant_denial_leaf_bytes_max':8192,
     'kernel_acquisition_plus_relevant_bytes_max':57344,
     'supplemental_namespace_bytes_conservative_max':122880},
 'scope_proof':{**pin(scope_path),'host_count':87,'selected_count':73,
     'owned_intersections_empty':True,
     'note':'The source proof preceded one comment-only diagnostic edit. Final 27-test receipt pins the final source; stock membership and code behavior are unaffected.'},
 'self_review':[
    'First observed syscall can only be claimed for the declared unshare/proc-map/mount/pipe/fork wrappers. Other stock preconditions and prctl failures remain original generic failures; no fabricated syscall attribution.',
    'Tool metadata fixtures prove parsing/refusal; they do not prove hosted factory availability or native runtime success.',
    'Kernel log unavailability and generic errno never authorize a profile. Retained records require later independent PID/executable/label/window analysis.',
    'The final fixture kernel query test was added after query preparation; it is not represented as an earlier RED. Existing behavioral regressions preserve actual preceding RED evidence.',
    'No original namespace, sudo query, Docker/model/native workload, full suite or hosted job was launched by this implementation turn. Tasks20.3 and19.4 retain actual-host verification obligations.'
 ],
 'preserved_constraints':{'single_full_test_child':True,'full_job_minutes':90,
     'production_budgets_ms':[600000,615000],'production_namespace_source_changed':False,
     'watchdog_in_test_child_added':False,'policy_profile_loaded':False,
     'tests_skipped_by_author':False,'hardware_acceptance':False,'full_ci_success_claimed':False},
 'closed_at_monotonic_ns':time.monotonic_ns()
}
out = HERE/'author-review.v1.json'
with out.open('xb') as stream:
    stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
    stream.flush();os.fsync(stream.fileno())
print(json.dumps(pin(out)))
