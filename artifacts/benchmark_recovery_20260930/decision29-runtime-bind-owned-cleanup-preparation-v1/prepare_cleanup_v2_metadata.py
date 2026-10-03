"""Author immutable v2 definitions/AST/diff only; no target imports or calls."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
old_path = HERE / 'capture_owned_runtime_bind_cleanup_v1.py'
old = old_path.read_bytes()
assert (len(old), hashlib.sha256(old).hexdigest()) == (29381, 'f12f742c63c332f4c700a9a607626346020d05255d66e95474c3281184703e88')
text = old.decode()
original_read = "    data = os.pread(fd, row['size_bytes'] + 1, 0)\n    assert len(data) == row['size_bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']\n"
bounded_read = """    blocks, offset = [], 0
    while offset < row['size_bytes']:
        gate()
        block = os.pread(fd, min(65536, row['size_bytes'] - offset), offset)
        assert block, 'held control payload ended early'
        blocks.append(block)
        offset += len(block)
    data = b''.join(blocks)
    assert len(data) == row['size_bytes'] and not os.pread(fd, 1, len(data)) and hashlib.sha256(data).hexdigest() == row['sha256']
"""
assert text.count(original_read) == 1
text = text.replace(original_read, bounded_read)
text = text.replace("groups = {r['pgid'] for r in owners}\n    sessions = {r['session'] for r in owners}", "groups = {r['pgid'] for r in owners if r['pgid'] is not None}\n    sessions = {r['session'] for r in owners if r['session'] is not None}")
start = text.index('def authentic_owners(value):')
end = text.index('\n\ndef evidence(', start)
text = text[:start] + """def normalize_owner(value):
    # Unknown fields stay null; neither sessions nor birth are inferred.
    assert isinstance(value, dict) and type(value.get('pid')) is int and value['pid'] > 0
    row = {key: value.get(key) for key in ('pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id')}
    for key in ('pgid', 'session', 'startticks'):
        assert row[key] is None or type(row[key]) is int and row[key] > 0
    for key in ('uid', 'gid'):
        assert row[key] is None or type(row[key]) is int and row[key] >= 0
    assert row['boot_id'] is None or row['boot_id'] == BOOT
    return row


def authentic_owners(value):
    found = []
    if isinstance(value, dict):
        if type(value.get('pid')) is int and value['pid'] > 0:
            found.append(normalize_owner(value))
        if type(value.get('reader_pid')) is int and value['reader_pid'] > 0:
            found.append(normalize_owner({'pid': value['reader_pid']}))
        if type(value.get('original_pid')) is int and value['original_pid'] > 0:
            found.append(normalize_owner({'pid': value['original_pid'], 'pgid': value.get('original_pgid')}))
        for nested in value.values():
            found.extend(authentic_owners(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(authentic_owners(nested))
    return found
""" + text[end:]
text = text.replace("HERE / 'capture_owned_runtime_bind_cleanup_v1.py'", "HERE / 'capture_owned_runtime_bind_cleanup_v2.py'")
text = text.replace("    documents, proof_pins = [], []", "    documents, proof_pins, conformance_proofs = [], [], {}")
text = text.replace("        value, pin = evidence(conformance[label], BASE)\n        documents.append(value)", "        value, pin = evidence(conformance[label], BASE)\n        conformance_proofs[label] = value\n        documents.append(value)")
original_required = """    assert 3 <= len(declared) <= 512 and len({(r['pid'], r['startticks']) for r in declared}) == len(declared)
    assert all(set(r) == {'pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id'} and r in authentic for r in declared), 'closed consumers require original dispatch/terminal-derived owners'
    required_ci = authentic_owners([documents[0]['controller'], documents[1]['original'], ci_review['facts']['actual_observer']['owner']])
    assert required_ci and all(r in declared for r in required_ci)
"""
new_required = """    assert 4 <= len(declared) <= 512 and len({(r['pid'], r['startticks']) for r in declared}) == len(declared)
    assert all(set(r) == {'pid', 'pgid', 'session', 'startticks', 'uid', 'gid', 'boot_id'} and normalize_owner(r) == r and r in authentic for r in declared), 'closed consumers require named actual dispatch/result/closure records'
    assert ci_review['facts']['actual_wrapper_dispatch'] == documents[0] and ci_review['facts']['actual_wrapper_terminal'] == documents[1]
    required_ci = [normalize_owner(documents[0]['controller']), normalize_owner(documents[1]['original']), normalize_owner(ci_review['facts']['actual_observer']['owner']), normalize_owner({'pid': ci_review['reader_pid']})]
    required_conformance = [normalize_owner({'pid': conf_terminal['original_pid'], 'pgid': conf_terminal.get('original_pgid')})]
    # Independent conformance reader PID must also be declared when its actual
    # top-level result provides it. Nested historical owners are not relabeled.
    for value in conformance_proofs.values():
        if type(value.get('reader_pid')) is int and value['reader_pid'] > 0:
            required_conformance.append(normalize_owner({'pid': value['reader_pid']}))
    assert conf_terminal['source_commit'] == COMMIT and all(r in declared for r in required_ci + required_conformance)
"""
assert text.count(original_required) == 1
text = text.replace(original_required, new_required)
text = text.replace("'consumer_owner_scans': consumer_scans,", "'consumer_owner_scans': consumer_scans, 'normalized_actual_consumer_owners_unknown_fields_null': declared,")
text = text.replace("'Only recorded original consumer and command PIDs/groups/sessions are scanned; no global descendant absence claim.'", "'Only recorded positive consumer and command PIDs/groups/sessions are scanned. Unknown original birth/session/group fields stay null, not inferred; no global descendant absence claim.'")
new_path = HERE / 'capture_owned_runtime_bind_cleanup_v2.py'
new = text.encode()
old_tree, new_tree = ast.parse(old), ast.parse(new)
funcs = lambda tree: {node.name: ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node, ast.FunctionDef)}
before_functions, after_functions = funcs(old_tree), funcs(new_tree)
changed = sorted(k for k in before_functions if before_functions[k] != after_functions.get(k))
assert changed == ['authentic_owners', 'read_control', 'scan']
same = sorted(k for k in before_functions if before_functions[k] == after_functions.get(k))
assert not (HERE / 'original-owned-cleanup-attempt01').exists()
assert not (HERE / 'consumer-closure.bound.v1.json').exists()
def desc(p):
    b = p.read_bytes()
    return {'path': str(p), 'size_bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
def put(name, data):
    p = HERE / name
    with p.open('xb') as stream:
        stream.write(data)
    return desc(p)
def publish(name, obj):
    return put(name, (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())
source_ref = put(new_path.name, new)
diff_ref = put('v1-v2.complete-source.delta.patch', ''.join(difflib.unified_diff(old.decode().splitlines(True), text.splitlines(True), fromfile=old_path.name, tofile=new_path.name)).encode())
original = json.loads((HERE / 'preparation.v1.json').read_bytes())
pending = json.loads((HERE / 'consumer-closure.pending.v1.json').read_bytes())
pending['reviewed_capture_sha256'] = source_ref['sha256']
pending_ref = publish('consumer-closure.pending.v2.json', pending)
original.update({
    'source': source_ref,
    'metadata_author': desc(Path(__file__)),
    'pending_binding': pending_ref,
    'preserved_preparation_v1': desc(HERE / 'preparation.v1.json'),
    'preserved_cleanup_source_v1': desc(old_path),
    'v1_v2_complete_source_diff': diff_ref,
    'current_source_AST': {'parse': True, 'exact_unchanged_functions': same, 'changed_functions': changed, 'new_functions': ['normalize_owner']},
    'v2_changes': [
        'Bounded repeated64KiB pread until exact held control size; original cap/deadline/SHA/full7epoch guards unchanged. Actual earlier peer demonstrated DrvFS short read65512 for127794.',
        'Normalize only actual owner fields with missing values null. Scan only observed positive PID/PGID/session; no original birth/session/group inferred.',
        'Require actual CI controller/original/observer and named result-reader PID plus genuine conformance mapper and reader PID when available; source rows join actual dispatch/result/closure bodies.',
        'Necessary reviewed v2 source leaf literal and self-SHA argv updates; sole fixed umount, originalcreatorproofs, physicalmount/interpreter/FD/error/30+10clock gates unchanged.',
    ],
    'actual_owner_shape_basis': {
        'CI_result': {'path': str(HERE.parent / 'decision29-local-ci-D-prerequisite-result-review-preparation-v1/original-prerequisite-review-attempt01/review.v1.json'), 'size_bytes': 119285, 'sha256': '5a58508acf35f71d3c2934a022de1bff2e60eb44a39b6f85bd48cc3715ab7c60'},
        'observer6999': 'Actual PID/PGID/startticks/UID/GID/boot observed; original session absent.',
        'reader10965': 'Only original reader PID observed; unknown birth/group/session/UID/GID/boot remain null.',
        'current_owner_late_peer': {'path': str(HERE.parent / 'decision29-local-ci-D-prerequisite-result-review-preparation-v1/independent-owner-late-closure-v1/actual-tool-and-owner-closure-supplement.v1.json'), 'size_bytes': 5410, 'sha256': '45957c4900ec9edd6d0712bfbb8cf94c07401a01457bea09106938e95f1ccd45'},
    },
    'inverse_claim': 'Explicit two-behavior correction plus necessary leaf bindings. No whole-source literal-only claim; all other' + str(len(same)) + ' original v1 function ASTs remain exact.',
})
original['capture_runtime_args'][-1] = source_ref['sha256']
original['future_external_argv'][-1] = source_ref['sha256']
original['future_external_argv'][8] = original['future_external_argv'][8].replace('_v1.py', '_v2.py')
original['future_binding_requirements'][5] = 'Supply normalized actual named consumer records with every missing field null. All required actual CI actors and current conformance mapper/reader PIDs must be included. No session, PGID or birth is inferred.'
ref = publish('preparation.v2.json', original)
print(json.dumps({'source': source_ref, 'preparation': ref, 'diff': diff_ref, 'changed_functions': changed, 'unchanged_function_count': len(same), 'target_execution_performed': False}, sort_keys=True))
