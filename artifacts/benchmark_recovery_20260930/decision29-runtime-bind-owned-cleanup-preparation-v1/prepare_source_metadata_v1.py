"""Metadata author only: read/AST/diff; never import or run the cleanup target."""
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ACCEPTED = BASE / 'decision29-runtime-bind-prerequisite-capture-preparation-v1/capture_stock_runtime_bind_v2.py'
CURRENT = HERE / 'capture_owned_runtime_bind_cleanup_v1.py'


def descriptor(path):
    data = path.read_bytes()
    return {'path': str(path), 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write(name, data):
    with (HERE / name).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return descriptor(HERE / name)


def publish(name, value):
    return write(name, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())


old = ACCEPTED.read_bytes()
new = CURRENT.read_bytes()
assert len(old) == 20895 and hashlib.sha256(old).hexdigest() == 'aa0beeff2f3d6057cd2e5f99bebd311845db0a162757bf5590b39ba6b5d79dff'
old_tree, new_tree = ast.parse(old), ast.parse(new)
functions = lambda tree: {node.name: ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
old_functions, new_functions = functions(old_tree), functions(new_tree)
same = sorted(name for name in old_functions.keys() & new_functions.keys() if old_functions[name] == new_functions[name])
popen = [node for node in ast.walk(new_tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess' and node.func.attr == 'Popen']
assert len(popen) == 1 and isinstance(popen[0].args[0], ast.Name) and popen[0].args[0].id == 'ARGV'
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('rmdir', 'unlink', 'remove', 'rmtree', 'rename', 'replace') for node in ast.walk(new_tree))
assert not (HERE / 'original-owned-cleanup-attempt01').exists()
assert not (HERE / 'consumer-closure.bound.v1.json').exists()
before_ref = write('accepted-bind-capture.before.raw', old)
diff_ref = write('complete-source.delta.v1.patch', ''.join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile=ACCEPTED.name, tofile=CURRENT.name)).encode())
source_ref = descriptor(CURRENT)
linux_here = '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/' + HERE.name
binding = {
    'schema_version': 1,
    'kind': 'original_owned_runtime_bind_cleanup_gate_v1',
    'source_commit_D': '3c025b29b3c1d5275c2ec693410e4b83700583de',
    'reviewed_capture_sha256': source_ref['sha256'],
    'cleanup_authorized': None,
    'all_D_consumers_closed': None,
    'no_new_D_consumers_since_closure': None,
    'underlying_target_directory_pre_mount_identity': None,
    'delete_directories': False,
    'umount_executable': None,
    'full_ci': {'dispatch': None, 'terminal': None, 'result_review': None, 'process_closure': None},
    'conformance': {'terminal': None, 'independent_review': None, 'process_closure': None},
    'additional_D_consumer_closures': None,
    'all_closed_consumer_owners': None,
}
binding_ref = publish('consumer-closure.pending.v1.json', binding)
creator_root = BASE / 'decision29-runtime-bind-prerequisite-capture-preparation-v1/original-bind-attempt01'
creator_ref = descriptor(creator_root / 'execution.v1.json')
closure_ref = descriptor(creator_root / 'root-original-closure.v1.json')
assert (creator_ref['size_bytes'], creator_ref['sha256']) == (19078, '829110b9b75faf53fcce812d188fe318540422c1c7d12acd2019257b6aaa9dea')
assert (closure_ref['size_bytes'], closure_ref['sha256']) == (5037, '3cf93ba8891604fdaddb2689ed3400ab5ce4ae50a8c6eac723466bff6815275b')
proof = json.loads((creator_root / 'execution.v1.json').read_bytes())
closure = json.loads((creator_root / 'root-original-closure.v1.json').read_bytes())
assert proof['mount_after']['rows'] == closure['actual_source_and_target_rows']
assert [row['mount_id'] for row in proof['mount_after']['rows']] == [331, 2708]
report = {
    'schema_version': 1,
    'prepared_only': True,
    'target_execution_performed': False,
    'cleanup_granted_by_preparation': False,
    'acceptance_claim': False,
    'source': source_ref,
    'metadata_author': descriptor(Path(__file__)),
    'accepted_capture_original': descriptor(ACCEPTED),
    'preserved_accepted_source': before_ref,
    'complete_source_diff': diff_ref,
    'pending_binding': binding_ref,
    'creator_execution': creator_ref,
    'creator_root_closure': closure_ref,
    'actual_creator_mount_rows': proof['mount_after']['rows'],
    'actual_creator_boot_and_namespace': {'boot_id': proof['mount_after']['boot_id'], 'namespace': proof['mount_after']['namespace'], 'namespace_stat7': proof['mount_after']['namespace_stat']},
    'canonical_interpreter_original': proof['mount_after']['target_python'],
    'scope': 'ONE exact owned-mount unmount after all D consumer/full-CI/conformance originals and owner closures genuinely close. No target dispatch now.',
    'sole_subprocess_argv': ['/usr/bin/umount', '--', '/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D/.publication-runtime/full-publication-cp312-v1'],
    'capture_runtime_args': ['BOUND_CLOSURE_SIZE', 'BOUND_CLOSURE_SHA256', source_ref['sha256']],
    'future_external_argv': ['/usr/bin/timeout', '--verbose', '--signal=TERM', '--kill-after=10s', '30s', '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python', '-I', '-B', linux_here + '/capture_owned_runtime_bind_cleanup_v1.py', 'BOUND_CLOSURE_SIZE', 'BOUND_CLOSURE_SHA256', source_ref['sha256']],
    'future_external_owner_uid_gid': [0, 0],
    'future_root_review_and_one_grant_required': True,
    'absolute_bounds_s': {'work': 30, 'whole_and_cleanup': 40, 'external_TERM': 30, 'external_KILL_after': 10},
    'byte_bounds': {'each_stdout_stderr': 65536, 'each_mountinfo': 4194304, 'each_control': 4194304, 'all_control_bytes': 33554432, 'canonical_python_exact': 8020928, 'umount_executable_max': 4194304},
    'actual_AST_checks': {'parse': True, 'exact_unchanged_primitives': same, 'old_functions': sorted(old_functions), 'new_functions': sorted(new_functions), 'one_fixed_Popen_only': True, 'no_directory_or_payload_deletion_calls': True},
    'inverse_claim': 'No whole-source literal inverse claim. Complete explicit capture adaptation replaces two stock setup commands with one exact umount and new closed-consumer/mount/FD gates.',
    'future_binding_requirements': [
        'Create a NEW concrete consumer-closure.bound.v1.json and exact size/SHA after all D consumers, full CI and conformance have genuinely closed; preserve this pending template.',
        'Root independently reviews concrete binding and exact source, records one grant, and ensures no new D consumers start between closure and unmount.',
        'Pin actual root-owned /usr/bin/umount regular executable with current full SHA/size/seven epochs; template carries no invented executable facts.',
        'Full-CI dispatch and terminal must be original prerequisite-output paths; result reader must have verified complete original evidence, actual FD release/balance, and SUCCESS or FAILED disposition retained honestly.',
        'Pin actual conformance generator terminal, independent review, and process closure; generator terminal must report all FD closes. Metadata generation itself is not conformance/release acceptance.',
        'Supply all original D consumer birth owners as seven-field identity dictionaries derived from held dispatch/terminal/closure metadata; include all original CI controller, stock child and observer owners plus other original reviewers/consumers.',
        'Two current error-free PID/group/session absence scans must pass before the sole command; unknown ownership or a reused PID refuses execution.',
        'Independent root postterminal observation must close this capture and its actual timeout parent as well as verify late companion absence. The live helper never claims its own process absent.',
    ],
    'code_path_checks': [
        'Original mount2708/source331, parent80/device8:48/ext4/read-only/raw rows, boot and full mount namespace identity are joined to exact original creator proofs before mutation.',
        'Canonical Python keeps its actual original full SHA and seven epochs before/after. Global source331 row and source-directory epoch remain exact.',
        'Temporary target/bin/python and all target-side ancestor/leaf FDs close independently before Popen; persistent holds explicitly reject any path below target.',
        'Only fixed umount argv; no force/lazy/recursive flags, root source unmount, remount, rmdir/delete, model/native/engine or test/CI invocation.',
        'Quick actual child zombie may expose empty cmdline; actual unreaped PID/stat/status identity and intended argv remain distinct. No executable observation fabricated.',
        'Real exit, reap, both EOFs, bounded raw channel full stored hashes/epochs, two error-free owned-group scans and independent retirement/FD balance are mandatory.',
        'First error remains latched; partial stored raw digest is not labeled complete. Command failure can retain post-mount facts but never pass cleanup.',
        'Receipt is exclusive, after independent FD retirements; final40s post-save/post-flush check publishes sticky failure companion/nonzero without rewriting original execution.',
    ],
    'limitations': [
        'Underlying target-directory identity before mount was never recorded. No old inode/epoch is invented or compared; post-unmount observation is explicitly new, empty directories retained.',
        'Completeness of the declared D consumer set requires the exact independent root binding review and closure record; scans prove only the named original owners/groups/sessions, not global absence.',
        'Preparation is source/AST/metadata authoring only. No subprocess, namespace/mount inspection, unmount, target import, test, CI, engine, model or hardware operation was performed.',
        'Original D CI failure and all benchmark/scientific/CI negative outcomes remain unchanged. Resource cleanup is not acceptance, conformance, archive or merge.',
    ],
}
ref = publish('preparation.v1.json', report)
print(json.dumps({'preparation': ref, 'source': source_ref, 'target_execution_performed': False}, sort_keys=True))
